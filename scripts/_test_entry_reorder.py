"""지정가 부분 체결 재주문 · 진입 마감 시각 검증 (API 호출 없음).

검증 대상
  1. 주문 '닫힘' 판정 — 미체결 0 ∧ 체결 + 취소 == 주문 (2026-08-26 실제 응답 행 포함)
  2. 2026-08-26 재현 — 25주 중 1주만 체결 → 잔량 취소 → 같은 주기에 나머지를 다시 산다
  3. 2026-09-30 재현 — 0주 체결로 걸려 있던 주문 → 취소 → 재주문
  4. 조회와 취소 사이에 체결된 물량을 놓치지 않는가 (원장 == 실제 잔고)
  5. 체결이 확정되지 않으면 재주문하지 않는가 (이중 매수 방지)
  6. 재주문 횟수 상한 · 목표 미달 경고 · 시장가는 1회
  7. 진입 마감 시각 — 경계값 · 지연과의 관계 · 마감 후 청산은 계속 · 사용자 교체 예외
"""
import sys
from contextlib import ExitStack
from datetime import datetime
from unittest.mock import patch

from core import kis_api as k
from core import trader as tr
from core.short_term import (
    allow_late_entry, entry_intent, invested_amount, late_entry_allowed, position_qty,
)

fails = []


def check(name, cond, detail=""):
    print(f"  {'✅' if cond else '❌'} {name}" + (f" — {detail}" if detail else ""))
    if not cond:
        fails.append(name)


CODE = "102110"
BASE = {"code": CODE, "name": "TIGER 200", "auto_enabled": True, "qty": 0,
        "entry_price": None, "invested": None, "entry_at": None, "peak": None}


class Broker:
    """주문·체결·취소를 흉내 내는 가짜 증권사. 주문마다 시나리오(plan)를 하나씩 소비한다.

    plan 키
      fill               주문 즉시 체결되는 수량 (기본: 전량)
      fill_price         체결 단가 (기본: 주문 단가)
      fill_before_cancel 체결 조회 뒤 · 취소 직전에 추가로 체결되는 수량
      cancel_rejected    취소가 거부되고 주문이 그대로 살아 있다
      lookup_fails       체결 조회가 None 을 돌려준다
      raise_on_order     주문은 접수됐지만 응답이 실패한다
      fee                취소 행이 생기기 전까지만 조회되는 제비용
    """

    def __init__(self, plans):
        self.plans = list(plans)
        self.orders = []
        self.held = 0
        self.cancels = []

    def _find(self, odno):
        return next(o for o in self.orders if o["odno"] == odno)

    def _fill(self, order, n):
        order["filled"] += n
        self.held += n

    def buy(self, code, qty, price=None):
        plan = self.plans[len(self.orders)] if len(self.orders) < len(self.plans) else {}
        order = {"odno": f"{len(self.orders) + 1:010d}", "qty": qty, "price": price,
                 "filled": 0, "cancelled": 0, "plan": plan,
                 "fill_price": plan.get("fill_price", price or 107_170)}
        self.orders.append(order)
        self._fill(order, min(qty, plan.get("fill", qty)))
        if plan.get("raise_on_order"):
            raise TimeoutError("응답 타임아웃")
        return {"output": {"ODNO": order["odno"], "KRX_FWDG_ORD_ORGNO": "91252"}}

    def execution(self, odno, code, side, date=None):
        order = self._find(odno)
        if order["plan"].get("lookup_fails"):
            return None
        fee = order["plan"].get("fee", 0.0) if not order["cancelled"] else 0.0
        return {
            "주문번호": odno, "주문수량": order["qty"], "체결수량": order["filled"],
            "체결평균가": order["fill_price"] if order["filled"] else 0.0,
            "총체결금액": float(order["filled"] * order["fill_price"]),
            "미체결수량": order["qty"] - order["filled"] - order["cancelled"],
            "취소수량": order["cancelled"], "추정제비용": fee, "제비용신뢰": bool(fee),
        }

    def cancel(self, odno, org_no, **kwargs):
        order = self._find(odno)
        self.cancels.append(odno)
        remaining = order["qty"] - order["filled"] - order["cancelled"]
        self._fill(order, min(order["plan"].get("fill_before_cancel", 0), remaining))
        if order["plan"].get("cancel_rejected"):
            raise RuntimeError("취소 거부")
        remaining = order["qty"] - order["filled"] - order["cancelled"]
        if remaining <= 0:
            raise RuntimeError("APBK0915 취소 가능 수량 없음")
        order["cancelled"] = remaining

    def holdings(self):
        return {CODE: {"qty": self.held, "avg_price": 107_170}} if self.held else {}


