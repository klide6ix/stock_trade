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
- [x] 매수 전략 3종 추가: `GoldenCrossBuyStrategy`(5MA가 최근 N일 내 20MA 상향 돌파, 교차 후 일수 오름차순) / `LowPerBuyStrategy`(시총 100 ∩ EPS≥0·PER≤per_max·PBR≤pbr_max → PER 오름차순) / `OversoldReboundBuyStrategy`(직전 RSI≤30 + 오늘 종가>직전 종가 + RSI 회복)
- [x] 매도 전략 2종 추가: `RsiSellStrategy`(RSI(14)≥`rsi_max` 시 매도, 과열 회피) / `MaDeadCrossSellStrategy`(5MA<20MA 시 매도, 데드크로스). 매 주기 `observe()` 에서 일봉 조회 → 캐시; 영속화 없음. `SellStrategy.display_name` 도입(사이드바·헤더 라벨용)
- [x] 전략 레지스트리 구조 도입 (`_activate.py`의 `BUY_STRATEGY_FACTORIES` / `SELL_STRATEGY_FACTORIES`) — 키→팩토리 dict, 옵션 헬퍼(`buy_strategy_options`/`sell_strategy_options`), 클래스→키 역인덱스(`sell_strategy_key_of`)
- [x] view 매수 전략을 사이드바 multiselect 로 사용자 선택 가능 (`data/settings.json::view_buy_strategies`, primary 키는 자동 제외). 트레이더는 `scan_buy_candidates()` 시작 시 매번 settings 재읽기
- [x] 매도 전략을 사이드바 selectbox 로 변경 가능 (`data/settings.json::sell_strategy`) — 트레이더 `_sync_sell_settings()` 가 키 변경 감지 시 새 인스턴스로 교체 + `load()` + 보유 종목으로 `on_buy()` priming. 헤더 metric `손절 기준 → 매도 전략`(전략 `display_name` 표시), 트레일링 스탑 외 선택 시 손절 기준 입력 숨김
- [x] 활성 매수 전략(primary)도 사이드바 selectbox 로 변경 가능 (`data/settings.json::primary_buy_strategy`) — `view_buy_strategy_options()` 가 현재 primary 키를 자동 제외해 multiselect 와 중복 표시 방지. 트레이더 `scan_buy_candidates()` 시작 시 primary·view 모두 settings 재읽기 → 변경 즉시 다음 스캔/재매수에 반영. 헤더 metric 에 "매수 전략" 추가 (5컬럼)
- [x] 사이드바 widget 영속화 race condition 수정: 모든 widget(toggle/selectbox/multiselect/number_input/slider) 에 명시적 `key=` 부여 + `on_change` 콜백으로 사용자 변경 시점에만 `set_setting()` 호출. auto-refresh rerun 마다 widget default 가 settings.json 을 덮어쓰던 문제 해결. session_state 1회 시드(`_init_sidebar_state`) 후 widget 자체가 상태를 유지하도록 변경
- [x] 팩토리 함수의 `or DEFAULT` 패턴이 빈 리스트(`[]`)를 default 로 오해석하던 버그 수정 — `_activate.py::primary_buy_key`/`view_buy_strategies`/`primary_sell_strategy` 와 `trader._sync_sell_settings` 모두 `isinstance` 기반 명시적 검증으로 전환. 빈 view 리스트도 사용자 의도대로 보존되며, 알 수 없는 키는 default 로 일관 fallback
- [x] `stop.sh` 가 main.py PID 만 종료하고 streamlit 자식 프로세스를 orphan 으로 남기던 문제 수정 — `pgrep -f` 로 streamlit/main.py 잔존 인스턴스를 SIGTERM 후 1초 grace period 거쳐 SIGKILL. 좀비 누적으로 인한 settings.json 동시 쓰기 race 재발 방지
- [x] 동시 보유 종목 한도(`max_holdings`) 도입 (기본 5, 1~20) — 사이드바 number_input 으로 변경 가능, `data/settings.json` 영속화. `plan_initial_buy(max_holdings)` 인자가 잔여 슬롯(`max_holdings - len(owned)`) 만큼만 상위 후보 선택. 매도 후 재매수도 한도 미만일 때만 실행 (`execute_post_sell_buy`), 잔고 반영 지연 대비해 방금 매도한 종목은 보유 카운트에서 제외. 매수 예정 미리보기에 "보유/한도" metric 추가
- [x] 매수 후보 전략 전체에 통일 `시그널점수` 컬럼 도입 (0~100, 100=최상위) — 단일 기준 전략은 정렬 기준의 절대 척도 기반 정규화(`HighProximity`/`QualityTrend` proximity×100, `LowPer` 1-PER/per_max, `GoldenCross` 1-(교차일수-1)/max_days, `OversoldRebound` 1-직전RSI/rsi_oversold), 다중 기준 (`TechnicalMomentum`/`VolumeMomentum`)은 기존 `종합티어`(낮을수록 상위) 를 `100×(1-가중rank합/(N-1))` 로 역변환·교체. 대시보드 후보 테이블에 시그널점수 그라데이션(Greens) 배경 적용
- [x] 시그널점수 그라데이션을 matplotlib 비의존 방식으로 전환 — `Styler.background_gradient(cmap="Greens")` 가 matplotlib import 오류를 내던 문제 해결. `_signal_score_bg` 헬퍼가 0~100 값을 (247,252,245)→(0,68,27) 선형 보간한 inline CSS 로 변환, `Styler.map()` 으로 적용. 50 이상은 글자색 흰색으로 가독성 보강
- [x] 후보 테이블 컬럼 순서 고정: `순위` 바로 옆에 `시그널점수` 위치 (전략별 컬럼 셋이 달라도 일관 비교 가능)
- [x] primary 매수 전략이 0개 후보를 반환할 때도 대시보드에 그룹 표시 — 빈 placeholder ("⚠️ 조건 통과 종목 없음") 노출로 "전략이 활성화돼 있으나 시장 조건이 맞지 않음" 을 명시. `buy_candidates.json` 에 `primary_strategy_label` 추가 저장 (trader/대시보드 새로고침 양쪽). 직전까지는 primary 가 0개면 그룹 자체가 사라져 사용자가 "선택은 했는데 안 보인다" 로 오해할 여지가 있었음
- [x] `GoldenCrossBuyStrategy` 풀 사이즈 50 → 100 으로 확대 (`_activate.py` 팩토리에서 `pool_size=100`) — 시총 100 ∩ 일간등락률 상위로 추린 풀 30 내에서 골든크로스 조건 통과 종목이 0개로 떨어지던 문제 대응. `get_daily_ohlcv` 호출 회수는 약 3배(30→100)로 증가
- [x] 매수 예정 미리보기 버그 수정 — primary 전략 후보가 0개일 때 view-only 후보로 fallback 되어 실제 매수 계획에 새어 들어가던 문제. `render_buy_plan_preview` 가 `json_loaded` 플래그를 두어 JSON 자체 로드 실패 시에만 세션 캐시로 fallback 하고, 정상 로드 후 primary 필터 결과가 비면 "조건 통과 종목 없음" 안내 표시
- [x] **종목별 자동매도 토글** 도입 — 보유 종목 테이블을 `st.data_editor` 로 전환해 "자동매도" 체크박스 컬럼 추가 (다른 컬럼은 disabled). 체크된 종목만 매도 조건 충족 시 실제 시장가 매도가 실행되고, 미체크 종목은 조건이 충족돼도 로그만 남기고 보류 (`[name(code)] 매도 조건 충족 (reason) — 자동매도 OFF 로 매도 보류`). `data/settings.json::auto_sell_enabled_codes` (기본 `[]` — 신규 매수 종목은 OFF 시작) 에 영속화, 트레이더가 매 매도 판단 시점에 settings 재읽기. 매도 성공 시 해당 코드를 enabled 리스트에서 자동 제거 → 재매수 시 다시 OFF 기본값으로 시작. 기존 행 색상 스타일(🟡주의/🟠임박/🔴손절)은 data_editor 제약으로 제거, "상태" 컬럼 이모지로 대체
- [x] 자동매도 체크박스 실시간 반영 버그 수정 — 두 가지 원인을 함께 해결: (1) `st.data_editor` 의 `edited_rows` 누적·재해석으로 settings 기반 input df 와 충돌하는 편집이 잘못 폐기되던 문제 → `on_change` 콜백 안에서 `session_state.holdings_editor.edited_rows` 를 직접 읽어 즉시 settings 에 반영, returned df 의존 제거. (2) auto-refresh 의 `time.sleep(refresh_interval) + st.rerun()` 이 Python 스크립트를 잠재워 그 사이 발생한 위젯 클릭이 큐잉만 되고 처리되지 않던 문제 → `streamlit-autorefresh` 의 `st_autorefresh()` 로 교체(JS 기반 비블로킹 새로고침). 의존성 `streamlit-autorefresh` 를 `requirements.txt` 에 추가
- [x] **단기 매매 (단타) 골격 추가** — 보유 종목 테이블 아래에 단일 종목 추적용 별도 테이블 도입 (단일 행 `st.data_editor` + 통합 "자동매매" 체크박스). `core/short_term.py::ShortTermStrategy` 가 `find_target()` / `should_buy()` / `should_sell()` 3개 메서드로 종목 선정 · 매수 · 매도 트리거를 통합 관리하는 stub 클래스로 추가 (조건은 모두 비어있어 실주문 미발생). 영속화는 `settings.json::short_term_trade` 단일 dict (`code` / `name` / `selected_at` / `auto_enabled`). 대시보드 "🔄 종목 선정" 버튼으로 `find_target()` 호출 → 결과를 settings 에 저장. 트레이더 메인 루프가 매 주기 `check_short_term()` 호출 — 자동매매 ON + 종목 지정 시 보유 여부에 따라 매수/매도 분기, 매도 후 슬롯 자동 비움. `auto_sell_enabled_codes` 와는 독립된 단타 전용 슬롯이므로 일반 매도 흐름과 간섭 없음
- [x] **단타 종목 선정 로직 구현** — 코스피200 근사(시가총액 상위 200) 풀에서 **N일(default 5) 연속 종가 상승** 통과 종목 중 **N영업일 누적 상승률 최대** 종목 1개 자동 선정. KIS API 에 코스피200 직접 조회가 없어 시총 상위 200 으로 근사 (시총 200 ≒ 코스피200 + 일부 코스닥 대형주). 호출 수: 시총 1 + 일봉 N+1개 × 200종목 ≈ 약 201회/일단위 1회. 호출 최적화 옵션 `prefilter_positive` (default OFF) 추가 — 일간 등락률 양수 종목으로 사전 필터링 시 일봉 호출 절감 가능하나 KIS ranking API 응답 한도로 누락 위험. `select_kospi200_universe()` 헬퍼로 분리해 추후 다른 단타 전략에서도 재사용 가능
- [x] **단타 매수·매도 트리거 + 수량 정책 구현** — 매수: 종목 선정 자체가 신호 (`should_buy` 항상 True), 주문가능금액의 `SHORT_TERM_BUDGET_RATIO=50%` 로 시장가 매수 (남은 50%는 일반 매수와 자금 경합 회피용). 매도: 매수 평균가 대비 `stop_loss_pct=5%` 이상 하락 시 전량 시장가 매도. **일단위 초기화** — `selected_at` 의 날짜가 오늘과 다르면 트레이더가 `needs_reselection()` 으로 감지해 자동 재선정. **같은 날 재매수 방지** — 매도 시 `sold=True` 플래그 마크, 다음 날 재선정 시 리셋. 대시보드 단타 테이블에 선정사유·매도 완료 안내 표시
- [x] 단타 default 값 조정: `pool_top_n` 200 → **100** (스캔 시간 약 10초 → 약 5초로 단축, 코스피200 의 시총 상위 절반에 집중), 매수 예산을 비율 기반(`SHORT_TERM_BUDGET_RATIO=0.5`) → 고정 상한액(`SHORT_TERM_BUDGET_MAX=3,000,000원`)으로 교체 — 주문가능금액과 300만원 중 작은 쪽으로 매수. 단발성 단타 특성상 비율보다 절대 상한이 자금 관리에 명확
- [x] **단타 선정 로직을 ranking 결합으로 교체** — 이전 "N일 연속 상승" 조건은 시총 상위에서 통과 종목이 0개로 떨어지는 경우가 잦아 폐기. 새 방식: 시총 상위 100 풀 ∩ KIS 등락률 ranking(양봉만) ∩ KIS 거래량 ranking → 두 ranking 모두 등장 종목에 대해 `등락률순위 + 거래량순위` 합산이 작을수록 상위(=양쪽에서 동시에 상위인 종목 선호). 최상위 1종목 선정. **호출 수 약 101회/일 → 3회/일로 절감** (시총 + 등락률 + 거래량, 일봉 조회 완전 제거). [core/kis_api.py](core/kis_api.py) 에 `get_volume_rank()` 복구(`quotations/volume-rank`, tr_id `FHPST01710000`). `ShortTermStrategy` 인자 정리: `consecutive_days`/`prefilter_positive` 제거, `ranking_fetch_n` 추가 (각 ranking API top_n 상한, default 100). 선정사유 포맷도 `"등락률 N위 · 거래량 M위 · +X.XX%"` 로 변경
- [x] 단타 후보 0개 버그 수정 — KIS 시총 API 응답이 30개로 한도 + 거래량 ranking 이 "주식 수 거래량" 기준이라 KOSPI 시총 상위 대형주가 KOSDAQ 저가 소형주에 밀려 시총 ∩ ranking 교집합이 0개로 떨어지던 문제. **시총 풀 fallback 도입** — 시총 풀 ∩ ranking 교집합이 있으면 그것을 우선 사용(코스피200), 없으면 두 ranking 의 시장 전체 교집합으로 fallback. 선정사유 끝에 `· 코스피200` 또는 `· 시장전체` 명시해 사용자가 어느 풀에서 선정됐는지 확인 가능. 종목명/현재가는 두 ranking 응답에서 추출하므로 시총 풀 밖 종목도 정상 표시
- [x] 단타 ranking 시장 구분을 KOSPI 로 한정 — KIS ranking 3종(`get_market_cap_rank`/`get_volume_rank`/`get_fluctuation_rank`)에 `market` 인자 추가 (`"all"`/`"kospi"`/`"kosdaq"` → `FID_INPUT_ISCD` 매핑: 0000/0001/1001). 다른 전략 영향 없도록 default 는 `"all"` 유지(backward compat), `ShortTermStrategy.find_target` 만 세 ranking 모두 `market="kospi"` 호출. KOSDAQ 저가 소형주가 거래량/등락률 상위를 채우는 문제를 ranking 응답 단계에서 차단. fallback 라벨도 `KOSPI 시총상위` / `KOSPI` 로 변경해 의미 명확화
- [x] 단타 ranking 을 **KOSPI200 지수 구성종목 한정**으로 더 좁힘 — `_MARKET_ISCD` 에 `"kospi200": "2001"` 추가, ranking 3종이 모두 `FID_INPUT_ISCD=2001` 응답을 정상 반환하는 것을 실 KIS 호출로 검증 완료. `select_kospi200_universe()` default 도 `market="kospi200"` 으로 갱신해 함수명과 의미 일치. 실 검증 결과: 이전 "양봉등락률∩풀 0 / 거래량∩풀 1 / 교집합 0" → "시총 30 / 양봉등락률 30 / 거래량 30 / 시총교집합 2" 로 후보 안정 확보 (한화오션 등 KOSPI200 종목 선정). fallback 라벨 `KOSPI200 시총상위` / `KOSPI200` 로 갱신
- [x] **단타 매도 후 실시간 재선정 + 독립 자금 풀** — 기존 `sold` 플래그 폐기, 매도 직후 즉시 `find_target(exclude_codes={매도종목})` 호출해 다음 단타 종목 선정 (같은 사이클에서 매도→재선정, 매수는 다음 사이클). 직전 매도 종목은 후보에서 제외해 매도 즉시 같은 종목 재진입 차단. **단타 자금 풀 독립 추적** — `short_term_trade.last_realized_amount` 에 직전 매도 회수 금액(체결가×수량) 저장, 다음 매수 예산은 `min(last_realized_amount, SHORT_TERM_BUDGET_MAX, 주문가능금액)`. 이익(330만 회수)은 상한(300만)으로 캡되어 일반 자금으로 풀려나가고, 손실(250만 회수)은 단타 풀에서 그대로 흡수 — **일반 자금에서 손실분을 보충하지 않음**. `target_to_settings(..., last_realized_amount=...)` 시그니처 변경, `find_target(exclude_codes=...)` 인자 추가. 대시보드에도 "다음 진입 예산 상한" caption 표시
- [x] **단타 개장 직후 매수 지연** — 시초가 변동성에 휩쓸려 '진짜 오르는 종목'을 못 잡는 문제 대응. 종목 탐색·선정은 9시부터 진행하되, 실제 시장가 매수는 **개장 후 지연(분) 경과 이후**에만 실행. `core/trader.py::short_term_buy_window_open(now)` 헬퍼가 `now ≥ 09:00 + delay` 를 판정, `check_short_term` 의 미보유 매수 분기에서 지연 시간 이전이면 로그만 남기고 보류. 매도·재선정은 시간 제약 없이 정상 동작 (지연 이후엔 종일 매수 허용이므로 장중 재매수에는 영향 없음)
- [x] **단타 매수 지연 사이드바 조절** — `settings.json::short_term_buy_delay_min` (기본 10, 0~60분, 0=개장 즉시) 영속화 + 사이드바 "🎯 단기 매매 (단타)" 섹션 number_input. `short_term_buy_window_open`/`short_term_buy_start_label`/`short_term_buy_delay_min(헬퍼)` 가 매 판정 시 settings 재읽기 → 변경 즉시 반영. 잘못된 타입/음수는 기본값 fallback. 대시보드 동작 안내에 실제 매수 시작 시각(예: 09:10) 동적 표시
- [x] **단타 보유 중 재선정 시 유지/교체 사용자 승인** — 활성 단타 종목을 **보유 중**일 때 일단위/수동 재선정으로 새 종목이 잡히면 즉시 덮어쓰지 않고 `short_term_trade.pending_target`(대기 후보, find_target 원형 보관)으로 staging 하고 활성 슬롯은 유지. 대시보드에 **[이전 종목 유지] / [새 종목으로 교체]** 버튼 노출 — 유지 시 대기 후보 폐기, 교체 시 `pending_action="switch"` 마킹 → 트레이더가 다음 주기에 **이전 보유 전량 시장가 매도(회수 금액을 다음 매수 예산 상한으로 이월) 후 전환**(장 시간 외면 개장 후 재시도). 미보유 슬롯은 기존처럼 즉시 자동 갱신. `reselect_checked_date` 로 같은 날 재선정 API 3회 중복 호출 차단. _(아래 다중 후보 모델 도입으로 '유지/교체 버튼'은 콤보 박스 선택으로 대체됨 — switch 메커니즘은 유지)_
- [x] **주문 `rt_cd` 검증 — HTTP 200·rt_cd≠"0" 거부를 유령 체결로 기록하던 버그 수정** — KIS 는 주문 거부도 **HTTP 200 + `rt_cd:"1"`** 로 보내는데(예: `"모의투자 영업일이 아닙니다"` msg_cd 40100000, 초당 거래건수 초과 EGW00201), `_request` 가 HTTP 상태만 검사해 거부를 '성공' 으로 처리 → 거래 이력에 체결되지 않은 유령 매수가 기록되고 잔고와 불일치하던 문제. `_request` 가 본문 `rt_cd != "0"` 이면 `KisApiError(msg_cd·msg1 포함)` 를 raise 하도록 보강 — 트레이더 except 가 잡아 `매수 실패: 모의투자 영업일이 아닙니다.` 로 정확히 로깅하고 `log_trade` 미호출(유령 이력 차단). 단, `EGW00201`(초당 거래건수 초과)은 일시 제한이라 backoff 후 재시도. 기존 유령 매수 이력 1건(LG전자) 정리. **모의서버는 영업일(평일)에만 체결**하므로 주말·시간외 주문은 이 경로로 거부됨 — 실거래 검증은 평일 장중 필요
- [x] **모의투자 상시거래 — 장 시간 게이트를 모의 모드에서 우회** — 주말·시간외에 매수가 일어나지 않는 게 정상(장 마감)인데 모의 테스트가 불편하다는 요구 대응. `core/trader.py` 에 `is_trading_time()` 추가 (`IS_MOCK or is_market_open()`) — 실전은 정규장(평일 09:00~15:30)에만 매매(오발주 방지), 모의는 장 시간 무관 상시 매매. 트레이더 매매 게이트 4곳(초기매수·메인 루프·단타 교체)을 `is_market_open()` → `is_trading_time()` 로 교체, `is_market_open()` 은 실제 시장 상태 표시(대시보드 '장 상태' 배지) 전용으로 유지. 대시보드 `market_open=is_trading_time()` 로 매매 활성 판정, 헤더는 `실제마감 ∧ 모의` 시 "🟢 운영 중 (모의)" + "모의 상시거래" 안내 배너 표시. 시작 로그에도 `[모의] 상시거래 모드` 명시. **주의(코드 주석·UI 에 명시)**: KIS 모의서버는 정규장 시간에만 체결하므로 시간외 시장가 주문은 서버에서 거부될 수 있음(주문 응답 msg1 로 확인) — 우회는 어디까지나 매매 '로직' 검증용
- [x] **단타 매매 종목 선택 UI 를 콤보 박스 → 라디오 목록으로 교체** — 후보 중 1종을 별도 콤보 박스(`st.selectbox`)로 고르던 방식이 직관적이지 않아, 후보 목록에서 직접 라디오 버튼으로 1종을 선택하는 방식(`st.radio`)으로 전환. 라디오 라벨에 `순위·종목명·[코드]·(등락률%)` 을 담아 목록 자체가 선택지 역할(상세 현재가·거래량·선정사유는 위 읽기전용 표가 보완). `key="short_term_select"`/`on_change=_on_short_term_select_change` 그대로라 선택 처리·교체 예약(`request_switch`)·자동매매 토글 로직은 무변경. 관련 docstring·help·안내 문구의 "콤보 박스" → "라디오 목록" 일괄 갱신
- [x] **KIS REST 호출 공용 헬퍼 `_request()` 도입 — 일시적 5xx 재시도 + 에러 본문 노출** — KIS 모의투자 서버가 잔고/주문 API 에서 간헐적으로 500 Internal Server Error 를 반환해 대시보드가 죽던 문제 대응. `core/kis_api.py` 의 모든 GET/POST 호출(13곳)을 `requests.X → raise_for_status → json()` 직접 패턴에서 `_request(method, url, tr_id, params=/json_body=)` 단일 헬퍼 경유로 전환. 헬퍼는 (1) 5xx·네트워크 오류를 지수 backoff(`_RETRY_BACKOFF=1s × attempt`)로 최대 `_MAX_ATTEMPTS=3`회 재시도, (2) 4xx·재시도 소진 시 KIS 가 본문에 담는 `msg_cd`/`msg1` 을 폐기하지 않고 로그·`KisApiError` 메시지에 노출(`raise_for_status()` 는 URL 만 보여주고 본문을 버림), (3) `_REQUEST_TIMEOUT=10s` 로 무한 대기 방지. 토큰 발급(`get_token`)은 인증 전용 헤더라 의도적으로 직접 호출 유지. 모의투자 실호출로 검증 중 실제 500 발생 → 재시도로 자동 복구 확인
- [x] **대시보드 '단타' 표현 중복 정리 — 대표 명칭을 '단기 매매'로 통일** — 단타 섹션 제목이 `🎯 단기 매매 (단타) — 단타 (코스피200···)` 처럼 같은 의미를 한 줄에 3번(병기 `(단타)` + `display_name` 접두사 `단타 `) 노출하던 중복 제거. `ShortTermStrategy.display_name` 에서 `단타 ` 접두사 삭제(→ `코스피200·등락률+거래량 ranking·5%손절`), 대시보드 화면 텍스트 7곳에서 '단타' 제거: 섹션/사이드바 제목 병기 `(단타)` 제거, `단타 후보→후보`, expander `단타 매매 동작 안내→동작 안내`, `단타 자금 풀→이 매매 자금 풀`, help `단타 실매수→실매수`. 코드 docstring 의 '단타'는 화면 비표시라 가독성용으로 유지. `display_name` 소비처는 대시보드 1곳뿐이라 영향 국소
- [x] **가격 확인 주기 `CHECK_INTERVAL` 10분 → 1분(600→60초) 단축** — 매도 판단이 polling 방식이라 조건 충족~실제 매도 사이 최대 1주기 지연이 발생하는데, 10분은 손절 반응성이 너무 둔하다는 판단. 한 사이클 호출량(`get_holdings` 1 + 보유 종목당 `get_current_price`, 매도 전략 `trailing_stop`은 추가 일봉 호출 없음)이 분당 수회 수준이라 KIS rate limit 에 여유 → 10배 잦아져도 안전. 손절 최대 지연 10분 → 1분. `config.py` 상수 유지(사이드바 노출은 별도 "다음 작업 후보" 로 보류)
- [x] **대시보드에서 모의/실전 모드 표시 일괄 제거** — 모의투자는 매매 로직 검증용으로만 쓰고 실사용은 안 해 view 의 모드 표시가 불필요하다는 판단. `ui/dashboard.py` 에서 (1) 탭 제목 `트레이더 [모의]/[실전]` → `트레이더`, (2) `🟢 모의투자(MOCK)` / `🔵 실전투자(LIVE)` 모드 배지, (3) `🟢 모의 상시거래` 안내 배너, (4) 장 상태 metric 의 `운영 중 (모의)` 분기를 모두 제거 — 장 상태는 `is_market_open()` 기준 `운영 중`/`마감` 만 표시. 미사용이던 `MODE_LABEL` import 와 `IS_MOCK` import 도 함께 정리. **로직은 무변경** — `config.IS_MOCK` · `core/trader.py::is_trading_time()`(모의 상시거래 게이트) 는 그대로 유지되므로 실제 모의/실전 동작·키 분리·상시거래는 코드 레벨에서 계속 작동. 대시보드 `market_open=is_trading_time()` 매매 활성 판정도 유지
- [x] **재매수 시 최고가(peak) stale 버그 수정** — 매도 후 `peak_prices` 에서 종목 항목이 제거되지 않아, 재매수 시 `on_buy` 가드(`code not in peak_prices`)가 통과하지 못해 이전 보유 구간의 (대개 더 높은) 최고가가 그대로 남던 문제. 매수가보다 낮게 재진입해도 옛 최고가 기준으로 하락률이 과대 계산돼 즉시 손절되는 오작동 발생. `SellStrategy` 에 **`on_sell(code)` 훅** 추가(기본 no-op), `TrailingStopSellStrategy.on_sell` 이 해당 종목 peak 제거 후 영속화. 트레이더 `check_and_sell` 가 매 주기 신규 매수 감지와 **대칭으로 사라진 종목(`_known_holdings - current_codes`)을 청산으로 감지**해 `on_sell` 호출(자동·수동·외부 체결 모두 포괄). 재매수 시 가드가 정상 통과 → `on_buy` 가 매수가를 새 최고가로 세팅 → `observe` 가 1분마다 상향 갱신. 더불어 대시보드를 peak_prices.json **읽기 전용 소비자**로 전환(`_load_peak_prices()` 가 매 새로고침 파일 재읽기, 자체 write 제거) — 트레이더 단일 소유로 dual-writer 가 stale 최고가를 파일에 재오염시키던 문제 차단
- [x] **VolumeMomentumBuyStrategy 가치 신호 EPS → ROE 교체** — PER=주가/EPS 라 PER·EPS 를 함께 비교하면 같은 축(주가 대비 이익)을 중복 평가해 무의미하던 문제. EPS 를 **ROE(자기자본이익률)** 로 교체해 PER(밸류에이션)·주간등락률(모멘텀)과 직교하는 자본 효율성 신호를 추가. ROE 는 높을수록 무조건 좋은 게 아니므로(과도한 레버리지·일회성 이익으로 부풀 수 있음) **적정 범위 근접도로 점수화**: 10~20% 만점, <10% 선형 감점, >20% 완만한 감점(50%↑ 잔여 0.3). 가중은 주간등락률 50% · PER 25% · ROE밴드 25%. KIS 재무비율 API(`get_roe`, `finance/financial-ratio`, tr_id `FHKST66430300`, `roe_val`) 추가. PER≤0·ROE 없음/적자(≤0) 종목 제외. `display_name` 의 `(legacy)` 제거 → `거래량+주간등락·PER·ROE`. 후보 dict EPS→ROE(%) 컬럼 교체(대시보드 `(%)` 자동 포맷 적용, 적자 배제로 양수만 표시)
- [x] **외부 툴 매매로 인한 stale 최고가(peak) 오염 차단** — 트레이더가 내려가 있는 동안(또는 외부 툴로) 매도된 종목은 `on_sell` 정리가 누락되어 `peak_prices.json` 에 orphan 최고가가 남고, 같은 종목 재매수 시 `on_buy` 가드(`code not in peak_prices`)에 막혀 이전 구간의 (대개 더 높은) 최고가가 그대로 남아 매수가 대비 과도 하락으로 즉시 손절되던 문제. **두 갈래로 차단**: (1) `SellStrategy.on_buy(code, buy_price, reset=False)` 에 `reset` 인자 추가 — `check_and_sell` 의 신규 편입 감지(`current_codes - _known_holdings`)는 `reset=True` 로 호출해 orphan 이 있어도 평균단가로 **강제 재설정**, 시작 priming 경로는 `reset=False`(기본)로 누적된 정상 최고가 보존. (2) `SellStrategy.reconcile(held_codes)` 훅 신설(기본 no-op, `TrailingStop` 구현) — 시작 시·매도 전략 교체 시 실제 보유하지 않는 종목의 orphan 최고가를 일괄 폐기. 외부 툴 매수/매도여도 다음 사이클 보유 갱신에서 평균단가가 최고가로 정상 세팅됨
- [x] **단타 다중 후보(최대 5종) + 콤보 박스 선택 모델** — 단일 자동 선정 → **상위 N종(`SHORT_TERM_CANDIDATE_COUNT`=5) 후보 선정**으로 전환. `ShortTermStrategy.find_targets(n, exclude_codes)` 가 ranking 결합 상위 N종 리스트 반환(`find_target` 은 n=1 wrapper). 후보는 `settings.json::short_term_candidates`(`{selected_at, items}`) 컨테이너에 일단위 보관. 대시보드: **읽기 전용 후보 테이블**(순위/종목명/현재가/등락률/거래량/선정사유) + **콤보 박스(selectbox)로 매매할 1종 선택** + 단일 `자동매매` 토글. 실거래는 한 번에 1종(활성 슬롯)만 진행. 재선정 시 **보유 종목은 유지**(보호), 미보유 슬롯만 새 후보 #1로 자동 지정(Q2). 보유 중 콤보로 다른 종목 선택 시 `request_switch` → 트레이더가 이전 보유 전량 매도 후 전환(`_short_term_switch` 재사용). `check_short_term` 의 reselect 로직을 `_short_term_refresh_candidates` 로 교체, `core/short_term.py` 에 `find_targets`/`candidates_to_settings`/`candidates_need_refresh`/`empty_candidates`/`request_switch` 추가, 단일-슬롯 전용 헬퍼(`stage_pending`/`mark_switch`/`mark_reselect_checked`/`reselect_checked_today`/`needs_reselection`/`reselect_checked_date` 필드) 제거. 대시보드 data_editor(체크박스) → dataframe + selectbox + toggle 로 교체
- [x] **초당 거래건수 초과(EGW00215) 대응 — 한도 코드 재시도 일반화 + 잔고 단기 캐시** — 실거래 중 `inquire-balance` 가 `rt_cd:1 / msg_cd:EGW00215`("원장에서 허용 가능한 초당 거래건수 초과") 를 HTTP 500 본문으로 반환하며 보유 조회가 실패하던 문제. EGW00215 는 게이트웨이(EGW00201)와 별개인 **원장(브로커리지 백엔드) 레벨** 한도라 trader 루프(매도점검·단타가 `get_holdings`/`get_cash_balance` 다회 호출)와 Streamlit 대시보드 subprocess 의 독립 호출이 합쳐져 초당 한도를 burst 로 초과. **(1) 한도 코드 재시도 일반화** — `_RATE_LIMIT_CODES={EGW00201,EGW00215}` 집합 도입, `_request` 가 본문 JSON 을 먼저 파싱해 HTTP 200·4xx·**500** 어느 상태로 오든 `msg_cd` 가 한도 코드면 `_RATE_LIMIT_BACKOFF(1s)×attempt + jitter(0~0.5s)` 후 재시도(다음 1초 창으로 이월). 기존엔 EGW00201 만, 그것도 200 응답 경로에서만 처리돼 500 본문 한도는 누락됐음. **(2) 잔고 단기 캐시** — `_inquire_balance` 에 `_BALANCE_CACHE_TTL=3.0s` 캐시 도입, 한 사이클 내 `get_holdings`+`get_cash_balance`+`get_holdings` 중복 원장 호출(EGW00215 의 직접 원인)을 1회로 합침(TTL≪`CHECK_INTERVAL`=60s 이라 판단 granularity 무영향). 자기 `buy_market_order`/`sell_market_order` 직후 `_invalidate_balance_cache()` 로 무효화해 stale 보유 방지. mock 검증 3종(500+EGW00215 재시도 성공 / 3회 호출→원장 1회 / 주문 후 무효화) 통과.
- [x] **KIS 호출 cross-process throttle — 두 프로세스 합산 burst 사전 차단 (계층 2)** — trader 프로세스와 Streamlit 대시보드 subprocess([main.py](main.py))가 같은 app key 의 초당 한도를 독립 소모해, in-process 캐시/재시도(계층 1·3)만으로는 두 프로세스 호출이 합쳐진 burst 를 못 막던 한계 해소. `data/.kis_throttle_{mock|real}.lock` 파일에 '다음 호출 허용 시각'을 기록하고 `fcntl.flock(LOCK_EX)` 으로 직렬화하는 **'슬롯 예약' 패턴** `_throttle()` 도입 — flock 진입 → 저장된 `prev` 읽기 → `slot=max(now,prev)` 계산 → 다음 호출자용 `slot+_MIN_INTERVAL` 기록 → flock 해제 후 슬롯까지 sleep(lock 쥔 채 자지 않아 상대 프로세스 불필요 차단 방지). 같은 머신 wall clock(`time.time()`) 공유라 프로세스 간에도 슬롯이 단조 증가. `_request()` 의 매 호출 직전(재시도 포함) 호출. 초당 한도 `_MAX_CALLS_PER_SEC`=실전 10/모의 2 (KIS 공식 상한 20·2 대비 보수적 — 원장 한도 + 2프로세스 분담 고려). `fcntl` 부재(비 Unix)·파일/flock 오류 시 throttle 없이 진행(가용성 우선, 거래 안 막음). 검증: 2프로세스×10호출 동시 기동 → 20건이 ~50ms 간격으로 직렬화(위반 0건, 총 ~950ms), 재시도+throttle 통합 동작 정상
- [x] **로그 파일 일별 분리** — 단일 `logs/trader.log` 무한 누적 → `logs/trader-YYYY-MM-DD.log` 일별 파일로 전환. `core/logger.py::log()` 가 **매 호출 시점의 날짜**로 경로를 산출하므로 트레이더가 자정을 넘겨 계속 실행돼도 재시작 없이 다음 날 파일로 자동 분리(`log_path_for(dt)` 헬퍼). 대시보드는 `current_log_file()`(오늘) 우선, 자정 직후·기동 직후처럼 오늘 파일이 아직 없으면 `latest_log_file()`(가장 최근 수정 일별 로그)로 폴백 — 표시 중인 파일명을 caption 으로 노출. glob 패턴 `trader-*.log` 는 하이픈 없는 레거시 `trader.log` 를 매칭하지 않아 과거 누적 파일과 깔끔히 분리(레거시 파일은 보존, 신규 로그만 일별). `start.sh` 의 `logs/startup.log`(nohup 콘솔 캡처)는 별개 메커니즘이라 무관
- [x] **오래된 로그 자동 정리(보존 5일)** — `core/logger.py::cleanup_old_logs(retention_days=RETENTION_DAYS=5)` 추가. **파일명 날짜**(mtime 아님 — touch 돼도 '기록된 날' 기준 일관 판정) 기준 `(오늘 - 파일날짜).days >= 5` 인 일별 로그 삭제. 예) 오늘 6/12 → 6/7(5일 전) 이전 삭제, 6/8~6/12(5일치) 보존. 트리거 2곳: **(1) 새 일별 파일 생성 직후** — `log()` 가 당일 첫 기록(=자정 경과/당일 첫 호출)을 `is_new_file` 로 감지해 호출, **(2) 프로세스 기동 시** — `main.py` 진입부에서 1회 호출. 삭제 실패(권한·동시 삭제 race)는 무시(`OSError` catch — 로그 정리가 본 로직·거래를 막지 않음). 레거시 `trader.log` 및 무관 파일(`startup.log`)은 정규식 `trader-\d{4}-\d{2}-\d{2}\.log` 에 안 잡혀 보존. 검증: 경계(0~7일 전) 정확 삭제·5일치 보존·레거시 보존, 새 파일 생성 트리거 동작 확인
- [x] **단타 매수·매도 조건 리팩토링 (진입 게이트 + 트레일링 청산)** — 기존 "선정 즉시 무조건 시장가 추격 매수 + 매수가 대비 -5% 손절만" 구조는 ① 진입 필터 부재로 급등 고점에 물리고 ② 익절 없이 손절 일변도라 "올라도 못 팔고 결국 -5%에서만 청산" → 기대값이 구조적으로 음수였던 문제 대응. **진입(`should_buy(target, snapshot)`)**: 선정은 후보일 뿐, 진입 시점 당일 시세로 게이트 검사 — (1) 과열 컷(전일대비등락률 ≤ `entry_max_chg_pct`=15%) (2) 반등 확인 컷(현재가 ≥ 당일 저가 × (1+`entry_min_rebound_pct`/100), 기본 +1% — 저점에서 흘러내리는 '떨어지는 칼날' 회피, 갭하락 시작 종목도 저점 반등 중이면 통과. 기존 "현재가 ≥ 시가" 기준을 교체) (3) 옵션 고점 추격 컷(`entry_min_pullback_pct`=0 비활성). 미충족 시 매수 보류·다음 주기 재평가(슬롯·후보 유지). **청산(`should_sell`)**: 3중 구조 — ① 하드 손절 매수가 대비 -`stop_loss_pct`(5%→**3%**) ② **트레일링 스탑** 수익 +`trail_arm_pct`(3%) 도달 무장 후 진입 후 최고가(peak) 대비 -`trail_drop_pct`(2%) 하락 시 청산 ③ 옵션 하드 익절(`take_profit_pct`=0 비활성, 트레일링 위임). peak 는 단타 슬롯(`short_term_trade.peak`)에 저장 — 트레이더가 매 주기 현재가로 상향 갱신(`update_peak`), 매수 직후 체결가로 초기화(`set_peak`), 매도/교체/재선정 시 `EMPTY_TARGET` 으로 자동 리셋(일반 보유 `peak_prices.json` 과 독립). **추가 API 호출 0** — `get_quote_snapshot` 에 당일 `시가/고가/저가` 필드 추가, 트레이더 단타 경로를 `get_current_price` → `get_quote_snapshot` 으로 교체(같은 `inquire-price` 1회). 대시보드 동작 안내 문구도 진입 게이트·3중 청산으로 갱신

