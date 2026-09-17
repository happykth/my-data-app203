# -*- coding: utf-8 -*-
"""
어제의 박스오피스 - 스트림릿 앱
KOBIS(영화진흥위원회) 일별 박스오피스 API를 사용합니다.

[초보자를 위한 설명]
- 이 파일 하나만 있으면 스트림릿 클라우드에 그대로 올릴 수 있어요.
- 인증키(API 키)는 코드에 직접 적지 않고, 스트림릿의 "비밀 금고"(secrets)에서 불러옵니다.
  스트림릿 클라우드 배포 화면의 [Settings] > [Secrets] 메뉴에 아래처럼 한 줄을 넣어주세요.

  KOBIS_KEY = "여기에_발급받은_인증키"

  로컬 컴퓨터에서 테스트하고 싶다면, main.py와 같은 폴더에 .streamlit 폴더를 만들고
  그 안에 secrets.toml 파일을 만들어 같은 내용을 넣으면 됩니다.
"""

import streamlit as st
import requests
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo  # 파이썬 표준 라이브러리라 별도 설치가 필요 없어요.

# -----------------------------
# 1. 기본 화면 설정
# -----------------------------
st.set_page_config(
    page_title="어제의 박스오피스",
    page_icon="🎬",
    layout="wide",
)

# 따뜻한 색감을 위한 색상 팔레트 (그래프 등에 사용)
WARM_COLORS = ["#E4572E", "#F3A712", "#EF6461", "#F2C14E", "#D9A05B"]

# KOBIS 일별 박스오피스 API 주소
API_URL = "https://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchDailyBoxOfficeList.json"


# -----------------------------
# 2. '어제' 날짜 계산하기 (한국 시간 기준!)
# -----------------------------
def get_yesterday_kst() -> str:
    """
    배포 서버의 시계가 한국 시간이 아닐 수 있으므로,
    반드시 한국 시간(Asia/Seoul) 기준으로 '오늘'을 구한 뒤 하루를 뺍니다.
    반환값은 API가 원하는 형식인 'yyyymmdd' 문자열입니다.
    """
    now_kst = datetime.now(ZoneInfo("Asia/Seoul"))
    yesterday_kst = now_kst - timedelta(days=1)
    return yesterday_kst.strftime("%Y%m%d")


# -----------------------------
# 3. API 호출 함수 (1시간 동안 결과를 기억함 = 캐시)
# -----------------------------
@st.cache_data(ttl=3600)  # ttl=3600초(1시간) 동안은 같은 target_dt로 다시 안 부르고 저장된 값을 씀
def fetch_box_office(target_dt: str):
    """
    KOBIS API를 호출해서 그 날짜의 박스오피스 목록을 가져옵니다.
    성공하면 (True, 영화 리스트) 를 반환하고,
    실패하면 (False, "사용자에게 보여줄 한국어 안내 메시지") 를 반환합니다.
    """
    api_key = st.secrets.get("KOBIS_KEY")
    if not api_key:
        return False, (
            "인증키를 찾을 수 없습니다. 스트림릿 클라우드의 [Settings] > [Secrets]에서 "
            "KOBIS_KEY 값이 올바르게 등록되어 있는지 확인해 주세요."
        )

    params = {
        "key": api_key,
        "targetDt": target_dt,
    }

    # 1) 네트워크 요청 자체가 실패하는 경우 (타임아웃, 연결 오류 등)
    try:
        response = requests.get(API_URL, params=params, timeout=10)
    except requests.exceptions.RequestException:
        return False, (
            "KOBIS 서버에 연결하지 못했습니다. 인터넷 연결 상태나 잠시 후 다시 시도해 주세요."
        )

    # 2) HTTP 상태 코드가 200이 아닌 경우 (요청 자체가 서버에서 거부됨)
    if response.status_code != 200:
        return False, (
            f"KOBIS 서버가 오류 응답(상태 코드 {response.status_code})을 보냈습니다. "
            "잠시 후 다시 시도해 주세요."
        )

    # 3) 응답이 JSON 형식이 아닌 경우
    try:
        data = response.json()
    except ValueError:
        return False, "KOBIS 서버 응답을 해석할 수 없습니다. 잠시 후 다시 시도해 주세요."

    # 4) 상태 코드는 200이어도 인증키가 틀리면 faultInfo 상자가 옵니다.
    if "faultInfo" in data:
        message = data["faultInfo"].get("message", "알 수 없는 오류")
        return False, (
            f"KOBIS API가 오류를 반환했습니다: {message}\n"
            "인증키(KOBIS_KEY)가 정확한지, 사용량 한도를 넘지 않았는지 확인해 주세요."
        )

    # 5) 정상 구조인지 확인
    box_office_result = data.get("boxOfficeResult")
    if not box_office_result:
        return False, "응답 형식이 예상과 다릅니다. KOBIS API 문서가 변경되지 않았는지 확인해 주세요."

    movie_list = box_office_result.get("dailyBoxOfficeList")

    # 6) 영화 목록이 비어 있는 경우 (예: 너무 이른 날짜, 데이터 없음 등)
    if not movie_list:
        return False, (
            "해당 날짜의 박스오피스 데이터가 비어 있습니다. "
            "조회 날짜(targetDt)가 너무 최근이거나, 아직 집계가 완료되지 않았을 수 있습니다."
        )

    return True, movie_list


