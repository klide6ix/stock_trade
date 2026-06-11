import json
import os
import time
from datetime import datetime, timedelta

from config import CHECK_INTERVAL, MODE_LABEL, IS_MOCK
from core.kis_api import (
    get_holdings,
    get_current_price,
    sell_market_order,
    buy_market_order,
    get_cash_balance,
)
from core.logger import log
from core.settings import get as get_setting, set_value as set_setting
from core.short_term import (
    SHORT_TERM_CANDIDATE_COUNT,
    ShortTermStrategy,
    candidates_need_refresh,
    candidates_to_settings,
    has_pending,
    target_to_settings,
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


# 단타 실매수 지연 (분) 기본값 — 개장(09:00) 후 이 시간이 지나야 실제 시장가 매수를 시작한다.
# 종목 탐색/선정은 9시부터 수행하되 매수만 미룬다. 실제 적용값은 settings.json 에서 조절 가능.
SHORT_TERM_BUY_DELAY_MIN = 10


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
    """단타 실매수 시작 시각 라벨 (예: '09:10') — 개장(09:00) + 설정 지연."""
    now = now or datetime.now()
    start = now.replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(
        minutes=short_term_buy_delay_min()
    )
    return start.strftime("%H:%M")


def short_term_buy_window_open(now: datetime | None = None) -> bool:
    """단타 실매수 허용 시간 여부 — 개장(09:00) 후 설정 지연(분) 경과 시 True.

    개장 직후에는 등락률·거래량 ranking 이 출렁여 '진짜 오르는 종목' 판별이 어렵다.
    따라서 종목 탐색·선정은 9시부터 진행하되, 실제 매수는 지연 시간 이후로 미뤄
    시초가 변동성에 휩쓸려 잘못된 종목을 잡는 것을 줄인다. 지연은 사이드바에서 조절 가능.
    """
    now = now or datetime.now()
    open_time = now.replace(hour=9, minute=0, second=0, microsecond=0)
    return now >= open_time + timedelta(minutes=short_term_buy_delay_min())


class Trader:
    def __init__(
        self,
        buy_strategy: BuyStrategy,
        sell_strategy: SellStrategy,
        view_strategies: list[BuyStrategy] | None = None,
        short_term_strategy: ShortTermStrategy | None = None,
    ) -> None:
        from core.strategy._activate import sell_strategy_key_of

        self.buy_strategy = buy_strategy
        self.sell_strategy = sell_strategy
        self.view_strategies = list(view_strategies or [])
        self.short_term_strategy = short_term_strategy or ShortTermStrategy()
        self._known_holdings: set[str] = set()
        self._sell_strategy_key: str = sell_strategy_key_of(sell_strategy)

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

        owned = set(get_holdings().keys())
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

        holdings = get_holdings()
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

    # ── 단타 처리 ──────────────────────────────────────────────────────────────

    # 단타 매수 1회 최대 사용 금액 (원). 주문가능금액이 이보다 많아도 이 금액으로 상한 제한.
    # 단타는 단발 진입 + 빠른 청산이므로 고정 상한으로 운용해 일반 매수와 자금 경합을 줄인다.
    SHORT_TERM_BUDGET_MAX = 3_000_000

    def check_short_term(self) -> None:
        """단기 매매 (단타) — 후보 목록 일단위 갱신 + 활성 종목 매수/매도/교체 처리.

        흐름:
          0. 후보 목록 일단위 재선정 (selected_at 날짜 ≠ 오늘 또는 비어있음):
             `find_targets()` 으로 상위 N종 후보를 새로 뽑아 저장. 활성 종목을 **보유 중**이면
             유지(보호), **미보유**면 새 후보 #1 종목을 활성으로 자동 지정 (빈 슬롯만 갱신).
          1. `pending_action == "switch"` (콤보로 보유 중 다른 종목 선택) → 이전 보유 전량 매도 후
             대기 후보(pending_target)로 전환.
          2. auto_enabled OFF 이면 종료.
          3. 활성 종목 보유 중 + should_sell True → 전량 시장가 매도 →
             회수 금액(`체결가 × 수량`)을 `last_realized_amount` 로 기록 →
             **즉시 `find_target(exclude_codes={매도종목})` 으로 다음 활성 종목 자동 지정**.
          4. 미보유 + should_buy True → 매수 (개장 후 지연 시간 경과 후).
             예산 = min(직전 `last_realized_amount` (없으면 `SHORT_TERM_BUDGET_MAX`),
                       `SHORT_TERM_BUDGET_MAX`, 주문가능금액).

        예산 정책의 의도: 단타 자금 풀을 독립 추적해 일반 매수와 자금 경합 차단.
        이익 발생 시 BUDGET_MAX 로 캡(=초과분은 일반 자금으로 풀어줌), 손실 시 단타 풀에서 흡수.
        """
        slot = get_setting("short_term_trade")
        if not isinstance(slot, dict):
            return

        try:
            holdings = get_holdings()
        except Exception as e:
            log(f"[단타] 보유 종목 조회 실패: {e}")
            return

        # 0. 후보 목록 일단위 갱신 + 활성 슬롯 처리 (보유 유지 / 미보유 갱신)
        slot = self._short_term_refresh_candidates(slot, holdings)

        auto_enabled = bool(slot.get("auto_enabled", False))
        last_realized = slot.get("last_realized_amount")

        # 1. 사용자 '교체' 예약 처리 — 이전 보유 전량 매도 후 대기 후보로 전환
        if slot.get("pending_action") == "switch" and has_pending(slot):
            self._short_term_switch(slot, holdings, auto_enabled)
            return

        if not auto_enabled:
            return

        code = slot.get("code")
        if not code:
            return
        name = slot.get("name") or code

        try:
            current_price = get_current_price(code)
        except Exception as e:
            log(f"[단타][{name}({code})] 가격 조회 실패: {e}")
            return

        held = holdings.get(code)

        if held:
            avg_price = held.get("avg_price")
            should_sell, reason = self.short_term_strategy.should_sell(slot, current_price, avg_price)
            if should_sell:
                qty = held["qty"]
                log(f"[단타][{name}({code})] ★ 매도 조건 충족 ({reason}) → {qty}주 시장가 매도")
                try:
                    sell_market_order(code, qty)
                    self.log_trade("sell", code, name, current_price, qty, reason=f"[단타] {reason}")

                    # 매도 회수 금액 (체결가 × 수량) — 다음 매수 예산 상한으로 사용.
                    realized = float(current_price) * int(qty)
                    log(
                        f"[단타][{name}({code})] 매도 회수 ≈ {realized:,.0f}원 → "
                        f"다음 진입 예산 = min({realized:,.0f}, 상한 {self.SHORT_TERM_BUDGET_MAX:,.0f}, 주문가능)"
                    )

                    # 실시간 재선정 — 직전 매도 종목 제외해 즉시 회전 방지.
                    new_target = self.short_term_strategy.find_target(exclude_codes={code})
                    new_slot = target_to_settings(
                        new_target,
                        auto_enabled=auto_enabled,
                        last_realized_amount=realized,
                    )
                    set_setting("short_term_trade", new_slot)
                    if new_target is None:
                        log("[단타] 매도 후 재선정 결과 없음 - 다음 사이클 재시도")
                    else:
                        log(
                            f"[단타] 매도 후 실시간 재선정 완료: "
                            f"{new_slot['name']}({new_slot['code']}) - "
                            f"{new_slot.get('selection_reason', '')}"
                        )
                except Exception as e:
                    log(f"[단타][{name}({code})] 매도 실패: {e}")
            return

        # 미보유 — 매수 진행
        should_buy, reason = self.short_term_strategy.should_buy(slot, current_price)
        if not should_buy:
            return

        # 개장 직후 변동성 회피 — 지연 시간 이전에는 선정만 유지하고 실매수는 보류.
        if not short_term_buy_window_open():
            log(
                f"[단타][{name}({code})] 개장 후 {short_term_buy_delay_min()}분 대기 — "
                f"실매수 보류 ({short_term_buy_start_label()} 이후 매수 시작)"
            )
            return

        try:
            cash = get_cash_balance()["주문가능금액"]
        except Exception as e:
            log(f"[단타][{name}({code})] 주문가능금액 조회 실패: {e}")
            return

        # 예산: 직전 매도 회수 금액(없으면 BUDGET_MAX) 과 상한, 주문가능금액 셋 중 최솟값.
        # 사용자 요구: 손실분은 단타 풀이 흡수, 일반 자금에서 끌어오지 않음.
        if isinstance(last_realized, (int, float)) and last_realized > 0:
            base_budget = float(last_realized)
        else:
            base_budget = float(self.SHORT_TERM_BUDGET_MAX)
        budget = min(base_budget, float(self.SHORT_TERM_BUDGET_MAX), float(cash))

        if budget < current_price:
            log(
                f"[단타][{name}({code})] 예산 부족 "
                f"(예산 {budget:,.0f}원 = min(직전회수 {base_budget:,.0f}, 상한 {self.SHORT_TERM_BUDGET_MAX:,.0f}, 주문가능 {cash:,.0f}) "
                f"< 현재가 {current_price:,.0f}원) - 스킵"
            )
            return

        qty = int(budget // current_price)
        if qty <= 0:
            return

        log(
            f"[단타][{name}({code})] ★ 매수 조건 충족 ({reason}) → "
            f"{qty}주 × {current_price:,.0f}원 ≈ {qty*current_price:,.0f}원 "
            f"(예산 {budget:,.0f}원 = min(직전회수 {base_budget:,.0f}, 상한 {self.SHORT_TERM_BUDGET_MAX:,.0f}, 주문가능 {cash:,.0f}))"
        )
        try:
            buy_market_order(code, qty)
            self.log_trade("buy", code, name, current_price, qty, reason=f"[단타] {reason}")
        except Exception as e:
            log(f"[단타][{name}({code})] 매수 실패: {e}")

    def _short_term_refresh_candidates(self, slot: dict, holdings: dict) -> dict:
        """단타 후보 목록 일단위 갱신 + 활성 슬롯 처리.

        후보 목록(`short_term_candidates`)의 selected_at 날짜가 오늘과 다르면(또는 비어있으면)
        `find_targets()` 으로 상위 N종을 새로 뽑아 저장한다.

        활성 슬롯은 사용자 결정(콤보 선택)대로:
          - 활성 종목 **보유 중** → 유지 (보호 — 새 후보가 와도 갈아타지 않음).
          - **미보유**(빈 슬롯/매도됨) → 새 후보 #1 종목을 활성으로 자동 지정.

        Returns:
            이후 로직에서 사용할 (갱신됐을 수 있는) 활성 슬롯 dict.
        """
        container = get_setting("short_term_candidates")
        if not candidates_need_refresh(container):
            return slot

        items = self.short_term_strategy.find_targets(n=SHORT_TERM_CANDIDATE_COUNT)
        set_setting("short_term_candidates", candidates_to_settings(items))
        if not items:
            log("[단타] 후보 재선정 — 조건 통과 종목 없음 (다음 주기 재시도)")
            return slot

        names = ", ".join(f"{c['종목명']}({c['종목코드']})" for c in items)
        log(f"[단타] 후보 {len(items)}종 재선정: {names}")

        active_code = slot.get("code")
        held_active = bool(active_code) and active_code in holdings
        if held_active:
            log(f"[단타] 활성 종목 {active_code} 보유 중 — 유지 (후보 목록만 갱신)")
            return slot

        # 미보유 — 새 후보 #1 을 활성으로 자동 지정 (예산 풀은 이월)
        new_slot = target_to_settings(
            items[0],
            auto_enabled=bool(slot.get("auto_enabled", False)),
            last_realized_amount=slot.get("last_realized_amount"),
        )
        set_setting("short_term_trade", new_slot)
        log(
            f"[단타] 활성 종목 자동 지정(미보유 슬롯): "
            f"{new_slot['name']}({new_slot['code']}) - {new_slot.get('selection_reason', '')}"
        )
        return new_slot

    def _short_term_switch(self, slot: dict, holdings: dict, auto_enabled: bool) -> None:
        """사용자 '교체' 선택 처리 — 이전 보유 종목 전량 매도 후 대기 후보로 전환.

        이전 종목을 보유 중이면 시장가로 전량 매도하고 회수 금액을 다음 매수 예산 상한으로
        이월한다. 장 시간 외에는 매도가 불가능하므로 다음 개장 후 사이클에서 재시도한다
        (`pending_action` 유지). 매도가 필요 없으면(미보유) 즉시 전환한다.
        """
        pending = slot.get("pending_target")
        active_code = slot.get("code")
        active_name = slot.get("name") or active_code
        realized = slot.get("last_realized_amount")  # 매도 없으면 직전 값 이월

        held = holdings.get(active_code) if active_code else None
        if held:
            if not is_trading_time():
                log("[단타] 교체 예약됨 — 장 시간 외, 개장 후 이전 보유 매도 진행")
                return
            qty = held["qty"]
            try:
                price = get_current_price(active_code)
            except Exception as e:
                log(f"[단타] 교체용 가격 조회 실패 ({active_name}): {e}")
                return
            log(f"[단타] 교체 — 이전 보유 {active_name}({active_code}) {qty}주 전량 시장가 매도")
            try:
                sell_market_order(active_code, qty)
                self.log_trade(
                    "sell", active_code, active_name, price, qty,
                    reason="[단타] 사용자 교체 — 이전 종목 전량 매도",
                )
                realized = float(price) * int(qty)
                log(f"[단타] 교체 매도 회수 ≈ {realized:,.0f}원 → 새 종목 매수 예산 상한으로 이월")
            except Exception as e:
                log(f"[단타] 교체 매도 실패 ({active_name}): {e}")
                return

        new_slot = target_to_settings(
            pending,
            auto_enabled=auto_enabled,
            last_realized_amount=realized,
        )
        set_setting("short_term_trade", new_slot)
        log(
            f"[단타] 교체 완료 → 새 종목: {new_slot['name']}({new_slot['code']}) - "
            f"{new_slot.get('selection_reason', '')}"
        )

    # ── 매도 체크 ──────────────────────────────────────────────────────────────

    def check_and_sell(self) -> None:
        """보유 종목 가격 확인 후 SellStrategy 판단에 따라 매도"""
        holdings = get_holdings()

        if not holdings:
            log("보유 종목 없음")
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

        # 기존 보유 종목 초기화 (재시작 시 false-positive 매수 감지 방지)
        try:
            initial = get_holdings()
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

        candidates = self.scan_buy_candidates()
        if is_trading_time():
            self.execute_initial_buy(candidates)
        else:
            log("[초기매수] 장 운영 시간 외 - 다음 개장 후 실행")

        did_initial_buy = is_trading_time()

        while True:
            self._sync_sell_settings()
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
                    log(f"[단타] 처리 중 오류: {e}")
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
                holdings = get_holdings()
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
