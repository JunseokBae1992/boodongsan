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
def load_series(statbl_id: str, dtacycle: str, start: str, end: str) -> pd.DataFrame:
    client = RebClient.from_env()
    rows = client.fetch_series(
        statbl_id=statbl_id,
        dtacycle_cd=dtacycle,
        start_wrttime=start or None,
        end_wrttime=end or None,
    )
    return rows_to_frame(rows)


def filter_seoul_gu(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    mask = df["region"].apply(lambda x: any(gu in str(x) for gu in SEOUL_GU))
    return df[mask].copy()


with st.sidebar:
    st.header("설정")
    statbl_id = st.text_input("STATBL_ID", DEFAULT_STATBL_ID,
                              help="(월) 매매가격지수_아파트 = A_2024_00045")
    dtacycle = st.text_input("DTACYCLE_CD", DEFAULT_DTACYCLE_CD, help="MM=월, QY=분기, YY=연")
    start = st.text_input("시작 기간 (YYYYMM)", "201501")
    end = st.text_input("종료 기간 (YYYYMM)", "")
    only_gu = st.checkbox("서울 25개 자치구만", value=True)
    run = st.button("데이터 불러오기", type="primary")

if run:
    st.session_state["loaded"] = True

if not st.session_state.get("loaded"):
    st.info("좌측에서 인증키 환경변수(REB_API_KEY) 설정 후 **데이터 불러오기**를 누르세요.")
    st.stop()

try:
    df = load_series(statbl_id, dtacycle, start, end)
except RebApiError as exc:
    st.error(f"API 오류: {exc}")
    st.stop()

if df.empty:
    st.warning("데이터가 없습니다. STATBL_ID/기간/인증키를 확인하세요.")
    st.stop()

if only_gu:
    df = filter_seoul_gu(df)
    if df.empty:
        st.warning("서울 자치구 데이터가 없습니다. '서울 25개 자치구만' 체크를 해제하고 지역명을 확인하세요.")
        st.stop()

stats = compute_all(df)

# ── 상단 요약 KPI ─────────────────────────────────────────
base_month = stats["current_time"].max() if not stats.empty else "-"
top_rise = stats.iloc[0] if not stats.empty else None
top_rec = stats.sort_values("recovery_from_peak_pct", ascending=False).iloc[0] if not stats.empty else None

k1, k2, k3, k4 = st.columns(4)
k1.metric("기준월", str(base_month))
k2.metric("분석 지역 수", f"{len(stats)}개 구")
if top_rise is not None:
    k3.metric("상승률 1위", top_rise["region"], f"저점대비 +{top_rise['rise_from_trough_pct']:.1f}%")
if top_rec is not None:
    k4.metric("회복률 1위", top_rec["region"], f"고점대비 {top_rec['recovery_from_peak_pct']:.1f}%")

st.divider()

tab_rank, tab_chart, tab_trend = st.tabs(["📋 구별 순위표", "📊 상승률·회복률", "📈 지수 추이"])

# ── 순위표 탭 ─────────────────────────────────────────────
with tab_rank:
    sort_key = st.radio(
        "정렬 기준", ["저점대비 상승률", "고점대비 회복률", "고점대비 낙폭", "지역명"],
        horizontal=True,
    )
    key_map = {
        "저점대비 상승률": ("rise_from_trough_pct", False),
        "고점대비 회복률": ("recovery_from_peak_pct", False),
        "고점대비 낙폭": ("drawdown_pct", True),
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
            "current_value": st.column_config.NumberColumn("현재지수", format="%.1f"),
            "current_time": st.column_config.TextColumn("기준월"),
            "peak_value": st.column_config.NumberColumn("고점", format="%.1f"),
            "peak_time": st.column_config.TextColumn("고점시점"),
            "trough_value": st.column_config.NumberColumn("저점", format="%.1f"),
            "trough_time": st.column_config.TextColumn("저점시점"),
            "rise_from_trough_pct": st.column_config.ProgressColumn(
                "저점대비 상승률(%)", format="%.1f%%",
                min_value=0, max_value=float(max(stats["rise_from_trough_pct"].max(), 1)),
            ),
            "recovery_from_peak_pct": st.column_config.NumberColumn("고점대비 회복률(%)", format="%.1f%%"),
            "drawdown_pct": st.column_config.NumberColumn("고점대비 낙폭(%)", format="%.1f%%"),
        },
        column_order=[
            "region", "current_value", "current_time",
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
        st.markdown("**저점 대비 상승률**")
        d = stats.sort_values("rise_from_trough_pct")
        fig = px.bar(d, x="rise_from_trough_pct", y="region", orientation="h",
                     labels={"region": "", "rise_from_trough_pct": "상승률(%)"},
                     text="rise_from_trough_pct")
        fig.update_traces(texttemplate="%{text:.1f}", textposition="outside")
        fig.update_layout(height=650, margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        st.markdown("**고점 대비 회복률** (100 = 고점 완전 회복)")
        d2 = stats.sort_values("recovery_from_peak_pct")
        fig2 = px.bar(d2, x="recovery_from_peak_pct", y="region", orientation="h",
                      labels={"region": "", "recovery_from_peak_pct": "회복률(%)"},
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
        sub = df[df["region"].isin(picked)]
        line = px.line(sub, x="time", y="value", color="region",
                       labels={"time": "기간", "value": "지수", "region": "지역"})
        line.update_layout(height=450, legend_title_text="지역")
        st.plotly_chart(line, use_container_width=True)

        for region in picked:
            s = compute_stats(df[df["region"] == region])
            if s:
                st.markdown(f"**{region}**")
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("현재지수", f"{s.current_value:.1f}", f"{s.current_time}")
                c2.metric("고점", f"{s.peak_value:.1f}", f"{s.peak_time}")
                c3.metric("저점대비 상승률", f"{s.rise_from_trough_pct:.1f}%")
                c4.metric("고점대비 회복률", f"{s.recovery_from_peak_pct:.1f}%")
    else:
        st.info("비교할 지역을 하나 이상 선택하세요.")
