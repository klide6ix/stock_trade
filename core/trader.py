import json
import os
import time
from datetime import datetime

from config import CHECK_INTERVAL
from core.kis_api import (
    get_holdings,
    get_current_price,
    sell_market_order,
    buy_market_order,
    get_cash_balance,
)
from core.logger import log
from core.settings import get as get_setting
from core.strategy.base import BuyStrategy, SellStrategy

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA_DIR = os.path.join(_BASE_DIR, "data")
os.makedirs(_DATA_DIR, exist_ok=True)

BUY_CANDIDATES_FILE = os.path.join(_DATA_DIR, "buy_candidates.json")
TRADE_HISTORY_FILE = os.path.join(_DATA_DIR, "trade_history.json")


def plan_initial_buy(candidates: list[dict], cash: float, owned_codes: set[str]) -> list[dict]:
    """예수금을 후보 수(미보유 기준)로 균등 분할한 매수 계획 생성.

    슬롯 금액이 주가보다 작아도 최소 1주를 배정하고, 누적 예산을 초과하지 않도록
    순서대로 잔여 예수금을 차감한다. 보유 중인 종목은 제외.

    Returns:
        [{"종목코드", "종목명", "현재가", "수량", "예상금액"}] — 실제 주문 가능한 항목만
    """
    if not candidates or cash <= 0:
        return []

    targets = [c for c in candidates if c["종목코드"] not in owned_codes]
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
    """장 운영 시간 체크 (평일 09:00 ~ 15:30)"""
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    t = now.time()
    return datetime.strptime("09:00", "%H:%M").time() <= t <= datetime.strptime("15:30", "%H:%M").time()


class Trader:
    def __init__(self, buy_strategy: BuyStrategy, sell_strategy: SellStrategy) -> None:
        self.buy_strategy = buy_strategy
        self.sell_strategy = sell_strategy
        self._known_holdings: set[str] = set()

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
        """BuyStrategy 로 매수 후보 탐색 후 buy_candidates.json 저장."""
        strategy_name = type(self.buy_strategy).__name__
        log(f"[매수후보] 탐색 시작 ({strategy_name})")
        try:
            candidates = self.buy_strategy.find_candidates()
            with open(BUY_CANDIDATES_FILE, "w", encoding="utf-8") as f:
                json.dump(
                    {"updated_at": datetime.now().isoformat(), "candidates": candidates},
                    f, ensure_ascii=False, indent=2,
                )
            names = ", ".join(c["종목명"] for c in candidates)
            log(f"[매수후보] 탐색 완료: {names}")
            return candidates
        except Exception as e:
            log(f"[매수후보] 탐색 실패: {e}")
            return []

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
        """예수금을 후보 수만큼 균등 분할하여 각 후보를 시장가 매수."""
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
        plan = plan_initial_buy(candidates, cash, owned)

        if not plan:
            log("[초기매수] 실행 가능한 주문 없음 - 스킵")
            return

        log(f"[초기매수] 주문가능금액 {cash:,.0f}원 / {len(plan)}종목 주문 예정")
        for item in plan:
            log(f"[초기매수] {item['종목명']}({item['종목코드']}) {item['수량']}주 × {item['현재가']:,.0f}원 ≈ {item['예상금액']:,.0f}원")
            self._place_buy(item["종목코드"], item["종목명"], item["수량"])

    def execute_post_sell_buy(self, sold_code: str) -> None:
        """매도 발생 시 후보 재탐색 후 미보유 최상위 1종목을 남은 예수금으로 매수."""
        if not get_setting("buy_enabled"):
            log(f"[매도후재매수] 매수 옵션 OFF - 스킵 ({sold_code} 매도 후)")
            return

        log(f"[매도후재매수] {sold_code} 매도 감지 - 후보 재탐색")
        candidates = self.scan_buy_candidates()
        if not candidates:
            return

        holdings = get_holdings()
        for c in candidates:
            code = c["종목코드"]
            if code == sold_code or code in holdings:
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
                self.sell_strategy.on_buy(code, buy_price)

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
                log(f"[{name}({code})] ★ 매도 조건 충족 ({reason}) → 매도 주문 실행")
                try:
                    result = sell_market_order(code, qty)
                    log(f"[{name}({code})] 매도 완료: {result}")
                    self.log_trade("sell", code, name, price, qty, reason=reason)
                    self.execute_post_sell_buy(code)
                except Exception as e:
                    log(f"[{name}({code})] 매도 실패: {e}")

    # ── 메인 루프 ──────────────────────────────────────────────────────────────

    def run(self) -> None:
        log(f"트레이더 시작 | 매수전략: {type(self.buy_strategy).__name__} | 매도전략: {type(self.sell_strategy).__name__} | 확인 주기: {CHECK_INTERVAL // 60}분")

        self.sell_strategy.load()

        # 기존 보유 종목 초기화 (재시작 시 false-positive 매수 감지 방지)
        try:
            initial = get_holdings()
            self._known_holdings.update(initial.keys())
            for code, info in initial.items():
                if info["avg_price"] > 0:
                    self.sell_strategy.on_buy(code, info["avg_price"])
            if initial:
                log(f"[초기화] 기존 보유 종목 {len(initial)}개 확인 완료")
        except Exception as e:
            log(f"[초기화] 보유 종목 조회 실패: {e}")

        candidates = self.scan_buy_candidates()
        if is_market_open():
            self.execute_initial_buy(candidates)
        else:
            log("[초기매수] 장 운영 시간 외 - 다음 개장 후 실행")

        did_initial_buy = is_market_open()

        while True:
            if is_market_open():
                if not did_initial_buy:
                    self.execute_initial_buy(candidates)
                    did_initial_buy = True
                try:
                    self.check_and_sell()
                except Exception as e:
                    log(f"오류 발생: {e}")
            else:
                log("장 운영 시간 외 - 대기 중")

            time.sleep(CHECK_INTERVAL)
