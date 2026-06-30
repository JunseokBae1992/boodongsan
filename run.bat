@echo off
REM 윈도우용 실행 스크립트 - 더블클릭 또는 cmd에서 실행
REM 사용 전: 같은 폴더에 .env 파일을 만들고 REB_API_KEY=발급받은키 한 줄 입력
REM (app.py 가 python-dotenv 로 .env 를 자동 로드함)

cd /d "%~dp0"

echo [1/2] 패키지 설치 확인...
pip install -r requirements.txt

echo [2/2] 대시보드 실행 (브라우저가 자동으로 열립니다)...
streamlit run app.py

pause
