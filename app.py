"""서울 자치구별 부동산 지수 대시보드 (Streamlit).

한국부동산원 R-ONE OpenAPI에서 (월) 아파트 매매가격지수를 받아
구별 고점/저점/현재 지수와 저점 대비 상승률·고점 대비 회복률을 계산해 보여준다.

실행:
  export REB_API_KEY=발급받은키
  streamlit run app.py
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
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

st.subheader("📊 구별 지표 요약")
nice = stats.rename(columns={
    "region": "지역",
    "peak_value": "고점",
    "peak_time": "고점시점",
    "trough_value": "저점",
    "trough_time": "저점시점",
    "current_value": "현재",
    "current_time": "기준월",
    "rise_from_trough_pct": "저점대비 상승률(%)",
    "recovery_from_peak_pct": "고점대비 회복률(%)",
    "drawdown_pct": "고점대비 낙폭(%)",
})
st.dataframe(nice, use_container_width=True, hide_index=True)
st.download_button("CSV 내려받기", nice.to_csv(index=False).encode("utf-8-sig"),
                   "seoul_index_stats.csv", "text/csv")

col1, col2 = st.columns(2)
with col1:
    st.markdown("**저점 대비 상승률 TOP**")
    fig = px.bar(stats.head(15), x="region", y="rise_from_trough_pct",
                 labels={"region": "지역", "rise_from_trough_pct": "상승률(%)"})
    st.plotly_chart(fig, use_container_width=True)
with col2:
    st.markdown("**고점 대비 회복률**")
    rec = stats.sort_values("recovery_from_peak_pct", ascending=False)
    fig2 = px.bar(rec.head(15), x="region", y="recovery_from_peak_pct",
                  labels={"region": "지역", "recovery_from_peak_pct": "회복률(%)"})
    fig2.add_hline(y=100, line_dash="dash", line_color="red")
    st.plotly_chart(fig2, use_container_width=True)

st.subheader("📈 지역별 지수 추이")
regions = sorted(df["region"].unique())
picked = st.multiselect("지역 선택", regions, default=regions[:3])
if picked:
    sub = df[df["region"].isin(picked)]
    line = px.line(sub, x="time", y="value", color="region",
                   labels={"time": "기간", "value": "지수", "region": "지역"})
    st.plotly_chart(line, use_container_width=True)

    for region in picked:
        s = compute_stats(df[df["region"] == region])
        if s:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric(f"{region} 현재", f"{s.current_value:.1f}", f"{s.current_time}")
            c2.metric("고점", f"{s.peak_value:.1f}", f"{s.peak_time}")
            c3.metric("저점 대비 상승률", f"{s.rise_from_trough_pct:.2f}%")
            c4.metric("고점 대비 회복률", f"{s.recovery_from_peak_pct:.2f}%")
