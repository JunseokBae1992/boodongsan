"""서울 자치구별 부동산 지수 대시보드 (Streamlit).

한국부동산원 R-ONE OpenAPI에서 (월) 아파트 매매가격지수를 받아
구별 고점/저점/현재 지수와 저점 대비 상승률·고점 대비 회복률을 계산해 보여준다.

실행:
  export REB_API_KEY=발급받은키
  streamlit run app.py
"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv

from analysis import compute_all, compute_stats, rows_to_frame
from reb_api import (
    DEFAULT_DTACYCLE_CD,
    DEFAULT_STATBL_ID,
    SEOUL_GU,
    RebApiError,
    RebClient,
)

load_dotenv()

# Streamlit Community Cloud 등 배포 환경에서는 인증키를 Secrets로 넣는다.
# st.secrets 에만 있고 환경변수에 없으면 환경변수로 옮겨준다(reb_api 가 os.environ 사용).
if not os.environ.get("REB_API_KEY"):
    try:
        if "REB_API_KEY" in st.secrets:
            os.environ["REB_API_KEY"] = str(st.secrets["REB_API_KEY"])
    except Exception:
        pass

st.set_page_config(page_title="서울 자치구 부동산 지수", layout="wide")
st.title("🏙️ 서울 자치구별 부동산 지수 분석")
st.caption("출처: 한국부동산원 R-ONE 부동산통계 OpenAPI · (월) 아파트 매매가격지수")

# 코스피처럼 맨 위에 표시할 '시황' 배너 자리 (데이터 로딩 후 채움)
market_slot = st.container()


def _pct(vals, n: int) -> float:
    if len(vals) <= n or vals[-1 - n] == 0:
        return 0.0
    return (vals[-1] / vals[-1 - n] - 1) * 100


def _seoul_series(df: pd.DataFrame):
    """서울 시황용 시계열(월별 값) + 출처 라벨. 옵션과 무관하게 서울 기준."""
    def only_seoul(sub):
        if "region_full" in df.columns:
            sub = sub[sub["region"].eq("서울 전체")
                      | sub["region_full"].astype(str).str.contains("서울", na=False)]
        return sub
    # 1) '서울 전체' 라벨 → 2) 원본 '서울/서울특별시' → 3) 서울 자치구 평균
    for names, label in [({"서울 전체"}, "서울 전체"),
                         ({"서울", "서울특별시"}, "서울 전체"),
                         (set(SEOUL_GU), "서울 구 평균")]:
        sub = only_seoul(df[df["region"].isin(names)])
        if not sub.empty:
            g = sub.groupby("time")["value"].mean().sort_index()
            return g.to_numpy(float), g.index.to_numpy(), label
    g = df.groupby("time")["value"].mean().sort_index()
    return g.to_numpy(float), g.index.to_numpy(), "전체 평균"


def seoul_market(df: pd.DataFrame) -> dict:
    """서울 시계열로 시황(상승/보합/하락) 판정."""
    vals, times, src = _seoul_series(df)
    cur = float(vals[-1])
    mom1, mom3, mom6, mom12 = _pct(vals, 1), _pct(vals, 3), _pct(vals, 6), _pct(vals, 12)
    ath = float(np.maximum.accumulate(vals)[-1])
    dd = (cur / ath - 1) * 100 if ath else 0.0
    # 최근 3개월 모멘텀으로 판정 (상승=빨강, 하락=파랑: 국내 증시 관행)
    if mom3 >= 0.5:
        status, emoji, bg, fg = "상승장", "📈", "#fdeceb", "#c0392b"
    elif mom3 <= -0.5:
        status, emoji, bg, fg = "하락장", "📉", "#eaf1fb", "#2471a3"
    else:
        status, emoji, bg, fg = "보합", "⏸️", "#eef0f2", "#566573"
    return dict(cur=cur, mom1=mom1, mom3=mom3, mom6=mom6, mom12=mom12, dd=dd,
                status=status, emoji=emoji, bg=bg, fg=fg, src=src, time=str(times[-1]),
                vals=list(map(float, vals)), times=[str(t) for t in times])


def _svg_sparkline(vals, color, months=36, w=200, h=46, pad=5) -> str:
    """배너 안에 넣을 가벼운 SVG 미니 추세선(면적 채움 + 끝점)."""
    v = [float(x) for x in vals if x == x][-months:]
    if len(v) < 2:
        return ""
    lo, hi = min(v), max(v)
    rng = (hi - lo) or 1.0
    n = len(v)
    pts = []
    for i, x in enumerate(v):
        px = pad + i * (w - 2 * pad) / (n - 1)
        py = pad + (h - 2 * pad) * (1 - (x - lo) / rng)
        pts.append((px, py))
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    fill = f"{pad},{h - pad} " + line + f" {w - pad},{h - pad}"
    lx, ly = pts[-1]
    return (
        f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" preserveAspectRatio="none" '
        f'style="vertical-align:middle">'
        f'<polygon points="{fill}" fill="{color}" fill-opacity="0.13"/>'
        f'<polyline points="{line}" fill="none" stroke="{color}" stroke-width="2" '
        f'stroke-linejoin="round" stroke-linecap="round"/>'
        f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="3" fill="{color}"/></svg>'
    )


def render_market_banner(slot, df: pd.DataFrame, vol_series=None) -> None:
    m = seoul_market(df)
    vol_txt = ""
    if vol_series is not None:
        vvals, _vtimes = vol_series
        # 거래량은 계절성이 커서 전년 동월 대비(YoY)로 비교
        if len(vvals) > 12:
            vyoy = _pct(vvals, 12)
            arrow = "▲증가" if vyoy > 5 else ("▼감소" if vyoy < -5 else "─비슷")
            vol_txt = f"&nbsp;·&nbsp;거래량 전년比 {vyoy:+.0f}% ({arrow})"
    spark = _svg_sparkline(m["vals"], m["fg"])
    with slot:
        st.markdown(
            f"""<div style="background:{m['bg']};border-radius:12px;padding:14px 20px;margin:4px 0 2px 0;
