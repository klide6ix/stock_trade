# 자동 주식 트레이더

## 개요

한국투자증권 KIS REST API를 이용해 보유 주식이 **최고점 대비 10% 하락** 시 자동으로 시장가 매도하는 프로그램.

---

## 진행 상태

- [x] 프로젝트 구조 설계
- [x] KIS API 연동 코드 작성 (인증, 잔고조회, 현재가, 매도주문)
- [x] 트레이딩 로직 작성 (최고가 추적 + 손절 조건 확인)
- [x] 한국투자증권 계좌 개설 및 API 키 발급
- [x] `.env` 파일에 API 키 입력
- [x] 모의투자로 테스트
- [x] 실전투자 전환
- [x] Streamlit 대시보드 추가 (보유 종목, 수익률, 손절 상태 시각화)
- [x] `main.py` 단일 실행으로 트레이더 + 대시보드 동시 구동
- [x] 장 마감/주말에도 대시보드 조회 가능 (캐시 기반 마지막 가격 표시)
- [x] `trader.py` 로그 파일(`logs/trader.log`) 기록 추가
- [x] 매수 후보 탐색 로직 추가 (시작 시 1회 실행, `data/buy_candidates.json` 저장)
- [x] 대시보드에 매수 후보 목록 표시 (거래량 상위 5종목 위에)
- [x] 매수/매도 거래 이력 저장 (`data/trade_history.json`) 및 대시보드 표시
- [x] 프로그램 재시작 시 최고가 복원 (`data/peak_prices.json`)
- [x] 로그/데이터 파일을 `logs/`, `data/` 폴더로 분리
- [x] 매수/매도 로직을 Strategy 패턴으로 리팩터링 (`core/strategy/`)
- [x] Strategy 디렉터리 `buy/` · `sell/` 로 분리, `SellStrategy` 인터페이스 범용화 (최고가 상태는 전략 내부로 이전)
- [x] `get_market_cap_rank` KIS 엔드포인트 수정 (`ranking/market-cap`, tr_id `FHPST01740000`) — 404 해결
- [x] KIS 접근토큰 디스크 캐싱 (`data/.kis_token_{mock|real}.json`) — 재시작 시 1분 rate limit 회피
- [x] 매수 후보 전략에 PER·EPS 기반 가치 평가 추가 (`get_per_eps` API, EPS 음수 종목 제외, PER*EPS + 주간등락률 순위 합산 정렬)
- [x] 실제 매수 주문 자동화: 시작 시 예수금을 후보 수로 균등 분할하여 시장가 매수 (슬롯 < 주가여도 최소 1주), 매도 발생 시 후보 재탐색 후 미보유 최상위 1종목을 남은 예수금으로 재매수 (`buy_market_order` 추가)
- [x] 매수 계획 로직을 순수 함수 `plan_initial_buy` 로 분리, 장 마감 시 대시보드에 "매수 예정 미리보기" 표시 (예수금 · 슬롯 · 예상 총액 + 종목별 수량/금액)
- [x] 매수 활성화 옵션 추가 (`data/settings.json`에 영속화, 대시보드 사이드바 토글로 on/off, 기본값 OFF) — 초기매수·매도후재매수 모두 이 플래그를 검사
- [x] 대시보드 자동 새로고침 on/off · 주기(초)도 `data/settings.json`에 영속화, 앱 재시작 시 이전 값 복원
- [x] 대시보드 매수 후보 섹션에 수동 새로고침 버튼 추가 (클릭 시 후보 재탐색 → 파일 저장 → UI 갱신)
- [x] 매수 주문 시 `예수금`(총액) 대신 `주문가능금액`(`nxdy_excc_amt`) 사용하도록 수정 — 이미 매수한 금액을 제외한 실제 주문 가능 금액 기준
- [x] 대시보드 상단에 예수금·주문가능금액 분리 표시
- [x] 매수 후보 선정 기준 변경: `종합순위점수` → `종합티어`로 리네임
- [x] 종합티어 산식 보정: PER*EPS(=주가) 제거 → PER 오름차순 + EPS 내림차순 + 주간등락률 내림차순 3개 순위 합산, PER ≤ 0 종목 제외
- [x] 매수 후보를 종합티어 상위 4종목으로 고정 (`pick_n=4`)
- [x] 대시보드 "거래량 상위 5종목" 섹션 제거 (테스트용 항목 정리), `get_volume_rank` API 함수도 함께 삭제
- [x] 종합티어 가중치 적용: 주간등락률 50%, PER 25%, EPS 25%
- [x] 매수 후보 거래량 상위 20 사전 필터 제거 — 시가총액 상위 100 전체에 종합티어 적용
- [x] 매수 후보 일간등락률 사전 필터 도입 (`get_fluctuation_rank`): 시총 100 ∩ 일간등락률 상위 → 풀 20개에 대해서만 weekly+PER/EPS 조회 (API 호출 200 → 약 42회)
- [x] 일간등락률 교집합 부족 시 시총 상위로 풀 보충 (KIS 일간 상위 상승률 ≒ 중·소형주 → 시총 100 교집합이 비는 케이스 대응) + 진단 로그 추가
- [x] 매수 전략 2종 추가: `HighProximityBuyStrategy`(52주 신고가 근접도 + PER/EPS) / `TechnicalMomentumBuyStrategy`(이평선 정배열·RSI(14)·거래량폭증·20일수익률)
- [x] KIS API 추가: `get_quote_snapshot`(52주 고/저 + PER/EPS/PBR 일괄), `get_daily_ohlcv`(일봉 OHLCV 시계열, `inquire-daily-itemchartprice`)
- [x] 모멘텀 전략 공통 풀 선정 헬퍼 `_pool.select_momentum_universe` 로 추출 (시총 ∩ 일간등락률 + 보충)
- [x] `main.py` · 대시보드 매수 후보 새로고침을 `HighProximityBuyStrategy` 로 전환 (TechnicalMomentum 은 정배열·RSI 필터에서 후보 0개로 통과 종목이 없어 일단 비활성)
- [x] `HighProximityBuyStrategy` 단순화: PER/EPS 가중 제거 → **PER ≤ 30 하한 필터 + EPS≥0** 만 유지, 정렬은 52주 신고가 근접도 단일 기준 (모멘텀 + 가치 신호 미스매치 회피)
- [x] `TechnicalMomentumBuyStrategy` 조건 완화: 정배열 `5MA>20MA>60MA` → `5MA>20MA`, RSI 상한 75 → 80, 최소 일봉 요구 60 → 21 (필터 통과 종목 0개 문제 대응)
- [x] 매수 후보를 전략별로 분리 표시: `Trader(view_strategies=[...])` 인자로 보조 전략 추가 가능, `BuyStrategy.display_name` property 도입, 후보 dict에 `_strategy`/`_strategy_label` 메타 필드 주입, 대시보드는 그룹별 테이블 + "매수 실행" / "view-only" 라벨 표시 (현재 primary=`HighProximity`, view=`TechnicalMomentum`)
- [x] 대시보드 후보 테이블을 컬럼 유연 렌더링으로 변경 (`*(%)` 컬럼 자동 포맷/색상)
- [x] `buy_candidates.json` 에 `status` 필드 도입 (`refreshing` / `ready`) — trader 시작 시·새로고침 시 즉시 갱신 마커를 써서 대시보드가 직전 세션의 stale 후보 대신 "🔄 매수 후보 탐색 중..." 안내 표시
- [x] `HighProximityBuyStrategy` 신고가 기준 52주 → 4주(20영업일)로 단축 (`window_days` 파라미터, `get_daily_ohlcv` 일봉으로 직접 계산) — 텀이 너무 길어 모멘텀 신호가 둔해지는 문제 대응
- [x] 매수 후보 1차 풀 사이즈 20 → 50 으로 확대 (`select_momentum_universe`·두 전략 기본값), 일간등락률 호출 `top_n` 도 풀 사이즈의 2배 자동 산정 — 후보가 신고가 종목으로만 쏠리는 다양성 부족 문제 대응
- [x] 우량+우상향 결합 전략 `QualityTrendBuyStrategy` 추가: EPS≥0 ∧ 0<PER≤50 ∧ 0<PBR≤5 ∧ 20MA>60MA ∧ 현재가>20MA ∧ RSI(14)≤70 필터 → 4주 신고가 근접도 정렬 상위 4. 탈락 카운트(가치/추세/RSI) 로그
  - PER 컷 30 → 50 완화: 한국시장 시총상위 100 중 반도체·2차전지·바이오 성장주 PER 30~50 다수 → 모멘텀 종목 누락 방지
  - PBR ≤ 5 추가: PER 만으로는 EPS 일시 급감 종목이 PER 비정상 통과할 수 있어 자산 기준 거품 차단 보강