- [x] **장 전 준비(pre-market) 시간 도입 — 개장 전 매수·단타 후보 사전 선정** — 정규장은 09:00 시작이지만 장외(시간외) 거래가 8:00/8:30 부터 먼저 열리는 경우가 있어, 매매 불가하지만 조회 가능한 이 구간에 매수/매도 항목을 미리 정해두고 싶다는 요구 대응. `config.PRE_MARKET_OPEN`(기본 `"08:30"`) + `settings.json::pre_market_open_time`(사이드바 `st.time_input` 30분 단위로 변경, "HH:MM" 영속화) 도입. `core/trader.py` 에 `is_pre_market(now)`(평일 설정시각~09:00 직전) · `pre_market_open_time()` · `Trader.prepare_market_open()`(=`scan_buy_candidates` + `_prepare_short_term`, **주문 없이 조회·후보 선정만**) 추가. `run()` 메인 루프에 **장전 준비 분기** 신설 — 정규장도 모의 상시거래도 아닌 시간에 `is_pre_market` 면 하루 1회(`prep_date` 가드) 매수·단타 후보를 사전 선정하고 `did_initial_buy=False` 리셋해 개장(09:00)과 동시에 신선한 후보로 초기매수·단타 진입. 새벽(장전 시작 이전)에 기동 시엔 `prep_date=None` 으로 두어 08:30 도달 시 신선한 데이터로 재선정. 매도 측은 `fetch_price` 가 `market_open` 무관하게 실시간 조회를 시도하므로 장전에도 보유 종목 현재가·하락률(매도 예상)이 이미 표시됨. 대시보드 헤더에 `🕗 장 전 준비` 장 상태 + 안내 배너 추가

