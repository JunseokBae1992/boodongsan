"""지역구별 지수 시계열로부터 고점/저점/현재 및 비율 지표 계산.

'가장 깊은 조정(하락) 구간' 기준:
  - 각 시점의 직전까지 최고치(running max) 대비 낙폭이 가장 컸던 지점을 저점으로,
  - 그 저점이 떨어져 나온 직전 고점(전고점)을 고점으로 본다.
  - 이렇게 하면 현재가 역대 최고가(신고가)인 구도 전고점·저점이 항상 잡혀
    상승률/회복률이 의미 있게 계산된다.
  - 현재값 >= 전고점 이면 '전고점 돌파'(신고가)로 구분한다.

지표:
  - 저점 대비 상승률 = (현재 - 저점) / 저점 * 100
  - 고점 대비 회복률 = 현재 / 전고점 * 100   (100 초과면 전고점 돌파)
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd

# R-ONE row 에서 기간/값 후보 키 (응답 표기 변동 대비)
TIME_KEYS = ["WRTTIME_IDTFR_ID", "WRTTIME_DESC", "WRTTIME"]
VALUE_KEYS = ["DTA_VAL", "DTA_VAL1", "VALUE"]
CLS_NAME_KEYS = ["CLS_NM", "CLS_FULLNM", "GRP_NM"]

STATUS_BREAKOUT = "전고점 돌파"
STATUS_RECOVERING = "회복 진행중"


@dataclass
class IndexStats:
    region: str
    peak_value: float            # 전고점 (가장 깊은 조정의 직전 고점)
    peak_time: str
    trough_value: float          # 조정 저점 (전고점 대비 낙폭 최대 지점)
    trough_time: str
    current_value: float
    current_time: str
    rise_from_trough_pct: float  # 저점 대비 상승률 (%)
    recovery_from_peak_pct: float  # 고점 대비 회복률 (%), 100 초과 = 돌파
    drawdown_pct: float          # 조정 낙폭 (%) = trough/peak - 1
    status: str                  # '전고점 돌파' 또는 '회복 진행중'

    def to_dict(self) -> dict:
        return asdict(self)


def _first_key(row: dict, keys: list[str]) -> str | None:
    for k in keys:
        if k in row and row[k] not in (None, ""):
            return k
    return None


def rows_to_frame(rows: list[dict]) -> pd.DataFrame:
    """API row 리스트 -> [region, time, value] 정규화 DataFrame."""
    if not rows:
        return pd.DataFrame(columns=["region", "time", "value"])

    sample = rows[0]
    tkey = _first_key(sample, TIME_KEYS)
    vkey = _first_key(sample, VALUE_KEYS)
    ckey = _first_key(sample, CLS_NAME_KEYS)
    if not (tkey and vkey and ckey):
        raise ValueError(
            f"행에서 기간/값/지역 컬럼을 찾지 못했습니다. 키: {list(sample.keys())}"
        )

    records = []
    for r in rows:
        try:
            value = float(r[vkey])
        except (TypeError, ValueError):
            continue
        records.append({"region": r[ckey], "time": str(r[tkey]), "value": value})

    df = pd.DataFrame.from_records(records)
    if not df.empty:
        df = df.sort_values(["region", "time"]).reset_index(drop=True)
    return df


def compute_stats(series: pd.DataFrame) -> IndexStats | None:
    """단일 지역 시계열(time, value 정렬됨)에서 지표 계산.

    가장 깊은 조정 구간을 찾는 방식:
      running max(직전까지 최고치) 대비 낙폭(drawdown)이 가장 큰 지점을 저점으로,
      그 저점이 떨어져 나온 전고점을 고점으로 삼는다. 현재가 신고가여도
      직전 사이클의 전고점·저점이 잡혀 지표가 항상 의미를 가진다.
    """
    s = series.dropna(subset=["value"]).sort_values("time")
    if s.empty:
        return None

    region = str(s["region"].iloc[0]) if "region" in s else ""
    values = s["value"].to_numpy(dtype=float)
    times = s["time"].to_numpy()

    current_value = float(values[-1])
    current_time = str(times[-1])

    # running max 대비 낙폭이 최대인 지점 = 조정 저점
    running_max = np.maximum.accumulate(values)
    drawdown_series = values / running_max - 1.0
    trough_idx = int(drawdown_series.argmin())
    trough_value = float(values[trough_idx])
    trough_time = str(times[trough_idx])

    # 저점이 떨어져 나온 전고점(= trough 이전 구간의 최고치)
    peak_value = float(running_max[trough_idx])
    upto = values[: trough_idx + 1]
    peak_idx = int(np.where(upto == peak_value)[0][-1])
    peak_time = str(times[peak_idx])

    rise = (current_value - trough_value) / trough_value * 100 if trough_value else 0.0
    recovery = current_value / peak_value * 100 if peak_value else 0.0
    drawdown = (trough_value / peak_value - 1) * 100 if peak_value else 0.0
    status = STATUS_BREAKOUT if current_value >= peak_value else STATUS_RECOVERING

    return IndexStats(
        region=region,
        peak_value=peak_value,
        peak_time=peak_time,
        trough_value=trough_value,
        trough_time=trough_time,
        current_value=current_value,
        current_time=current_time,
        rise_from_trough_pct=round(rise, 2),
        recovery_from_peak_pct=round(recovery, 2),
        drawdown_pct=round(drawdown, 2),
        status=status,
    )


def compute_all(df: pd.DataFrame) -> pd.DataFrame:
    """지역별 지표 표 생성."""
    out: list[dict] = []
    for region, grp in df.groupby("region"):
        stats = compute_stats(grp)
        if stats:
            out.append(stats.to_dict())
    result = pd.DataFrame(out)
    if not result.empty:
        result = result.sort_values("rise_from_trough_pct", ascending=False).reset_index(drop=True)
    return result
