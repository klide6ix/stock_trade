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
- [x] **개장 직후 진입 지연 실측 검증 — "10분 기다리면 이미 움직인 가격에 비싸게 산다" 는 성립하지 않음** ([scripts/_check_open_drift.py](scripts/_check_open_drift.py)). 먼저 사실 확인: **현재 대기 시간은 0분**이다(`settings.json::short_term_buy_delay_min`=0, `trader.SHORT_TERM_BUY_DELAY_MIN`=0). 10분은 개별주 단타 시절 기본값이었고 ETF 방향 매매로 바꾸며 0으로 내렸다(위 항목). 실제 진입은 `CHECK_INTERVAL`=60s 주기의 첫 폴링, 즉 **09:00~09:01** 이다. 그 위에서 "만약 기다린다면" 을 KODEX 200·KODEX 인버스 **1분봉 실측**(2026-03-10~07-31, 99영업일 / 판정 성립 79일 / 약 500회 조회, `data/.minute_bars_cache.json` 캐시)으로 정량 확인.
  - **① 지수 자체의 움직임**: 09:00 시가 대비 09:10 드리프트는 평균 **+0.00%** · 중앙 -0.01% · **평균 절대값 0.73%**(σ 0.97%). 1% 초과 24%, 2% 초과 7% 의 날. "많이 움직인다" 는 체감은 맞지만 **방향이 한쪽으로 쏠려 있지 않다**
  - **② 매매 방향 기준 진입가**(상승일=정방향 ETF·하락일=인버스 ETF, 즉 실제로 사는 종목의 가격): 09:10 진입은 09:00 대비 평균 **-0.09%**(오히려 싸다) · 중앙 -0.02% · 불리한 날 48% · **t=-0.84 로 유의하지 않음**. 불리한 날 평균 +0.59% / 유리한 날 평균 -0.73% 로 **양방향 대칭**이다. 청산가는 지연과 무관하므로 이 표가 곧 일별 손익 차이다 — 지연은 **체계적 손해가 아니라 거래당 ±0.9%p 의 잡음**을 더할 뿐
  - **③ 오히려 평균회귀**: corr(09:00→09:10 드리프트, 09:10→종가) = **-0.241**. 첫 10분 오른 날은 이후 평균 -0.41%, 내린 날은 +0.89%. 즉 개장 직후 튄 가격은 되돌리는 경향이라 '늦게 사서 고점을 떠안는' 구조가 아니다
  - **④ 자금 곡선**(시드 300만·손절 -10%·최고가 -10%): 09:00 +59.9% / 09:05 +86.7% / 09:10 +72.4% / 09:30 +62.1%. 지연을 늘려도 단조 악화가 없고, 편차는 거래당 σ 0.9%p × 77거래 규모의 잡음 범위 안이다 — **지연 유무로 우열을 가릴 근거 없음**
  - 이 스크립트는 트레이더의 1분 폴링을 그대로 재현(각 분봉 **종가**를 폴링 가격으로 사용)하므로, [_simulate_july.py](scripts/_simulate_july.py) 의 최대 한계였던 **장중 고가·저가 순서 가정(보수/낙관 경로)이 사라진다**. 다만 방향 판정은 3~7월 in-sample 이고 갭 신호에 실제 시가를 대용하므로 **절대 수익률은 낙관 편향** — 유효한 것은 지연 간 *비교*뿐이다(편향이 모든 시나리오에 동일하게 작용). 표본 79일
  - 부수 확인: 트레이더를 **08:30 장전 준비 창 이전에 켜 두는 것이 전제**다. 09:00 이후에 기동하면 `prepare_market_open()` 의 매수 후보 스캔(primary+view 전략 각각 수십~수백 회 조회)이 먼저 끝나야 단기 매매 진입 분기에 도달하므로, 이 경우엔 실제로 수 분의 지연이 생긴다
- [x] **🔴 장전 갭 신호가 0% 로 편입되던 결함 수정 — 확신도가 정확히 절반으로 희석되고 있었다** ([core/market_direction.py](core/market_direction.py)). 2026-08-03 08:25~08:28 실관측([scripts/_watch_premarket.py](scripts/_watch_premarket.py))으로 발견.
  - **증상**: 개장 35분 전인데 판정 로그의 갭 출처가 `장중 실시간 등락률` 이었다. KIS 는 개장 전에도 **오늘 날짜 일봉을 전일 종가로 채워서** 돌려주는데(실측: `stck_bsop_date`=오늘 · 종가=전일종가 108,820 · 거래량 0), `has_today_bar` 가 날짜만 보고 True 가 되어 `_gap_signal` 이 장전 예상체결가 경로 대신 실시간 등락률 경로를 탔다. 개장 전 실시간 등락률은 +0.00% 이므로 **가중치 0.50 짜리 갭이 '0' 이라는 값으로 점수에 편입**된다
  - **왜 미사용보다 나쁜가**: 갭을 못 쓰면 나머지 신호로 재정규화(분모 0.50)되어 확신도가 유지되는데, 0 으로 편입되면 분모만 1.0 으로 커져 **점수가 정확히 절반**이 된다. 실측 점수 -0.247 은 갭 제외 재정규화 시 -0.493 이었다. 방향이 팽팽한 날에는 부호가 뒤집히거나 중립 밴드에 걸릴 수 있다
  - **수정**: `_today_bar_is_live(bars, today_str, now)` 신설 — 오늘 봉을 장중 봉으로 인정하려면 **거래량 > 0** 과 **정규장 개장(09:00) 이후** 를 함께 요구한다. 거래량 조건이 장전·휴장일 placeholder 를 모두 걸러내고, 시각 조건은 거래량 필드에 직전 세션 값이 남는 경우의 보강이다. `past` 필터는 날짜 기준 그대로 두어 placeholder 가 전일 종가를 오염시키지 않는다
  - **앞선 개장 직후 재판정과 맞물린다** — 이 수정으로 장전에는 예상체결가가 형성될 때까지 갭이 '미사용'(재정규화)되고, 09:00 최종 재판정이 실측 갭을 잡는다. 두 변경이 함께 있어야 갭 신호가 온전히 살아난다
  - 검증: 회귀 8건 추가 ([scripts/_test_direction.py](scripts/_test_direction.py) — 거래량 0/장전·거래량 0/장중(휴장일)·거래량>0/장전·거래량>0/장중·오늘봉 없음의 경로 선택 5종 + **0% 편입이 점수를 정확히 2배 희석시킴을 항등식으로 확인** + gap_source None + 전일 종가 무오염). 실 KIS 호출로 확인: 같은 봉을 08:40 으로 판정하면 `False`(장전 경로), 09:18 현재(거래량 2,917,087주)는 `True`(실시간 경로) → 갭 -8.34% 로 판정 -0.710
- [x] **σ 추정치 MAD 전환 검토 — 명분은 입증됐으나 실손익은 악화, 채택 보류** ([scripts/_check_vol_estimator.py](scripts/_check_vol_estimator.py)). 표준편차가 급등락 하루에 오염되는 문제를 강건 추정치(MAD, 중앙값 절대편차 ×1.4826)로 풀 수 있는지 실측.
  - **명분은 그대로 확인됨** — 2026-07-31 의 +24.17% 하루가 표본에 편입될 때 표준편차는 5.16% → 7.50%(**+45.4%**, 트레일링 10.3% → 15.0%)로 뛰는 반면 MAD 는 6.61% → 7.02%(**+6.1%**)에 그친다. 이상치 저항성은 의도대로 작동한다
  - **그런데 손익은 오히려 나빠진다** — 30거래일: 표준편차 **+21.39%** vs MAD 배수그대로 +18.05% vs MAD 배수재보정(2.33σ/1.87σ) +20.19%. 전체 99일 train/test: 표준편차 **+54.50%**(train +18.37% / test +30.93%) vs MAD +50.92% / 재보정 +53.44%. 어느 구간에서도 MAD 가 앞서지 않았다
  - **원인은 안정성** — 인접 거래일 사이 σ 변화율 평균이 표준편차 **5.31%** vs MAD **10.15%** 로 MAD 가 두 배 출렁인다. 중앙값은 창이 굴러갈 때 계단식으로 점프하기 때문이다. 30일 구간 청산선 범위도 8.0~10.5%(표준편차) vs 5.4~13.7%(MAD)로 벌어졌고, 그 불안정이 장중 청산 1건을 더 만들어 손해로 이어졌다
  - **1.4826 상수의 함정** — 이 상수는 정규분포 전제다. 실제로 MAD/표준편차 비율이 평균 0.949 지만 범위가 **0.593~1.483** 이고, 2026-07-20~31 구간에서는 MAD 가 표준편차보다 **30~39% 크게** 나왔다(등락폭이 고르게 커서 꼬리가 얇은 구간). 회귀 테스트에 이 성질을 못박아 뒀다
  - **결론: 표준편차 유지.** 이상치 문제는 상한 클램프로 이미 충분히 막힌다 — 클램프를 5~15% → 3~30% 로 풀어도 전체 성과 차이가 +0.24%p 에 불과하고(트레일링 2.0σ 기준 **상한 발동 0일** / 하한 16일), 클램프 자체가 비용을 거의 치르지 않는 것도 함께 확인했다. `realized_vol_mad()` 는 향후 재검토용으로 [core/market_direction.py](core/market_direction.py) 에 남겨 둔다(현재 호출처 없음)
  - 검증: 회귀 7건 추가 ([scripts/_test_direction.py](scripts/_test_direction.py) — 하한·표본부족·정규분포 근사·꼬리 얇은 표본 과대추정·이상치 저항성 대조). 시뮬레이션 재사용을 위해 [_simulate_recent.py](scripts/_simulate_recent.py) 의 본체를 `run(days, vols, strategy)` 로 분리
- [x] **단기 매매 청산선을 실현변동성 배수로 전환 (권장안 적용)** — 위 검증 결과를 코드에 반영. 청산선 = **배수 × 진입 시점 일간 실현변동성 σ**, 손절 `SHORT_TERM_STOP_LOSS_MULT`=2.5σ · 트레일링 `SHORT_TERM_PEAK_DROP_MULT`=2.0σ, 결과는 `SHORT_TERM_EXIT_MIN_PCT`=5% ~ `SHORT_TERM_EXIT_MAX_PCT`=15% 로 클램프.
  - **σ 전달 경로**: `judge_direction()` 의 `vol` → `find_targets()` 후보 dict `변동성(%)` → `target_to_settings()` 가 슬롯 `vol` 로 복사 → `mark_entry` 이후에도 유지 → `should_sell` 이 참조. **진입 시점 σ 를 슬롯에 박제**하므로 보유 중에 σ 가 변해도 청산선이 흔들리지 않는다(같은 가격이 어제는 청산, 오늘은 유지가 되면 판단을 재현할 수 없다)
  - **클램프 근거**: 검증 구간 σ 가 2.83~7.35% 였고 트레일링 2.0σ 가 5.7~14.7% 였다 — **검증되지 않은 영역으로 나가지 않게** 하는 장치다. 상한이 특히 필요한데, 표준편차는 제곱 평균이라 2026-07-31 의 +24.17% 하루가 σ 를 5.16% → 7.50%(+45%)로 밀어올리고 그 효과가 20거래일간 유지된다
  - **fallback**: σ 를 못 구한 슬롯(판정 실패·구버전 데이터)은 고정 %(10/10)로 되돌아간다. 청산은 안전장치라 근거가 없다고 비워둘 수 없다
  - **사이드바에서 되돌릴 수 있다** — `settings.json::short_term_exit_mode`("vol" 기본 / "fixed") 라디오로 전환, 배수·하한·상한도 조절 가능. 고정 모드를 고르면 기존 `%` 입력이 다시 노출된다. 트레이더는 매 주기 `_sync_short_term_settings()` 로 재읽기(변경 시에만 로그)
  - **대시보드 표시**: 포지션 caption 이 `손절선 88,000원(-12.9%) · 최고가 → 청산선 …(-10.3%) · 기준 σ 5.16%` 형태로 실제 적용값과 근거를 함께 노출
  - 검증 25건 통과 ([scripts/_test_exit_thresholds.py](scripts/_test_exit_thresholds.py) — 배수 산출·클램프 상하한·fallback 4종·고정 모드·`should_sell` 경계값·σ 전달 경로·display_name)