- [x] **일 단위 단기 매매를 ETF 방향 매매로 전면 교체** — 개별주 ranking 방식(`ShortTermStrategy`) 폐기, **장 전 시장 방향 판정 → 상승이면 코스피200 지수 ETF · 하락이면 인버스 ETF** 를 개장과 함께 매수하는 `EtfDayTradeStrategy` 로 대체. 상세는 아래 4개 축.
  - **방향 판정** ([core/market_direction.py](core/market_direction.py)): 지수 프록시(KODEX 200) 일봉의 ① 이평선 추세(5MA vs 20MA, 가중 0.35) ② 전일 등락률(0.25) ③ 최근 3일 수익률(0.20) 에, ④ **장전 예상체결가 갭**(0.20) 을 가중 합산해 [-1, +1] 점수를 만들고 부호로 상승/하락을 가른다. 각 신호는 정규화 기준(추세 1.5% · 전일 1.5% · 3일 3% · 갭 1.0%)에서 ±1 로 포화. 갭을 못 쓰면 남은 가중치로 재정규화해 점수가 0 쪽으로 끌려가지 않게 한다. `neutral_band`(기본 0) 이내면 중립 → 당일 진입 보류.
  - **예상체결가 stale 판정**: KIS `inquire-asking-price-exp-ccn`(tr_id `FHKST01010200`, `get_expected_open_quote` 신규) 은 **장 시간 외에도 직전 세션 잔존값을 그대로 반환**한다(일요일 호출 시 금요일 데이터 확인 — 기준가 113,230 ≠ 전일 종가 106,365). 응답의 `기준가(stck_sdpr)` 가 일봉 기준 전일 종가와 일치할 때만 오늘 세션 데이터로 인정하고, `예상거래량 > 0` 도 함께 검사. 장중에는 실시간 등락률로 갭 신호를 대체(오늘 일봉 존재 여부로 분기).
  - **ETF 유니버스 + 대체 ETF** ([core/etf_universe.py](core/etf_universe.py)): 정방향 5종(KODEX 200 → TIGER 200 → RISE 200 → PLUS 200 → KIWOOM 200) · 인버스 3종(KODEX 인버스 → TIGER 인버스 → ACE 인버스) 을 유동성 순으로 정의. **1순위 ETF 를 일반 매수 슬롯이 이미 보유 중이면 같은 지수를 추종하는 대체 ETF 로 자동 회피**해 종목코드 레벨에서 포지션을 분리한다. 종목코드·종목명은 KIS `search-stock-info`(CTPF1002R) 실호출로 확인. 레버리지/인버스2X 는 제외(2배 상품은 지수 2.5% 변동만으로 -5% 손절에 걸려 전략 의도와 불일치).
  - **4중 청산**: ① 손절 매수가 대비 -5% ② 매수 이후 **최고가 대비 -5%** ③ **보유기간 만료** — 매수 다음 거래일 개장 시 전량 청산 후 그날 방향으로 재진입 ④ (옵션) 당일 15:15 마감 강제청산. **손절·최고가·마감 청산이 나면 그날은 재진입 차단**(`blocked_date`), 보유기간 만료만 같은 날 재진입 — 판단이 틀린 날 같은 자리에 다시 들어가는 것을 막는다.