BOOK = [(107_170, 40), (107_175, 30), (107_180, 50), (107_185, 10), (107_190, 10)]


def run(plans, pool=2_730_000, price=107_170, limit=True, books=None):
    """`_short_term_enter` 를 가짜 증권사 위에서 한 번 실행한다."""
    broker = Broker(plans)
    store = {"short_term_trade": dict(BASE)}
    logs, trades = [], []
    book_calls = []

    def orderbook(code, depth=5):
        book_calls.append(1)
        seq = books or [BOOK]
        return {"매도호가": seq[min(len(book_calls), len(seq)) - 1]}

    trader = tr.Trader.__new__(tr.Trader)
    trader.log_trade = lambda *a, **kw: trades.append(a)
    with ExitStack() as stack:
        for target, attr, value in [
            (tr, "get_setting", lambda key: store.get(key)),
            (tr, "set_setting", lambda key, v: store.__setitem__(key, v)),
            (tr, "log", lambda msg, *a, **kw: logs.append(msg)),
            (tr, "short_term_pool", lambda: pool),
            (tr, "use_limit_buy", lambda: limit),
            (tr, "get_holdings", broker.holdings),
            (tr, "get_orderbook", orderbook),
            (tr, "get_orderable_cash", lambda code, price=0, market_order=True: {
                "최대매수수량": 10_000, "주문가능현금": 10_000_000, "계산단가": price}),
            (tr, "buy_limit_order", broker.buy),
            (tr, "buy_market_order", broker.buy),
            (tr, "get_order_execution", broker.execution),
            (tr, "cancel_order", broker.cancel),
            (tr.time, "sleep", lambda s: None),
        ]:
            stack.enter_context(patch.object(target, attr, value))
        trader._short_term_enter(dict(BASE), price, "상승 판정")
    return broker, store["short_term_trade"], logs, trades, trader


def qtys(broker):
    return [o["qty"] for o in broker.orders]


print("── 1. 주문 '닫힘' 판정 ──")


def closed(ordered, filled, remaining, cancelled):
    info = {"주문수량": ordered, "체결수량": filled, "미체결수량": remaining, "취소수량": cancelled,
            "체결평균가": 107_170.0, "총체결금액": filled * 107_170.0, "추정제비용": 0.0}
    return tr._fill_from_execution(info, "buy", 107_170, ordered)["closed"]


check("전량 체결 → 닫힘", closed(28, 28, 0, 0))
check("부분 체결 후 잔량 취소 → 닫힘 (08-26: 25/1/취소 24)", closed(25, 1, 0, 24))
check("걸려 있는 주문 → 열림", not closed(28, 0, 28, 0))
check("부분 체결 · 잔량 살아 있음 → 열림", not closed(25, 1, 24, 0))
check("미체결 0 이어도 취소 행이 없으면 열림 (등식 불일치)", not closed(25, 1, 0, 0))

# 2026-08-26 실제 응답 행 (inquire-daily-ccld, 개인정보 필드 제외)
ROWS_0826 = [
    {"odno": "0004789000", "orgn_odno": "0004787200", "ord_qty": "24", "tot_ccld_qty": "0",
     "avg_prvs": "0", "tot_ccld_amt": "0", "rmn_qty": "0", "rjct_qty": "0"},
    {"odno": "0004787200", "orgn_odno": "", "ord_qty": "25", "tot_ccld_qty": "1",
     "avg_prvs": "107170", "tot_ccld_amt": "107170", "rmn_qty": "0", "rjct_qty": "0"},
]
with patch.object(k, "_request", return_value={"output1": ROWS_0826, "output2": {}}):
    info = k.get_order_execution("0004787200", CODE, "buy")
check("실제 응답에서 주문 25 · 체결 1 · 취소 24 를 읽는다",
      (info["주문수량"], info["체결수량"], info["취소수량"], info["미체결수량"]) == (25, 1, 24, 0),
      str(info))
check("그 주문은 닫힘으로 판정", tr._fill_from_execution(info, "buy", 107_170, 25)["closed"])
rejected = [dict(ROWS_0826[0], rjct_qty="24"), dict(ROWS_0826[1], rmn_qty="24")]
with patch.object(k, "_request", return_value={"output1": rejected, "output2": {}}):
    info = k.get_order_execution("0004787200", CODE, "buy")
