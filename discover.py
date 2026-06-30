"""통계표/지역/항목 코드 탐색용 CLI.

인증키 발급 후, 실제 응답에서 STATBL_ID·CLS_ID·ITM_ID·기간 표기를
직접 확인할 때 사용한다.

사용:
  export REB_API_KEY=발급받은키
  python discover.py tables                # 통계표 목록(메타)
  python discover.py tables A_2024_00045   # 특정 통계표 메타
  python discover.py sample A_2024_00045   # 데이터 한 페이지 미리보기 + 컬럼/지역 목록
"""

from __future__ import annotations

import json
import sys

from reb_api import DEFAULT_STATBL_ID, RebClient


def main(argv: list[str]) -> int:
    client = RebClient.from_env()
    cmd = argv[1] if len(argv) > 1 else "sample"

    if cmd == "tables":
        statbl_id = argv[2] if len(argv) > 2 else None
        rows = client.list_tables(statbl_id)
        print(f"통계표 {len(rows)}건")
        for r in rows[:50]:
            print(json.dumps(r, ensure_ascii=False))
        return 0

    if cmd == "sample":
        statbl_id = argv[2] if len(argv) > 2 else DEFAULT_STATBL_ID
        rows = client.fetch_series(statbl_id=statbl_id)
        print(f"행 {len(rows)}건 (STATBL_ID={statbl_id})")
        if rows:
            print("\n[컬럼]")
            print(list(rows[0].keys()))
            print("\n[샘플 행 3개]")
            for r in rows[:3]:
                print(json.dumps(r, ensure_ascii=False))
            cls = sorted({r.get("CLS_NM", "") for r in rows})
            itm = sorted({r.get("ITM_NM", "") for r in rows})
            print(f"\n[지역(CLS_NM) {len(cls)}종]")
            print(cls)
            print(f"\n[항목(ITM_NM) {len(itm)}종]")
            print(itm)
        return 0

    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