- [x] **단기 매매 자체 원장(ledger) 도입 — 일반 슬롯과 손익·수량 완전 분리** — 증권사 잔고는 같은 종목코드를 하나의 평균단가로 합치므로, 일반 매수로 KODEX 200 을 보유한 상태에서 단기 매매가 같은 종목을 사면 양쪽 수익률이 모두 왜곡된다. 단기 매매 슬롯이 `entry_price`/`qty`/`entry_at`/`peak` 를 `settings.json` 에 직접 기록하고 **손익 판단·매도 수량을 전부 원장 기준**으로 처리. `split_holdings(holdings, slot)` 이 잔고에서 원장 수량을 차감해 (일반 보유, 단기 보유) 로 나누며, 이 값을 `check_and_sell`·`execute_initial_buy`·`execute_post_sell_buy`·매도전략 priming·대시보드 보유 테이블이 모두 사용 — 일반 매도 전략이 단기 매매 물량을 팔거나, 단기 종목이 `max_holdings` 를 잡아먹는 간섭을 차단. **원장 정합성 보정**(`_reconcile_short_term_ledger`): 잔고에 없으면 외부 청산으로 보고 원장 정리, 잔고 < 원장이면 수량 하향, 잔고 == 원장이면 증권사 평균단가를 실제 체결가로 보고 진입가 보정(시장가 주문의 주문가↔체결가 괴리 해소).
- [x] **단기 매매 파라미터 사이드바 노출** — `short_term_budget`(진입 예산 상한, 기본 300만) · `short_term_stop_loss_pct`(5%) · `short_term_peak_drop_pct`(5%) · `short_term_close_at_market_end`(당일 마감 강제청산) 을 `settings.json` 영속화 + 사이드바 위젯으로 조절. 트레이더가 매 주기 `_sync_short_term_settings()` 로 재읽기해 변경 즉시 반영(변경 시에만 로그). 매수 지연 기본값도 10분 → **0분(개장 즉시)** 으로 변경 — ETF 방향 매매는 '장 전에 정한 방향대로 개장과 함께 진입' 이 설계 전제.
- [x] **대시보드 단기 매매 섹션 개편** — 오늘의 **방향 패널**(방향·점수·매매 방침 metric + 신호별 관측값/점수/가중치 표 + 갭 신호 출처·판정 시각) → ETF 후보 테이블(우선순위·시그널점수·선정사유) → 라디오 선택 + 자동매매 토글 → **원장 기반 포지션**(진입가·보유수량·수익률 + 손절선/최고가 청산선/청산 예정 시점 caption) → 재진입 차단 안내 + 수동 해제 버튼 순으로 구성. '🔄 후보 선정' 버튼은 '🔄 방향 재판정' 으로 교체. 보유 종목 테이블에서는 단기 매매 물량이 차감되어 표시.
- [x] **단기 매매 자금을 손익 누적형 '자금 풀' 로 전환** — 기존에는 진입 예산이 `min(직전 회수액, 상한 300만, 주문가능금액)` 이라 **이익이 나면 상한에서 잘려 초과분이 일반 자금으로 새어나가고**(300만 → 330만 회수 → 다시 300만만 투입), 손실만 다음 진입에 반영되는 비대칭 구조였다. 이제 `short_term_budget`(배정액/씨드)에서 출발하는 **자금 풀**(`settings.json::short_term_pool`)이 실제 운용 자금이 되고, 청산할 때마다 `풀 += (회수액 − 투입액)` 으로 **실현손익이 그대로 누적**된다 — 벌면 다음 진입 금액이 커지고(복리), 잃으면 줄어든 금액으로 들어간다. 진입 예산은 `min(자금 풀, 주문가능금액)`. 일반 자금에서 손실을 보충하지도, 이익을 빼내지도 않는 독립 풀 성격은 그대로 유지. `trader.apply_short_term_pnl(invested, realized)` 가 청산·교체 양쪽에서 정산하며, 투입액은 `invested_amount(slot) = 진입가 × 수량`(진입가는 실제 체결 평균단가로 보정된 값)이라 시장가 주문의 주문가↔체결가 괴리가 손익에 새지 않는다. 슬롯의 `last_realized_amount` 는 풀로 대체되어 제거. 사이드바 '배정 자금' 을 바꾸면 풀도 그 금액으로 재설정(재배정)되고, 대시보드에 **자금 풀 / 배정액 / 누적 실현손익** metric + 보유 중 평가손익 기준 "청산 시 풀 예상액" + 풀 초기화 버튼을 추가. (회수액 정확도는 아래 체결 조회 항목에서 해결)
- [x] **체결 조회로 실제 정산 금액 반영 — 손익 계산에서 근사치 제거** — 그동안 매수/매도 금액을 `주문 시점 현재가 × 수량` 으로 근사했는데, 시장가 주문은 호가 스프레드만큼 체결가가 어긋난다(1,125원 ETF 2,600주면 1틱 5원 차이가 1만원 이상 — 수수료의 100배 규모 오차). `get_order_execution(주문번호, 종목코드, side)` 추가: 주문 응답의 `ODNO` 로 `inquire-daily-ccld`(주식일별주문체결조회, tr_id `TTTC8001R`/모의 `VTTC8001R`)를 오늘·해당 종목·해당 매매구분으로 좁혀 조회하고 `odno` 가 일치하는 행에서 **체결수량·체결평균가·총체결금액**을 읽는다. `trader.settle_order()` 가 이를 감싸 체결 반영 지연에 대비해 최대 3회(1초 간격) 재시도하고, 실패 시 주문 시점 값으로 fallback 하되 `exact=False` 로 로그에 명시. **제비용(수수료·세금)**: `output2.prsm_tlex_smtl` 이 **ODNO 필터를 무시하고 조회 구간 전체를 합산**하는 것을 실측 확인(60일 조회 0원 / 1일 조회 118원)했기에, 조회 결과가 우리 주문 1건뿐일 때만 귀속시킨다(`제비용신뢰`). 현금흐름은 방향에 맞게 매수 `체결금액 + 제비용`, 매도 `체결금액 − 제비용`. 원장에 `invested`(실제 지출 현금) 필드를 추가해 자금 풀 정산이 `회수액 − 투입액` 으로 정확히 맞아떨어지고, 부분 체결·외부 매도로 수량이 줄면 `set_position_qty` 가 투입액도 같은 비율로 축소한다. 거래 이력(`trade_history.json`)에도 주문가가 아닌 체결가가 기록된다. 실계좌 과거 주문 3건으로 검증: 매도 1,081,000원 → 제비용 45원 · 매도 1,743,000원 → 73원 · 매수 1,672,500원 → 70원 (약 0.0042% = 온라인 위탁수수료, ETF 매도 증권거래세 면제 확인)
- [x] **시장가 매수 거부(APBK0952) 수정 — 주문 수량을 KIS 실제 매수 여력으로 상한** — 실거래 첫날 09:15 단기 매매 진입이 `rt_cd=7 msg_cd=APBK0952 주문가능금액을 초과 했습니다` 로 거부. 원인 두 가지를 실계좌 조회로 특정: **(1) 시장가 증거금** — KIS 는 시장가 매수를 체결가 미확정으로 보아 **상한가(현재가 +30%) 기준**으로 주문금액을 검증한다(실측: TIGER 인버스 현재가 1,252원 → 계산단가 1,627원). `예산 ÷ 현재가` 수량은 주문금액이 가용 현금의 약 77% 를 넘는 순간 반드시 거부된다 — 당시 예산 300만 ÷ 1,252 = 2,396주 × 1,627 = 3,898,292원 > 주문가능 3,387,580원. **(2) 잔고 API 필드 오류** — 주문가능금액으로 쓰던 `nxdy_excc_amt`(익일정산금액)는 매수 대금이 D+2 결제라 당일 체결분이 빠지지 않아 실제 여력보다 크다(실측: 잔고 API 3,387,580원 vs 실제 주문가능현금 478,180원 — 차액이 정확히 당일 매수 체결액 2,909,400원). `get_orderable_cash()`(매수가능조회 `inquire-psbl-order`, tr_id `TTTC8908R`) 추가 — `ord_psbl_cash`(주문가능현금)·`nrcvb_buy_qty`(미수없는매수수량)·`psbl_qty_calc_unpr`(계산단가)를 읽어 두 문제를 한 번에 해소. `trader.plan_market_buy_qty()` 가 `min(예산 ÷ 현재가, KIS 최대매수수량)` 으로 수량을 정하고 조회 실패 시 상한가 기준 보수 추정으로 fallback. 매수 3경로(단기매매 진입 · 초기매수 · 매도후재매수) 전부 적용 — 초기매수는 주문마다 재조회해 앞선 주문이 소모한 현금을 반영. 대시보드 상단 metric 을 `주문가능금액` → **`주문가능현금`**(실제 값)으로 교체하고 잔고 API 값과 차이가 있으면 미결제 매수분 안내 표시
- [x] **매수를 지정가(매도호가)로 전환 — 증거금 30% 절감 + 체결가 확정** — 시장가는 KIS 가 상한가(+30%) 기준으로 증거금을 잡아 같은 현금으로 살 수 있는 수량이 30% 줄고 체결가도 예측할 수 없다. `settings.json::buy_order_type`("limit" 기본 / "market") 도입, 사이드바 **"지정가로 매수"** 토글. 단가는 **호가창의 매도호가**에서 고른다(`get_orderbook()` → `pick_limit_buy_price()`) — 주문 수량을 덮는 누적 잔량의 첫 호가를 선택하므로 즉시 전량 체결을 노리고, 거래소가 준 호가라 **호가 단위를 계산할 필요가 없다**(실측: 인버스 ETF 1원 단위, KODEX 200 5원 단위로 서로 다름 — 현재가에 임의 버퍼를 더하면 무효 단가 발생). 매수가능조회도 지정가 기준(`ORD_DVSN=00` + 주문 단가)으로 호출해 수량 상한을 산정. 미체결 잔량은 `cancel_order()`(정정취소주문 `order-rvsecncl`, tr_id `TTTC0803U`)로 즉시 취소 — 살려두면 현금이 묶이고 나중에 체결돼 원장에 없는 유령 포지션이 된다. 단기 매매·일반 매수(초기매수·매도후재매수) 모든 매수 경로에 적용. **매도(청산)는 시장가 유지** — 손절은 체결 속도가 우선이고 증거금 이슈도 없다. 실계좌 실측(TIGER 인버스, 자금 풀 300만): 지정가 367주 vs 시장가 283주로 **29.7% 더 매수**
- [x] **방향 판정 전면 재보정 — 정규화 동적화 + 전일 등락률 평균회귀 전환 + 가중치 재배분** ([core/market_direction.py](core/market_direction.py)). KODEX 200 실일봉 78영업일(2026-03~07)로 검증한 결과 세 가지 결함을 확인하고 함께 수정.
  - **정규화 기준을 절대 % → 실현변동성 배수로 전환** — 기존 `NORM_*_PCT`(1.0~3.0%)는 코스피200 일간 변동폭 ~1% 를 가정했는데 실측 일간 σ 가 **6.5%** 였다. 그 결과 이평선 신호의 **92%가 ±1.0 으로 포화**되어 점수가 신호 강도를 잃고 사실상 '부호 투표' 로 붕괴, `neutral_band` 도 무력화. `realized_vol()`(20일 표준편차, 하한 0.3%) 을 스케일로 삼는 `NORM_*_MULT` 배수 방식으로 교체 — 배수는 무차원이라 국면이 바뀌어도 포화율이 유지된다. 배수는 (신호 표준편차 ÷ 일간 vol) × 여유계수로 산정(이평선 3.5 · 전일 1.6 · 3일 2.7 · 갭 1.2). **3일/전일 배수비가 1.69 로 확률보행 스케일링 √3(≈1.73) 과 일치**해 임의 curve-fit 이 아님이 교차 확인됨. 포화율 92/67/74/64% → **15/14/13/13%**. 일봉 조회는 이미 하고 있어 **추가 API 호출 0**
  - **전일 등락률을 순방향(모멘텀) → 평균회귀(부호 반전)로 전환** — 전일 등락률과 '시가 진입 → 익일 시가 청산' 수익의 상관이 **-0.297**(약 2.6σ), 구간별 평균 수익도 전일 -10~-5% → **+2.29%** / 전일 +5~+10% → **-2.44%** 로 단조 관계. 무작위 가중치 1만 개로 **부호만** 바꿔 비교한 한계효과에서 누적손익 중앙값 **-42.0% → +43.1%**, 하위 10% 시나리오도 -93% → -19% 로 개선. 순방향으로 쓰던 이전 버전은 이 신호에서 구조적으로 손실(단독 적중률 42.3%)을 냈다. 음수 가중치 대신 **신호 자체를 평균회귀로 재정의**(`W_PREV_DAY` → `W_PREV_DAY_REVERSION`, 점수에 `-` 적용)해 분모 왜곡 없이 의도가 코드·대시보드 라벨에 드러나게 함
  - **가중치 재배분** `이평선 .35 / 전일 .25 / 3일 .20 / 갭 .20` → **`갭 .50 / 전일(평균회귀) .25 / 이평선 .15 / 3일 .10`**. 갭은 다른 셋과 상관 ≈ 0 인 **유일한 독립 신호**이고 한계효과도 뚜렷(가중치 <0.2 시 손익 중앙 -17.0% vs >0.5 시 +27.7%). 반면 이평선은 78영업일 동안 부호가 **4번만** 바뀌어(평균 지속 15.6일) 독립 관측이 5개뿐, 유효 표준오차 ±22.4%p 로 **성능 판정 자체가 불가능** — 검증되지 않은 신호에 최대 가중을 주던 배분을 축소. 3일은 가중치 부호를 어느 쪽으로 돌려도 손익 차이가 없어(+5.2% vs -4.2%) 최소화. **의도적으로 in-sample 최대값을 택하지 않았다**(과최적화 회피)
  - **`weight_total` 을 가중치 절대값 합으로 변경** — 향후 음수 가중치를 도입해도 분모가 줄어 점수가 발산하지 않도록 방어. 갭 미사용 시 재정규화 경로도 동일하게 적용
  - 대시보드 방향 패널에 정규화 기준(일간 실현변동성) caption 추가, `judge_direction()` 결과에 `vol` 필드 추가
  - **표본 외(out-of-sample) 검증 완료** ([scripts/_check_oos.py](scripts/_check_oos.py)) — 위 결론이 7월을 학습에 포함한 탓은 아닌지 확인. **3~6월(train)만으로 판정 → 7월(test)에 적용**, 그리고 ETF 대신 **실제 지수**로도 교차 확인(`inquire-daily-indexchartprice`, tr_id `FHKUP03500100`, `FID_COND_MRKT_DIV_CODE=U` — 한 번에 50행 한도라 구간 분할 조회). ① 평균회귀 상관이 **7월을 뺀 train 에서도** KODEX 200 -0.329(2.4σ) · 코스피200 지수 -0.243(2.4σ) · 코스피 지수 -0.238(2.3σ)로 재현되고, 7월 단독으로도 -0.492 / -0.414 / -0.401 로 독립 확인 — **ETF 추적오차나 특정 월의 우연이 아님**. ② train 만으로 무작위 가중치 1만 개 한계효과를 다시 계산해도 전일 반전(+19.2% vs -19.1%) · 갭 상향(+21.7% vs -12.8%) · 이평선 축소 · 3일 무영향이 **동일하게 재현** — 가중치 결정 절차가 7월 없이도 같은 답에 도달. ③ 7월 실적: 현재 가중치 66.7% / +35.1%(ETF), 61.9% / +27.7%(코스피200) vs 이전 가중치 52.4% / +1.5%, 57.1% / +12.7%. **단 7월 n=21 이라 표준오차 ±10.9%p** — 갭 단독 적중률이 train 63.2% → 7월 47.6% 로 보이나 약 1.4σ 로 유의하지 않다(관찰 대상으로만 기록). 지수 기준 상관(-0.24)이 ETF(-0.33)보다 약하므로 실제 효과 크기는 지수 쪽에 가까울 것으로 본다
  - **7월 자금 곡선 시뮬레이션** ([scripts/_simulate_july.py](scripts/_simulate_july.py)) — 적중률이 아닌 실제 자금으로 재현. 7/1 시드 300만원, 실제 매매 규칙(08:30 방향 판정 → 09:00 개장가 진입 → 4중 청산 → 손실성 청산 시 당일 재진입 차단 → 자금 풀 복리 → 수수료 0.0042% 양방향) 그대로 22거래일. 일봉만으로는 장중 고가·저가 **순서**를 알 수 없어 보수(고가→저가)·낙관(저가→고가) 두 경로를 범위로 제시. **결론: 청산선이 결과를 지배한다** — 현행 -5%/-5% 는 -22.26%~+10.48%(판정 불가), -15%/-10% 는 두 경로 모두 +47.25%(경로 독립, 실현분만 +32.70%). 경로 독립 구간에서 가중치 비교 시 **현재 +47.25% vs 이전 -2.53%** 로 방향 판정 개선 효과가 분리 확인됨. 벤치마크 KODEX 200 매수보유 -21.41% · 인버스 매수보유 +17.25%. 진입 방향은 정방향 11회·인버스 11회로 균형, 청산 21회 중 이익 14회(67%). 갭에 실제 시가를 대용한 낙관 편향은 갭 미사용 하한(+39.69%)으로 확인해 결과를 뒤집지 않음. **한계**: 22거래일 단일 표본, 7월은 코스피200 이 -21% 하락한 고변동 국면, 7/31(+20% 급등일) 미실현분이 결과의 약 14.5%p, 진입가를 시가로 가정(실제는 매도호가)
