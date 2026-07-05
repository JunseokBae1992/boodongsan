"""한국부동산원(R-ONE) 부동산통계 OpenAPI 클라이언트.

OpenAPI 안내: https://www.reb.or.kr/r-one/portal/openapi/openApiIntroPage.do
- 통계표(메타) 조회 : SttsApiTbl.do
- 통계 데이터 조회   : SttsApiTblData.do

인증키(KEY)는 reb.or.kr 로그인 후 발급하거나, 공공데이터포털
(data.go.kr "한국부동산원_부동산통계 조회 서비스")에서 발급받아
환경변수 REB_API_KEY 로 넣어 사용한다.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Iterable

import requests

BASE_URL = "https://www.reb.or.kr/r-one/openapi"

# (월) 매매가격지수_아파트 — 월간 아파트 매매가격지수 (서울 자치구 시계열 제공)
DEFAULT_STATBL_ID = "A_2024_00045"
DEFAULT_DTACYCLE_CD = "MM"  # MM=월, QY=분기, YY=연

# 서울특별시 25개 자치구
SEOUL_GU = [
    "종로구", "중구", "용산구", "성동구", "광진구",
    "동대문구", "중랑구", "성북구", "강북구", "도봉구",
    "노원구", "은평구", "서대문구", "마포구", "양천구",
    "강서구", "구로구", "금천구", "영등포구", "동작구",
    "관악구", "서초구", "강남구", "송파구", "강동구",
]


class RebApiError(RuntimeError):
    pass


@dataclass
class RebClient:
    api_key: str
    timeout: int = 20
    max_retries: int = 4

    @classmethod
    def from_env(cls) -> "RebClient":
        key = os.environ.get("REB_API_KEY", "").strip()
        if not key:
            raise RebApiError(
                "REB_API_KEY 환경변수가 비어 있습니다. "
                "reb.or.kr 또는 data.go.kr 에서 인증키를 발급받아 설정하세요."
            )
        return cls(api_key=key)

    def _get(self, path: str, params: dict[str, Any]) -> dict:
        params = {**params, "KEY": self.api_key, "Type": "json"}
        url = f"{BASE_URL}/{path}"
        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                resp = requests.get(url, params=params, timeout=self.timeout)
                resp.raise_for_status()
                data = resp.json()
                _raise_on_api_error(data)
                return data
            except (requests.RequestException, ValueError) as exc:
                last_exc = exc
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)
        raise RebApiError(f"API 호출 실패: {url} :: {last_exc}")

    def list_tables(self, statbl_id: str | None = None) -> list[dict]:
        """통계표 메타 정보 조회 (STATBL_ID, 분류/항목 코드 확인용)."""
        params: dict[str, Any] = {}
        if statbl_id:
            params["STATBL_ID"] = statbl_id
        data = self._get("SttsApiTbl.do", params)
        return _extract_rows(data)

    def fetch_series(
        self,
        statbl_id: str = DEFAULT_STATBL_ID,
        dtacycle_cd: str = DEFAULT_DTACYCLE_CD,
        start_wrttime: str | None = None,
        end_wrttime: str | None = None,
        cls_id: str | None = None,
        itm_id: str | None = None,
        page_size: int = 1000,
        max_pages: int = 200,
    ) -> list[dict]:
        """통계 데이터(시계열) 조회. 모든 페이지를 순회해 전체 row를 반환.

        R-ONE OpenAPI는 pIndex/pSize 로 페이지네이션되므로, 한 번만
        호출하면 앞쪽 일부 지역만 나온다. list_total_count 에 도달하거나
        빈 페이지가 나올 때까지 페이지를 넘겨 전부 수집한다.
        """
        base: dict[str, Any] = {
            "STATBL_ID": statbl_id,
            "DTACYCLE_CD": dtacycle_cd,
        }
        if start_wrttime:
            base["START_WRTTIME"] = start_wrttime
        if end_wrttime:
            base["END_WRTTIME"] = end_wrttime
        if cls_id:
            base["CLS_ID"] = cls_id
        if itm_id:
            base["ITM_ID"] = itm_id

        all_rows: list[dict] = []
        seen: set = set()
        total: int | None = None
        for pindex in range(1, max_pages + 1):
            params = {**base, "pIndex": pindex, "pSize": page_size}
            data = self._get("SttsApiTblData.do", params)
            rows = _extract_rows(data)
            if not rows:
                break
            # 새 행만 누적 (일부 표는 pIndex를 무시하고 같은 페이지를 반복 반환하므로,
            # 새로 추가되는 행이 없으면 중단해 무한 루프/과도한 요청을 막는다)
            new = 0
            for r in rows:
                key = (r.get("WRTTIME_IDTFR_ID"), r.get("CLS_ID"), r.get("ITM_ID"))
                if key not in seen:
                    seen.add(key)
                    all_rows.append(r)
                    new += 1
            if total is None:
                total = _total_count(data)
            if total is not None and len(all_rows) >= total:
                break
            if len(rows) < page_size or new == 0:
                break
        return all_rows


def _iter_blocks(payload: Any) -> Iterable[dict]:
    """R-ONE 응답은 {"<service>":[{head:...},{row:[...]}]} 형태라
    중첩 구조 어디에 있든 dict 블록을 훑는다."""
    if isinstance(payload, dict):
        yield payload
        for v in payload.values():
            yield from _iter_blocks(v)
    elif isinstance(payload, list):
        for v in payload:
            yield from _iter_blocks(v)


def _raise_on_api_error(payload: Any) -> None:
    for block in _iter_blocks(payload):
        result = block.get("RESULT")
        if isinstance(result, dict):
            code = str(result.get("CODE", ""))
            msg = result.get("MESSAGE", "")
            # INFO-000 = 정상
            if code and not code.startswith("INFO-00"):
                raise RebApiError(f"API 오류 [{code}] {msg}")


def _total_count(payload: Any) -> int | None:
    """응답 head 의 list_total_count(전체 행 수)를 찾는다."""
    for block in _iter_blocks(payload):
        if "list_total_count" in block:
            try:
                return int(block["list_total_count"])
            except (TypeError, ValueError):
                return None
    return None


def _extract_rows(payload: Any) -> list[dict]:
    """응답에서 데이터 행(row) 배열을 찾아 반환."""
    for block in _iter_blocks(payload):
        rows = block.get("row")
        if isinstance(rows, list) and rows and isinstance(rows[0], dict):
            return rows
    return []
