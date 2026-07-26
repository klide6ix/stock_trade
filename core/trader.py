import json
import os
import time
from datetime import datetime, timedelta

from config import CHECK_INTERVAL, MODE_LABEL, IS_MOCK, PRE_MARKET_OPEN
from core.kis_api import (
    get_holdings,
    get_current_price,
    get_order_execution,
    get_quote_snapshot,
    sell_market_order,
    buy_market_order,
    get_cash_balance,
)
from core.logger import log
from core.settings import get as get_setting, set_value as set_setting
from core.short_term import (
    SHORT_TERM_CANDIDATE_COUNT,
    EtfDayTradeStrategy,
    block_today,
    invested_amount,
    candidates_need_refresh,
    candidates_to_settings,
    clear_position,
    has_pending,
    has_position,
    is_blocked,
    mark_entry,
    position_qty,
    set_position_qty,
    split_holdings,
    target_to_settings,
    update_peak,
)
from core.strategy.base import BuyStrategy, SellStrategy

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA_DIR = os.path.join(_BASE_DIR, "data")
os.makedirs(_DATA_DIR, exist_ok=True)

BUY_CANDIDATES_FILE = os.path.join(_DATA_DIR, "buy_candidates.json")
TRADE_HISTORY_FILE = os.path.join(_DATA_DIR, "trade_history.json")


def _tag_candidates(candidates: list[dict], strategy: BuyStrategy) -> None:
    """후보 dict 에 view 식별용 메타 필드를 in-place 주입."""
    name = type(strategy).__name__
    label = strategy.display_name
    for c in candidates:
        c["_strategy"] = name
        c["_strategy_label"] = label


def _safe_max_holdings(default: int = 5) -> int:
    """settings.json 의 `max_holdings` 를 정수로 안전하게 읽어 반환.

    음수/0/잘못된 타입은 모두 default 로 fallback (사이드바 number_input 의 min=1
    가드를 우회한 비정상 값에 대비). 매수 차단 의도가 명확한 0 을 허용하지 않는 이유는
    `buy_enabled` 토글이 이미 그 역할을 담당하기 때문.
    """
    raw = get_setting("max_holdings")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value if value >= 1 else default