- [x] 매수 실행 전략 `HighProximityBuyStrategy` → `QualityTrendBuyStrategy` 로 교체. HighProximity·TechnicalMomentum 은 view-only 보조 전략으로 비교 표시 (`main.py` + `ui/dashboard.py` 수동 새로고침 버튼 양쪽 모두)
- [x] 활성 매수 전략 구성을 `core/strategy/_activate.py` 로 추출 (`primary_buy_strategy()` / `view_buy_strategies()`) — `main.py`·`ui/dashboard.py` 가 동일 모듈을 import 하므로 전략 교체 시 한 곳만 수정
- [x] 기술 지표 헬퍼(`sma`, `rsi`)를 `_indicators.py` 로 추출 (`technical_momentum`·`quality_trend` 공유)
- [x] Python 3.14 기반 `.venv` 가상환경으로 실행 환경 통일 — `start.sh` 가 `.venv/bin/python` 으로 `main.py` 실행, 부재 시 안내 메시지 후 종료. 시스템 Python(3.9)/Homebrew Python(3.11) 혼용으로 인한 의존성 불일치 회피
- [x] 손절 기준(`stop_loss_pct`) 옵션화 — 대시보드 사이드바 number_input(1.0~50.0%, step 0.5)으로 변경 가능, `data/settings.json` 영속화. 기본값은 `config.STOP_LOSS_PCT`(10%) 사용. 트레이더는 매 확인 주기 시작 시 settings 재읽기 → `TrailingStopSellStrategy.stop_loss_pct` 갱신(변경 시 로그)