check("거부된 취소는 취소수량에 넣지 않는다", info["취소수량"] == 0 and info["미체결수량"] == 24)

print("\n── 2. 2026-08-26 재현 — 25주 중 1주만 체결 ──")
# 09:05:14 지정가 25주 × 107,170원 → 1주 체결 → 09:05:16 잔량 24주 취소. 자금 풀 273만원.
later_book = [(107_175, 5), (107_180, 20), (107_185, 30), (107_190, 40), (107_195, 40)]
broker, slot, logs, trades, _ = run(
    [{"fill": 1}, {"fill_price": 107_180}], books=[BOOK, later_book])
check("주문 2건 — 25주, 이어서 남은 예산으로 24주", qtys(broker) == [25, 24], str(qtys(broker)))
check("첫 주문 잔량을 취소했다", broker.cancels == ["0000000001"], str(broker.cancels))
check("재주문 단가는 새 호가창의 가장 깊은 호가", broker.orders[1]["price"] == 107_195,
      str(broker.orders[1]["price"]))
check("원장에 25주 전부 기록", position_qty(slot) == 25, f"{position_qty(slot)}주")
check("원장 수량 == 실제 잔고 (원장 밖 물량 없음)", position_qty(slot) == broker.held)
want_invested = 107_170 + 24 * 107_180
check("투입액 = 두 주문 체결금액의 합", invested_amount(slot) == want_invested,
      f"{invested_amount(slot):,.0f} vs {want_invested:,.0f}")
check("진입가 = 가중 평균 체결가", abs(slot["entry_price"] - want_invested / 25) < 1e-6,
      f"{slot['entry_price']:,.2f}")
check("상한(107,195)이 아니라 걸려 있던 호가(107,180)에 체결", slot["entry_price"] < 107_195)
check("진입 의도 정리", entry_intent(slot) is None)
check("이력은 1건 (25주)", len(trades) == 1 and trades[0][4] == 25, str(trades))
check("유휴 경고 없음", not any("유휴" in m for m in logs))
check("재주문 전 유휴였을 금액의 대부분이 투입됨",
      invested_amount(slot) / 2_730_000 > 0.97, f"{invested_amount(slot) / 2_730_000:.1%}")

print("\n── 3. 2026-09-30 재현 — 0주 체결로 걸려 있던 주문 ──")
# 09:05:45 지정가 28주 × 111,065원 → 가격이 111,315원까지 올라 체결되지 않음.
book_0930 = [(111_065, 40), (111_070, 10), (111_075, 10), (111_080, 10), (111_085, 10)]
moved = [(111_315, 30), (111_320, 30), (111_325, 30), (111_330, 30), (111_335, 30)]
broker, slot, logs, trades, _ = run(
    [{"fill": 0}, {"fill_price": 111_315}], pool=3_204_105, price=111_065,
    books=[book_0930, moved])
check("주문 2건 — 28주 미체결 취소 후 28주 재주문", qtys(broker) == [28, 28], str(qtys(broker)))
check("걸려 있던 주문을 취소했다", broker.cancels == ["0000000001"])
check("원장에 28주 기록 · 실제 잔고와 일치", position_qty(slot) == 28 == broker.held,
      f"원장 {position_qty(slot)} · 잔고 {broker.held}")
check("진입가는 실제 체결가(111,315)", slot["entry_price"] == 111_315)

print("\n── 4. 조회와 취소 사이에 체결된 물량 ──")
broker, slot, logs, trades, _ = run(
    [{"fill": 1, "fill_before_cancel": 4}, {}], books=[BOOK, later_book])
check("첫 주문 최종 체결은 5주 (조회 시점 1주 + 취소 직전 4주)", broker.orders[0]["filled"] == 5)
check("재주문은 5주어치를 뺀 예산으로", qtys(broker) == [25, 20], str(qtys(broker)))
check("원장 == 실제 잔고 (25주)", position_qty(slot) == broker.held == 25,
      f"원장 {position_qty(slot)} · 잔고 {broker.held}")

broker, slot, logs, trades, _ = run([{"fill": 1, "fill_before_cancel": 24}])
check("취소 직전 전량 체결 → 취소는 실패해도 재조회로 25주 확정", position_qty(slot) == 25)
check("이 경우 재주문하지 않는다", qtys(broker) == [25], str(qtys(broker)))

broker, slot, logs, trades, _ = run([{"fill": 1, "fee": 15.0}, {"fill_price": 107_180}],
                                    books=[BOOK, later_book])