# -----------------------------
# 4. 데이터 정리하기 (문자열 숫자 -> 진짜 숫자로 변환)
# -----------------------------
def to_dataframe(movie_list: list) -> pd.DataFrame:
    """
    API가 준 리스트를 표(DataFrame)로 만들고,
    숫자여야 하는 열들을 문자열에서 정수로 바꿔줍니다.
    (예: "12345" -> 12345)
    """
    df = pd.DataFrame(movie_list)

    numeric_columns = ["rank", "audiCnt", "audiAcc", "scrnCnt", "showCnt"]
    for col in numeric_columns:
        if col in df.columns:
            # errors="coerce": 혹시 숫자로 못 바꾸는 값이 있으면 에러 대신 빈 값(NaN) 처리
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 순위(rank) 기준으로 정렬
    df = df.sort_values("rank").reset_index(drop=True)
    return df


# -----------------------------
# 5. 화면 그리기
# -----------------------------
def main():
    st.title("🎬 어제의 박스오피스")

    target_dt = get_yesterday_kst()
    display_date = f"{target_dt[:4]}년 {target_dt[4:6]}월 {target_dt[6:]}일"
    st.caption(f"기준 날짜: {display_date} (한국 시간 기준 '어제')")

    with st.spinner("박스오피스 정보를 불러오는 중..."):
        success, result = fetch_box_office(target_dt)

    # 실패했을 때: 빈 화면 대신 무엇을 확인해야 하는지 안내
    if not success:
        st.error(result)
        st.stop()

    df = to_dataframe(result)

    # --- 5-1. 1위 영화: 지표 카드 3장 ---
    top1 = df.iloc[0]
    st.subheader(f"👑 1위: {top1['movieNm']}")

    col1, col2, col3 = st.columns(3)
    col1.metric("어제 관객수", f"{int(top1['audiCnt']):,}명")
    col2.metric("누적 관객수", f"{int(top1['audiAcc']):,}명")
    col3.metric("스크린수", f"{int(top1['scrnCnt']):,}개")

    st.divider()

    # --- 5-2. 관객수 상위 5편 막대그래프 ---
    st.subheader("📊 관객수 상위 5편")
    top5 = df.sort_values("audiCnt", ascending=False).head(5)

    fig = px.bar(
        top5,
        x="movieNm",
        y="audiCnt",
        text="audiCnt",
        color="movieNm",
        color_discrete_sequence=WARM_COLORS,
        labels={"movieNm": "영화명", "audiCnt": "관객수"},
    )
    fig.update_traces(texttemplate="%{text:,}", textposition="outside")
    fig.update_layout(showlegend=False, xaxis_title=None, yaxis_title="관객수(명)")
    st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # --- 5-3. 전체 표 ---
    st.subheader("📋 전체 순위표")
    table_df = df[["rank", "movieNm", "openDt", "audiCnt", "audiAcc", "scrnCnt"]].copy()
    table_df.columns = ["순위", "영화명", "개봉일", "관객수", "누적관객수", "스크린수"]

    st.dataframe(
        table_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "관객수": st.column_config.NumberColumn(format="%d"),
            "누적관객수": st.column_config.NumberColumn(format="%d"),
            "스크린수": st.column_config.NumberColumn(format="%d"),
        },
    )


if __name__ == "__main__":
    main()