- [x] **최근 30거래일 재시뮬레이션 (배수 청산선 적용)** — [scripts/_simulate_recent.py](scripts/_simulate_recent.py) 가 규칙을 재구현하지 않고 **구현체 `EtfDayTradeStrategy.should_sell` 을 직접 호출**하도록 바꿔 코드와 시뮬레이션의 괴리를 없앴다. 2026-06-19~07-31 · 시드 300만원 결과 **3,641,730원(+21.39%)** — 고정 10/10 의 3,560,019원(+18.67%) 대비 **+2.72%p**. 차이는 거의 전부 06-23 한 건에서 나왔다(청산선 8.0% 로 좁아져 14:16 에 -7.29% 로 청산, 고정 10% 였다면 15:09 에 -9.38%). 이 구간은 σ 가 3.99~5.26% 로 좁아 청산선이 8.0~10.5% 였고 고정 10% 와 크게 다르지 않아 개선폭도 제한적이다 — 배수 방식의 진가는 σ 가 2.8% 까지 내려갔던 3~5월 구간에서 나온다(전체 99일 기준 +81.61% vs +65.64%)
- [x] **청산 규칙 전면 비교 — 고정 % 는 국면이 바뀌면 무력해진다** ([scripts/_check_exit_rules.py](scripts/_check_exit_rules.py)). "초반에 오르다 폭락(이익 반납) / 초반에 내리다 폭등(손절 후 반등 놓침)" 두 케이스를 겨냥해 22개 규칙을 같은 분봉 데이터로 비교, **train(2026-03~05) / test(2026-06~07)** 로 나눠 집계.
  - **진단**: 장중 최고이익(MFE) 평균 +2.22% · 최대손실(MAE) 평균 -2.37% · **종가까지 반납한 이익 평균 2.05%p**(중앙 1.28%p). 장중 +3% 이상 찍은 날 19일 중 평균 2.04%p 반납. 반대로 장중 -5% 이상 밀린 날 10일 중 종가에 플러스로 끝난 날은 **2일뿐**
  - **이익 반납을 막으려는 시도는 전부 손해** — 부분익절 +5% 절반(+60.81%) · 하드익절 +5%(+50.79%) · 무장 트레일링 arm+3/trail3(+26.23%) 모두 장중 청산 없음(+71.07%)보다 나빴다. 반납은 실재하지만 그걸 자르면 더 잃는다
  - **현행 10/10 의 장중 청산은 값을 못 한다** — 99일 중 단 2회 발동했고 **둘 다 손해**였다(2026-06-23 -0.44%p · 07-29 -0.55%p, 순효과 -0.99%p). 사실상 '익일 개장 청산만' 과 같은 규칙이면서, 발동할 땐 오히려 손해를 보탠다
  - **유일하게 개선한 계열은 실현변동성 배수** — `손절 2.5σ / 트레일링 2.0σ` 가 **train +10.12% · test +64.43% · 전체 +81.61%(Sharpe 2.56, MDD -18.9%)** 로 현행 10/10(+2.25% / +61.21% / +65.64%, Sharpe 2.09)을 양 구간 모두 앞섰다. 장중 청산 5회 중 4회 이득(순효과 **+6.99%p**). **이유가 명확하다** — 저변동 국면이던 5월엔 고정 10% 가 너무 넓어 한 번도 발동하지 않았지만(train 이 '익일청산만' 과 완전히 동일), 배수 방식은 그때 σ 가 작아 자동으로 좁아져 제 역할을 했다. 방향 판정 정규화를 배수로 바꾼 것과 같은 논리
  - **손절선은 사실상 사문(死文)** — 모든 장중 청산이 트레일링(최고가 대비)에서 나왔고 하드 손절은 한 번도 발동하지 않았다. 실질 파라미터는 트레일링 폭 하나뿐
  - **한계**: 개선폭이 청산 5건에서 나온 것이라 표본이 매우 작다. 좁힐수록 whipsaw 위험이 커지는 것도 확인됐다 — 2.0σ/1.5σ 는 2026-07-14 에 -5.32% 에서 잘랐는데 익일 시가가 +6.6% 로 올라 **그 한 건에서만 -11.95%p** 를 잃었다(사용자가 말한 '초반에 내리다 폭등' 케이스). 채택 시 배수에 하한·상한 클램프 권장
- [x] **보유 방식 검증 — "오버나이트가 리스크의 70%니 매일 청산하자" 는 실측상 손해** ([scripts/_compare_hold_mode.py](scripts/_compare_hold_mode.py)). 진입→익일 시가 σ 4.69% 중 오버나이트가 σ 3.28%(70%)를 차지하고 손절 -10% 는 갭에 무력하므로(78일 중 장중 발동 2일·갭 우회 1일) `close_at_market_end` 를 켜는 게 맞아 보였으나, **수익도 같은 구간에서 나온다**. 분봉 캐시로 1분 폴링을 재현해 같은 날짜·같은 방향 판정으로 두 모드를 돌린 결과(2026-03-10~07-31, 79일):
  - **A. 1일 보유(현행)**: +59.91% · 거래당 +0.59%(σ 4.78%) · 승률 60% · **연환산 Sharpe +1.96** · MDD -24.20% · 최악 거래 -10.47%
  - **B. 당일 15:15 청산**: +18.24% · 거래당 +0.26%(σ 3.23%) · 승률 51% · **Sharpe +1.27** · MDD -19.14% · 최악 거래 -9.38%
  - **구간 분해**(청산 규칙 없이 순수 보유): 장중(09:00→15:15) 평균 +0.27%·σ 3.23%·일Sharpe +0.083 vs **오버나이트(15:15→익일 09:00) 평균 +0.43%·σ 3.29%·일Sharpe +0.130**. 오버나이트가 리스크의 70%지만 **수익의 62%** 를 만들고, 위험 대비로는 오히려 장중보다 낫다
  - **편향 주의**: 처음에 오버나이트를 '다음 날도 같은 방향이라 종목이 유지되는 날' 로 집계했더니 평균 +2.77%·승률 93% 가 나왔는데, 다음 날 방향은 갭 신호(가중치 0.50)가 **그날 시가로** 정하므로 그 조건 자체가 '익일 시가가 유리하게 움직인 날' 을 고르는 look-ahead 선택 편향이었다. 방향과 무관하게 전량 집계해 +0.43% 로 정정. 스크립트에 주석으로 박아 뒀다
  - **결론: 현행 유지(`close_at_market_end` OFF).** 오버나이트 꼬리(최악 -7.63%, 5% 분위 -4.62%)를 줄이고 싶다면 청산 시점이 아니라 **포지션 사이즈**로 조절하는 것이 정석이다 — A 를 B 와 같은 변동성(×0.676)으로 축소해도 기대수익은 +0.40% 로 B(+0.26%)의 **1.5배**다. 방향 판정의 갭=실제 시가 대용 편향은 **B 의 장중 leg 를 더 부풀리므로**(진입일 시가를 알고 방향을 정한 셈), 편향을 걷어내면 A 우위는 더 커진다. 한계: 79일 단일 고변동 국면 — 오버나이트 프리미엄은 국면 의존적일 수 있어 분기 재검증 대상