- [x] **단기 매매 청산선 기본값 5% → 10% (손절·최고가 청산 모두)** — 위 7월 시뮬레이션에서 이 설정이 방향 판정보다 실손익을 크게 좌우함이 확인되어 기본값 자체를 변경. `config.SHORT_TERM_STOP_LOSS_PCT` / `SHORT_TERM_PEAK_DROP_PCT` 상수를 신설해 단일 출처로 두고, `core/settings.py::DEFAULTS`(leaf 유지 위해 config 만 import) · `EtfDayTradeStrategy.__init__` · `trader.build_short_term_strategy` · `trader._sync_short_term_settings` · 대시보드 사이드바 시드값 5곳이 모두 이 상수를 참조하도록 배선 — 이전에는 같은 값이 5곳에 리터럴로 흩어져 있어 변경 시 누락 위험이 있었다. **두 값을 함께 올려야 하는 이유**: 최고가(peak)는 항상 매수가 이상이라 `최고가 × 0.9` 가 `매수가 × 0.9` 보다 늘 위에 있고, 따라서 **최고가 청산이 손절보다 먼저 걸린다**. 최고가 청산선을 그대로 둔 채 손절만 넓히면 손절선은 도달할 기회조차 없어 결과가 전혀 바뀌지 않는다(실측: 최고가 5% 고정 시 손절을 5→15% 로 늘려도 보수 경로 -22.26% 로 동일). 이미 `data/settings.json` 에 5.0 이 저장돼 있으면 기본값보다 우선하므로 기존 저장값도 10.0 으로 갱신(로컬 런타임 파일, git 미추적)
  - 검증: 순수 로직 25건 통과 ([scripts/_test_direction.py](scripts/_test_direction.py) — vol 하한·부호 반전·재정규화·음수 가중치 안전성·변동성 스케일링·중립 밴드·판정 불가·결과 계약). 실 KIS 호출로 갭 stale 시 재정규화 동작 확인(점수 -0.4936 = 가중합 ÷ 0.50). 검증 스크립트 3종 상주: [_check_weights.py](scripts/_check_weights.py)(신호별 적중률·상관·포화율) · [_check_reversion.py](scripts/_check_reversion.py)(평균회귀 + 무작위 1만 개 한계효과) · [_calibrate_norm.py](scripts/_calibrate_norm.py)(배수 재산정)
