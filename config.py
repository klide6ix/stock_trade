import os
from dotenv import load_dotenv

load_dotenv()

# KIS API 인증 정보
APP_KEY = os.getenv("APP_KEY")
APP_SECRET = os.getenv("APP_SECRET")
ACCOUNT_NO = os.getenv("ACCOUNT_NO")  # 예: "12345678-01"

# 모의투자: True / 실전투자: False
IS_MOCK = False

# API URL
if IS_MOCK:
    BASE_URL = "https://openapivts.koreainvestment.com:29443"
else:
    BASE_URL = "https://openapi.koreainvestment.com:9443"

# 트레이딩 설정
STOP_LOSS_PCT = 10.0    # 최고점 대비 하락 % (10 = 10%)
CHECK_INTERVAL = 600    # 가격 확인 주기 (초, 600 = 10분)
