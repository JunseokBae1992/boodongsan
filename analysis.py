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
CLS_NAME_KEYS = ["CLS_NM", "GRP_NM"]
# 전체 분류명(상위 시/도 포함) - 동명 자치구(예: 서울/부산 강서구) 구분용
CLS_FULL_KEYS = ["CLS_FULLNM", "CLS_FULL_NM", "GRP_FULLNM", "CLASS_FULLNM"]
CLS_ID_KEYS = ["CLS_ID", "GRP_ID"]

STATUS_BREAKOUT = "전고점 돌파"
STATUS_RECOVERING = "회복 진행중"

# 사이클 국면
PHASE_PEAK = "고점권"      # 역대 최고가 근처 (비쌈)
PHASE_FALLING = "하락 중"  # 최근 모멘텀 마이너스
PHASE_BOTTOM = "바닥권"    # 많이 빠지고 하락 멈춤 (매수 관심)
PHASE_RISING = "상승 중"   # 저점에서 반등 상승
PHASE_FLAT = "보합"        # 뚜렷한 방향 없음

# 국면 판정 임계값 (월간 지수 기준, %)
_MOM_FLAT = 0.3            # ±0.3% 이내면 보합/횡보로 간주
_NEAR_PEAK = -2.0         # 역대최고 대비 -2% 이내면 고점권
_MEANINGFUL_DIP = -3.0    # 역대최고 대비 -3% 이상 빠져야 바닥권 후보


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
    ath_value: float             # 역대 최고 지수
    cur_drawdown_pct: float      # 현재 역대최고 대비 낙폭 (%), 0이면 신고가
    mom_3m_pct: float            # 최근 3개월 변동률 (%)
    mom_6m_pct: float            # 최근 6개월 변동률 (%)
    mom_12m_pct: float           # 최근 12개월 변동률 (%)
    phase: str                   # 사이클 국면

    def to_dict(self) -> dict:
        return asdict(self)


def _pct_change(values, months: int) -> float:
    """최근 months개월 변동률(%). 데이터가 부족하면 가용 범위로."""
    if len(values) <= 1:
        return 0.0
    n = min(months, len(values) - 1)
    past = float(values[-1 - n])
    return (float(values[-1]) / past - 1) * 100 if past else 0.0


def _classify_phase(cur_drawdown_pct: float, mom_3m_pct: float) -> str:
    """현재 낙폭 + 3개월 모멘텀으로 사이클 국면 판정."""
    if cur_drawdown_pct > _NEAR_PEAK:          # 역대최고 -2% 이내
        return PHASE_PEAK
    if mom_3m_pct <= -_MOM_FLAT:               # 하락 모멘텀
        return PHASE_FALLING
    if cur_drawdown_pct <= _MEANINGFUL_DIP and mom_3m_pct < _MOM_FLAT:
        return PHASE_BOTTOM                     # 많이 빠졌고 하락 멈춤
    if mom_3m_pct >= _MOM_FLAT:
        return PHASE_RISING
    return PHASE_FLAT


def _first_key(row: dict, keys: list[str]) -> str | None:
    for k in keys:
        if k in row and row[k] not in (None, ""):
            return k
    return None


def rows_to_frame(rows: list[dict]) -> pd.DataFrame:
    """API row 리스트 -> [region, region_full, cls_id, time, value] 정규화 DataFrame.

    region       : 짧은 자치구명(표시용, 예: '강서구')
    region_full  : 상위 시/도 포함 전체 분류명(예: '서울특별시 강서구'). 동명 구 구분용.
    cls_id       : 분류 코드(있으면). 동명 구 최종 구분용.
    """
    if not rows:
        return pd.DataFrame(columns=["region", "region_full", "cls_id", "time", "value"])

    sample = rows[0]
    tkey = _first_key(sample, TIME_KEYS)
    vkey = _first_key(sample, VALUE_KEYS)
    ckey = _first_key(sample, CLS_NAME_KEYS)
    fkey = _first_key(sample, CLS_FULL_KEYS)   # 없을 수 있음
    ikey = _first_key(sample, CLS_ID_KEYS)     # 없을 수 있음
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
        region = str(r[ckey])
        records.append({
            "region": region,
            "region_full": str(r[fkey]) if fkey and r.get(fkey) else region,
            "cls_id": str(r[ikey]) if ikey and r.get(ikey) else "",
            "time": str(r[tkey]),
            "value": value,
        })

    df = pd.DataFrame.from_records(records)
    if not df.empty:
        df = df.sort_values(["region_full", "time"]).reset_index(drop=True)
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

    # 매수 타이밍용: 현재 낙폭 + 모멘텀 + 국면
    ath_value = float(running_max[-1])          # 역대 최고 지수
    cur_drawdown = (current_value / ath_value - 1) * 100 if ath_value else 0.0
    mom_3 = _pct_change(values, 3)
    mom_6 = _pct_change(values, 6)
    mom_12 = _pct_change(values, 12)
    phase = _classify_phase(cur_drawdown, mom_3)

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
        ath_value=round(ath_value, 2),
        cur_drawdown_pct=round(cur_drawdown, 2),
        mom_3m_pct=round(mom_3, 2),
        mom_6m_pct=round(mom_6, 2),
        mom_12m_pct=round(mom_12, 2),
        phase=phase,
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