- [x] 검증 — 순수 로직 38건(대체 ETF 회피 · 4중 청산 경계값 · 재진입 차단 · 원장 분리 · 일단위 갱신) + 모의 API 트레이더 사이클 40건(개장 진입 → 최고가 추적 → 최고가 청산 → 당일 차단 → 익일 보유기간 청산 → 방향 전환 재진입 · 겹침 시 대체 ETF · 외부 청산 감지 · 체결가 보정 · **자금 풀 손익 누적**: 손실 -36,000원 → 풀 2,964,000원 / 이익 +15,000원 → 풀 3,015,000원 → 다음 진입 603주(캡 방식이었다면 600주) · **체결 정산**: 주문가 10,000원 → 실제 체결 10,020원·제비용 450원이 원장·풀에 정확히 반영 · **시장가 증거금**: 주문가능 3,387,580원에서 2,396주 요청은 거부되고 2,080주로 하향돼 통과, 여력 충분 시엔 예산 수량 유지 · **지정가**: 매도1호가 주문·시장가 대비 +314주·부분 체결 시 체결분만 원장 기록 후 잔량 취소) 전부 통과. 실 KIS 조회로 방향 판정 동작 확인(📉 하락 -0.887 → 인버스 후보 3종), 예상체결가 stale 판정이 정상 작동함을 실측 확인

