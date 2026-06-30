"""헤드리스 리포트 CLI — Streamlit 없이 서버/터미널에서 바로 실행.

서울 자치구별 고점/저점/현재 지수와 저점 대비 상승률·고점 대비 회복률을
계산해 표로 출력하고 CSV로 저장한다. cron 등 서버 자동화에 적합.

사용:
  export REB_API_KEY=발급받은키
  python report.py                       # 기본: A_2024_00045, 월간, 서울 25개구
  python report.py --start 201501 --out seoul.csv
  python report.py --statbl A_2024_00045 --cycle MM --all-regions
"""

from __future__ import annotations

import argparse
import sys

from analysis import compute_all, rows_to_frame
from reb_api import (
    DEFAULT_DTACYCLE_CD,
    DEFAULT_STATBL_ID,
    SEOUL_GU,
    RebApiError,
    RebClient,
)


def filter_seoul_gu(df):
    mask = df["region"].apply(lambda x: any(gu in str(x) for gu in SEOUL_GU))
    return df[mask].copy()


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="서울 자치구 부동산 지수 리포트")
    p.add_argument("--statbl", default=DEFAULT_STATBL_ID, help="STATBL_ID (기본: 월간 아파트 매매가격지수)")
    p.add_argument("--cycle", default=DEFAULT_DTACYCLE_CD, help="DTACYCLE_CD: MM/QY/YY")
    p.add_argument("--start", default="201501", help="시작 기간 YYYYMM")
    p.add_argument("--end", default="", help="종료 기간 YYYYMM (비우면 최신)")
    p.add_argument("--all-regions", action="store_true", help="서울 자치구 필터 해제")
    p.add_argument("--out", default="", help="CSV 저장 경로")
    args = p.parse_args(argv[1:])

    try:
        client = RebClient.from_env()
        rows = client.fetch_series(
            statbl_id=args.statbl,
            dtacycle_cd=args.cycle,
            start_wrttime=args.start or None,
            end_wrttime=args.end or None,
        )
    except RebApiError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1

    df = rows_to_frame(rows)
    if df.empty:
        print("데이터가 없습니다. STATBL_ID/기간/인증키를 확인하세요.", file=sys.stderr)
        return 1

    if not args.all_regions:
        df = filter_seoul_gu(df)
        if df.empty:
            print("서울 자치구 데이터가 없습니다. --all-regions 로 지역명을 확인하세요.", file=sys.stderr)
            return 1

    stats = compute_all(df)
    print(f"\n=== 서울 자치구 부동산 지수 리포트 (STATBL_ID={args.statbl}, {args.cycle}) ===")
    print(f"기간: {df['time'].min()} ~ {df['time'].max()}  |  지역 {stats.shape[0]}개\n")
    with_pct = stats[[
        "region", "peak_value", "peak_time", "trough_value", "trough_time",
        "current_value", "current_time", "rise_from_trough_pct",
        "recovery_from_peak_pct", "drawdown_pct",
    ]]
    print(with_pct.to_string(index=False))

    if args.out:
        with_pct.to_csv(args.out, index=False, encoding="utf-8-sig")
        print(f"\n저장됨: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
