"""서울 자치구별 부동산 지수 대시보드 (Streamlit).

한국부동산원 R-ONE OpenAPI에서 (월) 아파트 매매가격지수를 받아
구별 고점/저점/현재 지수와 저점 대비 상승률·고점 대비 회복률을 계산해 보여준다.

실행:
  export REB_API_KEY=발급받은키
  streamlit run app.py
"""

from __future__ import annotations

import os

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


@st.cache_data(ttl=60 * 60 * 6, show_spinner=True)
def load_rows(statbl_id: str, dtacycle: str, start: str, end: str) -> list[dict]:
    client = RebClient.from_env()
    return client.fetch_series(
        statbl_id=statbl_id,
        dtacycle_cd=dtacycle,
        start_wrttime=start or None,
        end_wrttime=end or None,
    )


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


def filter_seoul_gu(df: pd.DataFrame) -> pd.DataFrame:
    """서울 25개 자치구만. 동명 타지역 구(예: 부산 강서구)를 전체분류명으로 배제."""
    if df.empty:
        return df
    gu_set = set(SEOUL_GU)
    # 1) 전체분류명에 '서울'이 있으면 그 행만 (부산/대구 등 동명 구 제거)
    has_seoul = df["region_full"].astype(str).str.contains("서울", na=False)
    base = df[has_seoul] if has_seoul.any() else df
    # 2) 짧은 이름이 서울 자치구인 것만
    out = base[base["region"].isin(gu_set)].copy()
    # 3) 안전장치: (지역, 월) 중복 제거 -> 톱니형 왜곡 방지
    out = out.drop_duplicates(subset=["region", "time"], keep="first")
    return out


with st.sidebar:
    st.header("설정")
    statbl_id = st.text_input("STATBL_ID", DEFAULT_STATBL_ID,
                              help="(월) 매매가격지수_아파트 = A_2024_00045")
    dtacycle = st.text_input("DTACYCLE_CD", DEFAULT_DTACYCLE_CD, help="MM=월, QY=분기, YY=연")
    start = st.text_input("시작 기간 (YYYYMM)", "201501")
    end = st.text_input("종료 기간 (YYYYMM)", "")
    only_gu = st.checkbox("서울 25개 자치구만", value=True)
    if st.button("🔄 새로고침 (최신 데이터 다시 받기)"):
        st.cache_data.clear()
        st.rerun()

# 페이지를 열면 자동으로 불러온다 (버튼 불필요). 결과는 6시간 캐시.
try:
    rows = load_rows(statbl_id, dtacycle, start, end)
except RebApiError as exc:
    st.error(f"API 오류: {exc}")
    st.stop()

if not rows:
    st.warning("데이터가 없습니다. STATBL_ID/기간/인증키를 확인하세요.")
    st.stop()

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
    df = filter_seoul_gu(df)
    if df.empty:
        st.warning("서울 자치구 데이터가 없습니다. '서울 25개 자치구만' 체크를 해제하고 지역명을 확인하세요.")
        st.stop()

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

# ── 상단 요약 KPI ─────────────────────────────────────────
base_month = stats["current_time"].max() if not stats.empty else "-"
top_rise = stats.iloc[0] if not stats.empty else None
# 저가 메리트 = 전고점 대비 수준이 가장 낮은(제일 싼) 구
cheapest = stats.sort_values("recovery_from_peak_pct").iloc[0] if not stats.empty else None

n_breakout = int((stats["status"] == "전고점 돌파").sum()) if not stats.empty else 0
k1, k2, k3, k4 = st.columns(4)
k1.metric("기준월", str(base_month))
k2.metric("전고점 돌파(고가 부담)", f"{n_breakout} / {len(stats)}개 구")
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

    # 국면 분포 요약
    phase_counts = stats["phase"].value_counts()
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

    cand = stats.copy()
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
        view,
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
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**저점 대비 반등폭** (바닥에서 얼마나 올랐나)")
        d = stats.sort_values("rise_from_trough_pct")
        fig = px.bar(d, x="rise_from_trough_pct", y="region", orientation="h",
                     labels={"region": "", "rise_from_trough_pct": "반등(%)"},
                     text="rise_from_trough_pct")
        fig.update_traces(texttemplate="%{text:.1f}", textposition="outside")
        fig.update_layout(height=650, margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        st.markdown("**전고점 대비 수준** (100 미만=고점보다 쌈/메리트, 초과=고점보다 비쌈/부담)")
        d2 = stats.sort_values("recovery_from_peak_pct")
        fig2 = px.bar(d2, x="recovery_from_peak_pct", y="region", orientation="h",
                      labels={"region": "", "recovery_from_peak_pct": "전고점 대비 수준(%)"},
                      text="recovery_from_peak_pct")
        fig2.update_traces(texttemplate="%{text:.1f}", textposition="outside")
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