## 다음 작업 후보

- [ ] 단기 매매 청산선을 **실현변동성 배수 기반 동적 값**으로 전환 검토 (예: `2.5 × vol`) — 기본값 10% 는 2026년 상반기 고변동 국면(일간 σ 6.5%) 기준이라, 시장이 진정되면 이번엔 반대로 너무 넓어진다. 방향 판정 정규화를 `realized_vol()` 배수로 바꾼 것과 같은 논리
- [ ] **장전 예상체결가 갭 신호 실장 검증** — 평일 08:30~09:00 에 실호출해 `기준가(stck_sdpr)` 가 당일 세션 기준으로 롤오버되는 시점 확인. 롤오버가 09:00 이후라면 stale 판정에 항상 걸려 갭 신호가 영구 미사용되므로, 그 경우 판정 기준을 `장운영구분코드(antc_mkop_cls_code)` 기반으로 교체. **갭 가중치가 0.50 으로 올라가 이 검증의 중요도가 커졌다** — 갭 제외 시 나머지 3신호로 재정규화되지만 정보량이 크게 준다
- [ ] 단기 매매 진입 시각 상한 도입 — `short_term_buy_window_open()` 이 하한(개장+지연)만 검사해, 자동매매를 오후에 켜면 장 전 판정 그대로 14시에도 진입한다. '개장과 동시에 진입' 전제와 어긋남
- [ ] 방향 판정 가중치 정기 재검증 — 7월 표본 외 검증은 통과했으나 3~7월이 모두 **하나의 고변동 국면**이다. 평균회귀는 고변동 국면의 특징이라 시장이 진정되면 사라질 수 있다. 분기 단위로 `scripts/_check_oos.py`(train/test 분할) 재실행 권장
- [ ] 갭 신호 적중률 관찰 — train 63.2% → 7월 47.6% (ETF 기준). n=21 · ±10.9%p 라 통계적으로 유의하지 않아 가중치 0.50 은 유지했으나, 다음 분기 재검증에서도 낮으면 하향 검토
- [ ] 중립 밴드(`neutral_band`) 사이드바 노출 — 방향 확신이 낮은 날 진입을 건너뛰는 옵션. 현재 0(항상 진입). 정규화 정상화로 점수가 연속값이 되어 이제 실효성이 생겼다
- [ ] 매도 주문도 매도가능수량(`inquire-psbl-sell`) 검증 추가 — 실계좌에서 지정가 매도 거부(2026-07-27 13:28 KODEX 인버스 2600주) 사례 확인. 당일 매수분 매도 제약 여부 점검 필요
- [ ] **(보류) 단기 매매 자금 선차감** — `execute_initial_buy` 가 주문가능금액 **전액**을 후보 수로 균등 분할하고 메인 루프에서 단기 매매보다 먼저 실행되므로, 일반 매수(`buy_enabled`)를 켜면 단기 매매가 "예산 부족" 으로 진입하지 못할 수 있다. 예산 상한은 한도일 뿐 예약이 아님. 해결안: `plan_initial_buy` 에 넘기는 cash 에서 자금 풀 잔액(포지션 미보유 시)을 미리 빼두어 물리적으로 예약. **현재는 자금 풀을 수동 관리하기로 하여 보류** — 두 매수를 함께 켤 계획이 생기면 착수
- [ ] 일반 매수 후보 선정도 장전 시세 반영 여부 점검 — 08:30~09:00 ranking API 가 전일 종가 기준이면 개장 후 1회 재스캔 트리거 고려
- [ ] 매도 발생 시 알림 (Telegram / 카카오톡 등)
- [ ] 확인 주기를 대시보드에서 실시간 변경
- [ ] 추가 매도 전략 (트레일링 스탑 + RSI/이평선 OR 결합 Composite)
- [ ] 매도 전략별 임계값(예: RSI `rsi_max`, 이평선 short/long)도 사이드바에서 변경 가능하게
- [ ] `_MAX_CALLS_PER_SEC`(throttle 초당 한도) 사이드바/설정 노출 — 현재 코드 상수(실전 10/모의 2). 스캔 속도 vs 한도 여유 튜닝용
- [ ] (선택) 대시보드를 trader 스냅샷 파일 read-only 소비자로 전환 — API 소비자를 1개로 축소하면 throttle 없이도 한도 여유 확보 (throttle 로 이미 burst 는 차단됨, 추가 최적화 성격)