- [x] **방향 판정을 장전 매분 재판정 + 개장 직후 최종 재판정으로 전환 — 갭 신호(가중치 0.50) 유실 방지** ([core/trader.py](core/trader.py) `run()`). 기존에는 `prep_date` 가드로 **08:30 첫 사이클 1회만** 판정했다. 그 순간 예상체결가가 stale 이거나 예상거래량이 0(동시호가 미형성)이면 [_gap_signal](core/market_direction.py#L141-L158) 의 3중 관문에 걸려 **그날 하루가 통째로 갭 없이 확정**되는데, 갭을 뺀 나머지 3신호는 실측 누적손익 -2.8% 로 우위가 사실상 없다. 08:31~08:59 의 29개 사이클은 장전 분기에 들어와서 아무것도 하지 않고 지나갔다.
  - **장전 매분 재판정** — 장전 분기에 `else` 를 달아 매 사이클 `_prepare_short_term(force=True, quiet=True)` 를 돌린다. 갭이 언제 형성되는지 미리 알 수 없으므로, 매분 다시 보면 쓸 수 있게 된 시점부터 자동 반영된다. 08:30 은 동시호가가 막 열려 호가가 가장 얇은 시점이라 **개장에 가까운 판정일수록 정확**하다는 점도 같이 해결된다. 무거운 매수 후보 스캔(`scan_buy_candidates`, 전략당 수십~수백 호출)은 `prepare_market_open` 에 남겨 하루 1회만 돌게 분리했다 — 방향 판정 경로만 떼면 사이클당 약 6회(일봉 1 + 갭 1 + ETF 시세 3 + 잔고 1), 30분간 약 180회로 한도에 여유가 있다
  - **개장 직후 최종 재판정** (`open_rejudge_window`, 평일 09:00~09:05 하루 1회) — 09:00 을 넘기면 오늘 일봉이 생기면서 갭 신호가 **예상체결가(추정) → 실시간 등락률(실측)** 로 자동 전환된다. 여기서 한 번 더 판정하면 예상체결가가 끝까지 stale 이어도 갭이 살아나고, 추정 오차가 방향 판정에서 사라진다. 무엇보다 **지금까지의 검증([_simulate_july.py](scripts/_simulate_july.py)·[_check_open_drift.py](scripts/_check_open_drift.py))이 전부 '실제 시가 기준 갭' 으로 이루어졌으므로, 이 변경은 검증 가정과 코드를 일치시킨다**. 진입이 09:00:30~09:01 로 밀리는 비용은 실측 +0.03%(t=0.81, 유의하지 않음). 창을 09:05 로 좁힌 이유는 장중 재시작 시 오후에 방향이 뒤집히지 않게 하기 위함 — 이 전략은 '개장 시점의 방향' 에 하루를 건다
  - **재판정이 잦아지며 새로 필요해진 3가지 안전장치** — ① **갭 우선**(`short_term.keeps_previous_verdict`): 조회 실패·stale 로 갭이 빠진 판정이 이미 갭을 반영한 오늘 판정을 덮지 않는다(어제 갭 판정은 대상 아님). ② **사용자 선택 보존**: 미보유 슬롯을 무조건 후보 #1 로 덮으면 대시보드에서 고른 종목이 1분 만에 되돌아가므로, 고른 종목이 새 후보 목록에 남아 있으면 유지하고 방향이 뒤집혀 사라졌을 때만 #1 로 교체한다. ③ **오늘 차단 유지**: `blocked_date=None` 무조건 초기화를 `is_blocked(slot)` 검사로 바꿔, 어제 차단은 풀되 **오늘 손절로 걸린 차단은 재판정으로 풀리지 않게** 했다. 더불어 종목·선정사유가 모두 같으면 settings 쓰기와 로그를 생략해 매분 churn 을 없앴다
  - 검증 33건 통과 ([scripts/_test_rejudge.py](scripts/_test_rejudge.py)) — 갭 우선 규칙 7건 · 재판정 창 경계 7건 · 슬롯 갱신 규칙 9건 + **메인 루프 배선 9건**(가상 시계로 08:29 기동→09:02 까지 34사이클 재생: 무거운 스캔 2회만 · 장전 재판정 08:31~08:59 29회 · 개장 재판정 09:00 정확히 1회 · 재판정이 진입 판정보다 먼저 실행)
- [x] **보유 방식 재검증 (σ 배수 청산선 기준) — "매일 마감 전 청산" 은 여전히 손해, 다만 근거는 바뀌었다** ([scripts/_compare_hold_mode.py](scripts/_compare_hold_mode.py)). 이전 비교는 **고정 10/10 청산선** 시절 결과였고, 그 뒤 청산선이 실현변동성 배수(2.5σ/2.0σ)로 바뀌었다. 청산선이 실손익을 지배한다는 게 이 프로젝트의 반복 관찰이므로 현행 구현으로 다시 돌렸다. 스크립트를 규칙 재구현 방식에서 **[_simulate_recent.py](scripts/_simulate_recent.py) 의 `run()` 본체 + 전략 인스턴스만 교체**하는 방식으로 바꿔, 청산 판정을 구현체 `EtfDayTradeStrategy.should_sell` 에 그대로 위임한다. 2026-03-10~07-31 · 99영업일 · 시드 300만원.
  - **A. 1일 보유(현행)**: **+54.50%** · 거래당 +0.56%(σ 4.73%) · 승률 59%(75회) · 자산곡선 Sharpe **+1.96** · MDD -20.48% · 최악 거래 -10.47%
  - **B. 당일 15:15 청산**: **+26.08%** · 거래당 +0.34%(σ 3.15%) · 승률 51%(79회) · Sharpe **+1.56** · MDD -16.03% · 최악 거래 -8.47%
  - **표본 외**: train(03~05) A +18.37% vs B +5.32%(**+13.05%p**) · test(06~07) A +30.93% vs B +19.24%(**+11.70%p**) — 양 구간 모두 같은 방향
  - **리스크 감소는 실재한다** — MDD -20.5%→-16.0%, 최악 거래 -10.47%→-8.47%, 거래당 σ 4.73%→3.15%. 문제는 **수익이 더 많이 줄어든다**는 것이다(위험 -33%, 수익 -52%)
  - **🔴 이전 결론의 근거는 정정한다** — 예전 기록은 "오버나이트가 리스크의 70% 지만 수익의 62% 를 만들고 위험 대비로도 장중보다 낫다(오버나이트 Sharpe 0.130 > 장중 0.083)" 였다. 방향 판정 소스를 08:30 일봉 시가 갭 → **09:00 실측 갭**(현행 개장 직후 재판정 배선과 일치)으로 바꾸자 장중 +0.32%(t 0.89) · 오버나이트 +0.31%(t 0.82) 로 **거의 동률**이 되고, 짝지은 차이(장중−오버나이트)는 -0.13%p · **t -0.26 으로 유의하지 않다**. 뒤집힌 원인은 **79일 중 단 2일의 방향 차이**였다 — leg 별 우열 주장은 이 표본이 지탱하지 못한다. 반면 **A vs B 모드 비교 자체는 이와 무관하게 견고**하다(train·test 모두 A 우위)
  - **위험조정 우위는 이전보다 약하다** — 거래당 σ 를 같게 맞추면(A×0.665) 기대수익 +0.37% vs B +0.34% 로 **사실상 동률**이다(이전 기록의 1.5배 우위는 재현되지 않음). 자산곡선 Sharpe 로는 A(+1.96) > B(+1.56). 즉 **"오버나이트가 위험 대비 더 낫다" 는 주장은 세울 수 없지만, "위험을 줄이려고 마감 청산한다" 는 것도 비효율**이다 — 같은 위험으로 맞추면 기대수익이 같거나 A 가 약간 높으면서 왕복 거래(비용)는 A 가 더 적다
  - **결론: 현행 유지(`close_at_market_end` OFF).** 오버나이트 꼬리(최악 -7.63%, 5% 분위 -5.14%)를 줄이려면 청산 시점이 아니라 **포지션 사이즈**(`short_term_budget`)로 조절하는 것이 맞다
  - **부수 수정**: `_simulate_recent.run()` 이 장중 청산을 `stop_loss`/`peak_drop` 두 사유로만 받아 **`close_at_market_end` 옵션이 시뮬레이션에서 통째로 무시되던 결함**을 고쳤다(`INTRADAY_EXITS` 로 `market_end` 포함). 이 결함이 있는 채로는 B 모드가 A 와 동일한 결과를 내 비교 자체가 성립하지 않는다. 기본 전략(옵션 OFF) 결과는 무변경 — 30거래일 재현값 +21.39% 동일, 회귀 `_test_exit_thresholds`·`_test_direction` 전부 통과
  - **한계**: 99일 단일 고변동 국면(코스피200 -21% 구간 포함), 방향 판정은 in-sample, 지정가 스프레드·시장가 슬리피지 미반영. 오버나이트 프리미엄은 국면 의존적일 수 있어 분기 재검증 대상
- [x] **극단 변동 구간(2026-07-27~31) 제외 재검증 — 결론은 그 5일이 만든 게 아니었다** ([scripts/_compare_hold_mode.py](scripts/_compare_hold_mode.py) `EXCLUDE_FROM`). 위 99일 표본의 마지막 주가 유난히 격해(07-28 **-11.19%** · 07-31 **+24.17%**) 결론을 혼자 떠받치고 있는지 확인. **제외 구간 5일 σ 13.68% vs 나머지 94일 4.49% — 3.0배**로 '변동성이 심하다' 는 전제 자체가 실측으로 확인됐다. 이 5일은 표본의 **마지막 주**라 제외 = 단순 절단이고, 중간을 도려낼 때 생기는 '없던 오버나이트가 이어붙는' 왜곡이 없다(스크립트에 `assert` 로 못박음). 청산선 σ 는 직전 20일 종가로 산출되므로 뒤를 자르는 것은 남은 구간의 청산선에 영향을 주지 않는다.
  - **94일 결과**: A. 1일 보유 **+47.34%**(Sharpe **+2.16** · MDD -19.32%) vs B. 마감 청산 **+22.75%**(Sharpe **+1.63** · MDD -16.03%) — 차이 **+24.59%p**
  - **99일 대비**: 차이는 +28.42%p → +24.59%p 로 줄었지만 **위험조정 성과는 오히려 좋아졌다**(A Sharpe 1.96 → 2.16 · B 1.56 → 1.63). 즉 그 5일은 수익의 크기에는 기여했어도 **결론의 방향을 만들지는 않았다**
  - **train/test 모두 유지** — train(03~05) +13.05%p(불변, 제외 구간이 test 쪽에만 있음) · test(06~07, 43→38일) +11.70%p → **+8.35%p**. 제외 후에도 양 구간 A 우위
  - 구간 분해도 그대로 — 장중 +0.29%(t 0.89) vs 오버나이트 +0.27%(t 0.77), 짝지은 차이 t -0.10 으로 **여전히 어느 쪽도 유의하지 않다**. 동일 변동성 환산은 A×0.596 → +0.36% vs B +0.31%
  - 부수 확인: A 의 최악 거래 -10.47% 는 제외 구간 **밖**에서 나왔다(제외해도 그대로). B 는 -8.47% → -7.29% 로 개선 — 마감 청산이 줄이는 꼬리가 실제로 극단일에 몰려 있었다는 뜻이라, **그 5일을 빼면 B 의 존재 이유(꼬리 절단)가 오히려 약해진다**
- [x] **개장 후 매수 지연 재검증 (σ 배수 청산선 기준) — 5분 지연이 실제로 유리하다** ([scripts/_check_open_drift.py](scripts/_check_open_drift.py) ④). 이전 검증도 고정 10/10 청산선 + 08:30 갭 판정 시절 결과라 "지연 유무로 우열을 가릴 근거 없음" 이었는데, 현행 규칙으로 다시 돌리자 **결론이 바뀌었다**. ④ 지연별 자금 곡선을 규칙 재구현(`simulate()`, 고정 10/10 하드코딩)에서 **[_simulate_recent.py](scripts/_simulate_recent.py) `run(entry_at=…)` 위임**으로 교체 — 청산 판정이 구현체로 가고 방향 판정도 09:00 실측 갭으로 통일된다. `run()` 에 `entry_at` 인자 신설(**청산은 지연과 무관하게 09:00** — 실제 트레이더도 `short_term_buy_window_open()` 이 매수만 막고 매도는 막지 않는다).
  - **94일(극단 5일 제외) 수익률**: 09:00 +47.34%(Sharpe 2.16) · 09:03 +55.69% · **09:05 +72.29%(Sharpe 2.81)** · 09:10 +63.51% · 09:15 +66.42% · 09:30 +62.46%. 99일 표본도 같은 형태(09:00 +54.50% → 09:05 +82.24%)
  - **train·test 양쪽에서 재현** — train(03~05) 09:00 +18.37% → 09:05 +24.54% · test(06~07) +24.52% → +37.53%. 09:03~09:30 전 구간이 09:00 을 앞선다(09:01 만 예외)
  - **메커니즘은 순수 진입가** — 지연을 바꿔도 거래 수 70건·장중 청산 6건·보유만료 64건이 **모든 지연에서 동일**하다. 즉 청산 구조와의 상호작용이 아니라 5분 뒤에 더 싸게 사는 것이 전부다. 거래당 평균 +0.604% → **+0.833%**(+0.23%p) 이고 거래당 σ 는 4.58% → 4.68% 로 사실상 불변 — **위험을 더 지지 않고 얻는 개선**
  - **근거는 ③ 평균회귀** — corr(09:00→09:10 드리프트, 이후 종가) = **-0.241**, 첫 10분 오른 날 이후 평균 -0.41% / 내린 날 +0.89%. 개장 직후 튄 가격이 되돌아오므로 조금 기다리면 그 되돌림을 받는다. 진입가 실측: 09:05 진입은 09:00 대비 평균 **-0.202%**(t **-2.30**, n=74)
  - **⚠️ 과최적화 경계** — 09:05 가 정확히 최고점인 것은 6개 후보를 같은 표본에서 비교한 결과라 그대로 믿을 수 없다. Bonferroni 보정(6검정, |t|>2.64) 은 통과하지 못하고 하위구간 t 도 -1.80/-1.65 로 개별로는 유의하지 않다. **표본이 지탱하는 주장은 "3분 이상 기다리는 편이 낫다" 까지**이고, 3~30분 사이 우열은 잡음이다. 5분은 그 구간 안이면서 장 초반 유동성도 확보되는 지점
  - **코드 기본값은 0 유지** — `settings.json` 저장값이 우선하는 구조라 기본값 변경은 실효가 없고, 위 경계 때문에 in-sample 최적값을 상수로 박지 않는다(방향 판정 가중치 때와 같은 원칙). 운영값은 사이드바에서 조절
- [x] **94영업일 일자별 시뮬레이션 (현재 운영 설정 그대로)** — [_simulate_recent.py](scripts/_simulate_recent.py) 에 `--start/--end/--days/--entry` CLI 인자 + 월별 집계 + 위험지표(Sharpe·MDD·거래당 σ·최고/최악)를 추가해 임의 구간을 일자별로 재현할 수 있게 했다. 인자 없이 실행하면 기존과 동일(최근 30거래일·09:00, 재현값 +21.39% 불변). `.venv/bin/python -m scripts._simulate_recent --start 20260310 --end 20260724 --entry 0905`
  - **결과(시드 300만 · 09:05 진입 · 1일 보유 · 손절 2.5σ/트레일링 2.0σ)**: 최종 평가자산 **5,168,574원(+72.29%)** · 실현 자금 풀 4,985,240원 · 거래 70회 승률 60% · 거래당 +0.83%(σ 4.68%) · **Sharpe +2.81 · MDD -18.78%** · 청산 보유만료 64 · 손절 2 · 최고가 4
  - **월별**: 4월 +10.44% · 5월 +12.77% · 6월 +10.53% · 7월(24일까지) **+25.15%**. 벤치마크 KODEX 200 매수보유 +29.19% · 인버스 매수보유 -33.12%
  - **⚠️ 94일 중 실제 매매는 74일** — 앞 20거래일(03-10~04-06)은 방향 판정에 필요한 20일 이평선 warm-up 구간이라 전량 '판정불가'로 미진입이다. `get_daily_ohlcv` 가 100행 한도라 일봉이 2026-03-10 부터만 있어 그 앞을 못 채운다. 이 구간의 자산은 시드 그대로이고, **앞선 모든 비교(보유방식·지연)도 동일한 74일 위에서 이뤄졌다**
  - **09:00 진입 대조**: +47.34%(Sharpe 2.16 · MDD -19.32% · 거래당 +0.60%) — 같은 70거래에서 진입 시각만 5분 옮긴 차이
  - **한계**: 방향 판정 in-sample, 지정가 스프레드·시장가 슬리피지 미반영, 분봉 종가를 체결가로 가정. 마지막 날 인버스 4,594주 미청산분(평가손익)이 결과에 포함
- [x] **보유 이월 방식 비교 — "방향이 같으면 들고 간다" 는 현행보다 낫지 않다** ([scripts/_compare_carry_mode.py](scripts/_compare_carry_mode.py)). 현행은 보유기간 만료(1일)에 **방향과 무관하게** 전량 청산 후 그날 방향으로 재진입한다([core/trader.py](core/trader.py) `_short_term_exit` — "같은 종목이어도 무방"). 실측상 보유만료 청산 63건 중 **33건이 같은 종목 재매수**였다. 이월이 단순 거래비용 절감이 아니라 **전략 변경**인 점이 핵심 — ① 트레일링 최고가가 며칠에 걸쳐 누적(현행은 매 진입마다 매수가로 리셋) ② 손절선이 최초 진입가 기준 ③ 청산선 σ 가 최초 진입일 값으로 고정 ④ 09:00 청산 → 09:05 재매수 사이 5분 공백과 그 구간 평균회귀 이득 소멸.
  - **두 모드를 같은 루프(`simulate(carry=…)`)로 돌리고, `carry=False` 가 [_simulate_recent.py](scripts/_simulate_recent.py) `run()` 과 동일한 결과를 내는지 assert 로 검증**했다 — 서로 다른 코드 경로로 비교하면 차이가 모드 때문인지 구현 차이 때문인지 알 수 없다. 청산 판정은 두 모드 모두 구현체 `should_sell` 위임
  - **결과 (93영업일 · 09:05 진입)**: A. 현행 **+60.83%**(Sharpe +2.55 · MDD -19.07% · 69거래 · 승률 59% · 거래당 +0.75%/σ 4.67%) vs B. 이월 **+51.31%**(Sharpe +2.29 · MDD -17.92% · 35거래 · 승률 54% · 거래당 +1.29%/σ 6.52%)
  - **train·test 모두 A 우위** — train(03~05) +17.25% vs +16.07%(-1.18%p) · test(06~07) +37.53% vs +30.78%(-6.76%p). 다만 **일별 수익률 짝지은 차이 t +1.27 로 유의하지 않다**
  - **A 우위의 대부분은 5분 왕복 드리프트다** — 09:00 진입(지연 0)으로 바꾸면 격차가 상대 +6.29% → **+1.59%**(+38.82% vs +36.65%, t +0.69)로 줄어든다. 이월 33일의 09:00→09:05 드리프트 평균 -0.161%(누적 약 +5.32%p)가 09:05 격차와 거의 일치한다. **즉 현행이 이기는 이유는 '매일 리셋' 자체가 아니라 '개장 직후 되돌림을 매일 한 번 더 먹는 것'** 이다
  - **이월의 실제 장점도 있다** — 왕복 34회 감소(시뮬레이션 미반영 스프레드 약 1.7%p 절감분), 최악 거래 -11.47% → **-7.79%**, 09:05 기준 MDD -19.07% → -17.92%. 그래도 9.5%p 격차를 뒤집지 못한다
  - **⚠️ 성격이 바뀐다** — 이월 시 최장 **16일** 연속 보유가 나왔고 거래당 σ 가 4.67% → 6.52% 로 커졌다. '일 단위 매매' 가 사실상 스윙 매매가 된다. 채택하려면 청산선(σ 배수)도 그 보유기간에 맞게 재보정해야 한다
  - **결론: 현행 유지.** B 가 어느 구간에서도 앞서지 못했고, 이론적 이점(스프레드 절감·꼬리 축소)이 격차를 메우지 못한다. 다만 차이가 통계적으로 확립된 것도 아니라 **"바꿀 이유가 없다"** 가 정확한 표현이다
  - **부수 수정**: [_test_rejudge.py](scripts/_test_rejudge.py) 가 날짜에 따라 깨지던 문제(2026-08-04 실측 2건 실패). 실제 `datetime.now()` 를 타는 `_short_term_refresh_candidates` 검증이 저장된 판정의 `selected_at` 을 **하드코딩된 2026-08-03** 으로 두어, 그 날짜가 지나자 '어제 판정' 이 되며 갭 우선 규칙이 정상적으로 덮어쓴 것을 실패로 집계했다. `REAL_TODAY` 를 도입해 이 경로만 실행 시점 기준으로 바꿨다 — 창 경계·요일 검증은 실행 요일에 영향받지 않도록 고정 평일(08-03 월요일) 유지. **코드 결함이 아니라 테스트의 달력 의존성**
  - **📌 표본 주의 — 일봉 API 100행 한도로 표본이 매일 밀린다.** 같은 09:05 설정이 전날 실행에서는 94일 +72.29%, 이번 실행에서는 93일 +60.83% 로 나온다. `get_daily_ohlcv` 가 최근 약 100행만 반환해 시작일이 03-10 → 03-11 로 하루 밀렸고, 20일 이평선 warm-up 도 함께 밀려 **첫 거래일이 04-07 → 04-08 로 이동하면서 +6.22% 거래 1건이 표본에서 빠진 것**이 전부다(1.7229 ÷ 1.0622 ≒ 1.62). **A·B 는 같은 93일 위에서 비교했으므로 이 비교 자체는 영향받지 않는다**
- [x] 검증 — 순수 로직 38건(대체 ETF 회피 · 4중 청산 경계값 · 재진입 차단 · 원장 분리 · 일단위 갱신) + 모의 API 트레이더 사이클 40건(개장 진입 → 최고가 추적 → 최고가 청산 → 당일 차단 → 익일 보유기간 청산 → 방향 전환 재진입 · 겹침 시 대체 ETF · 외부 청산 감지 · 체결가 보정 · **자금 풀 손익 누적**: 손실 -36,000원 → 풀 2,964,000원 / 이익 +15,000원 → 풀 3,015,000원 → 다음 진입 603주(캡 방식이었다면 600주) · **체결 정산**: 주문가 10,000원 → 실제 체결 10,020원·제비용 450원이 원장·풀에 정확히 반영 · **시장가 증거금**: 주문가능 3,387,580원에서 2,396주 요청은 거부되고 2,080주로 하향돼 통과, 여력 충분 시엔 예산 수량 유지 · **지정가**: 매도1호가 주문·시장가 대비 +314주·부분 체결 시 체결분만 원장 기록 후 잔량 취소) 전부 통과. 실 KIS 조회로 방향 판정 동작 확인(📉 하락 -0.887 → 인버스 후보 3종), 예상체결가 stale 판정이 정상 작동함을 실측 확인

- [x] **🔴 8월 표본 외 실측 — 실손실 -6.79%. 원인은 '저변동' 이 아니라 '청산선이 고변동 기준으로 굳어 있었던 것'** (2026-09-01 확인). 시드 300만원으로 2026-08-03~08-31 매매 후 09-01 개장 청산 기준 **2,796,240원(-6.79%)**. 같은 기간 KODEX 200 매수보유 +5.79% · 인버스 매수보유 -6.76%. 3~7월 검증 구간(+60~72%)과 정반대 결과가 처음으로 나온 표본 외 구간이다.
  - **재현**: `.venv/bin/python -m scripts._simulate_recent --start 20260803 --end 20260901 --entry 0905`. 09:00 진입이면 -5.33%(2,839,975원) — 5분 지연 우위도 이 구간에서는 재현되지 않았다(반대 방향 -1.46%p)
  - **원인 ① 방향 판정 붕괴 — 적중 9/20 = 45%** (동전던지기 이하, 3~7월은 60%). 손익의 주된 원인은 청산이 아니라 방향이다
  - **🔴 원인 ② 청산선이 통째로 잠들어 있었다 — 20건 전부 `보유만료`, 손절·트레일링 발동 0회.** 8월 실제 일간 등락은 평균 2.81%(σ 3.75%)로 조용했는데, 청산선 산출에 쓰는 **20일 realized_vol 은 7.50%** 로 최대치였다. 07-28(-11.19%)·07-31(+24.17%) 두 극단일이 20거래일 창에 남아 σ 를 밀어올렸고, 그 결과 손절 **15%(상한 클램프)** · 트레일링 12.8~14.3% — 평균 2.8% 움직이는 시장에서 **도달 자체가 불가능한 선**이 됐다. σ 배수 방식은 국면 적응을 목표로 도입했는데 **정확히 그 목적에서 실패**했다(σ 가 20일 지연 + 이상치 오염으로 국면과 역행)
  - **반사실 — 청산선만 8월 실제 변동성(σ 3.75%)에 맞췄다면**: 손절 9.4%/트레일 7.5% → **-3.70%**(손실 약 45% 축소) · 더 좁은 6%/5% → **-1.50%** · 최악 거래 -9.47% → -4.18%. 방향이 45% 인 이상 흑자 전환은 못 하지만 **손실 폭은 청산선이 좌우**한다는 기존 관찰이 다시 확인됐다
  - **MAD 전환으로는 못 고친다** — 이전 검토([_check_vol_estimator.py](scripts/_check_vol_estimator.py))에서 MAD 는 07-31 편입 시 6.61% → 7.02% 로만 올랐지만, 그래도 트레일링 14.0% 라 8월에는 여전히 상한 근처다. **이상치 저항성만으로는 부족하고 창 길이·클램프 상한이 함께 문제**다

- [x] **🔴 σ 오염·지연 수정 — 청산선 전용 σ 를 `min(20일, 5일)` 로 분리** ([core/market_direction.py](core/market_direction.py) `realized_vol_adaptive`). 위 8월 실측에서 드러난 결함(20일 σ 가 극단 하루에 오염되고 그 효과가 20거래일 유지되어, 조용한 8월 내내 청산선이 상한에 붙박여 장중 청산 0건)을 고쳤다.
  - **핵심은 σ 를 둘로 나눈 것** — `vol`(신호 정규화, 20일 σ **그대로**)과 `exit_vol`(청산선, `min(20일, 5일)`)을 `judge_direction` 이 각각 실어 보낸다. 정규화 배수(`NORM_*_MULT`)는 20일 σ 를 전제로 보정된 값이라 **스케일을 바꾸면 방향 판정 자체가 달라진다** — 청산선만 고치려면 분리가 필수였다. `find_targets` 가 후보 dict `변동성(%)` 에 `exit_vol` 을 싣고(구버전 판정 결과는 `vol` 로 fallback), 이후 슬롯 → `exit_thresholds` 경로는 무변경
  - **`min` 의 비대칭이 의도된 설계** — 최근 5일이 조용하면 즉시 좁혀 보호장치를 되살리고, 최근 5일이 격하면 **넓히지 않는다**(표본 5개짜리 추정치로 안전장치를 푸는 것은 근거가 약하다). 단순히 창을 10일로 줄이면 급등 직후 σ 가 오히려 9.5% 까지 뛰는 것을 실측으로 확인했다
  - **두 국면 모두 개선** ([scripts/_check_vol_lag.py](scripts/_check_vol_lag.py), 2026-05-07~09-01 · 80일 · 09:05 진입): 고변동(5~7월) +29.49% → **+31.35%** · 저변동(8월) -6.79% → **-1.01%** · 전체 +22.33% → **+31.92%**(Sharpe +1.10 → **+1.42**). 장중 청산 7 → 10건. **8월만 고치고 기존 구간을 망가뜨리지 않는 것**이 채택 기준이었다
  - **8월 재실행**: 2,796,240원(-6.79%) → **2,969,693원(-1.01%)**. 청산 사유가 `보유만료 20 / 장중 0` → `보유만료 19 / 최고가 1` 로 바뀌며 보호장치가 되살아났고, 최악 거래는 **-9.47% → -3.77%**
  - **단기 창 5일은 plateau 중앙** — N=3 은 고변동을 망치고(+23.30%) N≥12 는 8월 개선이 사라진다(-6.79%). **N=4~10 이 모두 개선**되는 넓은 plateau 라 knife-edge 가 아니다. in-sample 최대값(N=7~8, 전체 +33.47%)을 의도적으로 피해 1거래주에 해당하는 5일을 택했다(방향 판정 가중치 때와 같은 원칙)
  - **클램프는 건드리지 않았다** — 상한 12% 는 현행과 결과가 **완전히 동일**했고(σ 가 이미 상한 위라 무의미), 상한 10% 는 8월을 -3.70% 로만 개선했다. σ 가 제대로 적응하면 클램프가 애초에 걸리지 않으므로(`min(20,5)` + 상한 12% = `min(20,5)` 단독과 동일 결과) 검증된 5~15% 를 유지
  - **MAD 는 여전히 해법이 아니다** — 오염 저항성은 있으나(7.02%) 8월 트레일링이 14.0% 로 상한 근처라 -3.70% 에 그쳤고, MDD 는 -22.71% 로 후보 중 최악이었다. **창 길이가 문제의 본질**임이 확인됐다
  - **대시보드**: 정규화 σ 와 청산선 σ 가 갈릴 때 방향 패널 caption 에 두 값을 함께 표시(같으면 생략)
  - 검증: 회귀 10건 추가 ([scripts/_test_direction.py](scripts/_test_direction.py) 9절 — 오염 구간 단기<장기 · min 선택 · 비대칭(최근이 격해도 안 넓힘) · 평온 구간 · 하한 · 표본 부족 · `exit_vol` 필드 계약). 기존 회귀 3종 전부 통과

- [x] **청산선 배수(2.5σ/2.0σ) 적정성 검토 — 트레일링 2.0 은 유지, 손절 2.5 는 성능 파라미터가 아니라 fallback 이었다** ([scripts/_check_exit_mult.py](scripts/_check_exit_mult.py)). σ 추정을 `min(20일,5일)` 로 바꾸면서 **같은 배수라도 청산선이 평균 20.6% 좁아졌으므로**(20일 σ 평균 4.72% → adaptive 3.62%) 배수를 다시 봤다. 2026-05-07~09-11 · 88일 · 09:05 진입 · σ 와 클램프(5~15%)는 고정하고 배수만 비교.
  - **트레일링 배수**: 1.5 +51.85% · 1.75 +47.45% · **2.0 +59.70%(Sharpe +2.22 · MDD -19.98%)** · 2.25 +59.14% · 2.5 +58.26% · 3.0 +56.26%. 현행 2.0 이 최고이고 2.0~2.5 가 평평하다. 좁힐수록 whipsaw 로 나빠지는 것도 확인(1.75 가 최악)
  - **🔴 손절 배수는 정상 경로에서 발동 자체가 불가능하다 — 수학적으로 그렇다.** `peak` 은 진입가로 초기화돼 위로만 갱신되므로 `peak ≥ entry` 이고, 트레일링%(p) ≤ 손절%(s) 인 한 `트레일링 발동가 = peak×(1-p) ≥ entry×(1-p) ≥ entry×(1-s) = 손절 발동가` 이므로 **항상 트레일링이 먼저 걸린다**. 실측으로도 손절 배수를 2.5 → 3.0 → 3.5 → **10.0(사실상 비활성)** 으로 바꿔도 수익률이 한 푼도 달라지지 않았고, 청산 사유 **라벨만** '손절' → '최고가' 로 바뀌었다(갭으로 두 선을 한 번에 통과한 경우 `should_sell` 이 손절을 먼저 검사하기 때문)
  - **그래도 지운다면 안 된다** — 트레일링 분기는 `peak > 0` 을 요구하므로, 외부 체결·파일 손상으로 **원장 `peak` 이 유실되면 손절이 유일한 안전장치**로 남는다. 즉 손절 배수는 성능 파라미터가 아니라 **fallback** 이다. 이 성질을 모르면 죽은 손잡이를 튜닝하게 되므로 [core/short_term.py](core/short_term.py) `should_sell` 주석과 회귀 테스트에 못박았다
  - **⚠️ 근거는 매우 얇다** — 88일 전체에서 장중 청산이 **3건**(손절 1 · 트레일링 2)뿐이다. 배수 간 수익률 차이는 사실상 2~3건의 거래에서 나온 것이라, "2.0 이 최적" 은 이 표본의 관찰일 뿐 통계적 근거가 아니다. **바꿀 근거가 없어 유지**하는 것이지 최적이 입증된 것이 아니다
  - **클램프 하한이 28% 구간에서 배수를 무력화한다** — 2.0σ 기준 88일 중 **25일이 하한 5% 에 눌린다**(σ < 2.5% 인 날). 상한 15% 는 5일. 배수를 2.0 → 2.5 로 바꿔도 실제 청산선이 달라지는 날은 67/88일(76%)뿐이다. σ 가 더 작아지는 국면이 오면 **하한이 실질 파라미터가 될 수 있으므로** 관찰 대상
  - **9월 — σ 수정 이후 첫 표본 외 구간**: 09-01~09-11 9거래일 **+11.32%**(실현 풀 3,386,505원) · 8거래 승률 **88%** · 거래당 +1.56% · MDD -2.41% · 장중 청산 0건. 방향 판정이 8월(45%)에서 회복된 모습이나 **9일 표본이라 판단 근거는 못 된다**. 10월 이후 `scripts/_check_oos.py` 로 재검증 필요
  - 검증: 회귀 3건 추가 ([scripts/_test_exit_thresholds.py](scripts/_test_exit_thresholds.py) 7절 — 배수 관계 불변식 27조합 · peak 유실 시 손절 fallback · 트레일링>손절 로 뒤집으면 손절이 먼저 걸림). 기존 회귀 3종 전부 통과

- [x] **매매 빈도 대안 검토 (주단위 보유 등) — 빈도는 답이 아니다. 방향 신호가 구조적으로 1일짜리다** ([scripts/_check_trade_frequency.py](scripts/_check_trade_frequency.py)). "8~9월처럼 조용한 구간에서는 매일 회전이 수수료만 먹는 것 아닌가, 주단위로 바꾸면 어떤가" 라는 문제 제기를 정량 검증했다. 2026-05-18~09-11 · 76일 · 09:05 진입.
  - **🔴 먼저 그동안 빠져 있던 비용을 채웠다** — 기존 시뮬레이션은 분봉 종가를 매수·매도 양쪽 체결가로 써서 **호가 스프레드를 전혀 반영하지 않았다**. 실제로는 매수가 지정가(매도호가)·매도가 시장가(매수호가)라 왕복마다 1틱을 온전히 부담한다(실측 틱: KODEX 200 5원 ≈ 0.005% · 인버스 1원 ≈ 0.098% — **인버스가 20배 비싸다**). `_compare_carry_mode.simulate()` 에 `spread=True` 모델을 추가(매수 +틱/2 · 매도 -틱/2)
  - **스프레드 실측 비용: 76거래에 5.66%p (거래당 0.074%p)** — 현행 +59.70% → **+54.04%**. 실재하는 비용이지만 **후보 간 순위를 바꾸지는 않았다**
  - **⚠️ 전제는 절반만 맞다** — 현행 월별(스프레드 반영): 5~7월 +37.67%(47거래) · **8월 +1.18%(19거래 · Sharpe -1.31)** · 9월 **+12.43%**(8거래). **8월은 지적이 정확하다**(한 달 19왕복으로 +1.18%, 스프레드 비용 ≈1.4%p 가 월 수익보다 크다). 다만 9월은 같은 저변동인데도 +12.43% 라, '저변동 = 무의미' 가 아니라 특정 국면의 문제다
  - **🔴 주단위(보유기간 확대)는 모든 구간에서 대참패**: hold_days 2일 **-7.09%** · 3일 -15.42% · 5일 **-47.51%** · 7일 -40.45% · 10일 -34.11% (현행 +54.04%). 저변동 구간에서도 -8.72%~-14.51% 로 현행(+10.25%)보다 한참 나쁘다
  - **원인이 명확하다 — 방향 신호의 유효 horizon 이 정확히 1일이다.** 진입 후 적중률: **1거래일 58% → 2거래일 50% → 3거래일 42% → 5거래일 45%**. 이틀만 지나도 동전던지기이고 사흘이면 그 이하다. 당연한 결과인데, 방향 판정은 **갭 가중치 0.50**(= 그날 시가 갭)이 지배하는 **당일 신호**이기 때문이다. 청산 구성도 이를 뒷받침한다 — hold_days=5 면 청산 26건 중 **21건이 트레일링**(현행은 76건 중 6건)이고 승률 57% → **31%**, 거래당 +0.68% → **-2.34%**. 며칠에 걸친 하락을 뒤집어쓰고 잘리는 구조
  - **유일하게 유망한 후보는 중립 밴드**(확신 낮은 날 진입 보류) — 0.20 이면 거래 76 → 38회로 **절반**인데 전체 **+90.72%**(Sharpe **+4.44** · MDD **-8.65%**, 현행 +54.04% / +2.12 / -20.39%). 0.18~0.25 가 모두 +73~90% 로 ridge 를 이룬다
  - **다만 중립 밴드는 저변동에 듣지 않는다** — 고변동 +37.67% → **+84.48%** 로 극적이지만 저변동은 +10.25% → **+1.87%** 로 **오히려 나빠진다**. 질문하신 8월 문제의 답이 아니다. 게다가 0.15(+53.50%)·0.30(+50.78%)에서 급락해 ridge 가 좁고, 필터 후 표본이 30여 거래라 과최적화 위험이 크다 — **표본 외 검증 전에는 채택 불가**
  - **결론: 8월 문제는 매매 빈도로 못 고친다.** 8월의 진짜 원인은 방향 판정 적중률 **45%**(동전던지기 이하)였고, 신호가 틀린 날을 덜 자주 매매해도 기대값은 여전히 음수다. 빈도 조절은 비용(거래당 0.074%p)만 아끼고 신호 품질은 손대지 못한다

- [x] **'확신 없는 날은 쉬기' 원리 검증 — 관계는 실재하나 저변동 국면에서 사라진다** ([scripts/_check_conviction.py](scripts/_check_conviction.py)). 앞선 중립 밴드 검토는 **수익률 sweep 만** 보고 "ridge 가 좁아 과최적화 위험" 이라고 판단했는데, 정작 **원리 자체**(|방향점수| 가 적중률을 예측하는가)를 재지 않았다. 임계값의 수익률이 아니라 신호와 결과의 관계를 직접 측정했다. 표본 79거래일(2026-05-19~09-11).
  - **원리는 성립한다** — |점수| 5분위별 적중률 **53% / 50% / 44% / 69% / 75%**, 평균수익 -0.35% / +0.72% / -0.94% / +1.44% / +2.50%. 하위 3분위는 전부 동전던지기인데 상위 2분위만 뚜렷이 높다. corr(|점수|, 수익률) = **+0.222**(t +2.00). 밴드 0.20 분할 시 건너뛸 날 적중 49%·평균 -0.41% vs 진입할 날 적중 68%·평균 +1.87%, **차이 +2.27%p (t +2.18, 유의)**
  - **🔴 그런데 국면에 따라 갈린다** — 고변동 5~7월은 39% vs 75%(**차이 +3.35%p**)로 극명하지만, 저변동 8~9월은 61% vs 50%(**차이 +0.04%p**)로 **효과가 사라진다**. 조용한 장에서는 |점수| 자체가 작아진다(평균 0.258 → 0.176, >0.20 인 날 55% → 36%) — 신호들이 서로 엇갈려 가중합이 0 근처로 몰리기 때문이다. 즉 **|점수| 는 확신 지표이면서 동시에 국면 지표**다
  - **임계값 on/off 대신 확신 비례 사이징을 시험했다** — 넘으면 전액/못 넘으면 0 이 아니라 확신이 낮으면 금액을 줄이는 방식. 튜닝할 임계값이 없어 과최적화 위험이 낮다. `_compare_carry_mode.simulate()` 에 `size_fn(score) -> 0~1` 인자를 추가(미투입분은 현금 보유)
  - **🔴 결정적 대조군 — 고정 비율 축소는 Sharpe 를 바꾸지 못한다**(스케일 불변): 고정 100/75/50/30% 모두 Sharpe **+2.11~+2.16** 로 동일하고 MDD 만 비례 축소된다. 따라서 확신 사이징이 같은 평균 투입비율의 고정 규칙보다 Sharpe 가 높아야 **정보를 실제로 쓴 것**이다. 2단계 규칙(|점수|≤0.20 이면 절반)의 평균 투입비율은 74% 이므로 고정 75% 가 공정한 대조군이다
  - **train 에서는 압도적, test 에서는 진다**:
    - train(5~7월): 확신 2단계 **+57.11% · Sharpe +4.43 · MDD -10.66%** vs 고정 75% +28.39% / +2.73 / -15.40% — **세 지표 모두 우위**
    - test(8~9월): 확신 2단계 +6.28% · Sharpe **+1.25** · MDD -6.32% vs 고정 75% +7.96% / **+1.93** / -7.35% — **수익·Sharpe 모두 대조군에 진다**
  - **결론: 원리는 타당하지만 지금 채택할 수 없다.** 기각도 아니다 — test 가 28거래일뿐이고, 저변동 한 국면에서만 무너진 것이다. 앞선 '좁은 ridge' 지적은 방향은 맞았으나 이유가 얕았다. **진짜 이유는 과최적화가 아니라 국면 의존성**이고, 그것을 train/test 대조군으로 분리해 확인했다. `neutral_band` 기본값 0(항상 진입) 유지
  - 부수: `simulate()` 가 `neutral_band` 를 무시하던 것도 수정(실제 전략은 `find_targets` 에서 같은 판정을 하므로 반영해야 등가)

- [x] **현행 알고리즘 시뮬레이션 vs 실계좌 실측 대조 (2026-08-03 ~ 09-18, 34거래일)** — "알고리즘대로 굴렸다면 얼마였나" 와 "실제로 얼마였나" 를 같은 구간에서 처음으로 맞대 봤다. 실측은 KIS `inquire-daily-ccld`(일별주문체결조회)로 체결 67건을 그대로 받아 매수→매도 33쌍으로 페어링한 것이다 — 로컬 `logs/`·`data/trade_history.json` 에는 이 구간 기록이 **하나도 없다**(운영은 AWS, 로컬 `settings.json` 은 07-27 에서 멈춰 있음)
  - **① 현행 알고리즘 · 원금 300만 · 09:00 진입 → 3,654,459원 (+21.82%)** — 거래 33회 · 승률 61% · 거래당 +0.64% · Sharpe +3.79 · MDD -7.97%. 같은 기간 벤치마크는 KODEX 200 매수보유 +7.16% / 인버스 매수보유 -8.68%
  - **② 실계좌 실측 → 3,156,223원에서 3,271,076원 (+3.64%)** (09-18 미청산 TIGER 200 29주를 종가 109,560원으로 평가 포함). 원금 300만 환산 시 **3,109,168원**. 승률은 20/33(61%)로 시뮬과 같은데 **거래당 평균이 +0.64% → +0.26% 로 반토막**이다 — 이긴 횟수가 아니라 이긴 날의 크기에서 갈렸다
  - **격차 +16.42%p 의 요인 분해** (포지션 수익률이 아니라 **자금 풀 대비 실효 증가율**의 복리 곱으로 분해 — 8/26 처럼 자금 일부만 투입된 날을 바르게 반영하기 위함. 곱 1.1642 = 시뮬/실측 1.1642 로 검산 일치):

    | 요인 | 기여 | 내용 |
    | ---- | ---- | ---- |
    | **방향 불일치 5일** | **+16.82%p** | 08-10 · 08-12 · 08-26 · 08-31 · 09-16 의 진입 방향이 갈렸다. 특히 08-12 한 날이 +13.56%p (시뮬 +6.5% vs 실측 -6.2%) |
    | 청산 규칙 차이 | +3.29%p | 08-18 을 시뮬은 12:22 최고가 청산으로 -3.7% 에 끊었고, 실제는 익일까지 들고 가 **-9.5%** |
    | 자금 미투입 (08-26) | -3.81%p | 실제가 **1주(10.7만원)만** 매수 — 자금 97% 가 하루 유휴. 그날 시뮬이 -3.7% 였어서 결과적으로는 실측에 유리하게 작용 |
    | 기타 (체결가·종목) | +0.30%p | 실제는 정방향에 **TIGER 200**(일반 슬롯 겹침 회피), 시뮬은 KODEX 200. 34일 누적 영향이 0.3%p 로 무시 가능 |

  - **판정식 자체는 어긋나지 않았다** — 실제 진입 방향을 현행 판정식(09:00 실측 갭)이 **28/33(85%)** 재현한다. 대조군으로 세운 구버전 둘은 모두 기각: 갭이 0% 로 편입되던 결함 버전(`723fe55` 이전) **17/33(52%)**, 가중치 재배분 이전(ma .35 / 전일 .25 순방향 / 3일 .20 / 갭 .20, 고정 정규화) **17/33(52%)** — 둘 다 동전던지기다. 즉 운영도 현행과 같은 판정식으로 돌고 있었다
  - **불일치 5일은 원인이 둘로 갈린다** (09:00 봉 OHLC + 방향 전환선 역산으로 분리). 각 날짜마다 **점수 부호가 0 이 되는 갭 가격**(전환선)을 이분법으로 구해, 09:00 봉의 고가~저가가 그 선의 어느 쪽에 있는지 봤다:

    | 날짜 | 전일종가 | 09:00 시가 | 09:00 종가 | 전환선 | 실제 | 판정 |
    | ---- | -------- | ---------- | ---------- | ------ | ---- | ---- |
    | 08-10 | 98,090 | 98,835 | 98,275 | **98,415** | up | 시가면 up ○ / 종가면 dn ✗ |
    | 09-16 | 104,275 | 104,345 | 104,410 | **104,367** | down | 시가면 dn ○ / 종가면 up ✗ |
    | 08-12 | 99,265 | 100,550 | 100,420 | 99,937 | **down** | 봉 전체(저가 100,320)가 선 **위** — 어느 시점도 up ✗ |
    | 08-26 | 106,795 | 106,350 | 106,315 | 106,739 | **up** | 봉 전체(고가 106,435)가 선 **아래** — 어느 시점도 dn ✗ |
    | 08-31 | 107,180 | 104,455 | 104,145 | 106,140 | **up** | 고가 104,520 ≪ 106,140 — 명백히 dn ✗ |

    - **08-10 · 09-16 은 시뮬레이터 쪽 근사 오차다.** 시뮬은 갭을 `09:00 분봉 종가`(≈09:00:59)로 넣는데 운영은 개장 직후(09-18 실측 09:00:13) 스냅샷을 본다. 두 날 모두 **전환선이 시가와 종가 사이**를 지나 부호가 갈렸다. 갭 입력을 **09:00 시가**로 바꾸면 운영 재현율이 28/33(85%) → **29/33(88%)** 로 오른다(대신 09-17 이 새로 어긋나 완전한 답은 아니다 — 운영이 보는 건 시가도 종가도 아닌 그 사이의 한 틱이다)
    - **🔴 08-12 · 08-26 · 08-31 은 시뮬이 틀린 게 아니다.** 09:00 봉의 **고가~저가 전 범위**가 전환선 한쪽에 있어 개장 후 어느 시점을 봐도 시뮬 방향이 나온다. 그런데도 운영은 반대로 진입했다 — **개장 갭이 판정에 반영되지 않았다**는 뜻이다. 실제로 이 3일은 **갭을 아예 뺀 판정**(장전 판정 유지 시의 부호)과 3/3 일치한다(08-12 -0.039 dn · 08-26 +0.003 up · 08-31 +0.063 up). 반면 갭 미사용을 전 구간에 적용하면 17/33(52%) 로 무너지므로, **평소엔 갭을 쓰고 이 3일만 못 썼다**는 해석이 가장 설명력이 높다
    - **의심 경로** — `trader.run()` 의 개장 직후 재판정은 `open_judge_date = now.date()` 를 **갭을 실제로 썼는지와 무관하게** 마킹한다. 개장 직후 몇 초는 KIS 일봉에 오늘 봉이 아직 없어 `_today_bar_is_live()` 가 False → 예상체결가 경로 → 09:00 이후라 동시호가가 끝나 갭 미사용 → `keeps_previous_verdict` 가 장전 판정을 유지하는데, 마킹은 이미 끝나 **그날 다시 시도하지 않는다**. 방증: 그 3일의 전날 포지션 청산(재판정 직후)이 **09:00:07 · 09:00:11 · 09:00:04** 로 유난히 이르고, 갭이 정상 반영된 09-18 은 09:00:13 이었다(대시보드 실측: "갭 신호 출처: **장중 실시간 등락률** KODEX 200 +2.67%")
    - **08-12 한 날의 값**: 갭 +1.29%(99,265 → 100,550)가 방향을 맞게 가리켰고 그날 지수는 다음 날 개장까지 +6.5% 올랐다. 운영은 인버스로 -6.1% 를 맞았다 — 격차 기여 **+13.56%p** 로 34일 중 단일 최대 요인이며, **경계선 운이 아니라 놓친 신호**다
  - **장중 청산 0회의 정체 — 운영 설정이 아니라 σ 산출 방식의 '시점' 차이였다** (2026-09-20 운영 대시보드 직접 확인으로 **정정**). 실측 34거래일 장중 청산이 **0회**라 처음엔 운영이 고정 10% 로 돌고 있다고 추정했으나(같은 구간 청산선만 바꾸면 σ 배수 1회 · 고정 5% 2회 · 고정 10% 0회), 확인해 보니 **AWS 는 σ 배수(손절 2.5σ · 트레일링 2.0σ · 5~15%)로 정상 운영 중**이었다. 진짜 원인은 `realized_vol_adaptive`(min(20일, 5일)) 를 도입한 커밋 `96020eb` 가 **09-01** 이라는 것이다 — 08-18 당시 운영 σ 는 20일 단일 창이라 07-28·07-31 극단값에 오염돼 7.5% 였고 청산선이 상한 15% 에 붙어 있었다(위 'σ 오염·지연' 항목이 서술한 바로 그 상태). 반면 시뮬레이터는 **수정 후 코드를 8월에 소급 적용**해 그날 청산선을 5.0% 로 계산했고 그래서 12:22 에 끊었다. 즉 이 +3.29%p 는 운영 설정 오류가 아니라 **백테스트의 look-ahead** 이며, 08-18 의 -9.5% 는 σ 오염 문제가 실제로 지불한 청구서다
  - **부수 확인** — 실제 진입은 매일 **09:05**(매도는 09:00~09:01)라 운영의 `short_term_buy_delay_min` 은 **5**(로컬은 0)다. 다만 09:05 진입으로 시뮬을 다시 돌려도 +20.65% 라, 지연 자체는 격차의 원인이 아니다(-1.2%p). 그리고 **08-03 만 15:15 마감청산**이 있고 08-04 부터 없다 — 그날 AWS 의 `short_term_close_at_market_end` 가 ON 이었다는 기존 관측과 일치하며, 이후 OFF 로 바뀐 것으로 보인다
  - 재현: `python -m scripts._simulate_recent --start 20260803 --end 20260918 --seed 3000000` (실측 대조는 `inquire-daily-ccld` 조회가 필요 — 조회 전용)

- [x] **개장 직후 재판정을 '실측 갭 반영' 까지 재시도하도록 수정** (위 대조에서 드러난 결함). `trader.run()` 이 `_prepare_short_term(force=True)` 호출 뒤 **성공 여부와 무관하게** `open_judge_date` 를 찍어, 갭 없이 끝난 날은 장전 판정이 그대로 굳었다. 개장 직후 몇 초는 KIS 일봉에 오늘 봉이 없어 `_today_bar_is_live()` 가 False → 갭 경로가 예상체결가로 빠지는데, 그 시각엔 동시호가도 끝나 갭이 '미사용' 으로 떨어진다. 갭은 가중치 0.50 이라 방향이 통째로 뒤집힌다.
  - **`market_direction.GAP_SOURCE_LIVE` / `GAP_SOURCE_EXPECTED` 상수 신설** — 갭 출처 라벨이 표시용 문자열에서 **판정 상태를 읽는 계약**으로 승격됐다. 문자열을 바꾸면 판별이 조용히 깨지므로 상수로 고정하고 주석에 못박았다
  - **`short_term.today_gap_source(container, now)` 신설** — 저장된 **오늘자** 판정이 실제로 쓴 갭 출처 라벨(없거나 어제 판정이면 `""`). `keeps_previous_verdict` 를 이 함수 위에 다시 써서 같은 질문("오늘 갭이 반영됐는가")의 답이 한 곳에서 나오게 했다
  - **루프는 `GAP_SOURCE_LIVE` 일 때만 마킹**한다 — 장전 예상체결가는 추정이라 불충분하므로 라벨이 비어 있지 않은 것만으로는 부족하고 **실측 갭인지**까지 따진다. 실패하면 마킹하지 않고 다음 주기에 재시도하며, 창은 `OPEN_REJUDGE_UNTIL`(09:05)이 그대로 닫으므로 오후에 방향이 뒤집힐 위험은 없다
  - **로그에 갭 출처를 남긴다** — `[개장판정] 실측 갭 반영 완료 — 출처 '장중 실시간 등락률'` / `[개장판정] 실측 갭 미반영 (현재 출처: '장전 예상체결가') — 09:05 까지 다음 주기에 재시도`. 8월 로그가 이미 지워져(보관 5일) 이번 진단이 정황 증거에 머물렀는데, 앞으로는 이 한 줄로 확정된다
  - 회귀 **9건 추가** ([scripts/_test_rejudge.py](scripts/_test_rejudge.py) — 3.5절 `today_gap_source` 6종, 4절 재시도 3종: 갭 미반영 시 09:00~09:04 **매 주기 재시도** · 첫 시도에 반영되면 **1회로 끝** · 3번째 주기에 반영되면 거기까지). 기존 회귀 전부 통과(`_test_rejudge` · `_test_direction` · `_test_exit_thresholds`)
  - **한계 — 매수 지연 0분이면 재시도 기회가 없다.** 운영은 지연 5분이라 09:00~09:04 에 최대 5번 시도하지만, 지연 0 이면 첫 사이클에서 곧바로 진입하므로 그 사이클의 판정이 최종이다. 지연을 0 으로 되돌릴 때 함께 고려해야 한다

- [x] **개장 직후 갭이 `+0.00%` 로 편입되던 결함 수정 — 전날 수정이 놓친 진짜 경로** (2026-09-21 운영 실측으로 현장 확인). 전날 대조에서 08-12·08-26·08-31 의 방향 불일치를 '갭 **미사용**' 으로 추정해 재판정 재시도를 넣었는데, 실제 메커니즘은 **갭이 0 이라는 값으로 들어가는 것**이었다. 그래서 그 수정은 이 경우를 잡지 못했다(출처가 `장중 실시간 등락률` 이라 '반영 완료' 로 마킹됨).
  - **현장 기록** — 운영 대시보드에 그대로 남아 있었다: `갭 신호 출처: 장중 실시간 등락률 KODEX 200 **+0.00%**` · `판정 시각 2026-09-21 09:00:03` · `방향 점수 **-0.142**` → 하락 → 인버스 진입. 그런데 실제 개장 갭은 **+0.79%**(전일 109,285 → 개장 110,185)였다. 09:00:03 시점 `inquire-price` 의 현재가가 아직 전일 종가였던 것
  - **완전 재현** — 갭 가격을 전일 종가로(= 갭 0.00%) 놓고 계산하면 **-0.142**, 운영 실측치와 소수점까지 일치한다. 실측 갭을 넣으면 **+0.007(상승)**. 정규화 σ 도 2.21% 로 대시보드 표기와 같다. **판정식은 정상이고 입력 하나가 0 이었다**
  - **왜 치명적인가** — 갭은 가중치 **0.50**이다. 0 이 들어가면 분모만 1.0 으로 커져 나머지 세 신호가 정확히 절반으로 희석되고, 부호는 나머지 셋이 결정한다. 그날 지수는 **+2.21%** 올랐고 인버스 포지션은 종가 기준 **-0.71%** 였다
  - **`723fe55` 가 고친 결함의 다른 경로다** — 그 커밋은 *장전* 에 일봉이 오늘 날짜로 채워져 실시간 경로를 타는 문제를 `_today_bar_is_live()`(일봉 거래량 + 시각)로 막았다. 이번은 **일봉은 진짜 live 인데 현재가 스냅샷이 stale** 한 경우라 그 검사를 통과해 버린다
  - **수정** — `_gap_signal` 의 장중 경로에 stale 검사를 추가했다: **등락률이 정확히 0.00% 이거나 시가(`stck_oprc`)가 0 이면 갭 미사용**(`장중 스냅샷 미갱신`). 갭이 진짜로 0.00% 인 날도 함께 걸리지만 손해가 아니다 — 갭 0 은 방향 정보가 없다는 뜻이고, 미사용으로 떨어뜨려 나머지 가중치로 재정규화하는 편이 **더 정확**하다(`723fe55` 의 논리 그대로)
  - **전날 수정과 맞물린다** — 갭이 미사용이 되면 `today_gap_source()` 가 `GAP_SOURCE_LIVE` 를 돌려주지 않으므로 `open_judge_date` 마킹이 미뤄지고, `OPEN_REJUDGE_UNTIL`(09:05) 까지 매 주기 재시도한다. 두 수정이 함께 있어야 동작한다
  - 회귀 **6건 추가** ([scripts/_test_direction.py](scripts/_test_direction.py) 5-d 절 — 장중 경로 진입 확인 · 0.00% 는 갭 미사용 · 희석 소멸(갭 미사용과 동일 점수) · 정상 등락률이면 갭 사용 · 시가 0 이면 미갱신 · 회피한 손해 크기 항등식). 기존 5-c 의 '0% 편입 희석' 테스트는 그 결함이 제거됐으므로 새 계약으로 교체

- [x] **판정 시각을 09:01 로 늦추는 안 검토 — 채택 보류** (사용자 제안, 2026-03-02~09-21 · 100거래일). "09:00 정각은 요동쳐서 판정이 뒤집히니 09:01 분봉을 쓰면 어떤가". **관찰은 맞지만 개선이 잡음 수준**이라 바꿀 근거가 못 된다.
  - **안정성** — 각 날짜의 방향 전환선(점수 부호가 0 이 되는 갭 가격)을 역산해, 판정 시각 분봉의 저가~고가가 그 선을 걸치는 날을 셌다(걸치면 그날 판정은 초 단위 타이밍의 함수 = 재현 불가). 09:00 **8.2%** · 09:01 5.1% · 09:02 7.0% · 09:03 7.0% · 09:05 3.0%. 09:00 이 가장 불안정한 건 사실이나 8일 vs 5일은 √8≈2.8 이라 구분되지 않고, 09:02·09:03 이 다시 오르므로 **단조성도 없다**
  - **🔴 손익으로 고르면 과최적화** — 09:00 +60.21% / 09:01 +12.90% / 09:02 +48.03% / 09:03 +9.95% / 09:05 +14.81% 로 인접 값이 요동치는 knife-edge 다. 실제로 **100일 중 방향이 갈린 날은 4일**(06-22 · 07-30 · 09-10 · 09-16)이고 **07-30 하루가 +22.19%p** 를 만들었다. 갈린 날의 |점수| 중앙값은 **0.015**
  - **진짜 문제는 시각이 아니라 경계선 날** — 전환선까지의 여유(분봉 변동폭 대비) 중앙값이 측정 상한에 붙는다. 90% 이상의 날은 어느 시각에 봐도 같은 방향이고, 문제는 |점수| ≈ 0 인 소수의 날이다. 시각을 바꿔도 그 날들은 여전히 뒤집힌다
  - **'그 날을 쉬면?' 도 아니다** — 좁은 중립 밴드 sweep: 0.00 +44.29% / 0.01 +41.29% / 0.02 +30.64% / 0.03 +27.74% / 0.05 +39.15% / 0.10 +36.82%. 전부 현행과 같거나 나쁘고 승률도 59% → 57~58% 로 내린다. **경계선 날은 손해를 끼치는 게 아니라 기댓값 0 의 무작위**라, 제거해도 얻을 게 없다
  - 부수 기록: 09:05 가 3.0% 로 가장 안정적인 건 그것이 **진입 시각과 같아** 판정·진입 사이에 가격이 움직일 틈이 없기 때문이다. 매수 지연 5분을 유지한다면 '판정도 09:05' 는 구조적으로 성립하지만, 지연을 0 으로 되돌리면 이점이 사라지므로 **지연 설정과 묶인 결정**이다

- [x] **초당 한도 초과(EGW00215) 완화 — 원장 전용 throttle + 매수 OFF 시 후보 스캔 생략** (운영 로그 `[API] 초당 한도 초과 (TTTC8434R/EGW00215)` 에서 출발).
  - **원인** — `_throttle` 이 모든 호출에 **같은 간격**(게이트웨이 10/s = 0.1초)을 적용했다. 원장(브로커리지 백엔드) 계열은 그보다 훨씬 빡빡한 별도 한도가 걸리는데, 한 사이클에서 잔고 → 매수가능 → 체결조회가 0.1초 간격으로 연달아 나가며 한도를 넘었다
  - **슬롯을 둘로 분리** — lock 파일에 `게이트웨이 / 원장` 두 개의 '다음 허용 시각' 을 두고, 원장 TR(`TTTC`/`VTTC` 접두)은 **양쪽 max** 를 취하고 둘 다 전진시킨다(원장 2/s = 0.5초). 시세 조회는 게이트웨이 슬롯만 쓰므로 **원장 호출 때문에 시세가 밀리지 않는다**. 레거시 단일 값 파일도 그대로 읽힌다. 사이클이 60초이고 원장 호출은 사이클당 몇 건뿐이라 의사결정 지연은 없다
  - **매수 OFF 면 후보 스캔 자체를 건너뛴다** — `execute_initial_buy` 는 이미 `buy_enabled` 에서 막고 있었는데, `prepare_market_open` 은 그와 무관하게 primary + view 전략을 **매번 스캔**해 수십~수백 회 시세 API 를 때리고 그 결과를 버렸다. 이제 꺼져 있으면 스캔을 생략하고 후보 파일에 `status: disabled` 마커를 쓴다(대시보드는 안내 문구 표시, 수동 새로고침은 그대로 동작). **부수 효과로 09:00 이후 기동 시 스캔이 끝나기를 기다리느라 단기 매매 진입이 수 분 밀리던 문제도 사라진다**
  - 회귀 **10건 추가** ([scripts/_test_throttle.py](scripts/_test_throttle.py) — 게이트웨이/원장 간격 · 모의 VTTC 인식 · 원장이 시세를 밀지 않는 비대칭 · 레거시 파일 호환 · 깨진 파일 시 가용성 우선)

## 다음 작업 후보

- [x] ~~**🔴 운영(AWS) 배포 버전·설정 확인**~~ (2026-09-20 완료 — 위 진행 상태 참조). 운영 대시보드(`http://3.37.17.19:8501`)의 Streamlit 렌더 트리를 **조회 전용**으로 받아(WebSocket `/_stcore/stream` → `ForwardMsg` 파싱, 위젯 조작 없음) 적용값을 직접 읽었다.
  - **런타임 동작은 현재 HEAD 와 같다** — "청산선 기준 σ 는 1.93%(min(20일, 5일))" caption 이 살아 있어 `96020eb`(09-01) 배포가 확인되고, 그 이후 `core/`·`ui/` 변경은 `6438be8` 의 **주석 추가뿐**이라 동작 차이가 없다. 판정 시각도 `2026-09-18 09:00:13` 로 찍혀 개장 직후 재판정(`660cae9`)까지 살아 있다
  - **확인된 운영값**: 청산선 **변동성 배수(σ)** · 손절 **2.5** · 트레일링 **2.0** · 하한 **5%** / 상한 **15%** · 배정 자금 **300만** · 당일 마감 강제청산 **OFF** · 지정가 매수 **ON** · 단기 매매 자동매매 **ON** · 일반 매수 **OFF** · 활성 매수/매도 전략 기술 모멘텀 / 트레일링 스탑(-10%)
  - **로컬과 갈린 항목**: 개장 후 매수 지연 **5분**(로컬 0) · 최대 보유 종목 **3**(로컬 4) · 보조 매수 전략 **없음**(로컬 2종) · 새로고침 **120초**(로컬 60). 청산선 계열은 전부 일치한다
  - **부수로 얻은 것** — 대시보드 렌더 트리 조회는 SSH 없이 운영 설정을 읽는 실용적인 경로다. '호스트 간 설정 불일치' 항목의 해결안 ①(설정 요약 패널)은 이 방식으로 대체 가능하지만, **과거 시점의 설정·로그는 여전히 못 본다** — ②(기동 시 설정 덤프 로그)는 그대로 유효하다
- [x] ~~**08-26 단기 매매가 1주만 매수한 원인 규명**~~ (2026-09-20 완료). 당초 `주문가능금액` 미반영으로 수량이 깎였다고 의심했으나, KIS 주문 내역(`CCLD_DVSN=00` 으로 **미체결·취소 포함** 조회)에 전 과정이 남아 있었다:

  | 시각 | 내용 |
  | ---- | ---- |
  | 09:05:14 | TIGER 200 **25주** 지정가 107,170원 매수 → **1주만 체결** |
  | 09:05:16 | 미체결 **24주 취소** (`_cancel_remainder`, 설계된 동작) |

  - **수량 산출은 정상이었다** — 자금 풀 273만원으로 25주는 맞는 계산이다. 문제는 `pick_limit_buy_price` 가 고른 매도호가 107,170원이 **주문이 도달했을 땐 이미 1주밖에 남아 있지 않았다**는 것이다. 08-26 은 장 초반 지수가 오르던 날이라(09:00 106,315 → 09:05 106,695) 호가 조회와 주문 사이에 매도 물량이 걷혔다
  - **미체결 취소 자체는 의도된 설계다** — 잔량을 살려두면 현금이 묶이고 나중에 체결되면 원장 밖 유령 포지션이 된다. `pick_limit_buy_price` 주석도 "나머지는 미체결 후 취소된다" 고 명시한다
  - **🔴 진짜 빈틈은 취소 후 재주문이 없다는 것** — `_short_term_enter` 는 `fill["qty"] <= 0`(전량 미체결)일 때만 "다음 주기 재시도" 로 빠지고, **부분 체결이면 그 수량 그대로 원장에 기록하고 끝낸다**. 다음 주기에는 이미 포지션이 있어 추가 진입도 안 한다. 그 결과 그날 자금의 **97% 가 유휴**였다. 실측 기여 -3.81%p — 이번엔 시뮬이 -3.68% 였던 날이라 우연히 손실을 피했지만, 방향이 맞은 날이었다면 그대로 기회 손실이다
- [ ] **개장판정 로그 관찰 (수정 효과 확인)** — 갭 stale 판별 + 재판정 재시도가 실제로 듣는지는 며칠치 `[개장판정]` 로그로만 확정된다. 확인할 것: ① `실측 갭 미반영 (현재 출처: ...)` 이 09:00 첫 시도에서 찍히는가 ② 몇 번째 주기에 `실측 갭 반영 완료` 로 넘어가는가 ③ 09:05 까지 끝내 실패하는 날이 있는가 ④ `[방향판정] 갭 신호 미사용 — 장중 스냅샷 미갱신` 의 빈도. ③ 이 잦으면 `OPEN_REJUDGE_UNTIL` 연장 또는 일봉 대신 스냅샷 자체로 장중 여부를 판정하는 쪽을 검토한다. 09-21 은 수정 배포 **전날** 이라 `실측 갭 반영 완료` 가 1회로 끝났지만 실제로는 갭이 0.00% 였다 — 수정 후에는 같은 상황이 '미반영 → 재시도' 로 찍혀야 한다. 로그 보관이 5일(`logger.RETENTION_DAYS`)이라 **주 단위로 들여다봐야** 놓치지 않는다
- [ ] **시뮬레이터 갭 입력을 09:00 시가로 교체 검토** — 현행은 `09:00 분봉 종가`(≈09:00:59)라 운영이 보는 개장 직후 스냅샷과 최대 1분 어긋난다. 시가로 바꾸면 운영 재현율 85% → 88%. 다만 09-17 이 새로 어긋나 완전한 해결은 아니고(운영이 보는 값은 시가와 종가 사이의 한 틱), **전환선이 그 구간을 지나는 날은 애초에 재현 불가**라는 점을 한계로 명시하는 편이 정직하다
- [ ] **🔴 지정가 부분 체결 시 재주문 경로 추가** (위 08-26 규명에서 도출). `_short_term_enter` 가 부분 체결을 그대로 확정해 자금이 통째로 놀 수 있다. 검토안: ① 체결 수량이 목표의 일정 비율 미만이면 취소 직후 **남은 자금으로 재주문**(다음 호가 또는 시장가) ② 매 주기 원장 수량 < 목표 수량이면 **추가 매수로 채우기**(진입 시각 상한과 함께 설계해야 오후 진입을 막을 수 있다) ③ 애초에 매도호가를 1~2단계 위로 잡아 체결 확실성을 사는 방식(스프레드 비용 대비 유휴 손실 비교 필요). 08-26 은 34일 중 1일이지만 손실 기여가 -3.81%p 로 단일 요인 3위였다
- [ ] **확신 기반 사이징 재검증 (10월 이후)** — 원리(|점수| ↔ 적중률)는 고변동 구간에서 유의하게 확인됐으나(+3.35%p) 저변동 8~9월에서 사라졌고(+0.04%p), train/test 대조군 비교에서도 test 는 고정 75% 에 졌다(Sharpe +1.25 vs +1.93). test 표본이 28거래일뿐이라 기각이 아니라 **판정 보류**다. 10월 이후 데이터가 쌓이면 `scripts/_check_conviction.py` 재실행 — 저변동 국면에서도 상위 분위가 이기면 채택, 아니면 '고변동 전용' 으로 조건부 적용 검토. 채택 시 on/off 밴드보다 **2단계 사이징**(|점수|≤0.20 절반)이 임계값 민감도가 낮아 우선
- [ ] ~~**중립 밴드(`neutral_band`) 표본 외 검증**~~ (위 항목으로 대체) — 0.18~0.25 에서 거래를 절반으로 줄이며 전체 +90.72%(Sharpe +4.44 · MDD -8.65%)를 냈으나, ridge 가 좁고(0.15·0.30 에서 급락) 필터 후 표본이 30여 거래뿐이다. 고변동에서만 듣고 저변동에서는 오히려 나빠지는 점도 확인 필요. 10월 이후 데이터로 train/test 분할 재검증 후 채택 여부 결정. 현재 기본값 0(항상 진입) 유지
- [ ] 청산선 **하한 클램프(5%)** 재검토 — 현재 88일 중 25일(28%)이 하한에 눌려 트레일링 배수가 무력화된다. σ 가 더 낮은 국면에서는 하한이 실질 파라미터가 되므로, 하한을 낮출지(예: 3%) 또는 σ 연동으로 바꿀지 검토. 단 장중 청산 표본이 3건뿐이라 지금은 판단 근거가 부족 — 표본이 쌓인 뒤 착수
- [x] ~~**σ 오염·지연으로 청산선이 국면과 역행하는 문제**~~ (완료 — 위 진행 상태 참조) (2026-08 실측 — 위 진행 상태 참조). 20일 realized_vol 이 극단 2일에 오염되면 그 효과가 **20거래일 유지**되어, 시장이 진정된 뒤에도 청산선이 상한(15%)에 붙어 보호장치가 꺼진다. 검토안: ① **창 단축**(20일 → 10일 등)으로 국면 전환 반응 속도 확보 ② **상한 클램프 하향**(15% → 10~12%) — 3~7월 검증에서 상한 발동은 0일이었으므로 낮춰도 그 구간 성과는 불변이고 8월 같은 구간만 개선된다 ③ 단기·장기 σ 중 **작은 쪽 채택**(min(20일, 5일))으로 진정 국면에 빠르게 좁히기. ②가 가장 비용이 낮고 즉시 효과가 있다
- [ ] ~~단기 매매 청산선을 실현변동성 배수로 전환~~ (완료 — 위 진행 상태 참조) — `손절 2.5σ / 트레일링 2.0σ` 가 train·test 양 구간에서 현행 고정 10/10 을 앞섰다([_check_exit_rules.py](scripts/_check_exit_rules.py), 전체 +81.61% vs +65.64%). 현재 σ 5.16% 기준 환산 시 손절 -12.9% · 트레일링 -10.3%, 시장이 진정되면 자동으로 좁아진다. 적용 시 `EtfDayTradeStrategy` 가 진입 시점 σ 를 받아 청산선을 산출하도록 배선 + 배수 클램프(예: 5~20%) 필요
- [ ] **시뮬레이션 재현성 — 일봉 캐시 도입** — `get_daily_ohlcv` 가 최근 약 100행만 반환해 **실행 날짜가 하루 지나면 표본 시작일도 하루 밀린다**. 20일 이평선 warm-up 까지 함께 밀려 첫 거래일이 이동하므로 같은 설정도 날짜마다 다른 수치가 나온다(실측: 09:05 설정이 08-03 실행 94일 +72.29% → 08-04 실행 93일 +60.83%, 차이는 빠진 +6.22% 거래 1건). 분봉은 이미 `data/.minute_bars_cache.json` 에 캐시하므로 **일봉도 같은 방식으로 캐시**하면 과거 결과를 그대로 재현할 수 있다. 같은 실행 안에서의 A/B 비교는 영향받지 않으므로 우선순위는 중간
- [ ] **🔴 호스트 간 설정 불일치 — 로컬과 AWS 의 `settings.json` 이 따로 논다** (2026-08-03 확인). `data/` 는 `.gitignore` 대상이라 설정이 **호스트별 런타임 파일**이고, 실제로 AWS 는 `short_term_close_at_market_end` 가 **ON**(로컬은 OFF)이었다 — 검증상 명확히 불리한 설정으로 운영되고 있었다. 로컬에서 값을 확인해도 운영을 대변하지 못한다는 뜻. 해결안: ① 대시보드 사이드바에 현재 적용값 요약 패널(운영 호스트에서 직접 확인) ② 기동 시 주요 설정값을 로그에 1회 덤프해 `logs/trader-*.log` 로 사후 추적 가능하게 ③ (선택) 권장값과 다른 항목을 대시보드에 경고 표시. 최소한 ② 는 비용이 거의 없다
- [ ] **장전 예상체결가 형성 시점 재관측** — 2026-08-03 관측은 08:28 에 중단되어 **08:30 이후 예상체결가·예상거래량이 실제로 형성되는지 미확인**이다(08:25~08:28 은 예상체결가 0 · 예상거래량 0 — 동시호가 개시 전이라 정상). 부수 확인된 것: `기준가`(108,820)는 전일 종가와 **일치**했고 `장운영구분코드`=112 였으므로 **stale 판정 자체는 통과**한다 — 예상거래량만 형성되면 갭 신호를 장전에도 쓸 수 있다. `.venv/bin/python -m scripts._watch_premarket` 를 평일 08:25 이전에 띄워 재확인. 2026-08-03 08:25~09:02 에 [scripts/_watch_premarket.py](scripts/_watch_premarket.py) 로 1분 간격 관측(기준가 롤오버·예상거래량 형성 시점·갭 사용 여부·예상체결가 vs 실제 시가 오차)을 시작했고, 기록은 `data/premarket_watch_YYYY-MM-DD.jsonl`. **개장 직후 최종 재판정 도입으로 최악의 경우(끝까지 stale)에도 갭이 실시간 등락률로 살아나 리스크는 낮아졌지만**, 장전 30분 동안 방향을 알 수 있는지는 이 관측이 답한다. 끝까지 stale 이면 판정 기준을 `장운영구분코드(antc_mkop_cls_code)` 기반으로 교체 검토
- [ ] **🎯 리스크 줄이기 — 배정 자금(`short_term_budget`) 하향으로 MDD 조절** (2026-09-13 검증 완료, 실행만 남음). 현행 300만원 전액 투입의 MDD 는 **-20.39%**(실측: 2026-07-20 4,653,160원 → 07-30 3,704,250원, 열흘에 -94.9만원). 이 폭이 감당 범위를 넘는다면 **배정 자금을 낮추는 것이 유일하게 검증된 수단**이다.
  - **검증된 성질 — 고정 비율 축소는 Sharpe 를 바꾸지 않는다**(스케일 불변). 수익과 위험이 같은 비율로 줄 뿐이라 '효율' 손해가 없다:

    | 투입 비율 | 배정액 | 전체 수익률 | Sharpe | MDD |
    | --------- | ------ | ----------- | ------ | --- |
    | 100% (현행) | 300만 | +54.04% | +2.12 | **-20.39%** |
    | 75% | 225만 | +39.77% | +2.11 | -15.40% |
    | 50% | 150만 | +26.76% | +2.16 | **-10.27%** |
    | 30% | 90만 | +15.33% | +2.12 | -6.19% |

  - **이건 전략 변경이 아니라 리스크 선호 설정이다** — 표본 외 검증이 필요한 종류의 결정이 아니므로 바로 적용 가능하다. `settings.json::short_term_budget` 변경 시 자금 풀도 그 금액으로 재설정된다(대시보드 사이드바 '배정 자금')
  - **결정에 필요한 것**: ① 계좌 전체 자산 대비 단기 매매 비중 ② 감내 가능한 최대 손실액. 예) 감내 한도가 100만원이면 MDD -20% 기준 배정액 상한은 500만, -10%(150만 배정) 기준이면 훨씬 여유. 현재 300만이 계좌에서 차지하는 비중 확인 필요
  - **다른 수단은 이미 배제됐다** — 당일 마감 청산은 Sharpe 를 떨어뜨리고(+1.96 → +1.56), 청산선 조정은 손익을 좌우하지만 꼬리를 줄이지 못하며, 확신 기반 사이징은 표본 외 검증에 실패해 보류 중이다([_check_conviction.py](scripts/_check_conviction.py)). **남은 정공법은 배정액 하향 하나뿐**
