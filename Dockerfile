FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8501

# 인증키는 런타임에 환경변수로 주입: docker run -e REB_API_KEY=...
# 대시보드 실행 (헤드리스 리포트는: docker run ... python report.py)
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501"]