---

## 설정값

| 항목           | 값                   |
| -------------- | -------------------- |
| 손절 기준      | 최고점 대비 10% 하락 |
| 가격 확인 주기 | 1분                  |
| 매수 방식      | 지정가 (매도호가 — 사이드바에서 시장가 전환 가능) |
| 매도 방식      | 시장가 (청산 속도 우선) |
| 장 운영 시간   | 평일 09:00 ~ 15:30   |
| 장 전 준비     | 평일 08:30 ~ 09:00 (조회·후보 사전 선정, 매매는 개장 후) |

### 일 단위 단기 매매 (ETF 방향 매매)

| 항목                | 값                                                          |
| ------------------- | ----------------------------------------------------------- |
| 대상                | 코스피200 지수 ETF (상승) / 인버스 ETF (하락) — ETF 로 제한 |
| 방향 판정 시점      | 장 전 준비 시각 (기본 08:30, 개장 30분 전)                  |
| 방향 판정 신호      | 갭 0.50 · 전일등락(평균회귀) 0.25 · 이평선 0.15 · 3일 0.10  |
| 신호 정규화         | 일간 실현변동성(20일) × 배수 — 변동성 국면에 자동 적응        |
| 매수 시점           | 개장 즉시 (09:00, 지연 0분 — 사이드바에서 조절 가능)        |
| 배정 자금 (씨드)    | 300만원 (사이드바 조절 — 변경 시 자금 풀 재설정)            |
| 진입 예산           | min(자금 풀 잔액, 주문가능금액) — 풀에 실현손익이 누적(복리) |
| 손익 정산           | 체결 조회 기반 실제 체결가·제비용 (주문가 근사 아님)         |
| 보유 기간           | 1일 (다음 거래일 개장 시 청산 후 그날 방향으로 재진입)      |
| 손절                | 매수가 대비 -10% (사이드바 조절)                              |
| 최고가 청산         | 매수 이후 최고가 대비 -10% (사이드바 조절)                    |
| 당일 마감 강제청산  | 옵션 (ON 시 15:15 전량 청산 — 오버나이트 미보유)            |
| 재진입 차단         | 손절·최고가·마감 청산 시 당일 재진입 금지 (다음 거래일 재개) |
| 슬롯 분리           | 자체 원장(진입가·수량·최고가) + 겹치는 종목은 대체 ETF 로 회피 |

---

## 파일 구조

```
stock_trader/
├── main.py              # 진입점 (트레이더 + 대시보드 동시 구동)
├── config.py            # 설정값 (손절%, 주기, URL 등)
├── start.sh             # 실행 스크립트
├── stop.sh              # 종료 스크립트
├── core/
│   ├── kis_api.py       # KIS API 호출 (인증, 잔고조회, 현재가, 예상체결가, 매도주문, 매수후보 탐색)
│   ├── trader.py        # Trader 클래스 (전략 주입, 매도/매수 루프 실행, 단기 매매 처리, 보유 분리)
│   ├── logger.py        # 로깅 유틸리티
│   ├── etf_universe.py  # 단기 매매 ETF 유니버스 (방향별 후보 + 대체 ETF 우선순위)
│   ├── market_direction.py  # 장 전 시장 방향 판정 (지수 일봉 추세 + 장전 예상체결가 갭)
│   ├── short_term.py    # 일 단위 ETF 방향 매매 — EtfDayTradeStrategy + 자체 원장·슬롯 헬퍼
│   └── strategy/
│       ├── base.py                        # BuyStrategy / SellStrategy ABC
│       ├── _activate.py                   # 전략 레지스트리 + 활성 전략 팩토리 (settings.json 반영)
│       ├── buy/
│       │   ├── _pool.py                   # 모멘텀 전략 공통 풀 (시총 ∩ 일간등락률 + 보충)
│       │   ├── _indicators.py             # 기술 지표 헬퍼 (sma, rsi)
│       │   ├── volume_momentum.py         # 주간등락률·PER·EPS 가중 티어 (legacy)
│       │   ├── high_proximity.py          # 4주 신고가 근접도·PER 필터
│       │   ├── technical_momentum.py      # 이평선 정배열·RSI 필터 + 거래량폭증·20일수익률 티어
│       │   ├── quality_trend.py           # 우량(EPS/PER/PBR) + 우상향(20MA>60MA·RSI≤70) — 현재 매수 실행
│       │   ├── golden_cross.py            # 5MA가 최근 N일 내 20MA 상향 돌파
│       │   ├── low_per.py                 # 시총 100 ∩ 저PER 가치주 (PER 오름차순)
│       │   └── oversold_rebound.py        # 직전 RSI≤30 + 오늘 종가 반등 + RSI 회복
│       └── sell/
│           ├── trailing_stop.py           # 트레일링 스탑 — 최고가 대비 N% 하락 시 매도 (peak 영속화)
│           ├── rsi_overbought.py          # RSI(14) ≥ rsi_max 시 매도
│           └── ma_dead_cross.py           # 단기MA < 장기MA 시 매도 (데드크로스)
├── ui/
│   └── dashboard.py     # Streamlit 대시보드 UI
├── scripts/             # 전략 검증 도구 (조회 전용 — 주문 없음)
│   ├── _test_direction.py    # 방향 판정 순수 로직 회귀 테스트 (API 불필요)
│   ├── _check_weights.py     # 신호별 적중률·상관·포화율
│   ├── _check_reversion.py   # 평균회귀 검증 + 무작위 가중치 한계효과
│   ├── _check_oos.py         # 표본 외 검증 (train/test 분할 + 지수 교차 확인)
│   ├── _calibrate_norm.py    # 정규화 배수 재산정
│   └── _simulate_july.py     # 자금 곡선 시뮬레이션 (시드·기간 상수로 조절)
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

> `scripts/` 실행은 프로젝트 루트에서 `PYTHONPATH=. .venv/bin/python scripts/_test_direction.py` 형태로 합니다.
> `_test_direction.py` 만 API 없이 돌고, 나머지는 KIS 조회를 사용합니다 (주문은 어느 것도 하지 않습니다).

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

실전·모의투자 키를 **분리**해서 넣습니다. `config.py` 의 `IS_MOCK` 값에 따라 알맞은 키 세트가 자동 선택되므로, 한 번 넣어두면 전환 시 키를 바꿔치기할 필요가 없습니다.

```
# 실전투자 (IS_MOCK=False 일 때 사용)
APP_KEY=실전_앱키
APP_SECRET=실전_앱시크릿
ACCOUNT_NO=실전_계좌번호       # 예: 12345678-01

# 모의투자 (IS_MOCK=True 일 때 사용 — 한국투자증권이 모의투자용으로 별도 발급)
MOCK_APP_KEY=모의_앱키
MOCK_APP_SECRET=모의_앱시크릿
MOCK_ACCOUNT_NO=모의_계좌번호
```

> 모의투자는 **실전과 다른 별도 APP Key/Secret/계좌번호**가 필요합니다 (실전 키로 모의 서버 접속 불가).
> `MOCK_*` 가 없으면 단일 키(`APP_KEY` …)로 fallback 하지만, 모의 서버에는 모의 키만 인증되므로 권장하지 않습니다.
> **실전 모드는 절대 `MOCK_*` 를 읽지 않으므로**, 모의 키가 실거래에 새어 들어갈 위험은 없습니다.

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
| 보유 종목 테이블 | 현재가, 최고가, 수익률, 최고가 대비 하락률 실시간 표시 + 종목별 **자동매도** 체크박스 (체크된 종목만 매도 실행). 단기 매매 물량은 차감되어 표시 |
| 상태 컬럼        | 🟢 정상 / 🟡 주의 / 🟠 손절 임박 / 🔴 손절 실행                                   |
| 단기 매매        | 오늘의 시장 방향(점수·신호별 근거) + ETF 후보 + 원장 기반 포지션(진입가·손절선·청산 예정) |
| 매수 후보 목록   | 전략별 그룹 표시 (primary = 매수 실행 / 보조 = view-only, 사이드바 multiselect 로 선택) |
| 매수 전략 선택   | 사이드바 selectbox: 활성 매수 전략(primary) 변경 가능 — 다음 스캔부터 즉시 반영             |
| 매도 전략 선택   | 사이드바 selectbox: 트레일링 스탑 / RSI 과열 / 이평선 데드크로스 (실시간 교체)            |
| 거래 이력        | 매수/매도 시각, 체결가, 수량, 메모 (최신순) |
| 최근 로그        | `logs/trader.log` 최근 50줄 표시                                                  |
| 자동 새로고침    | 사이드바에서 주기 설정 (기본 60초)                                                |

---

## 테스트 → 실전 전환

[config.py](config.py) 에서 한 줄만 변경 후 재시작(`./stop.sh && ./start.sh`):

```python
# 모의투자
IS_MOCK = True

# 실전투자로 전환 시
IS_MOCK = False
```

전환 시 자동으로 처리되는 것:
- KIS API 서버 (모의 `openapivts:29443` ↔ 실전 `openapi:9443`) 및 거래 tr_id (`VT...` ↔ `TT...`)
- 인증 키 세트 (`MOCK_APP_KEY ...` ↔ `APP_KEY ...`)
- 토큰 캐시 파일 (`data/.kis_token_mock.json` ↔ `.kis_token_real.json` — 서로 안 섞임)

**현재 모드 확인**: 대시보드 상단에 `🟢 모의투자(MOCK)` / `🔴 실전투자(LIVE)` 배지가 상시 표시되고,
브라우저 탭 제목(`트레이더 [모의]`/`[실전]`)과 `logs/trader.log` 시작 로그(`트레이더 시작 [모의투자]`)에도 찍힙니다.

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
 └─ 1분마다 반복 (장 운영시간 내)
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