## 다음 작업 후보

- [ ] 매도 발생 시 알림 (Telegram / 카카오톡 등)
- [ ] 확인 주기를 대시보드에서 실시간 변경
- [ ] 추가 전략 구현 (예: RSI / 이동평균 기반 매도, 시가총액 외 다른 매수 기준)

---

## 설정값

| 항목           | 값                   |
| -------------- | -------------------- |
| 손절 기준      | 최고점 대비 10% 하락 |
| 가격 확인 주기 | 10분                 |
| 매도 방식      | 시장가               |
| 장 운영 시간   | 평일 09:00 ~ 15:30   |

---

## 파일 구조

```
stock_trader/
├── main.py              # 진입점 (트레이더 + 대시보드 동시 구동)
├── config.py            # 설정값 (손절%, 주기, URL 등)
├── start.sh             # 실행 스크립트
├── stop.sh              # 종료 스크립트
├── core/
│   ├── kis_api.py       # KIS API 호출 (인증, 잔고조회, 현재가, 매도주문, 매수후보 탐색)
│   ├── trader.py        # Trader 클래스 (전략 주입, 매도/매수 루프 실행)
│   ├── logger.py        # 로깅 유틸리티
│   └── strategy/
│       ├── base.py                        # BuyStrategy / SellStrategy ABC
│       ├── _activate.py                   # 활성 매수 전략 구성 (primary / view) — main·dashboard 공유
│       ├── buy/
│       │   ├── _pool.py                   # 모멘텀 전략 공통 풀 (시총 ∩ 일간등락률 + 보충)
│       │   ├── _indicators.py             # 기술 지표 헬퍼 (sma, rsi)
│       │   ├── volume_momentum.py         # 주간등락률·PER·EPS 가중 티어
│       │   ├── high_proximity.py          # 4주 신고가 근접도·PER 필터 (view-only)
│       │   ├── technical_momentum.py      # 이평선 정배열·RSI 필터 + 거래량폭증·20일수익률 티어 (view-only)
│       │   └── quality_trend.py           # 우량(EPS/PER/PBR) + 우상향(20MA>60MA·RSI≤70) 결합 (현재 매수 실행)
│       └── sell/
│           └── trailing_stop.py           # 트레일링 스탑 매도 전략 (최고가 상태 소유)
├── ui/
│   └── dashboard.py     # Streamlit 대시보드 UI
├── logs/
│   ├── trader.log       # 트레이더 실행 로그 (자동 생성)
│   └── startup.log      # 프로세스 시작 출력 (자동 생성)
├── data/
│   ├── buy_candidates.json  # 매수 후보 탐색 결과 (시작 시 자동 생성)
│   ├── peak_prices.json     # 종목별 최고가 (재시작 시 복원용)
│   └── trade_history.json   # 매수/매도 거래 이력
├── .env                 # API 키 (git에 올리면 안됨)
├── requirements.txt
└── README.md
```

