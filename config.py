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

# 장 전 준비(pre-market) 시작 시각 — 정규장(09:00) 개장 전, 매매는 불가하지만 조회는 가능한 구간.
# 이 시각부터 매수·단타 후보를 미리 선정해 개장과 동시에 매매에 진입할 수 있게 한다.
# 장외(시간외) 거래가 8:00/8:30 부터 시작되는 경우에 대응. settings.json 에서 변경 가능.
PRE_MARKET_OPEN = "08:30"

# ── 일 단위 단기 매매(ETF 방향 매매) 청산 기준 ────────────────────────────────
#
# 둘 다 settings.json 에서 사이드바로 조절 가능하며, 여기 값은 그 초기값이다.
#
# 왜 10% 인가: 코스피200 이 일간 σ 6.5% · 장중 고가→저가 낙폭 평균 6.34%(5% 이상인 날
# 63%)인 고변동 국면이라, 이전 기본값 5% 는 **정상 변동폭 안에 있었다**. 2026-07
# 시뮬레이션(시드 300만·22거래일, `scripts/_simulate_july.py`)에서 5%/5% 는 청산 20회 중
# 17회가 최고가 청산이었고, 장중 고가·저가 순서 가정에 따라 -22.26% ~ +10.48% 로 갈려
# 손익 판정조차 불가능했다. 둘 다 10% 로 넓히면 +26.72% ~ +50.34% 로 두 경로 모두 양(+)이
# 된다.
#
# 두 값을 함께 올려야 하는 이유: 최고가(peak)는 항상 매수가 이상이므로 `최고가 × 0.9` 가
# `매수가 × 0.9` 보다 늘 위에 있다. 즉 **최고가 청산이 손절보다 먼저 걸리므로**, 최고가
# 청산선을 그대로 둔 채 손절만 넓히면 손절선은 도달할 기회조차 없어 결과가 바뀌지 않는다
# (실측: 최고가 5% 고정 시 손절을 5→15% 로 늘려도 보수 경로 -22.26% 로 동일).
SHORT_TERM_STOP_LOSS_PCT = 10.0   # 매수가 대비 손절 하락률 %
SHORT_TERM_PEAK_DROP_PCT = 10.0   # 매수 이후 최고가 대비 청산 하락률 % (트레일링)