check("취소 전에 확인한 제비용은 투입액에 남는다",
      invested_amount(slot) == want_invested + 15, f"{invested_amount(slot):,.0f}")

print("\n── 5. 체결 미확정이면 재주문하지 않는다 ──")
broker, slot, logs, trades, _ = run([{"fill": 1, "cancel_rejected": True}])
check("취소가 거부돼 주문이 살아 있으면 재주문 없음", qtys(broker) == [25], str(qtys(broker)))
check("원장에 쓰지 않고 진입 의도를 남긴다",
      position_qty(slot) == 0 and entry_intent(slot) is not None)
trader2 = tr.Trader.__new__(tr.Trader)
store = {}
with patch.object(tr, "set_setting", lambda key, v: store.__setitem__(key, v)), \
     patch.object(tr, "log", lambda *a, **kw: None):
    after = trader2._reconcile_short_term_ledger(slot, broker.holdings())
check("다음 주기에 잔고 증가분(1주)을 편입", position_qty(after) == 1 == broker.held)

broker, slot, logs, trades, _ = run([{"lookup_fails": True}])
check("체결 조회 실패 → 잔량 취소 · 재주문 없음 · 의도 유지",
      qtys(broker) == [25] and broker.cancels == ["0000000001"]
      and position_qty(slot) == 0 and entry_intent(slot) is not None)

broker, slot, logs, trades, _ = run([{"fill": 1}, {"lookup_fails": True}],
                                    books=[BOOK, later_book])
check("재주문의 체결이 미확정이면 확정분(1주)도 원장에 직접 쓰지 않는다",
      position_qty(slot) == 0 and entry_intent(slot) is not None and not trades)
with patch.object(tr, "set_setting", lambda key, v: store.__setitem__(key, v)), \
     patch.object(tr, "log", lambda *a, **kw: None):
    after = trader2._reconcile_short_term_ledger(slot, broker.holdings())
check("다음 주기 잔고 정산이 전부(25주) 편입 — 원장 밖 물량 없음",
      position_qty(after) == broker.held == 25, f"원장 {position_qty(after)} · 잔고 {broker.held}")

broker, slot, logs, trades, _ = run([{"fill": 1}, {"raise_on_order": True}],
                                    books=[BOOK, later_book])
check("재주문 응답 실패 → 더 주문하지 않고 의도 유지",
      qtys(broker) == [25, 24] and position_qty(slot) == 0 and entry_intent(slot) is not None)
with patch.object(tr, "set_setting", lambda key, v: store.__setitem__(key, v)), \
     patch.object(tr, "log", lambda *a, **kw: None):
    after = trader2._reconcile_short_term_ledger(slot, broker.holdings())
check("응답은 실패했지만 체결된 24주까지 다음 주기에 편입", position_qty(after) == broker.held == 25)

print("\n── 6. 횟수 상한 · 목표 미달 · 시장가 ──")
broker, slot, logs, trades, _ = run([{"fill": 0}, {"fill": 0}, {"fill": 0}, {}])
check(f"전부 미체결이면 {tr.ENTRY_MAX_ROUNDS}회에서 멈춘다",
      len(broker.orders) == tr.ENTRY_MAX_ROUNDS, f"{len(broker.orders)}건")
check("주문을 전부 취소했다", len(broker.cancels) == tr.ENTRY_MAX_ROUNDS and broker.held == 0)
check("체결 없음이 확인됐으니 의도를 지워 다음 주기에 재시도",
      position_qty(slot) == 0 and entry_intent(slot) is None)

broker, slot, logs, trades, _ = run([{"fill": 1}, {"fill": 1}, {"fill": 1}, {}])
check("부분 체결이 이어져도 상한에서 멈추고 체결분을 확정",
      len(broker.orders) == tr.ENTRY_MAX_ROUNDS and position_qty(slot) == 3 == broker.held)
check("목표 미달은 유휴 금액과 함께 경고한다", any("⚠️" in m and "유휴" in m for m in logs),
      next((m for m in logs if "유휴" in m), "로그 없음"))

broker, slot, logs, trades, _ = run([{"fill": 1}, {}], books=[BOOK, []])
check("재주문용 호가가 없으면 낡은 가격으로 주문하지 않고 체결분만 확정",
      qtys(broker) == [25] and position_qty(slot) == 1)

broker, slot, logs, trades, _ = run([{"fill": 25}])
check("첫 주문이 전량 체결되면 주문 1건 · 취소 없음 (평소 경로 불변)",
      qtys(broker) == [25] and broker.cancels == [] and position_qty(slot) == 25)