---

## 시작 전 필수 준비

### 1. 한국투자증권 계좌 개설

1. "한국투자" 앱 설치 후 비대면 계좌 개설
2. **종합매매계좌(위탁계좌)** 선택 (CMA는 안됨)
3. 앱/홈페이지에서 온라인 ID 생성 후 계좌 연결

### 2. KIS Developers API 신청

1. [apiportal.koreainvestment.com](https://apiportal.koreainvestment.com) 접속
2. 한국투자증권 홈페이지 > Open API 서비스 신청
3. **APP Key / APP Secret 발급**
4. 모의투자 계좌도 별도 신청 (테스트용)

### 3. `.env` 파일 설정

```
APP_KEY=발급받은_앱키
APP_SECRET=발급받은_앱시크릿
ACCOUNT_NO=계좌번호  # 예: 12345678-01
```

---

## 실행 방법

### 1. 가상환경 생성 및 패키지 설치 (최초 1회)

Python 3.14 기준 `.venv` 가상환경을 사용합니다.

```bash
# Python 3.14 설치 (Homebrew)
brew install python@3.14

# 가상환경 생성 + 패키지 설치
python3.14 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### 2. 스크립트로 실행

```bash
# 실행 (백그라운드)
./start.sh

# 종료
./stop.sh
```

실행 후 브라우저에서 `http://localhost:8501` 로 접속합니다.

| 명령         | 설명                                                                     |
| ------------ | ------------------------------------------------------------------------ |
| `./start.sh` | 트레이더 + 대시보드를 백그라운드로 실행. 이미 실행 중이면 중복 실행 방지 |
| `./stop.sh`  | 실행 중인 트레이더 종료                                                  |

> 실행 중 오류는 `logs/startup.log` 파일에서 확인할 수 있습니다.

### 스크립트 실행 권한 설정 (최초 1회)

처음 클론하거나 권한이 없는 경우:

```bash
chmod +x start.sh stop.sh
```

### 대시보드 기능

| 기능             | 설명                                                                              |
| ---------------- | --------------------------------------------------------------------------------- |
| 장 상태          | 현재 장 운영 여부 표시                                                            |
| 보유 종목 테이블 | 현재가, 최고가, 수익률, 최고가 대비 하락률 실시간 표시                            |
| 행 색상          | 🟢 정상 / 🟡 주의 / 🟠 손절 임박 / 🔴 손절 실행                                   |
| 매수 후보 목록   | 전략별 그룹 표시 (primary = 매수 실행 / 보조 = view-only) — 트레이더 시작 시 1회 탐색 |
| 거래 이력        | 매수/매도 시각, 체결가, 수량, 메모 (최신순) |
| 최근 로그        | `logs/trader.log` 최근 50줄 표시                                                  |
| 자동 새로고침    | 사이드바에서 주기 설정 (기본 60초)                                                |

---

## 테스트 → 실전 전환

[config.py](config.py) 에서 한 줄만 변경:

```python
# 모의투자
IS_MOCK = True

# 실전투자로 전환 시
IS_MOCK = False
```

> 반드시 모의투자로 먼저 테스트 후 실전 전환할 것

---

## 동작 흐름

```
실행
 ├─ Trader 인스턴스 생성 (BuyStrategy + SellStrategy 주입)
 │
 ├─ [초기화]
 │     ├─ SellStrategy.load() → 전략 내부 상태 복원 (예: peak_prices.json)
 │     └─ 기존 보유 종목을 _known_holdings 로 등록 (false-positive 매수 감지 방지)
 │           └─ SellStrategy.on_buy() 로 초기 상태 세팅
 │
 ├─ [1회] BuyStrategy.find_candidates() → data/buy_candidates.json 저장
 │     └─ QualityTrendBuyStrategy: 시총 100 ∩ 일간등락률 상위 50 → 종목별 PER/EPS/PBR + 80일 일봉 조회
 │       → EPS<0·PER 0~50·PBR 0~5 + 20MA>60MA·현재가>20MA·RSI(14)≤70 필터 → 4주 신고가 근접도 내림차순 상위 4
 │
 └─ 10분마다 반복 (장 운영시간 내)
      └─ 보유 종목 전체 조회
           ├─ 신규 편입 종목 감지 → trade_history.json 에 매수 기록 + SellStrategy.on_buy()
           └─ 각 종목 현재가 조회
                ├─ SellStrategy.observe() → 전략 내부 상태 갱신
                └─ SellStrategy.should_sell() 판단
                     └─ True → 시장가 전량 매도 + trade_history.json 에 매도 기록
                        (TrailingStopSellStrategy: 최고가 대비 10% 이상 하락)
```

## 확장 방법 (Strategy 패턴)

매수/매도 로직은 [core/strategy/base.py](core/strategy/base.py) 의 ABC 를 구현하여 교체할 수 있습니다.
`SellStrategy` 는 범용 훅만 노출하고, 전략별 내부 상태(최고가, RSI 지표 등)는 각 구현체가 소유·영속화합니다.

| 훅 | 호출 시점 | 기본 동작 |
| --- | --- | --- |
| `should_sell(code, current_price)` → `(bool, reason)` | 매 주기 매도 판단 | **필수 구현** (abstractmethod) |
| `observe(code, current_price)` | 매 주기 현재가 수신 시 | no-op (내부 상태 갱신용) |
| `on_buy(code, buy_price)` | 신규 매수 감지 · 시작 시 기존 보유 등록 | no-op (초기 상태 세팅용) |
| `load()` / `save()` | 시작 시 · 상태 변경 시 | no-op (영속화 필요 시 override) |
| `describe(code, current_price)` → `str` | 매 주기 로그 출력 | 빈 문자열 (상태 요약 문자열 반환) |

> **네이밍**: `check_sellable` 은 "지금 팔 수 있는 상태인가?"(수량·영업시간 등 capability 체크) 의미에 가깝고,
> 여기서 필요한 건 "지금 팔아야 하는가?"(전략의 policy 결정) 이므로 `should_sell` 을 유지합니다.

```python
# core/strategy/sell/rsi.py (예시)
class RsiSellStrategy(SellStrategy):
    def __init__(self, rsi_threshold: float):
        self.rsi_threshold = rsi_threshold
        self.history: dict[str, list[float]] = {}

    def observe(self, code, current_price):
        self.history.setdefault(code, []).append(current_price)

    def should_sell(self, code, current_price):
        rsi = compute_rsi(self.history.get(code, []))
        if rsi is not None and rsi >= self.rsi_threshold:
            return True, f"RSI 과열 ({rsi:.1f})"
        return False, ""

# main.py 에서 교체
trader = Trader(
    buy_strategy=VolumeMomentumBuyStrategy(),
    sell_strategy=RsiSellStrategy(rsi_threshold=70),
)
```

---

## 참고 링크

- KIS Developers 포털: https://apiportal.koreainvestment.com
- KIS 공식 GitHub 샘플: https://github.com/koreainvestment/open-trading-api
- 한국투자증권 고객센터: 1588-0012
