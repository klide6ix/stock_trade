import os
from dotenv import load_dotenv

load_dotenv()

# 모의투자: True / 실전투자: False
IS_MOCK = False

# 모드 라벨 (대시보드 배지·로그용)
MODE_LABEL = "모의투자" if IS_MOCK else "실전투자"

# KIS API 인증 정보 — 모의/실전 키를 분리해 IS_MOCK 토글만으로 안전하게 전환.
#   실전: APP_KEY / APP_SECRET / ACCOUNT_NO
#   모의: MOCK_APP_KEY / MOCK_APP_SECRET / MOCK_ACCOUNT_NO  (한국투자증권이 모의투자용으로 별도 발급)
# 모의 키가 .env 에 없으면 단일 키(APP_KEY ...)로 fallback — 기존 단일 키 설정과의 하위 호환.
# 실전 모드는 절대 MOCK_* 를 쓰지 않으므로, 모의 키가 실거래에 새어 들어갈 위험이 없다.
if IS_MOCK:
    BASE_URL = "https://openapivts.koreainvestment.com:29443"
    APP_KEY = os.getenv("MOCK_APP_KEY") or os.getenv("APP_KEY")
    APP_SECRET = os.getenv("MOCK_APP_SECRET") or os.getenv("APP_SECRET")
    ACCOUNT_NO = os.getenv("MOCK_ACCOUNT_NO") or os.getenv("ACCOUNT_NO")  # 예: "12345678-01"
else:
    BASE_URL = "https://openapi.koreainvestment.com:9443"
    APP_KEY = os.getenv("APP_KEY")
    APP_SECRET = os.getenv("APP_SECRET")
    ACCOUNT_NO = os.getenv("ACCOUNT_NO")  # 예: "12345678-01"

# 트레이딩 설정
STOP_LOSS_PCT = 10.0    # 최고점 대비 하락 % (10 = 10%)
CHECK_INTERVAL = 60     # 가격 확인 주기 (초, 60 = 1분) — 손절 반응성 우선. 보유 종목당 현재가 호출 ×사이클이라 KIS rate limit 여유(분당 수회 수준)