broker, slot, logs, trades, _ = run([{"fill": 10}, {}], limit=False)
check("시장가 모드는 재주문하지 않는다", len(broker.orders) == 1, f"{len(broker.orders)}건")

print("\n── 7. 진입 마감 시각 ──")


def at(hh, mm, ss=0):
    return datetime(2026, 10, 12, hh, mm, ss)


with patch.object(tr, "short_term_buy_delay_min", return_value=5):
    check("09:29 은 진입 가능", not tr.short_term_entry_closed(at(9, 29)))
    check("09:30:00 정각까지 진입 가능", not tr.short_term_entry_closed(at(9, 30)))
    check("09:30:01 부터 마감", tr.short_term_entry_closed(at(9, 30, 1)))
    check("14:00 은 마감 (오후에 자동매매를 켜도 진입 없음)", tr.short_term_entry_closed(at(14, 0)))
    check("개장 전(08:40)은 마감이 아니다", not tr.short_term_entry_closed(at(8, 40)))
    check("지연 5분이면 마감은 09:30", tr.short_term_entry_deadline(at(9, 0)) == at(9, 30))
with patch.object(tr, "short_term_buy_delay_min", return_value=45):
    check("지연 45분이면 마감이 09:55 로 밀린다 (창이 통째로 닫히지 않음)",
          tr.short_term_entry_deadline(at(9, 0)) == at(9, 55)
          and not tr.short_term_entry_closed(at(9, 50)))

check("교체 표시는 당일에만 유효",
      late_entry_allowed(allow_late_entry(BASE, at(14, 0)), at(15, 0))
      and not late_entry_allowed(allow_late_entry(BASE, at(14, 0)), datetime(2026, 10, 13, 9, 0)))


def cycle(slot, held_qty, closed_now):
    """`check_short_term` 한 주기 — (시세 조회 횟수, 진입 호출 횟수, 청산 판정 횟수)."""
    store = {"short_term_trade": dict(slot)}
    calls = {"snapshot": 0, "enter": 0, "sell": 0}
    trader = tr.Trader.__new__(tr.Trader)

    class Strategy:
        def should_buy(self, s, snap):
            return True, "상승"

        def should_sell(self, s, price):
            calls["sell"] += 1
            return type("D", (), {"sell": False})()

    trader.short_term_strategy = Strategy()
    holdings = {CODE: {"qty": held_qty, "avg_price": 107_170}} if held_qty else {}

    def snapshot(code):
        calls["snapshot"] += 1
        return {"현재가": 107_170}

    with patch.object(tr, "get_setting", lambda key: store.get(key)), \
         patch.object(tr, "set_setting", lambda key, v: store.__setitem__(key, v)), \
         patch.object(tr, "log", lambda *a, **kw: None), \
         patch.object(tr, "get_holdings", lambda: holdings), \
         patch.object(tr, "get_quote_snapshot", snapshot), \
         patch.object(tr, "short_term_buy_window_open", return_value=True), \
         patch.object(tr, "short_term_entry_closed", return_value=closed_now), \
         patch.object(trader, "_sync_short_term_settings", lambda: None), \
         patch.object(trader, "_short_term_refresh_candidates", lambda s, g: s), \
         patch.object(trader, "_short_term_enter",
                      lambda *a, **kw: calls.__setitem__("enter", calls["enter"] + 1)):
        trader.check_short_term()
    return calls


c = cycle(BASE, 0, closed_now=False)
check("마감 전 미보유 → 진입", c["enter"] == 1, str(c))
c = cycle(BASE, 0, closed_now=True)
check("마감 후 미보유 → 진입하지 않고 시세도 조회하지 않는다",
      c["enter"] == 0 and c["snapshot"] == 0, str(c))
c = cycle(allow_late_entry(BASE), 0, closed_now=True)
check("사용자가 교체한 종목은 마감 후에도 진입", c["enter"] == 1, str(c))
holding = {**BASE, "qty": 25, "entry_price": 107_170, "invested": 2_679_250.0,
           "entry_at": datetime(2026, 10, 12, 9, 5).isoformat(), "peak": 107_170}
c = cycle(holding, 25, closed_now=True)
check("마감 후에도 보유 포지션의 청산 판정은 계속 돈다",
      c["sell"] == 1 and c["enter"] == 0, str(c))

print()
if fails:
    print(f"❌ 실패 {len(fails)}건: {fails}")
    sys.exit(1)
print("✅ 전부 통과")
