# 박스오피스 — KOBIS 일별 박스오피스 API
import datetime

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

st.set_page_config(page_title="박스오피스", page_icon="🎬", layout="wide")

# 인증키는 비밀 금고(secrets)에서 불러온다 — 코드에 직접 쓰지 않는다
API_KEY = st.secrets["KOBIS_KEY"]
URL = "https://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchDailyBoxOfficeList.json"

# 고를 수 있는 가장 늦은 날짜 = 어제 (한국 시간 기준, 오늘 건 아직 집계 전이다)
KST = datetime.timezone(datetime.timedelta(hours=9))
yesterday = datetime.datetime.now(KST).date() - datetime.timedelta(days=1)


@st.cache_data(ttl=3600)  # 같은 날짜는 한 시간 동안 기억해 두고 API를 다시 부르지 않는다
def fetch_boxoffice(date_str):
    """KOBIS API에서 해당 날짜의 일별 박스오피스를 받아 온다."""
    params = {"key": API_KEY, "targetDt": date_str}
    res = requests.get(URL, params=params, timeout=10)
    res.raise_for_status()
    return res.json()


def rank_arrow(v):
    """rankInten(전날 대비 순위 증감)을 색깔 있는 화살표 HTML로 바꾼다."""
    if pd.isna(v) or v == 0:
        return ""
    if v > 0:  # 양수 = 순위가 오름
        return "<span style='color:#e4572e; font-weight:bold;'>▲</span>"
    return "<span style='color:#1f77b4; font-weight:bold;'>▼</span>"  # 음수 = 순위가 내림


st.title("🎬 박스오피스")

# 날짜를 어제로 고정하지 않고, 달력에서 직접 고른다 (오늘은 선택 불가)
selected_date = st.date_input(
    "조회할 날짜를 선택하세요",
    value=yesterday,
    max_value=yesterday,
)
target_dt = selected_date.strftime("%Y%m%d")
st.caption(f"조회 날짜: {selected_date}")

try:
    data = fetch_boxoffice(target_dt)
except requests.RequestException:
    st.error("서버에 연결하지 못했습니다. 인터넷 연결을 확인하고 잠시 뒤 새로고침해 주세요.")
    st.stop()

# 인증키가 틀리면 상태코드는 200이지만 faultInfo 상자가 온다
if "faultInfo" in data:
    st.error(f"API가 오류를 돌려주었습니다: {data['faultInfo'].get('message', '')}")
    st.info("비밀 금고(secrets)의 KOBIS_KEY 값이 올바른지 확인해 주세요.")
    st.stop()

movies = data.get("boxOfficeResult", {}).get("dailyBoxOfficeList", [])

# 영화 목록이 비어서 오면 — 그날은 아직 집계가 안 된 것이다
if not movies:
    st.warning("그날은 아직 집계 전입니다.")
    st.stop()

df = pd.DataFrame(movies)

# 숫자가 글자로 오므로 숫자로 바꿔야 정렬과 그래프에 쓸 수 있다
for col in ["rank", "rankInten", "audiCnt", "audiAcc", "scrnCnt"]:
    df[col] = pd.to_numeric(df[col])

# 1위 영화는 지표 카드 세 장으로 크게
top = df.sort_values("rank").iloc[0]
st.subheader(f"🥇 1위 — {top['movieNm']}")
c1, c2, c3 = st.columns(3)
c1.metric("관객수", f"{top['audiCnt']:,}명")
c2.metric("누적 관객수", f"{top['audiAcc']:,}명")
c3.metric("스크린수", f"{top['scrnCnt']:,}개")

# 전체 순위표
st.subheader("📋 순위표")

table = df.sort_values("rank").copy()

# 증감(rankInten)을 색깔 있는 화살표로 표시
table["증감"] = table["rankInten"].apply(rank_arrow)

# 누적관객이 100만 명을 넘은 영화는 영화명 옆에 트로피 이모지를 붙인다
table["영화명"] = table.apply(
    lambda row: f"{row['movieNm']} 🏆" if row["audiAcc"] >= 1_000_000 else row["movieNm"],
    axis=1,
)

table["관객수"] = table["audiCnt"].apply(lambda v: f"{v:,}")
table["누적관객"] = table["audiAcc"].apply(lambda v: f"{v:,}")
table["스크린수"] = table["scrnCnt"].apply(lambda v: f"{v:,}")
table["개봉일"] = table["openDt"]
table["순위"] = table["rank"]

table = table[["순위", "증감", "영화명", "개봉일", "관객수", "누적관객", "스크린수"]]

# 화살표에 색을 입히기 위해 HTML 표로 그린다 (st.dataframe은 셀 색상을 지원하지 않는다)
st.markdown(table.to_html(escape=False, index=False), unsafe_allow_html=True)

# 관객수 상위 5편은 막대그래프로
st.subheader("📊 관객수 상위 5편")
top5 = df.sort_values("audiCnt", ascending=False).head(5)
fig = px.bar(top5, x="movieNm", y="audiCnt", labels={"movieNm": "영화명", "audiCnt": "관객수"})
st.plotly_chart(fig, width="stretch")
