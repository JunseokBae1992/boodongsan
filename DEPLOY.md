# 배포 가이드 — 다른 사람도 볼 수 있게 공개하기

본인 PC에서 `streamlit run` 하면 그 PC에서만 보입니다.
인터넷 주소(URL)로 누구나 접속하게 하려면 아래 중 하나로 "배포"하세요.

---

## 방법 1. Streamlit Community Cloud (무료, 가장 쉬움) ⭐ 추천

GitHub 레포만 연결하면 공개 URL이 자동 생성됩니다.

### 절차
1. https://share.streamlit.io 접속 → **GitHub 계정으로 로그인**
2. **"Create app" → "Deploy a public app from GitHub"** 선택
3. 항목 입력:
   - **Repository**: `junseokbae1992/boodongsan`
   - **Branch**: `claude/seoul-realestate-index-calc-pu4u37` (또는 main 에 머지 후 main)
   - **Main file path**: `app.py`
4. **"Advanced settings" → "Secrets"** 에 인증키를 아래 형식으로 입력:
   ```toml
   REB_API_KEY = "발급받은_인증키"
   ```
5. **Deploy** 클릭 → 잠시 후 `https://<앱이름>.streamlit.app` 주소가 생성됩니다.

> 코드가 이미 `st.secrets` 의 `REB_API_KEY` 를 읽도록 처리돼 있어,
> 위 Secrets 만 넣으면 바로 동작합니다.

> ⚠️ 한국부동산원 API가 해외(클라우드) IP를 막는 경우가 드물게 있습니다.
> 데이터가 안 나오면 "방법 3"(국내 서버)로 전환하세요.

---

## 방법 2. 같은 네트워크(집/사무실) 안에서만 공유 — 설치 없이 즉시

같은 와이파이에 있는 사람만 접속 가능. 배포 아님, 임시 공유용.

```powershell
python -m streamlit run app.py --server.address=0.0.0.0
```
실행하면 터미널에 `Network URL: http://192.168.x.x:8501` 이 표시됩니다.
같은 네트워크의 다른 사람이 그 주소로 접속하면 됩니다.
(본인 PC가 켜져 있어야 하고, 방화벽에서 8501 허용 필요)

---

## 방법 3. 직접 서버(VPS/클라우드)에 Docker로 배포 — 국내 서버 권장

24시간 운영, 국내 IP 사용 가능. AWS/네이버클라우드/가비아 등 리눅스 서버에서:

```bash
git clone https://github.com/junseokbae1992/boodongsan.git
cd boodongsan
docker build -t boodongsan .
docker run -d -p 80:8501 -e REB_API_KEY=발급받은키 --restart unless-stopped boodongsan
```
서버 공인 IP(또는 연결한 도메인)로 누구나 접속 가능합니다.

---

## 어떤 걸 고를까?

| 상황 | 추천 |
|------|------|
| 그냥 빨리 남들에게 보여주고 싶다 | **방법 1 (Streamlit Cloud)** |
| 같은 사무실/집 사람만 잠깐 본다 | 방법 2 |
| 정식 서비스/24시간/국내 IP 필요 | 방법 3 (서버 구축 시) |

> 공통 주의: 어느 방법이든 인증키는 코드/깃에 넣지 말고
> **Secrets 또는 환경변수**로만 주입하세요. (`.env` 는 `.gitignore` 처리됨)