display:flex;align-items:center;gap:16px;">
  <div style="flex:1;min-width:0">
    <div style="font-size:1.6rem;font-weight:800;color:{m['fg']}">{m['emoji']} 서울 부동산 <u>{m['status']}</u></div>
    <div style="font-size:1.0rem;color:{m['fg']};margin-top:2px">
      매매지수 <b>{m['cur']:.1f}</b>&nbsp;·&nbsp;전월 {m['mom1']:+.2f}%&nbsp;·&nbsp;3개월 {m['mom3']:+.2f}%&nbsp;·&nbsp;12개월 {m['mom12']:+.2f}%{vol_txt}
    </div>
  </div>
  <div style="flex:0 0 auto">{spark}</div>
</div>""",
            unsafe_allow_html=True,
        )
        st.caption(
            f"기준: {m['src']} · {m['time']} · 역대최고 대비 {m['dd']:+.1f}% · "
            f"추세선: 최근 3년 · 판정: 최근 3개월 {m['mom3']:+.2f}% (≥+0.5% 상승 / ≤−0.5% 하락 / 그 사이 보합)"
        )


DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def _snapshot_path(statbl_id: str) -> str:
    return os.path.join(DATA_DIR, f"{statbl_id}.csv")


def _yyyymm_minus(ym: str, months: int) -> str:
    """YYYYMM 에서 months개월 뺀 값."""
    y, m = int(ym[:4]), int(ym[4:6])
    idx = y * 12 + (m - 1) - months
    return f"{idx // 12:04d}{idx % 12 + 1:02d}"


# 과거 지수는 바뀌지 않으므로 디스크에 캐시(앱이 잠들었다 깨어나도 유지) + 24시간 TTL
@st.cache_data(ttl=60 * 60 * 24, show_spinner=True, persist="disk")
def load_rows(statbl_id: str, dtacycle: str, start: str, end: str) -> list[dict]:
    client = RebClient.from_env()
    path = _snapshot_path(statbl_id)
    if os.path.exists(path):
        # 레포에 커밋된 과거 스냅샷을 즉시 읽고, 최근 몇 달만 API로 갱신(개정 반영)
        snap = pd.read_csv(path, dtype=str, keep_default_na=False)
        snap_rows = snap.to_dict("records")
        last = max((str(r.get("WRTTIME_IDTFR_ID", "")) for r in snap_rows), default="")
        fresh_start = _yyyymm_minus(last, 6) if len(last) >= 6 else (start or None)
        try:
            fresh = client.fetch_series(statbl_id, dtacycle, fresh_start, end or None)
        except RebApiError:
            fresh = []
        merged: dict = {}
        for r in snap_rows:
            merged[(r.get("WRTTIME_IDTFR_ID"), r.get("CLS_ID"), r.get("ITM_ID"))] = r
        for r in fresh:  # 최근분이 스냅샷을 덮어씀(개정치 반영)
            merged[(r.get("WRTTIME_IDTFR_ID"), r.get("CLS_ID"), r.get("ITM_ID"))] = r
        return list(merged.values())
    return client.fetch_series(
        statbl_id=statbl_id,
        dtacycle_cd=dtacycle,
        start_wrttime=start or None,
        end_wrttime=end or None,
    )


def style_highlight_total(frame: pd.DataFrame):
    """'서울 전체' 행을 노란 배경 + 굵게 강조한 Styler 반환."""
    def _hl(row):
        if str(row.get("region", "")) == "서울 전체":
            return ["background-color: rgba(255,193,7,0.25); font-weight:700"] * len(row)
        return [""] * len(row)
    return frame.style.apply(_hl, axis=1)


def bar_colors(regions) -> list[str]:
    """서울 전체는 금색, 나머지 자치구는 파란색."""
    return ["#f1c40f" if str(r) == "서울 전체" else "#4C78A8" for r in regions]


def appeal_label(recovery_pct: float) -> str:
    """전고점 대비 수준(%)을 매수 관점 라벨로. 높을수록 고가 부담, 낮을수록 저가 메리트."""
    if recovery_pct >= 105:
        return "🔴 고가 부담 큼"
    if recovery_pct >= 100:
        return "🟠 고가 부담"
    if recovery_pct >= 95:
        return "🟡 고점 근접"
    if recovery_pct >= 85:
        return "🟢 저가 메리트"
    return "🔵 저가 메리트 큼"


SEOUL_TOTAL_NAMES = {"서울", "서울특별시"}
SEOUL_TOTAL_LABEL = "서울 전체"


def filter_seoul_gu(df: pd.DataFrame, include_total: bool = True) -> pd.DataFrame:
    """서울 25개 자치구(+선택 시 서울 전체). 동명 타지역 구는 전체분류명으로 배제."""
    if df.empty:
        return df
    gu_set = set(SEOUL_GU)
    # 1) 전체분류명에 '서울'이 있으면 그 행만 (부산/대구 등 동명 구 제거)
    has_seoul = df["region_full"].astype(str).str.contains("서울", na=False)
    base = df[has_seoul] if has_seoul.any() else df
    # 2) 짧은 이름이 서울 자치구인 것만
    out = base[base["region"].isin(gu_set)].copy()
    # 3) 서울 전체 집계 행 추가 (벤치마크용)
    if include_total:
        is_total = base["region"].isin(SEOUL_TOTAL_NAMES) | base["region_full"].isin(SEOUL_TOTAL_NAMES)
        total = base[is_total].copy()
        if not total.empty:
            total["region"] = SEOUL_TOTAL_LABEL
            out = pd.concat([total, out], ignore_index=True)
    # 4) 안전장치: (지역, 월) 중복 제거 -> 톱니형 왜곡 방지
    out = out.drop_duplicates(subset=["region", "time"], keep="first")
    return out


with st.sidebar:
    st.header("설정")
    if st.button("🔄 새로고침 (최신 데이터 다시 받기)"):
        st.cache_data.clear()
        st.rerun()
    only_gu = st.checkbox("서울 25개 자치구만", value=True)
    include_total = st.checkbox("서울 전체(평균) 포함", value=True)

    with st.expander("⚙️ 고급 설정 (평소엔 안 건드려도 됨)"):
        statbl_id = st.text_input("STATBL_ID (통계표 코드)", DEFAULT_STATBL_ID,
                                  help="(월) 매매가격지수_아파트 = A_2024_00045")
        dtacycle = st.text_input("DTACYCLE_CD (주기)", DEFAULT_DTACYCLE_CD,
                                 help="MM=월, QY=분기, YY=연")
        start = st.text_input("시작 기간 (YYYYMM)", "201801")
        end = st.text_input("종료 기간 (YYYYMM)", "")
        vol_statbl = st.text_input(
            "거래량 STATBL_ID", "A_2024_00554",
            help="기본값 A_2024_00554 = (월) 행정구역별 아파트매매거래현황. "
                 "비우면 거래량 미표시.")

# 페이지를 열면 자동으로 불러온다 (버튼 불필요). 결과는 6시간 캐시.
try:
    rows = load_rows(statbl_id, dtacycle, start, end)
except RebApiError as exc:
    st.error(f"API 오류: {exc}")
    st.stop()

if not rows:
    st.warning("데이터가 없습니다. STATBL_ID/기간/인증키를 확인하세요.")
    st.stop()

price_rows_raw = list(rows)  # 스냅샷 저장용 원본(항목 필터 전)

# 표에 항목(ITM)이 여러 개면(예: 지수/변동률) 하나만 골라야 지표가 정확하다.
item_names = sorted({str(r.get("ITM_NM", "")) for r in rows if r.get("ITM_NM")})
picked_item = None
if len(item_names) > 1:
    with st.sidebar:
        # '지수' 항목을 기본 선택 (없으면 첫 번째)
        default_idx = next((i for i, n in enumerate(item_names) if "지수" in n), 0)
        picked_item = st.selectbox("항목(ITM) 선택", item_names, index=default_idx,
                                   help="지수/변동률 등이 섞여 있으면 '지수'를 고르세요.")
    rows = [r for r in rows if str(r.get("ITM_NM", "")) == picked_item]

df = rows_to_frame(rows)
if df.empty:
    st.warning("데이터가 없습니다. STATBL_ID/기간/인증키를 확인하세요.")
    st.stop()

if only_gu:
    df = filter_seoul_gu(df, include_total=include_total)
    if df.empty:
        st.warning("서울 자치구 데이터가 없습니다. '서울 25개 자치구만' 체크를 해제하고 지역명을 확인하세요.")
        st.stop()

# 거래량(선택): 코드가 입력되면 서울 거래량 시계열을 가져옴
# (거래량은 배너 모멘텀용이라 최근 몇 년만 받아 로딩을 가볍게 한다)
vol_series = None
vrows_raw: list = []
if vol_statbl.strip():
    try:
        _maxt = str(df["time"].max())
        vol_start = f"{int(_maxt[:4]) - 3}{_maxt[4:]}" if len(_maxt) >= 6 and _maxt[:4].isdigit() else start
        vrows = load_rows(vol_statbl.strip(), dtacycle, vol_start, end)
        if vrows:
            vrows_raw = list(vrows)  # 스냅샷 저장용 원본
            # 항목(건수/면적 등)이 섞이면 단위 혼합을 막기 위해 하나만 선택
            vitems = sorted({str(r.get("ITM_NM", "")) for r in vrows if r.get("ITM_NM")})
            if len(vitems) > 1:
                pref = next((n for n in vitems if any(k in n for k in ["호", "건", "거래"])),
                            vitems[0])
                vrows = [r for r in vrows if str(r.get("ITM_NM", "")) == pref]
            vvals, vtimes, _ = _seoul_series(rows_to_frame(vrows))
            vol_series = (list(map(float, vvals)), [str(t) for t in vtimes])
    except RebApiError:
        vol_series = None

# 개발용: 현재 받은 데이터를 스냅샷 CSV로 내려받아 레포에 커밋하면 첫 로딩이 빨라짐
with st.sidebar:
    with st.expander("📦 스냅샷 다운로드 (개발용)"):
        st.caption("이 CSV를 받아 개발자에게 전달하면 앱에 내장돼 첫 로딩이 빨라집니다.")
        st.download_button(
            f"① 가격 데이터 ({statbl_id}.csv)",
            pd.DataFrame(price_rows_raw).to_csv(index=False).encode("utf-8-sig"),
            f"{statbl_id}.csv", "text/csv")
        if vol_statbl.strip() and vrows_raw:
            st.download_button(
                f"② 거래량 데이터 ({vol_statbl.strip()}.csv)",
                pd.DataFrame(vrows_raw).to_csv(index=False).encode("utf-8-sig"),
                f"{vol_statbl.strip()}.csv", "text/csv")

# 코스피 지수처럼 맨 위에 서울 시황 배너 표시
render_market_banner(market_slot, df, vol_series=vol_series)

# ── 진단 (값이 이상할 때 원본 확인) ────────────────────────
with st.expander("🔍 진단 — 원본 데이터/항목 확인"):
    st.caption(
        f"총 {len(rows)}행 · 지역 {df['region'].nunique()}개 · "
        f"기간 {df['time'].min()}~{df['time'].max()}"
        + (f" · 선택 항목: {picked_item}" if picked_item else "")
    )
    if item_names:
        st.caption(f"표에 포함된 항목(ITM_NM): {item_names}")
    if rows:
        st.caption(f"원본 필드: {list(rows[0].keys())}")
        if "region_full" in df:
            st.caption(f"전체분류명 예시: {sorted(df['region_full'].unique())[:5]}")
    rsel = st.selectbox("지역 원본 보기", sorted(df["region"].unique()))
    rd = df[df["region"] == rsel].sort_values("time").reset_index(drop=True)
    hi = rd.loc[rd["value"].idxmax()]
    lo = rd.loc[rd["value"].idxmin()]
    d1, d2 = st.columns(2)
    d1.metric("최댓값(고점) 시점", f"{hi['time']}", f"{hi['value']:.2f}")
    d2.metric("최솟값 시점", f"{lo['time']}", f"{lo['value']:.2f}")
    st.dataframe(rd, use_container_width=True, height=250)

stats = compute_all(df)
stats["appeal"] = stats["recovery_from_peak_pct"].map(appeal_label)

# 서울 전체(집계)는 KPI '구 개수'/매수 후보 계산에서 제외, 표·차트엔 포함
gu_stats = stats[stats["region"] != SEOUL_TOTAL_LABEL]

# ── 상단 요약 KPI ─────────────────────────────────────────
base_month = stats["current_time"].max() if not stats.empty else "-"
top_rise = gu_stats.iloc[0] if not gu_stats.empty else None
# 저가 메리트 = 전고점 대비 수준이 가장 낮은(제일 싼) 구
cheapest = gu_stats.sort_values("recovery_from_peak_pct").iloc[0] if not gu_stats.empty else None

n_breakout = int((gu_stats["status"] == "전고점 돌파").sum())
k1, k2, k3, k4 = st.columns(4)
k1.metric("기준월", str(base_month))
k2.metric("전고점 돌파(고가 부담)", f"{n_breakout} / {len(gu_stats)}개 구")
if top_rise is not None:
    k3.metric("반등 1위(저점대비)", top_rise["region"], f"+{top_rise['rise_from_trough_pct']:.1f}%")
if cheapest is not None:
    k4.metric("저가 메리트 1위", cheapest["region"], f"전고점 대비 {cheapest['recovery_from_peak_pct']:.0f}%")

st.divider()

tab_buy, tab_rank, tab_chart, tab_trend = st.tabs(
    ["🏠 매수 타이밍", "📋 구별 순위표", "📊 상승률·회복률", "📈 지수 추이"]
)

# ── 매수 타이밍 탭 ────────────────────────────────────────
PHASE_EMOJI = {
    "고점권": "🔴 고점권", "하락 중": "📉 하락 중", "바닥권": "🟢 바닥권",
    "상승 중": "📈 상승 중", "보합": "⏸ 보합",
}
with tab_buy:
    st.markdown("#### 다음 하락장 매수 판단")
    st.caption(
        "**국면**: 🔴고점권(비쌈) → 📉하락 중 → 🟢바닥권(하락 멈춤, 매수관심) → 📈상승 중. "
        "**현재낙폭**: 지금 역대최고 대비 얼마나 싸졌나. "
        "**역대최대낙폭**: 과거 하락장 최대 낙폭(=더 빠질 여지 가늠). "
        "**3/6/12개월**: 최근 모멘텀(마이너스=하락, 0 근처=바닥 신호)."
    )

    # 국면 분포 요약 (구 기준)
    phase_counts = gu_stats["phase"].value_counts()
    pc = st.columns(5)
    for i, ph in enumerate(["고점권", "하락 중", "바닥권", "상승 중", "보합"]):
        pc[i].metric(PHASE_EMOJI[ph], f"{int(phase_counts.get(ph, 0))}개 구")

    st.divider()

    # 매수 후보 조건 설정
    st.markdown("**매수 후보 조건**")
    cc1, cc2 = st.columns(2)
    target_dd = cc1.slider("전고점 대비 최소 하락폭 (%)", 0, 40, 15,
                           help="이만큼 이상 싸진 구만 후보로. 예) 15 = 전고점 대비 -15% 이상 하락")
    require_stall = cc2.checkbox("하락이 멈춘 구만 (3개월 변동률 ≥ -0.3%)", value=True,
                                 help="계속 떨어지는 중이면 '떨어지는 칼날'. 하락이 멈춘 구만 보려면 체크")

    cand = gu_stats.copy()  # 서울 전체(집계) 제외
    cand = cand[cand["cur_drawdown_pct"] <= -target_dd]
    if require_stall:
        cand = cand[cand["mom_3m_pct"] >= -0.3]
    cand = cand.sort_values("cur_drawdown_pct")  # 많이 빠진 순

    if cand.empty:
        st.info("조건을 만족하는 구가 없습니다. 하락폭 기준을 낮추거나, 다음 하락장이 오면 후보가 나타납니다. "
                "(현재 서울 대부분이 고점권/회복 국면일 수 있어요.)")
    else:
        st.success(f"매수 후보 {len(cand)}개 구 (많이 빠진 순)")
        st.dataframe(
            cand, use_container_width=True, hide_index=True,
            column_config={
                "region": st.column_config.TextColumn("지역"),
                "phase": st.column_config.TextColumn("국면"),
                "current_value": st.column_config.NumberColumn("현재지수", format="%.1f"),
                "cur_drawdown_pct": st.column_config.NumberColumn("현재낙폭(%)", format="%.1f%%"),
                "drawdown_pct": st.column_config.NumberColumn("역대최대낙폭(%)", format="%.1f%%"),
                "mom_3m_pct": st.column_config.NumberColumn("3개월(%)", format="%.1f%%"),
                "mom_6m_pct": st.column_config.NumberColumn("6개월(%)", format="%.1f%%"),
                "mom_12m_pct": st.column_config.NumberColumn("12개월(%)", format="%.1f%%"),
            },
            column_order=["region", "phase", "current_value", "cur_drawdown_pct",
                          "drawdown_pct", "mom_3m_pct", "mom_6m_pct", "mom_12m_pct"],
        )

    st.divider()
    st.markdown("**전체 구 국면·모멘텀** (현재낙폭 큰 순)")
    allv = stats.sort_values("cur_drawdown_pct")
    st.dataframe(
        allv, use_container_width=True, hide_index=True,
        column_config={
            "region": st.column_config.TextColumn("지역"),
            "phase": st.column_config.TextColumn("국면"),
            "current_value": st.column_config.NumberColumn("현재지수", format="%.1f"),
            "cur_drawdown_pct": st.column_config.NumberColumn("현재낙폭(%)", format="%.1f%%"),
            "drawdown_pct": st.column_config.NumberColumn("역대최대낙폭(%)", format="%.1f%%"),
            "mom_3m_pct": st.column_config.NumberColumn("3개월(%)", format="%.1f%%"),
            "mom_6m_pct": st.column_config.NumberColumn("6개월(%)", format="%.1f%%"),
            "mom_12m_pct": st.column_config.NumberColumn("12개월(%)", format="%.1f%%"),
        },
        column_order=["region", "phase", "current_value", "cur_drawdown_pct",
                      "drawdown_pct", "mom_3m_pct", "mom_6m_pct", "mom_12m_pct"],
    )
    st.caption("⚠️ 지수는 시장 참고용입니다. 실제 매수는 개별 단지 시세·금리·정책·본인 상황을 함께 보세요.")

# ── 순위표 탭 ─────────────────────────────────────────────
with tab_rank:
    sort_key = st.radio(
        "정렬 기준",
        ["저가 메리트순(전고점 대비 낮은순)", "저점대비 반등", "전고점 대비 수준", "지역명"],
        horizontal=True,
    )
    key_map = {
        "저가 메리트순(전고점 대비 낮은순)": ("recovery_from_peak_pct", True),
        "저점대비 반등": ("rise_from_trough_pct", False),
        "전고점 대비 수준": ("recovery_from_peak_pct", False),
        "지역명": ("region", True),
    }
    col, asc = key_map[sort_key]
    view = stats.sort_values(col, ascending=asc).reset_index(drop=True)
    view.index = view.index + 1  # 순위 1부터

    st.dataframe(
        style_highlight_total(view),
        use_container_width=True,
        column_config={
            "region": st.column_config.TextColumn("지역"),
            "appeal": st.column_config.TextColumn("가격 매력도"),
            "status": st.column_config.TextColumn("상태"),
            "current_value": st.column_config.NumberColumn("현재지수", format="%.1f"),
            "current_time": st.column_config.TextColumn("기준월"),
            "peak_value": st.column_config.NumberColumn("전고점", format="%.1f"),
            "peak_time": st.column_config.TextColumn("전고점시점"),
            "trough_value": st.column_config.NumberColumn("저점", format="%.1f"),
            "trough_time": st.column_config.TextColumn("저점시점"),
            "rise_from_trough_pct": st.column_config.ProgressColumn(
                "저점대비 반등(%)", format="%.1f%%",
                min_value=0, max_value=float(max(stats["rise_from_trough_pct"].max(), 1)),
            ),
            "recovery_from_peak_pct": st.column_config.NumberColumn(
                "전고점 대비 수준(%)", format="%.1f%%",
                help="100=고점과 동일, 100 초과=고점보다 비쌈(부담), 미만=고점보다 쌈(메리트)",
            ),
            "drawdown_pct": st.column_config.NumberColumn("전고점대비 낙폭(%)", format="%.1f%%"),
        },
        column_order=[
            "region", "appeal", "status", "current_value", "current_time",
            "peak_value", "peak_time", "trough_value", "trough_time",
            "rise_from_trough_pct", "recovery_from_peak_pct", "drawdown_pct",
        ],
    )
    st.download_button(
        "⬇️ CSV 내려받기",
        view.to_csv(index=False).encode("utf-8-sig"),
        "seoul_index_stats.csv", "text/csv",
    )

# ── 차트 탭 (가로 막대: 25개 구도 읽기 편함) ────────────────
with tab_chart:
    st.caption("🟡 금색 막대 = 서울 전체(평균) 벤치마크, 🔵 파란 막대 = 자치구")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**저점 대비 반등폭** (바닥에서 얼마나 올랐나)")
        d = stats.sort_values("rise_from_trough_pct")
        fig = px.bar(d, x="rise_from_trough_pct", y="region", orientation="h",
                     labels={"region": "", "rise_from_trough_pct": "반등(%)"},
                     text="rise_from_trough_pct")
        fig.update_traces(texttemplate="%{text:.1f}", textposition="outside",
                          marker_color=bar_colors(d["region"]))
        fig.update_layout(height=650, margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        st.markdown("**전고점 대비 수준** (100 미만=고점보다 쌈/메리트, 초과=고점보다 비쌈/부담)")
        d2 = stats.sort_values("recovery_from_peak_pct")
        fig2 = px.bar(d2, x="recovery_from_peak_pct", y="region", orientation="h",
                      labels={"region": "", "recovery_from_peak_pct": "전고점 대비 수준(%)"},
                      text="recovery_from_peak_pct")
        fig2.update_traces(texttemplate="%{text:.1f}", textposition="outside",
                           marker_color=bar_colors(d2["region"]))
        fig2.add_vline(x=100, line_dash="dash", line_color="red")
        fig2.update_layout(height=650, margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig2, use_container_width=True)

# ── 추이 탭 ───────────────────────────────────────────────
with tab_trend:
    regions = sorted(df["region"].unique())
    default = list(stats.head(5)["region"]) if not stats.empty else regions[:5]
    picked = st.multiselect("지역 선택 (여러 개 비교 가능)", regions, default=default)
    if picked:
        sub = df[df["region"].isin(picked)].copy()
        # "YYYYMM" 문자열 -> 실제 날짜로 변환(월 간격이 균등해지고 축이 날짜로 표시됨)
        sub["날짜"] = pd.to_datetime(sub["time"], format="%Y%m", errors="coerce")
        x_col = "날짜" if sub["날짜"].notna().all() else "time"
        line = px.line(sub, x=x_col, y="value", color="region",
                       labels={x_col: "기간", "value": "지수", "region": "지역"})
        # 서울 전체는 굵은 검은 선으로 강조
        for tr in line.data:
            if tr.name == "서울 전체":
                tr.line.width = 4
                tr.line.color = "#111111"
        line.update_layout(height=450, legend_title_text="지역")
        st.plotly_chart(line, use_container_width=True)

        for region in picked:
            s = compute_stats(df[df["region"] == region])
            if s:
                st.markdown(f"**{region}** · {s.status} · {appeal_label(s.recovery_from_peak_pct)}")
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("현재지수", f"{s.current_value:.1f}", f"{s.current_time}")
                c2.metric("전고점", f"{s.peak_value:.1f}", f"{s.peak_time}")
                c3.metric("저점대비 반등", f"{s.rise_from_trough_pct:.1f}%")
                c4.metric("전고점 대비 수준", f"{s.recovery_from_peak_pct:.1f}%")
    else:
        st.info("비교할 지역을 하나 이상 선택하세요.")