- [ ] 단기 매매 진입 시각 상한 도입 — `short_term_buy_window_open()` 이 하한(개장+지연)만 검사해, 자동매매를 오후에 켜면 장 전 판정 그대로 14시에도 진입한다. '개장과 동시에 진입' 전제와 어긋남
- [ ] (약한 후보) 개장 직후 **평균회귀를 진입 타이밍에 활용** — 첫 10분 드리프트와 이후 수익률의 상관이 -0.241(n=79)로, 방향과 반대로 튄 날 기다렸다 사면 유리할 수 있다. 다만 지연 자체의 손익 효과는 유의하지 않았고(t=-0.84) 표본이 79일뿐이라, 규칙화하려면 표본 외 재현부터 확인 필요 ([_check_open_drift.py](scripts/_check_open_drift.py))
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
| 방향 판정 시점      | 장전 08:30~09:00 매 1분 재판정 + 09:00 개장 직후 최종 확정  |
| 방향 판정 신호      | 갭 0.50 · 전일등락(평균회귀) 0.25 · 이평선 0.15 · 3일 0.10  |
| 신호 정규화         | 일간 실현변동성(20일) × 배수 — 변동성 국면에 자동 적응        |
| 매수 시점           | 개장 즉시 (09:00, 지연 0분 — 사이드바에서 조절 가능)        |
| 배정 자금 (씨드)    | 300만원 (사이드바 조절 — 변경 시 자금 풀 재설정)            |
| 진입 예산           | min(자금 풀 잔액, 주문가능금액) — 풀에 실현손익이 누적(복리) |
| 손익 정산           | 체결 조회 기반 실제 체결가·제비용 (주문가 근사 아님)         |
| 보유 기간           | 1일 (다음 거래일 개장 시 청산 후 그날 방향으로 재진입)      |
| 손절                | 매수가 대비 **-2.5σ** (진입 시점 실현변동성 배수, 5~15% 클램프) |
| 최고가 청산         | 매수 이후 최고가 대비 **-2.0σ** (사이드바에서 배수·클램프·고정% 전환) |
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
│   ├── _simulate_july.py     # 자금 곡선 시뮬레이션 (시드·기간 상수로 조절)
│   ├── _check_open_drift.py  # 개장 직후 진입 지연 효과 (1분봉 실측 + 분 단위 폴링 재현)
│   ├── _watch_premarket.py   # 장전 08:25~09:02 예상체결가 실시간 관측 (갭 신호 실장 확인)
│   ├── _compare_hold_mode.py # 1일 보유 vs 당일 마감 청산 비교 (구간 분해 포함)
│   ├── _check_exit_rules.py  # 청산 규칙 22종 비교 (train/test 분리 + 청산 건별 검증)
│   ├── _check_vol_estimator.py # σ 추정치 비교 (표준편차 vs MAD)
│   ├── _test_exit_thresholds.py # 변동성 배수 청산선 순수 로직 회귀
│   ├── _simulate_recent.py   # 최근 30거래일 일자별 시뮬레이션 (매수 종목·자산 표)
│   └── _test_rejudge.py      # 장전 매분·개장 직후 재판정 순수 로직 + 메인 루프 배선 회귀
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
