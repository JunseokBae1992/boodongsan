"""analysis 모듈 단위 테스트 (API 키 없이 실행 가능).

  python -m pytest test_analysis.py   또는   python test_analysis.py
"""

import pandas as pd

from analysis import compute_all, compute_stats, rows_to_frame


def _frame(region, pairs):
    return pd.DataFrame(
        [{"region": region, "time": t, "value": v} for t, v in pairs]
    )


def test_basic_cycle():
    # 상승 100->120(고점) -> 하락 ->90(저점) -> 회복 ->108(현재)
    df = _frame("강남구", [
        ("202001", 100.0),
        ("202006", 120.0),  # 고점
        ("202012", 90.0),   # 고점 이후 저점
        ("202106", 108.0),  # 현재
    ])
    s = compute_stats(df)
    assert s.peak_value == 120.0 and s.peak_time == "202006"
    assert s.trough_value == 90.0 and s.trough_time == "202012"
    assert s.current_value == 108.0
    # 저점 대비 상승률 = (108-90)/90*100 = 20.0
    assert s.rise_from_trough_pct == 20.0
    # 고점 대비 회복률 = 108/120*100 = 90.0
    assert s.recovery_from_peak_pct == 90.0
    # 낙폭 = 90/120-1 = -25.0
    assert s.drawdown_pct == -25.0


def test_trough_is_after_peak_only():
    # 초반에 더 낮은 값(80)이 있어도, 저점은 '고점 이후' 구간에서만 찾는다.
    df = _frame("송파구", [
        ("201901", 80.0),   # 전체 최저지만 고점 이전 -> 저점 아님
        ("202006", 120.0),  # 고점
        ("202012", 95.0),   # 고점 이후 저점
        ("202106", 110.0),
    ])
    s = compute_stats(df)
    assert s.trough_value == 95.0
    assert s.rise_from_trough_pct == round((110 - 95) / 95 * 100, 2)


def test_still_rising_recovery_100():
    # 최신이 곧 고점(하락 없음) -> 저점=현재, 상승률 0, 회복률 100
    df = _frame("마포구", [
        ("202001", 100.0),
        ("202106", 130.0),  # 고점=현재
    ])
    s = compute_stats(df)
    assert s.trough_value == 130.0
    assert s.rise_from_trough_pct == 0.0
    assert s.recovery_from_peak_pct == 100.0


def test_rows_to_frame_and_compute_all():
    rows = [
        {"CLS_NM": "강남구", "WRTTIME_IDTFR_ID": "202001", "DTA_VAL": "100"},
        {"CLS_NM": "강남구", "WRTTIME_IDTFR_ID": "202006", "DTA_VAL": "120"},
        {"CLS_NM": "강남구", "WRTTIME_IDTFR_ID": "202012", "DTA_VAL": "90"},
        {"CLS_NM": "송파구", "WRTTIME_IDTFR_ID": "202001", "DTA_VAL": "100"},
        {"CLS_NM": "송파구", "WRTTIME_IDTFR_ID": "202012", "DTA_VAL": "110"},
    ]
    df = rows_to_frame(rows)
    assert set(df["region"]) == {"강남구", "송파구"}
    result = compute_all(df)
    assert len(result) == 2
    assert {"rise_from_trough_pct", "recovery_from_peak_pct"} <= set(result.columns)


if __name__ == "__main__":
    test_basic_cycle()
    test_trough_is_after_peak_only()
    test_still_rising_recovery_100()
    test_rows_to_frame_and_compute_all()
    print("모든 테스트 통과 ✅")