def plan_initial_buy(
    candidates: list[dict],
    cash: float,
    owned_codes: set[str],
    max_holdings: int = 5,
) -> list[dict]:
    """예수금을 후보 수(미보유 기준)로 균등 분할한 매수 계획 생성.

    슬롯 금액이 주가보다 작아도 최소 1주를 배정하고, 누적 예산을 초과하지 않도록
    순서대로 잔여 예수금을 차감한다. 보유 중인 종목은 제외.

    `max_holdings` 한도를 초과하지 않도록, 잔여 슬롯(`max_holdings - len(owned)`) 만큼만
    상위 후보를 선택. 잔여 슬롯이 0 이하면 빈 계획 반환.

    Returns:
        [{"종목코드", "종목명", "현재가", "수량", "예상금액"}] — 실제 주문 가능한 항목만
    """
    if not candidates or cash <= 0:
        return []

    remaining_slots = max_holdings - len(owned_codes)
    if remaining_slots <= 0:
        return []

    targets = [c for c in candidates if c["종목코드"] not in owned_codes][:remaining_slots]
    if not targets:
        return []

    slot = cash / len(targets)
    remaining = cash
    plan: list[dict] = []

    for t in targets:
        price = t.get("현재가", 0)
        if price <= 0:
            continue

        qty = max(1, int(slot // price))
        if price * qty > remaining:
            qty = int(remaining // price)
        if qty <= 0:
            continue

        amount = price * qty
        plan.append({
            "종목코드": t["종목코드"],
            "종목명": t["종목명"],
            "현재가": price,
            "수량": qty,
            "예상금액": amount,
        })
        remaining -= amount

    return plan


def is_market_open() -> bool:
    """실제 장 운영 시간 체크 (평일 09:00 ~ 15:30). 모드와 무관한 '실제 시장' 상태."""
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    t = now.time()
    return datetime.strptime("09:00", "%H:%M").time() <= t <= datetime.strptime("15:30", "%H:%M").time()


def is_trading_time() -> bool:
    """매매(매수·매도·교체)를 진행해도 되는 시간인지 판정 — 매매 게이트 전용.

    - 실전(IS_MOCK=False): 정규장(평일 09:00~15:30)에만 True. 시간외 오발주를 막는다.
    - 모의(IS_MOCK=True): 장 시간과 무관하게 항상 True. 주말·시간외에도 매매 흐름을
      자유롭게 시험할 수 있게 한다.

    주의: 이 게이트는 '클라이언트가 매매 로직을 실행할지' 의 문제일 뿐, 체결 보장과는
    별개다. KIS 모의투자 서버는 정규장 시간에만 체결하므로 시간외 시장가 주문은
    서버에서 거부될 수 있다(주문 응답 msg1 로 확인 가능). 실제 시장 상태가 필요한
    화면 표시에는 is_market_open() 을 쓴다.
    """
    return IS_MOCK or is_market_open()


def _parse_hhmm(value: object, default: str):
    """'HH:MM' 문자열을 datetime.time 으로 안전하게 파싱. 실패 시 default 적용."""
    try:
        return datetime.strptime(str(value), "%H:%M").time()
    except (TypeError, ValueError):
        return datetime.strptime(default, "%H:%M").time()


def pre_market_open_time():
    """장 전 준비 시작 시각(datetime.time) — settings.json 의 `pre_market_open_time` 우선, 실패 시 config 기본값."""
    return _parse_hhmm(get_setting("pre_market_open_time"), PRE_MARKET_OPEN)


def is_pre_market(now: datetime | None = None) -> bool:
    """장 전 준비 시간 여부 — 평일 (설정된 장전 시작 시각) ~ 정규장 개장(09:00) 직전.

    이 구간에는 매매(주문)는 불가하지만 조회는 가능하므로, 매수 후보와 오늘의 시장 방향을
    미리 정해 개장과 동시에 매매에 진입할 수 있게 한다. 장외(시간외) 거래가 8:00/8:30
    부터 시작되는 경우에 대응하기 위한 '준비 창'.
    """
    now = now or datetime.now()
    if now.weekday() >= 5:
        return False
    t = now.time()
    market_open_t = datetime.strptime("09:00", "%H:%M").time()
    return pre_market_open_time() <= t < market_open_t


# 단기 매매 실매수 지연 (분) 기본값 — 개장(09:00) 후 이 시간이 지나야 실제 시장가 매수를 시작한다.
# ETF 방향 매매는 '개장과 동시에 진입' 이 기본 설계라 0 (즉시). 시초가 변동성을 피하고 싶으면
# 사이드바에서 늘릴 수 있다. 후보 선정은 지연과 무관하게 장 전에 이미 끝나 있다.
SHORT_TERM_BUY_DELAY_MIN = 0


def short_term_buy_delay_min() -> int:
    """settings.json 의 `short_term_buy_delay_min` 을 정수(분)로 안전하게 반환.

    잘못된 타입/음수는 기본값 `SHORT_TERM_BUY_DELAY_MIN` 으로 fallback. 0 이면 개장 즉시 매수 허용.
    """
    raw = get_setting("short_term_buy_delay_min")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return SHORT_TERM_BUY_DELAY_MIN
    return value if value >= 0 else SHORT_TERM_BUY_DELAY_MIN


def short_term_buy_start_label(now: datetime | None = None) -> str:
    """단기 매매 실매수 시작 시각 라벨 (예: '09:10') — 개장(09:00) + 설정 지연."""
    now = now or datetime.now()
    start = now.replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(
        minutes=short_term_buy_delay_min()
    )
    return start.strftime("%H:%M")


def short_term_buy_window_open(now: datetime | None = None) -> bool:
    """단기 매매 실매수 허용 시간 여부 — 개장(09:00) 후 설정 지연(분) 경과 시 True.

    ETF 방향 매매는 개장과 동시에 진입하는 것이 기본(지연 0분)이다. 다만 시초가 변동성이
    큰 날 진입을 조금 늦추고 싶을 수 있어 지연을 사이드바에서 조절할 수 있게 열어 둔다.
    매수 대상 자체는 장 전 준비 시각에 이미 정해져 있으므로 지연은 주문 시점만 미룬다.
    """
    now = now or datetime.now()
    open_time = now.replace(hour=9, minute=0, second=0, microsecond=0)
    return now >= open_time + timedelta(minutes=short_term_buy_delay_min())


# 단기 매매에 배정하는 초기 자금(원). settings.json 의 `short_term_budget` 로 조절.
# 이 값은 '씨드(seed)' 이고, 실제로 굴리는 금액은 아래 자금 풀(`short_term_pool`)이다.
SHORT_TERM_BUDGET_DEFAULT = 3_000_000


def _safe_float_setting(key: str, default: float, minimum: float = 0.0) -> float:
    """settings.json 의 실수 설정값을 안전하게 읽는다. 타입 오류·범위 미달은 default."""
    try:
        value = float(get_setting(key))
    except (TypeError, ValueError):
        return default
    return value if value >= minimum else default


def short_term_budget() -> float:
    """단기 매매 배정 자금(씨드, 원). 잘못된 값은 기본값으로 fallback.

    사이드바에서 이 값을 바꾸면 자금 풀도 그 금액으로 재설정된다(= 재배정).
    """
    return _safe_float_setting("short_term_budget", SHORT_TERM_BUDGET_DEFAULT, minimum=1.0)


def short_term_pool() -> float:
    """단기 매매 자금 풀 잔액(원) — 손익이 누적되는 실제 운용 자금.

    배정액(씨드)에서 출발해 청산할 때마다 **실현손익이 그대로 더해지거나 빠진다**.
    이익이 나면 다음 진입 금액이 커지고(복리), 손실이 나면 줄어든 금액으로 다시 들어간다.
    일반 매수 자금에서 손실분을 보충하지도, 이익을 일반 자금으로 빼내지도 않는다.

    미초기화(None)면 배정액으로 시작한다.
    """
    raw = get_setting("short_term_pool")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return short_term_budget()
    return max(0.0, value)


def apply_short_term_pnl(invested: float, realized: float) -> float:
    """청산 결과를 자금 풀에 반영하고 새 잔액을 반환한다.

    `풀 += (회수액 - 투입액)` — 즉 실현손익만큼 풀이 늘거나 준다. 포지션 보유 중에는
    자금이 주식으로 바뀌어 있을 뿐 풀 잔액은 그대로 두고, 청산 시점에 한 번만 정산한다.

    주의: 회수액은 `청산가 × 수량` 근사치다. 위탁수수료(및 해당 시 세금)는 반영되지
    않으므로 풀 잔액이 실제 현금보다 아주 조금 높게 잡힐 수 있다. 국내 주식형 ETF 는
    매도 증권거래세가 면제라 오차는 수수료 수준(수천 원)에 그친다.
    """
    pnl = float(realized) - float(invested)
    new_pool = max(0.0, short_term_pool() + pnl)
    set_setting("short_term_pool", new_pool)
    log(
        f"[단기매매][자금풀] 실현손익 {pnl:+,.0f}원 반영 → 풀 잔액 {new_pool:,.0f}원 "
        f"(투입 {invested:,.0f} → 회수 {realized:,.0f} · 배정 {short_term_budget():,.0f})"
    )
    return new_pool


def build_short_term_strategy() -> EtfDayTradeStrategy:
    """settings.json 의 사용자 설정을 반영한 단기 매매 전략 인스턴스."""
    return EtfDayTradeStrategy(
        stop_loss_pct=_safe_float_setting("short_term_stop_loss_pct", 5.0, minimum=0.1),
        peak_drop_pct=_safe_float_setting("short_term_peak_drop_pct", 5.0, minimum=0.1),
        close_at_market_end=bool(get_setting("short_term_close_at_market_end")),
    )


# 체결 조회 재시도 — 시장가는 즉시 체결되지만 원장 반영에 약간의 지연이 있을 수 있다.
_SETTLE_ATTEMPTS = 3
_SETTLE_RETRY_DELAY = 1.0


def settle_order(
    order_result: dict,
    code: str,
    side: str,
    fallback_price: float,
    fallback_qty: int,
) -> dict:
    """주문 응답을 실제 체결 내역으로 정산한다.

    시장가 주문은 주문 시점 현재가와 체결가가 어긋나므로(호가 스프레드), 손익을 현재가로
    계산하면 오차가 매 거래 누적된다. 주문 응답의 `ODNO` 로 체결 내역을 되짚어 실제
    체결가·체결수량·현금흐름을 확정한다.

    현금흐름(`amount`)은 방향에 맞게 제비용을 반영한다 — 매수는 비용만큼 더 나가고
    (체결금액 + 제비용), 매도는 비용만큼 덜 들어온다(체결금액 − 제비용). 제비용을 이
    주문에 귀속할 수 없으면(같은 종목을 그날 여러 번 거래) 0 으로 두고 체결금액만 쓴다.

    체결 조회가 실패하면 주문 시점 값(fallback)으로 되돌아가되 `exact=False` 로 표시해
    호출부가 근사치임을 로그에 남길 수 있게 한다.

    Returns:
        {qty, price, amount, fee, exact} — exact=False 면 fallback 근사치.
    """
    order_no = ((order_result or {}).get("output") or {}).get("ODNO", "")
    if order_no:
        for attempt in range(1, _SETTLE_ATTEMPTS + 1):
            exec_info = get_order_execution(order_no, code, side)
            if exec_info:
                gross = exec_info["총체결금액"]
                fee = exec_info["추정제비용"]
                amount = gross + fee if side == "buy" else gross - fee
                return {
                    "qty": exec_info["체결수량"],
                    "price": exec_info["체결평균가"] or fallback_price,
                    "amount": amount,
                    "fee": fee,
                    "exact": True,
                }
            if attempt < _SETTLE_ATTEMPTS:
                time.sleep(_SETTLE_RETRY_DELAY)

    log(
        f"[체결조회] {code} {side} 체결 확인 실패 (주문번호 {order_no or '없음'}) — "
        f"주문 시점 값으로 근사: {fallback_qty}주 × {fallback_price:,.0f}원"
    )
    return {
        "qty": int(fallback_qty),
        "price": float(fallback_price),
        "amount": float(fallback_price) * int(fallback_qty),
        "fee": 0.0,
        "exact": False,
    }


class Trader:
    def __init__(
        self,
        buy_strategy: BuyStrategy,
        sell_strategy: SellStrategy,
        view_strategies: list[BuyStrategy] | None = None,
        short_term_strategy: EtfDayTradeStrategy | None = None,
    ) -> None:
        from core.strategy._activate import sell_strategy_key_of

        self.buy_strategy = buy_strategy
        self.sell_strategy = sell_strategy
        self.view_strategies = list(view_strategies or [])
        self.short_term_strategy = short_term_strategy or build_short_term_strategy()
        self._known_holdings: set[str] = set()
        self._sell_strategy_key: str = sell_strategy_key_of(sell_strategy)

    # ── 보유 분리 (일반 슬롯 ↔ 단기 매매 슬롯) ─────────────────────────────────

    def general_holdings(self, holdings: dict | None = None) -> dict:
        """일반 매수 슬롯의 보유분만 반환 — 단기 매매 원장 수량을 차감한다.

        일반 매도 전략·초기매수·보유 한도 계산은 모두 이 값을 기준으로 해야 한다.
        그러지 않으면 단기 매매가 사 둔 물량을 일반 매도 전략이 팔아버리거나, 단기 매매
        종목이 보유 한도를 잡아먹어 일반 매수가 막히는 등 두 슬롯이 서로 간섭한다.
        """
        if holdings is None:
            holdings = get_holdings()
        slot = get_setting("short_term_trade")
        general, _ = split_holdings(holdings, slot if isinstance(slot, dict) else None)
        return general

    # ── 거래 이력 ──────────────────────────────────────────────────────────────

    def log_trade(self, trade_type: str, code: str, name: str, price: float, qty: int, **extra) -> None:
        """거래 이력을 trade_history.json 에 추가 (type: 'buy' | 'sell')"""
        record = {
            "timestamp": datetime.now().isoformat(),
            "type": trade_type,
            "code": code,
            "name": name,
            "price": price,
            "qty": qty,
            "amount": price * qty,
            **extra,
        }
        history = []
        if os.path.exists(TRADE_HISTORY_FILE):
            try:
                with open(TRADE_HISTORY_FILE, "r", encoding="utf-8") as f:
                    history = json.load(f).get("trades", [])
            except Exception:
                history = []
        history.append(record)
        try:
            with open(TRADE_HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump({"trades": history}, f, ensure_ascii=False, indent=2)
        except Exception as e:
            log(f"[거래이력] 저장 실패: {e}")

    # ── 매수 후보 탐색 ─────────────────────────────────────────────────────────

    def scan_buy_candidates(self) -> list[dict]:
        """매수 전략 + view 전략을 모두 실행하고 buy_candidates.json 저장.

        반환값은 매수 실행에 쓰일 메인 전략의 후보만 포함. 파일에는 모든 후보를
        통합하여 저장하고, 각 항목에 `_strategy` / `_strategy_label` 식별 필드를 주입한다.
        탐색 시작 즉시 `status: refreshing` 마커로 덮어써서 대시보드가 stale 데이터 대신
        '갱신 중' 상태를 표시하게 한다.

        primary · view 전략 모두 매 호출마다 settings.json 에서 다시 읽어,
        사용자가 사이드바에서 변경한 선택을 즉시 반영한다.
        """
        from core.strategy._activate import (
            primary_buy_strategy as _load_primary_strategy,
            view_buy_strategies as _load_view_strategies,
        )

        self.buy_strategy = _load_primary_strategy()
        primary_name = type(self.buy_strategy).__name__
        log(f"[매수후보] 탐색 시작 ({primary_name})")
        self._write_candidates_status(primary_name)
        try:
            main_candidates = self.buy_strategy.find_candidates()
            _tag_candidates(main_candidates, self.buy_strategy)

            self.view_strategies = _load_view_strategies()
            all_candidates: list[dict] = list(main_candidates)
            for vs in self.view_strategies:
                vs_name = type(vs).__name__
                log(f"[매수후보][view] 탐색 시작 ({vs_name})")
                try:
                    view_results = vs.find_candidates()
                    _tag_candidates(view_results, vs)
                    all_candidates.extend(view_results)
                except Exception as e:
                    log(f"[매수후보][view] {vs_name} 탐색 실패: {e}")

            with open(BUY_CANDIDATES_FILE, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "status": "ready",
                        "updated_at": datetime.now().isoformat(),
                        "strategy": primary_name,
                        "primary_strategy": primary_name,
                        "primary_strategy_label": self.buy_strategy.display_name,
                        "candidates": all_candidates,
                    },
                    f, ensure_ascii=False, indent=2,
                )
            names = ", ".join(c["종목명"] for c in main_candidates)
            log(f"[매수후보] 탐색 완료 (매수용): {names}")
            return main_candidates
        except Exception as e:
            log(f"[매수후보] 탐색 실패: {e}")
            return []

    def _write_candidates_status(self, strategy_name: str) -> None:
        try:
            with open(BUY_CANDIDATES_FILE, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "status": "refreshing",
                        "started_at": datetime.now().isoformat(),
                        "strategy": strategy_name,
                        "candidates": [],
                    },
                    f, ensure_ascii=False, indent=2,
                )
        except Exception as e:
            log(f"[매수후보] 갱신 마커 저장 실패: {e}")

    # ── 매수 실행 ──────────────────────────────────────────────────────────────

    def _place_buy(self, code: str, name: str, qty: int) -> bool:
        """시장가 매수 주문 실행. 성공 시 True."""
        try:
            result = buy_market_order(code, qty)
            log(f"[매수] {name}({code}) {qty}주 시장가 주문 완료: {result.get('msg1', '')}")
            return True
        except Exception as e:
            log(f"[매수] {name}({code}) 실패: {e}")
            return False

    def execute_initial_buy(self, candidates: list[dict]) -> None:
        """예수금을 후보 수만큼 균등 분할하여 각 후보를 시장가 매수.

        `max_holdings` 한도를 초과하지 않도록 잔여 슬롯만큼만 상위 후보 선택.
        """
        if not candidates:
            return

        if not get_setting("buy_enabled"):
            log("[초기매수] 매수 옵션 OFF - 스킵 (대시보드에서 활성화 가능)")
            return

        try:
            cash = get_cash_balance()["주문가능금액"]
        except Exception as e:
            log(f"[초기매수] 주문가능금액 조회 실패: {e}")
            return

        # 단기 매매 물량은 별도 슬롯이므로 일반 보유 수·한도 계산에서 제외한다.
        owned = set(self.general_holdings().keys())
        max_holdings = _safe_max_holdings()
        plan = plan_initial_buy(candidates, cash, owned, max_holdings=max_holdings)

        if not plan:
            if len(owned) >= max_holdings:
                log(f"[초기매수] 보유 {len(owned)}종 ≥ 한도 {max_holdings}종 - 스킵")
            else:
                log("[초기매수] 실행 가능한 주문 없음 - 스킵")
            return

        log(
            f"[초기매수] 주문가능금액 {cash:,.0f}원 / {len(plan)}종목 주문 예정 "
            f"(보유 {len(owned)} → 매수 후 {len(owned) + len(plan)} / 한도 {max_holdings})"
        )
        for item in plan:
            log(f"[초기매수] {item['종목명']}({item['종목코드']}) {item['수량']}주 × {item['현재가']:,.0f}원 ≈ {item['예상금액']:,.0f}원")
            self._place_buy(item["종목코드"], item["종목명"], item["수량"])

    def execute_post_sell_buy(self, sold_code: str) -> None:
        """매도 발생 시 후보 재탐색 후 미보유 최상위 1종목을 남은 예수금으로 매수.

        보유 한도(`max_holdings`)를 초과하지 않을 때만 재매수. KIS 잔고 반영 지연을
        감안해 방금 매도한 `sold_code` 는 보유 카운트에서 제외해 비교한다.
        """
        if not get_setting("buy_enabled"):
            log(f"[매도후재매수] 매수 옵션 OFF - 스킵 ({sold_code} 매도 후)")
            return

        holdings = self.general_holdings()
        max_holdings = _safe_max_holdings()
        # 잔고 반영 지연 가능성 — 방금 매도한 종목은 보유 수에서 빼고 판단
        effective_owned = {k for k in holdings.keys() if k != sold_code}
        if len(effective_owned) >= max_holdings:
            log(f"[매도후재매수] 보유(매도제외) {len(effective_owned)}종 ≥ 한도 {max_holdings}종 - 스킵")
            return

        log(
            f"[매도후재매수] {sold_code} 매도 감지 - 후보 재탐색 "
            f"(보유(매도제외) {len(effective_owned)} / 한도 {max_holdings})"
        )
        candidates = self.scan_buy_candidates()
        if not candidates:
            return

        for c in candidates:
            code = c["종목코드"]
            if code == sold_code or code in effective_owned:
                continue

            try:
                cash = get_cash_balance()["주문가능금액"]
            except Exception as e:
                log(f"[매도후재매수] 주문가능금액 조회 실패: {e}")
                return

            price = c["현재가"]
            if price <= 0:
                continue

            qty = max(1, int(cash // price))
            if price * qty > cash:
                qty = int(cash // price)
            if qty <= 0:
                log(f"[매도후재매수] 주문가능금액 부족 ({cash:,.0f}원 < {price:,.0f}원) - 스킵")
                return

            log(f"[매도후재매수] 선정: {c['종목명']}({code}) {qty}주 × {price:,.0f}원 ≈ {price*qty:,.0f}원")
            self._place_buy(code, c["종목명"], qty)
            return

        log("[매도후재매수] 미보유 후보 없음 - 스킵")

    # ── 단기 매매 (지수/인버스 ETF 방향 매매) ───────────────────────────────────

    def _sync_short_term_settings(self) -> None:
        """단기 매매 파라미터를 settings.json 에서 다시 읽어 반영 (변경 시에만 로그)."""
        s = self.short_term_strategy
        for attr, key, default, label in (
            ("stop_loss_pct", "short_term_stop_loss_pct", 5.0, "손절 기준"),
            ("peak_drop_pct", "short_term_peak_drop_pct", 5.0, "최고가 대비 청산"),
        ):
            value = _safe_float_setting(key, default, minimum=0.1)
            if getattr(s, attr) != value:
                log(f"[단기매매][설정] {label} 변경: {getattr(s, attr):g}% → {value:g}%")
                setattr(s, attr, value)

        close_end = bool(get_setting("short_term_close_at_market_end"))
        if s.close_at_market_end != close_end:
            log(f"[단기매매][설정] 당일 마감 강제청산 {'ON' if close_end else 'OFF'}")
            s.close_at_market_end = close_end

    def check_short_term(self) -> None:
        """일 단위 ETF 방향 매매 — 후보 갱신 · 진입 · 청산 · 교체를 매 주기 처리한다.

        흐름:
          0. 원장 정합성 보정 — 외부 매도/부분 체결로 실제 잔고가 원장과 어긋나면 맞춘다.
          1. 후보 일단위 갱신 — 날짜가 바뀌었으면 오늘 방향을 판정해 ETF 후보를 다시 세운다
             (장 전 준비 시각에 이미 끝나 있으면 재판정하지 않음).
          2. 교체 예약(`pending_action == "switch"`) 처리 — 이전 포지션 청산 후 전환.
          3. 포지션 보유 중 → 최고가 갱신 후 4중 청산 판정 (손절 / 최고가 / 보유기간 / 마감).
          4. 미보유 → 개장 후 매수 창이 열렸으면 시장가 진입.

        모든 손익 판단은 **자체 원장**(진입가·수량) 기준이다. 같은 ETF 를 일반 매수로도
        보유 중이면 증권사 평균단가가 섞이므로 잔고 평단은 신뢰하지 않는다.
        """
        slot = get_setting("short_term_trade")
        if not isinstance(slot, dict):
            return

        self._sync_short_term_settings()

        try:
            holdings = get_holdings()
        except Exception as e:
            log(f"[단기매매] 보유 종목 조회 실패: {e}")
            return

        # 0. 원장 ↔ 실제 잔고 정합성 보정
        slot = self._reconcile_short_term_ledger(slot, holdings)
        general, _ = split_holdings(holdings, slot)

        # 1. 후보 일단위 갱신 (+ 미보유 슬롯 자동 지정)
        slot = self._short_term_refresh_candidates(slot, general)

        auto_enabled = bool(slot.get("auto_enabled", False))

        # 2. 사용자 '교체' 예약 처리
        if slot.get("pending_action") == "switch" and has_pending(slot):
            self._short_term_switch(slot, general, auto_enabled)
            return

        code = slot.get("code")
        if not code:
            return
        name = slot.get("name") or code

        holding = has_position(slot)
        # 포지션도 없고 자동매매도 꺼져 있으면 시세를 조회할 이유가 없다 (불필요한 API 호출 회피).
        if not holding and not auto_enabled:
            return

        try:
            snapshot = get_quote_snapshot(code)
        except Exception as e:
            log(f"[단기매매][{name}({code})] 시세 조회 실패: {e}")
            return
        current_price = float(snapshot.get("현재가", 0) or 0)
        if current_price <= 0:
            log(f"[단기매매][{name}({code})] 현재가 0 — 스킵")
            return

        # 3. 보유 중 — 최고가 갱신 후 청산 판정
        if holding:
            bumped = update_peak(slot, current_price)
            if bumped is not None:
                slot = bumped
                set_setting("short_term_trade", slot)
            if not auto_enabled:
                log(f"[단기매매][{name}({code})] 자동매매 OFF — 청산 판정 보류 (최고가만 추적)")
                return
            decision = self.short_term_strategy.should_sell(slot, current_price)
            if decision.sell:
                self._short_term_exit(slot, current_price, decision, general)
            else:
                entry = slot.get("entry_price") or 0
                profit = ((current_price - entry) / entry * 100) if entry else 0
                log(
                    f"[단기매매][{name}({code})] 보유 중 {position_qty(slot)}주 · "
                    f"현재가 {current_price:,.0f}원 · 수익률 {profit:+.2f}% · "
                    f"최고가 {float(slot.get('peak') or 0):,.0f}원"
                )
            return

        # 4. 미보유 — 진입 시도
        if not auto_enabled:
            return
        if is_blocked(slot):
            log(
                f"[단기매매][{name}({code})] 오늘은 청산 후 재진입 차단 상태 "
                f"— 다음 거래일 개장부터 재개"
            )
            return

        should_buy, reason = self.short_term_strategy.should_buy(slot, snapshot)
        if not should_buy:
            log(f"[단기매매][{name}({code})] 진입 보류 — {reason}")
            return

        if not short_term_buy_window_open():
            log(
                f"[단기매매][{name}({code})] 개장 후 {short_term_buy_delay_min()}분 대기 — "
                f"실매수 보류 ({short_term_buy_start_label()} 이후 매수 시작)"
            )
            return

        self._short_term_enter(slot, current_price, reason)

    # ── 단기 매매: 진입 ────────────────────────────────────────────────────────

    def _short_term_enter(self, slot: dict, current_price: float, reason: str) -> None:
        """시장가 진입 + 자체 원장 기록.

        예산 = min(자금 풀 잔액, 주문가능금액). 자금 풀은 배정액(씨드)에서 출발해 청산할
        때마다 실현손익이 누적되므로, **번 만큼 다음 진입 금액이 커지고 잃은 만큼 작아진다**.
        일반 매수 자금에서 손실을 보충하거나 이익을 빼내지 않고 풀 안에서만 굴린다.
        주문가능금액으로 한 번 더 자르는 이유는 실제 현금보다 많이 주문할 수 없기 때문이다.
        """
        code = slot["code"]
        name = slot.get("name") or code

        try:
            cash = get_cash_balance()["주문가능금액"]
        except Exception as e:
            log(f"[단기매매][{name}({code})] 주문가능금액 조회 실패: {e}")
            return

        pool = short_term_pool()
        budget = min(pool, float(cash))

        if budget < current_price:
            log(
                f"[단기매매][{name}({code})] 예산 부족 (예산 {budget:,.0f}원 = "
                f"min(자금풀 {pool:,.0f}, 주문가능 {cash:,.0f}) "
                f"< 현재가 {current_price:,.0f}원) - 스킵"
            )
            return

        qty = int(budget // current_price)
        if qty <= 0:
            return

        log(
            f"[단기매매][{name}({code})] ★ 진입 ({reason}) → {qty}주 × {current_price:,.0f}원 "
            f"≈ {qty * current_price:,.0f}원 (예산 {budget:,.0f}원 = "
            f"min(자금풀 {pool:,.0f}, 주문가능 {cash:,.0f}))"
        )
        try:
            result = buy_market_order(code, qty)
        except Exception as e:
            log(f"[단기매매][{name}({code})] 매수 실패: {e}")
            return

        # 실제 체결가·체결수량·지출액을 확정 — 이후 손익 계산이 전부 이 값을 따른다.
        fill = settle_order(result, code, "buy", current_price, qty)
        log(
            f"[단기매매][{name}({code})] 체결 {fill['qty']}주 @ {fill['price']:,.0f}원 "
            f"· 지출 {fill['amount']:,.0f}원 (제비용 {fill['fee']:,.0f}원)"
            + ("" if fill["exact"] else " ※ 주문 시점 근사치")
        )
        self.log_trade("buy", code, name, fill["price"], fill["qty"], reason=f"[단기매매] {reason}")
        set_setting(
            "short_term_trade",
            mark_entry(slot, fill["price"], fill["qty"], invested=fill["amount"]),
        )

    # ── 단기 매매: 청산 ────────────────────────────────────────────────────────

    def _short_term_exit(
        self,
        slot: dict,
        current_price: float,
        decision,
        general: dict,
    ) -> None:
        """원장 수량만큼 시장가 청산 후 재진입 여부를 사유에 따라 결정.

        - 보유기간 만료 청산 → 오늘 방향의 후보로 슬롯을 갱신해 **같은 날 재진입**한다
          (일 단위 회전이 이 전략의 정상 동작).
        - 손절·최고가·마감 청산 → 오늘은 재진입하지 않는다 (`blocked_date` 마킹).
        """
        code = slot["code"]
        name = slot.get("name") or code
        qty = position_qty(slot)
        entry = slot.get("entry_price") or 0
        invested = invested_amount(slot)
        profit_pct = ((current_price - entry) / entry * 100) if entry else 0

        log(
            f"[단기매매][{name}({code})] ★ 청산 조건 충족 ({decision.reason}) → "
            f"{qty}주 시장가 매도 (수익률 {profit_pct:+.2f}%)"
        )
        try:
            result = sell_market_order(code, qty)
        except Exception as e:
            log(f"[단기매매][{name}({code})] 매도 실패: {e}")
            return

        fill = settle_order(result, code, "sell", current_price, qty)
        log(
            f"[단기매매][{name}({code})] 체결 {fill['qty']}주 @ {fill['price']:,.0f}원 "
            f"· 회수 {fill['amount']:,.0f}원 (제비용 {fill['fee']:,.0f}원)"
            + ("" if fill["exact"] else " ※ 주문 시점 근사치")
        )
        self.log_trade("sell", code, name, fill["price"], fill["qty"], reason=f"[단기매매] {decision.reason}")
        # 실현손익을 자금 풀에 누적 — 다음 진입 금액이 이 잔액을 그대로 따라간다.
        apply_short_term_pnl(invested, fill["amount"])

        if not decision.allows_reentry_today:
            set_setting("short_term_trade", block_today(clear_position(slot)))
            log("[단기매매] 손실성 청산 — 오늘은 재진입하지 않음 (다음 거래일 개장부터 재개)")
            return

        # 보유기간 만료 — 오늘 방향의 후보로 갈아타 재진입 (같은 종목이어도 무방).
        auto_enabled = bool(slot.get("auto_enabled", False))
        next_target = self._short_term_pick_from_candidates(set(general.keys()))
        new_slot = target_to_settings(
            next_target,
            auto_enabled=auto_enabled,
            blocked_date=None,
        )
        set_setting("short_term_trade", new_slot)
        if next_target is None:
            log("[단기매매] 청산 후 재진입 후보 없음 — 다음 주기 재시도")
        else:
            log(
                f"[단기매매] 청산 후 재진입 대상: {new_slot['name']}({new_slot['code']}) - "
                f"{new_slot.get('selection_reason', '')}"
            )

    def _short_term_pick_from_candidates(self, exclude_codes: set[str]) -> dict | None:
        """오늘 후보 목록에서 매매할 1종을 고른다. 목록이 오래됐으면 방향을 다시 판정한다.

        장 전 준비 시각에 정한 오늘의 방향을 그대로 쓰는 것이 이 전략의 전제이므로,
        같은 날 청산 직후에는 저장된 후보를 재사용하고 API 를 다시 때리지 않는다.
        """
        container = get_setting("short_term_candidates")
        if candidates_need_refresh(container):
            items, verdict = self.short_term_strategy.find_targets(
                n=SHORT_TERM_CANDIDATE_COUNT, exclude_codes=exclude_codes
            )
            set_setting("short_term_candidates", candidates_to_settings(items, verdict))
        else:
            items = (container or {}).get("items") or []
        for item in items:
            if item.get("종목코드") and item["종목코드"] not in exclude_codes:
                return item
        return None

    # ── 단기 매매: 원장 정합성 ─────────────────────────────────────────────────

    def _reconcile_short_term_ledger(self, slot: dict, holdings: dict) -> dict:
        """자체 원장을 실제 잔고와 대조해 보정한다.

        보정 대상:
          - 잔고에 없는데 원장에 수량이 남아 있음 → 외부(HTS/MTS) 매도로 청산된 것으로 보고
            원장을 비운다. 남겨두면 유령 포지션으로 계속 청산 판정을 돌린다.
          - 잔고 수량 < 원장 수량 → 부분 체결·부분 매도. 잔고 수량까지로 낮춘다.
          - 잔고 수량 == 원장 수량 (겹치는 일반 보유 없음) → 증권사 평균단가가 곧 이 포지션의
            실제 체결가이므로 진입가를 그것으로 보정한다. 시장가 주문은 주문 시점 현재가와
            체결가가 어긋날 수 있어, 확인 가능한 시점에 진짜 체결가로 맞춰준다.
        """
        code = slot.get("code")
        qty = position_qty(slot)
        if not code or qty <= 0:
            return slot

        held = holdings.get(code)
        held_qty = int(held.get("qty") or 0) if held else 0
        name = slot.get("name") or code

        if held_qty <= 0:
            log(f"[단기매매][{name}({code})] 잔고에 없음 — 외부 청산으로 보고 원장 정리")
            updated = clear_position(slot)
            set_setting("short_term_trade", updated)
            return updated

        updated = slot
        changed = False
        if held_qty < qty:
            log(f"[단기매매][{name}({code})] 원장 수량 보정: {qty}주 → {held_qty}주 (실제 잔고 기준)")
            updated = set_position_qty(updated, held_qty)
            changed = True

        avg_price = float(held.get("avg_price") or 0)
        if held_qty == position_qty(updated) and avg_price > 0:
            # 잔고가 단기 매매 물량뿐 → 평균단가 = 이 포지션의 실제 체결가.
            recorded = float(updated.get("entry_price") or 0)
            if abs(recorded - avg_price) >= 1:
                log(
                    f"[단기매매][{name}({code})] 진입가 보정: {recorded:,.0f}원 → "
                    f"{avg_price:,.0f}원 (실제 체결 평균단가)"
                )
                updated = {**updated, "entry_price": avg_price}
                # 체결 조회로 확정한 투입액이 있으면 그쪽이 더 정확하므로 건드리지 않고,
                # 기록이 없을 때(외부 매수 등)만 평단 기준으로 채운다.
                if not updated.get("invested"):
                    updated["invested"] = avg_price * position_qty(updated)
                # 최고가가 진입가보다 낮게 기록돼 있으면 함께 끌어올린다.
                if float(updated.get("peak") or 0) < avg_price:
                    updated = {**updated, "peak": avg_price}
                changed = True

        if changed:
            set_setting("short_term_trade", updated)
        return updated

    # ── 단기 매매: 후보 갱신 / 교체 ────────────────────────────────────────────

    def prepare_market_open(self, force_short_term: bool = False) -> list[dict]:
        """장 전(또는 시작 시) 매매 없이 조회만으로 매수·단기매매 후보를 미리 선정.

        정규장 개장(09:00) 전 '준비 창'(`is_pre_market`)이나 시작 시점에 호출해,
        매수 후보(`scan_buy_candidates`)와 단기 매매 후보(`_prepare_short_term`)를 함께
        갱신한다. 실제 주문은 일절 발생하지 않으며(조회·후보 선정만), 개장 시
        `execute_initial_buy`·`check_short_term` 이 이 결과를 그대로 사용한다.

        Args:
            force_short_term: True 면 같은 날 이미 판정했더라도 시장 방향을 다시 판정한다.
                장 전 준비 창(08:30~09:00)에서 쓴다 — 그 이전(예: 08:00)에 트레이더를 켜면
                당일 날짜로 판정 기록이 남아 일단위 가드에 걸리는데, 개장 전 갭 신호
                (예상체결가)는 08:30 이후에만 형성되므로 그 시각에 반드시 다시 판정해야 한다.

        Returns:
            매수 실행용 primary 전략 후보 리스트 (개장 후 초기매수에 사용).
        """
        candidates = self.scan_buy_candidates()
        self._prepare_short_term(force=force_short_term)
        return candidates

    def _prepare_short_term(self, force: bool = False) -> None:
        """오늘의 시장 방향을 판정해 ETF 후보·활성 슬롯을 미리 준비 (주문 없음).

        개장 30분 전(장 전 준비 시각)에 호출되며, 평소에는 일단위 날짜 가드
        (`candidates_need_refresh`)가 있어 하루 1회만 실제 판정한다. `force=True` 면
        가드를 건너뛰고 재판정한다.
        """
        slot = get_setting("short_term_trade")
        if not isinstance(slot, dict):
            return
        self._sync_short_term_settings()
        try:
            holdings = get_holdings()
        except Exception as e:
            log(f"[장전준비][단기매매] 보유 종목 조회 실패: {e}")
            return
        slot = self._reconcile_short_term_ledger(slot, holdings)
        general, _ = split_holdings(holdings, slot)
        self._short_term_refresh_candidates(slot, general, force=force)

    def _short_term_refresh_candidates(self, slot: dict, general: dict, force: bool = False) -> dict:
        """후보 목록 일단위 갱신 + 활성 슬롯 처리.

        후보 목록(`short_term_candidates`)의 selected_at 날짜가 오늘과 다르면 오늘의 시장
        방향을 판정해 ETF 후보를 새로 세운다. 일반 매수로 이미 보유 중인 종목은 후보에서
        제외해(`exclude_codes`) 대체 ETF 가 선택되게 한다 — 평단 혼입 회피.

        활성 슬롯:
          - 포지션 **보유 중** → 유지 (보호). 청산은 `should_sell` 이 판단한다.
          - **미보유** → 새 후보 #1 을 활성으로 지정하고 진입 차단(blocked_date)을 해제한다
            (날짜가 바뀌었으므로 어제의 손절 차단은 더 이상 유효하지 않다).

        Args:
            force: True 면 일단위 날짜 가드를 무시하고 다시 판정한다 (장 전 준비 창).

        Returns:
            이후 로직에서 사용할 (갱신됐을 수 있는) 활성 슬롯 dict.
        """
        container = get_setting("short_term_candidates")
        if not force and not candidates_need_refresh(container):
            return slot

        exclude = set(general.keys())
        items, verdict = self.short_term_strategy.find_targets(
            n=SHORT_TERM_CANDIDATE_COUNT, exclude_codes=exclude
        )
        set_setting("short_term_candidates", candidates_to_settings(items, verdict))

        if not items:
            log("[단기매매] 후보 재선정 — 진입 대상 없음 (중립 판정이거나 가용 ETF 없음)")
            return slot

        if has_position(slot):
            log(
                f"[단기매매] 활성 종목 {slot.get('name')}({slot.get('code')}) 보유 중 — 유지 "
                f"(후보 목록만 갱신, 청산은 보유기간·손절 판정에 위임)"
            )
            return slot

        new_slot = target_to_settings(
            items[0],
            auto_enabled=bool(slot.get("auto_enabled", False)),
            blocked_date=None,  # 날짜가 바뀌었으므로 어제의 재진입 차단 해제
        )
        set_setting("short_term_trade", new_slot)
        log(
            f"[단기매매] 오늘의 매매 대상: {new_slot['name']}({new_slot['code']}) - "
            f"{new_slot.get('selection_reason', '')}"
        )
        return new_slot

    def _short_term_switch(self, slot: dict, general: dict, auto_enabled: bool) -> None:
        """사용자 '교체' 선택 처리 — 이전 포지션을 청산한 뒤 대기 후보로 전환.

        원장 수량만 매도하므로 같은 종목을 일반 매수로 보유 중이어도 그쪽 물량은 건드리지
        않는다. 장 시간 외에는 매도가 불가능하므로 다음 개장 후 사이클에서 재시도한다
        (`pending_action` 유지).
        """
        pending = slot.get("pending_target")
        active_code = slot.get("code")
        active_name = slot.get("name") or active_code
        invested = invested_amount(slot)

        qty = position_qty(slot)
        if qty > 0 and active_code:
            if not is_trading_time():
                log("[단기매매] 교체 예약됨 — 장 시간 외, 개장 후 이전 포지션 청산 진행")
                return
            try:
                price = get_current_price(active_code)
            except Exception as e:
                log(f"[단기매매] 교체용 가격 조회 실패 ({active_name}): {e}")
                return
            log(f"[단기매매] 교체 — 이전 포지션 {active_name}({active_code}) {qty}주 전량 시장가 매도")
            try:
                result = sell_market_order(active_code, qty)
            except Exception as e:
                log(f"[단기매매] 교체 매도 실패 ({active_name}): {e}")
                return
            fill = settle_order(result, active_code, "sell", price, qty)
            self.log_trade(
                "sell", active_code, active_name, fill["price"], fill["qty"],
                reason="[단기매매] 사용자 교체 — 이전 포지션 전량 매도",
            )
            # 교체도 실현손익이 확정되는 청산이므로 자금 풀에 그대로 반영한다.
            apply_short_term_pnl(invested, fill["amount"])

        new_slot = target_to_settings(
            pending,
            auto_enabled=auto_enabled,
            blocked_date=slot.get("blocked_date"),
        )
        set_setting("short_term_trade", new_slot)
        log(
            f"[단기매매] 교체 완료 → 새 종목: {new_slot['name']}({new_slot['code']}) - "
            f"{new_slot.get('selection_reason', '')}"
        )

    # ── 매도 체크 ──────────────────────────────────────────────────────────────

    def check_and_sell(self) -> None:
        """보유 종목 가격 확인 후 SellStrategy 판단에 따라 매도.

        단기 매매 원장 수량은 잔고에서 차감한 뒤 판단한다 — 별도 슬롯으로 운용되는
        물량을 일반 매도 전략이 대신 팔아버리지 않도록 하기 위해서다.
        """
        raw_holdings = get_holdings()
        st_slot = get_setting("short_term_trade")
        holdings, short_term_held = split_holdings(
            raw_holdings, st_slot if isinstance(st_slot, dict) else None
        )
        for code, info in short_term_held.items():
            if code in holdings:
                # 같은 ETF 를 양쪽 슬롯이 함께 보유 — 대체 ETF 로 피하는 게 원칙이라 이례적.
                log(
                    f"[{info['name']}({code})] 단기 매매 {info['qty']}주 분리 — "
                    f"일반 슬롯 {holdings[code]['qty']}주만 매도 판단 대상 "
                    f"(증권사 평단은 합산되므로 수익률 표시는 참고용)"
                )

        if not holdings:
            log("보유 종목 없음" + (" (단기 매매 물량 제외)" if short_term_held else ""))
            self._known_holdings = set()
            return

        current_codes = set(holdings.keys())

        # 신규 편입 종목 = 매수 감지 (시작 직후 첫 사이클은 _known_holdings 가 비어 있으므로 제외)
        if self._known_holdings:
            for code in current_codes - self._known_holdings:
                info = holdings[code]
                buy_price = info["avg_price"]
                log(f"[{info['name']}({code})] ★ 신규 매수 감지 (평균단가: {buy_price:,.0f}원 × {info['qty']}주)")
                self.log_trade("buy", code, info["name"], buy_price, info["qty"])
                # reset=True: 외부 툴 매매로 남은 orphan 최고가가 있어도 평균단가로 강제
                # 재설정해, stale 한 이전 구간 최고가로 즉시 손절되는 오판을 막는다.
                self.sell_strategy.on_buy(code, buy_price, reset=True)

            # 사라진 종목 = 보유 청산 감지 (자동 매도·수동 매도·외부 체결 모두 포괄).
            # 매도 전략의 종목별 내부 상태(최고가 등)를 정리해, 재매수 시 stale 한
            # 이전 최고가가 남아 매수가 대비 과도한 하락으로 오판되는 것을 막는다.
            for code in self._known_holdings - current_codes:
                self.sell_strategy.on_sell(code)

        self._known_holdings = current_codes

        for code, info in holdings.items():
            name = info["name"]
            qty = info["qty"]

            try:
                price = get_current_price(code)
            except Exception as e:
                log(f"[{name}({code})] 가격 조회 실패: {e}")
                continue

            self.sell_strategy.observe(code, price)

            detail = self.sell_strategy.describe(code, price)
            log(f"[{name}({code})] 현재가: {price:,.0f}원" + (f" | {detail}" if detail else ""))

            should_sell, reason = self.sell_strategy.should_sell(code, price)
            if should_sell:
                # 자동매도 활성화 종목인지 매번 settings 재읽기 — 대시보드에서 토글한 결과 즉시 반영.
                raw_enabled = get_setting("auto_sell_enabled_codes")
                enabled_codes = set(raw_enabled) if isinstance(raw_enabled, list) else set()
                if code not in enabled_codes:
                    log(f"[{name}({code})] 매도 조건 충족 ({reason}) — 자동매도 OFF 로 매도 보류")
                    continue
                log(f"[{name}({code})] ★ 매도 조건 충족 ({reason}) → 매도 주문 실행")
                try:
                    result = sell_market_order(code, qty)
                    log(f"[{name}({code})] 매도 완료: {result}")
                    self.log_trade("sell", code, name, price, qty, reason=reason)
                    # 매도 성공 시 enabled 리스트에서 제거 — 재매수 시 기본 OFF 로 다시 시작.
                    if code in enabled_codes:
                        from core.settings import set_value as _set_setting
                        _set_setting("auto_sell_enabled_codes", sorted(enabled_codes - {code}))
                    self.execute_post_sell_buy(code)
                except Exception as e:
                    log(f"[{name}({code})] 매도 실패: {e}")

    # ── 메인 루프 ──────────────────────────────────────────────────────────────

    def run(self) -> None:
        log(f"트레이더 시작 [{MODE_LABEL}] | 매수전략: {type(self.buy_strategy).__name__} | 매도전략: {type(self.sell_strategy).__name__} | 확인 주기: {CHECK_INTERVAL // 60}분")
        if IS_MOCK and not is_market_open():
            log("[모의] 상시거래 모드 — 장 시간 외에도 매매 로직 동작 (KIS 모의서버는 정규장에만 체결될 수 있음)")

        self.sell_strategy.load()

        # 기존 보유 종목 초기화 (재시작 시 false-positive 매수 감지 방지).
        # 단기 매매 원장 물량은 제외 — 일반 매도 전략의 추적 대상이 아니다.
        try:
            initial = self.general_holdings()
            self._known_holdings.update(initial.keys())
            for code, info in initial.items():
                if info["avg_price"] > 0:
                    self.sell_strategy.on_buy(code, info["avg_price"])
            # 트레이더 down 중 외부 툴로 매도된 종목의 orphan 최고가를 정리.
            self.sell_strategy.reconcile(set(initial.keys()))
            if initial:
                log(f"[초기화] 기존 보유 종목 {len(initial)}개 확인 완료")
        except Exception as e:
            log(f"[초기화] 보유 종목 조회 실패: {e}")

        # 시작 시 매수 후보와 오늘의 시장 방향을 미리 선정 (매매 없이 조회만).
        now = datetime.now()
        candidates = self.prepare_market_open(force_short_term=is_pre_market(now))
        did_initial_buy = is_trading_time()
        # 장 전 준비를 마친 날짜 — 하루 1회만 사전 선정. 시작 시점이 장전/정규장이면
        # 방금 prepare_market_open 으로 끝낸 셈이라 오늘 날짜로 마킹한다. 그 이전(예: 새벽)에
        # 시작했다면 None 으로 두어, 장전 시작 시각이 되면 신선한 데이터로 다시 선정한다.
        prep_date = now.date() if (is_trading_time() or is_pre_market(now)) else None

        if is_trading_time():
            self.execute_initial_buy(candidates)
        elif is_pre_market(now):
            log("[장전준비] 매매 없이 매수 후보·시장 방향 사전 선정 완료 — 개장(09:00) 후 매매 시작")
        else:
            log("[초기매수] 장 운영 시간 외 - 다음 개장 후 실행")

        while True:
            self._sync_sell_settings()
            now = datetime.now()
            if is_trading_time():
                if not did_initial_buy:
                    self.execute_initial_buy(candidates)
                    did_initial_buy = True
                try:
                    self.check_and_sell()
                except Exception as e:
                    log(f"오류 발생: {e}")
                try:
                    self.check_short_term()
                except Exception as e:
                    log(f"[단기매매] 처리 중 오류: {e}")
            elif is_pre_market(now):
                # 장 전 준비: 매매 없이 후보만 하루 1회 사전 선정. 개장 시 신선한 후보로 진입.
                if prep_date != now.date():
                    log(f"[장전준비] 매수 후보·시장 방향 사전 선정 시작 (매매는 개장 후 — 현재 {now.strftime('%H:%M')})")
                    # force: 장전 창 이전에 기동해 오늘 날짜로 판정 기록이 남았더라도,
                    # 갭 신호를 반영해 이 시각에 반드시 다시 판정한다.
                    candidates = self.prepare_market_open(force_short_term=True)
                    prep_date = now.date()
                    did_initial_buy = False  # 사전 선정된 후보로 개장 후 초기매수 실행
            else:
                log("장 운영 시간 외 - 대기 중")

            time.sleep(CHECK_INTERVAL)

    def _sync_sell_settings(self) -> None:
        """매도 전략의 사용자 설정값을 settings.json 에서 다시 읽어 반영.

        - `sell_strategy` 키가 변경되면 새 인스턴스로 교체 후 보유 종목으로 priming.
        - 트레일링 스탑의 `stop_loss_pct` 같은 단일 파라미터 변경은 in-place 갱신.
        """
        from core.strategy._activate import (
            DEFAULT_SELL_KEY,
            build_sell_strategy,
        )

        desired_key = get_setting("sell_strategy")
        if not isinstance(desired_key, str) or not desired_key:
            desired_key = DEFAULT_SELL_KEY
        if desired_key != self._sell_strategy_key:
            log(f"[설정] 매도 전략 변경: {self._sell_strategy_key} → {desired_key}")
            new_strategy = build_sell_strategy(desired_key)
            new_strategy.load()
            try:
                holdings = self.general_holdings()
                for code, info in holdings.items():
                    if info["avg_price"] > 0:
                        new_strategy.on_buy(code, info["avg_price"])
                new_strategy.reconcile(set(holdings.keys()))
            except Exception as e:
                log(f"[설정] 매도 전략 priming 실패: {e}")
            self.sell_strategy = new_strategy
            self._sell_strategy_key = desired_key

        if hasattr(self.sell_strategy, "stop_loss_pct"):
            new_pct = float(get_setting("stop_loss_pct"))
            if new_pct != self.sell_strategy.stop_loss_pct:
                log(f"[설정] 손절 기준 변경: {self.sell_strategy.stop_loss_pct}% → {new_pct}%")
                self.sell_strategy.stop_loss_pct = new_pct
