"""지역구별 지수 시계열로부터 고점/저점/현재 및 비율 지표 계산.

저점 정의: '직전 고점 이후의 바닥'
  - 전체 시계열에서 최고점(고점)을 찾고,
  - 그 고점 시점 이후 구간의 최저값을 저점으로 본다.
  - 고점이 가장 최근(=하락 전)이면 저점=현재값이 되어 회복률 100%.

지표:
  - 저점 대비 상승률 = (현재 - 저점) / 저점 * 100
  - 고점 대비 회복률 = 현재 / 고점 * 100
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

import pandas as pd

# R-ONE row 에서 기간/값 후보 키 (응답 표기 변동 대비)
TIME_KEYS = ["WRTTIME_IDTFR_ID", "WRTTIME_DESC", "WRTTIME"]
VALUE_KEYS = ["DTA_VAL", "DTA_VAL1", "VALUE"]
CLS_NAME_KEYS = ["CLS_NM", "CLS_FULLNM", "GRP_NM"]


@dataclass
class IndexStats:
    region: str
    peak_value: float
    peak_time: str
    trough_value: float          # 직전 고점 이후 바닥
    trough_time: str
    current_value: float
    current_time: str
    rise_from_trough_pct: float  # 저점 대비 상승률 (%)
    recovery_from_peak_pct: float  # 고점 대비 회복률 (%)
    drawdown_pct: float          # 고점 대비 낙폭 (%) = trough/peak - 1

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
    """단일 지역 시계열(time, value 정렬됨)에서 지표 계산."""
    s = series.dropna(subset=["value"]).sort_values("time")
    if s.empty:
        return None

    region = str(s["region"].iloc[0]) if "region" in s else ""
    values = s["value"].to_numpy()
    times = s["time"].to_numpy()

    peak_idx = int(values.argmax())
    peak_value = float(values[peak_idx])
    peak_time = str(times[peak_idx])

    # 고점 이후 구간에서 바닥
    post = values[peak_idx:]
    post_times = times[peak_idx:]
    trough_rel = int(post.argmin())
    trough_value = float(post[trough_rel])
    trough_time = str(post_times[trough_rel])

    current_value = float(values[-1])
    current_time = str(times[-1])

    rise = (current_value - trough_value) / trough_value * 100 if trough_value else 0.0
    recovery = current_value / peak_value * 100 if peak_value else 0.0
    drawdown = (trough_value / peak_value - 1) * 100 if peak_value else 0.0

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
