# 서울 자치구 부동산 지수 분석

한국부동산원 **R-ONE 부동산통계 OpenAPI**를 통해 서울 25개 자치구의
**(월) 아파트 매매가격지수**를 받아와, 구별 **고점 · 저점 · 현재 지수**와
**저점 대비 상승률**, **고점 대비 회복률**을 계산하는 웹 대시보드입니다.

## 지표 정의

| 지표 | 계산식 |
|------|--------|
| 고점 | 시계열 최고값 |
| 저점 | **직전 고점 이후 구간의 최저값** (부동산 사이클 바닥) |
| 현재 | 최신월 지수 |
| 저점 대비 상승률 | `(현재 − 저점) / 저점 × 100` |
| 고점 대비 회복률 | `현재 / 고점 × 100` |
| 고점 대비 낙폭 | `저점 / 고점 × 100 − 100` |

> 저점은 "전체 최저"가 아니라 **고점을 찍은 뒤의 바닥**으로 정의합니다.
> 따라서 고점 이전에 더 낮은 값이 있어도 무시하며, 아직 하락 전이라면
> 저점=현재값(상승률 0%, 회복률 100%)이 됩니다.

## 사전 준비: 인증키 발급

OpenAPI 인증키(`KEY`)가 **반드시** 필요합니다.

1. https://www.reb.or.kr/r-one/portal/openapi/openApiIntroPage.do (로그인 후 인증키 발급)
2. 또는 공공데이터포털 https://www.data.go.kr/data/15134761/openapi.do 에서 활용신청

발급받은 키를 환경변수로 설정합니다.

```bash
cp .env.example .env
# .env 파일을 열어 REB_API_KEY 값을 채웁니다
# 또는
export REB_API_KEY="발급받은_인증키"
```

## 설치 & 실행

```bash
pip install -r requirements.txt

# 1) 통계표/지역/항목 코드 확인 (선택)
python discover.py sample A_2024_00045

# 2-a) 웹 대시보드 실행
streamlit run app.py

# 2-b) 헤드리스 리포트 (서버/cron용, 표 출력 + CSV 저장)
python report.py --start 201501 --out seoul.csv
```

### Docker (서버 배포)

```bash
docker build -t boodongsan .

# 대시보드
docker run -p 8501:8501 -e REB_API_KEY=발급받은키 boodongsan

# 헤드리스 리포트
docker run -e REB_API_KEY=발급받은키 boodongsan python report.py --out /tmp/seoul.csv
```

대시보드 좌측에서 `STATBL_ID`, 주기(`DTACYCLE_CD`), 기간을 조정할 수 있습니다.
기본값은 `A_2024_00045` (월간 아파트 매매가격지수), `MM`(월간)입니다.

## 구성

| 파일 | 설명 |
|------|------|
| `reb_api.py` | R-ONE OpenAPI 클라이언트 (재시도, JSON 파싱) |
| `analysis.py` | 고점/저점/현재 및 비율 계산 |
| `app.py` | Streamlit 대시보드 (표 · 차트 · CSV 내보내기) |
| `report.py` | 헤드리스 리포트 CLI (서버/cron용, 표 출력 + CSV) |
| `discover.py` | STATBL_ID / CLS_ID / ITM_ID 탐색 CLI |
| `Dockerfile` | 컨테이너 배포용 |
| `test_analysis.py` | 계산 로직 단위 테스트 (API 키 불필요) |

## 테스트

```bash
python test_analysis.py
```

## 참고

- API 응답 표기(컬럼명, 지역명)가 통계표마다 다를 수 있어, `reb_api.py`와
  `analysis.py`는 여러 키 후보를 자동 탐색하도록 작성되어 있습니다.
  실제 응답과 다르면 `python discover.py sample <STATBL_ID>`로 컬럼을 확인하세요.
- 월간 통계가 자치구 단위를 제공하지 않는 경우, 주기를 `QY`(분기)로 바꾸거나
  다른 `STATBL_ID`를 사용하세요.
