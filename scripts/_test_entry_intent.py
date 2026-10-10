"""진입 의도(write-ahead) · 설정 저장 원자성 검증 (API 호출 없음).

검증 대상
  1. `resolve_entry_intent` — 잔고 증가분 편입 / 대기 / 만료
  2. 2026-09-30 재현 — 주문은 체결됐는데 응답이 실패해도 다음 주기에 원장에 편입되고,
     그 사이 추가 주문이 나가지 않는가
  3. 원장 확정이 이력 저장보다 먼저인가 (log_trade 예외에도 포지션을 잃지 않는다)
  4. `set_value` 잠금 — 두 프로세스가 동시에 써도 서로의 변경을 되돌리지 않는가
"""
import multiprocessing as mp
import os
import sys
import tempfile
from datetime import datetime, timedelta
from unittest.mock import patch

from core import settings as cs
from core import trader as tr
from core.short_term import (
    ENTRY_INTENT_TTL_SEC, entry_intent, position_qty, resolve_entry_intent, with_entry_intent,
)

fails = []


def check(name, cond, detail=""):
    print(f"  {'✅' if cond else '❌'} {name}" + (f" — {detail}" if detail else ""))
    if not cond:
        fails.append(name)


NOW = datetime(2026, 9, 30, 9, 5, 46)
BASE = {"code": "102110", "name": "TIGER 200", "auto_enabled": True, "qty": 0,
        "entry_price": None, "invested": None, "entry_at": None, "peak": None}

print("── 1. resolve_entry_intent ──")
s0 = with_entry_intent(BASE, baseline_qty=0, planned_qty=28, price=111_065, now=NOW)
s, st = resolve_entry_intent(s0, {"102110": {"qty": 28, "avg_price": 111_080}}, NOW + timedelta(seconds=60))
check("잔고가 늘었으면 편입", st == "adopted" and position_qty(s) == 28, f"{st} {position_qty(s)}주")
check("주문 전 0주면 평단을 진입가로", s.get("entry_price") == 111_080)
check("진입 시각은 의도 시각", s.get("entry_at") == NOW.isoformat())
check("편입 후 의도는 지워진다", entry_intent(s) is None)

s1 = with_entry_intent(BASE, baseline_qty=6, planned_qty=10, price=110_000, now=NOW)
s, st = resolve_entry_intent(s1, {"102110": {"qty": 16, "avg_price": 120_000}}, NOW)
check("일반 보유와 섞이면 증가분만, 단가는 주문가", position_qty(s) == 10 and s["entry_price"] == 110_000,
      f"{position_qty(s)}주 @ {s['entry_price']:,.0f}")

s, st = resolve_entry_intent(s0, {}, NOW + timedelta(seconds=30))
check("TTL 전 잔고 변화 없음 → 대기 (의도 유지)", st == "waiting" and entry_intent(s) is not None)
s, st = resolve_entry_intent(s0, {}, NOW + timedelta(seconds=ENTRY_INTENT_TTL_SEC))
check("TTL 경과 → 만료 (의도 정리, 포지션 없음)", st == "expired" and entry_intent(s) is None
      and position_qty(s) == 0)
s, st = resolve_entry_intent({**s0, "qty": 28}, {}, NOW)
check("이미 원장에 포지션이 있으면 의도만 정리", st == "none" and entry_intent(s) is None)

print("\n── 2. 2026-09-30 재현 — 체결됐는데 응답 실패 ──")
store = {"short_term_trade": dict(BASE)}
held = {"qty": 0}
orders = []


def fake_holdings():
    return {"102110": {"qty": held["qty"], "avg_price": 111_080, "name": "TIGER 200"}} if held["qty"] else {}


def boom_order(code, qty, price):
    orders.append(qty)
    held["qty"] += qty            # 거래소에서는 체결됐다
    raise TimeoutError("응답 타임아웃")


trader = tr.Trader.__new__(tr.Trader)
common = [
    patch.object(tr, "get_setting", side_effect=lambda k: store.get(k)),
    patch.object(tr, "set_setting", side_effect=lambda k, v: store.__setitem__(k, v)),
    patch.object(tr, "get_holdings", side_effect=fake_holdings),
    patch.object(tr, "log", lambda *a, **k: None),
]
for p in common:
    p.start()
with patch.object(tr, "short_term_pool", return_value=3_100_000), \
     patch.object(tr, "use_limit_buy", return_value=True), \
     patch.object(tr, "pick_limit_buy_price", return_value=(111_065, "매도1호가")), \
     patch.object(tr, "plan_market_buy_qty", return_value=(28, "자금풀")), \
     patch.object(tr, "buy_limit_order", side_effect=boom_order):
    trader._short_term_enter(dict(BASE), 111_065, "상승 판정")

slot = store["short_term_trade"]
check("주문 1건 (28주)", orders == [28], str(orders))
check("응답 실패 후에도 의도가 남는다", entry_intent(slot) is not None)
check("원장에는 아직 포지션 없음", position_qty(slot) == 0)

# 다음 주기 — 정산이 진입보다 먼저
slot = trader._reconcile_short_term_ledger(slot, fake_holdings())
check("다음 주기에 28주가 원장에 편입된다", position_qty(store["short_term_trade"]) == 28,
      f"{position_qty(store['short_term_trade'])}주")
check("편입 후 의도 정리", entry_intent(store["short_term_trade"]) is None)

# 의도 대기 중에는 진입 분기가 주문하지 않는다
store["short_term_trade"] = with_entry_intent(dict(BASE), baseline_qty=0, planned_qty=28,
                                              price=111_065)
held["qty"] = 0
entered = []
with patch.object(trader, "_sync_short_term_settings", lambda: None), \
     patch.object(trader, "_short_term_refresh_candidates", side_effect=lambda s, g: s), \
     patch.object(tr, "get_quote_snapshot", return_value={"현재가": 111_065}), \
     patch.object(trader, "_short_term_enter", side_effect=lambda *a, **k: entered.append(1)), \
     patch.object(tr, "short_term_buy_window_open", return_value=True), \
     patch.object(tr, "short_term_entry_closed", return_value=False):
    trader.short_term_strategy = type("S", (), {"should_buy": lambda self, s, snap: (True, "상승")})()
    trader.check_short_term()
check("정산 대기 중에는 추가 주문이 나가지 않는다 (09:06:50 의 2주 매수 차단)", entered == [])

print("\n── 3. 원장 확정이 이력 저장보다 먼저 ──")
store["short_term_trade"] = dict(BASE)
held["qty"] = 0


def ok_order(code, qty, price):
    held["qty"] += qty
    return {"output": {"ODNO": "1"}}


with patch.object(tr, "short_term_pool", return_value=3_100_000), \
     patch.object(tr, "use_limit_buy", return_value=True), \
     patch.object(tr, "pick_limit_buy_price", return_value=(111_065, "매도1호가")), \
     patch.object(tr, "plan_market_buy_qty", return_value=(28, "자금풀")), \
     patch.object(tr, "buy_limit_order", side_effect=ok_order), \
     patch.object(tr, "settle_order", return_value={"qty": 28, "price": 111_065, "amount": 3_109_950,
                                                    "fee": 130, "remaining": 0, "exact": True,
                                                    "closed": True}), \
     patch.object(trader, "_cancel_remainder", lambda *a, **k: None), \
     patch.object(trader, "log_trade", side_effect=OSError("disk full")):
    try:
        trader._short_term_enter(dict(BASE), 111_065, "상승 판정")
    except OSError:
        pass
check("log_trade 가 예외를 내도 원장에 28주가 남는다",
      position_qty(store["short_term_trade"]) == 28 and entry_intent(store["short_term_trade"]) is None)
for p in common:
    p.stop()


print("\n── 3-b. 2026-09-30 실제 경로 — 지정가가 체결되지 않고 걸려 있던 경우 ──")
# 로그: 09:05:45 지정가 28주 × 111,065 → 09:05:48 '체결 확인 실패 — 28주로 근사'
#       → 09:06:49 '잔고에 없음 — 외부 청산' → 2주 재진입 → 이후 28주가 뒤늦게 체결.
with patch.object(tr.time, "sleep", lambda s: None), patch.object(tr, "log", lambda *a, **k: None):
    with patch.object(tr, "get_order_execution", return_value=None):
        f = tr.settle_order({"output": {"ODNO": "4072600"}}, "102110", "buy", 111_065, 28)
    check("매수 체결 확인 실패 → 체결로 가정하지 않음 (0주 · 잔량 28)",
          f["qty"] == 0 and f["remaining"] == 28 and not f["exact"], str(f))
    resting = {"체결수량": 0, "미체결수량": 28, "체결평균가": 0, "총체결금액": 0, "추정제비용": 0}
    with patch.object(tr, "get_order_execution", return_value=resting):
        f = tr.settle_order({"output": {"ODNO": "4072600"}}, "102110", "buy", 111_065, 28)
    check("걸려 있는 주문(0주 체결) → 잔량 28 로 보고", f["qty"] == 0 and f["remaining"] == 28, str(f))
    with patch.object(tr, "get_order_execution", return_value=None):
        f = tr.settle_order({"output": {"ODNO": "1"}}, "114800", "sell", 1_000, 300)
    check("매도(시장가)는 기존대로 주문 시점 값으로 근사", f["qty"] == 300 and not f["exact"])

store2 = {"short_term_trade": dict(BASE)}
held2 = {"qty": 0}
cancels = []


def holdings2():
    return {"102110": {"qty": held2["qty"], "avg_price": 111_065}} if held2["qty"] else {}


def run_entry(cancel_effect):
    with patch.object(tr, "get_setting", side_effect=lambda k: store2.get(k)), \
         patch.object(tr, "set_setting", side_effect=lambda k, v: store2.__setitem__(k, v)), \
         patch.object(tr, "get_holdings", side_effect=holdings2), \
         patch.object(tr, "log", lambda *a, **k: None), \
         patch.object(tr.time, "sleep", lambda s: None), \
         patch.object(tr, "short_term_pool", return_value=3_204_105), \
         patch.object(tr, "use_limit_buy", return_value=True), \
         patch.object(tr, "pick_limit_buy_price", return_value=(111_065, "매도1호가")), \
         patch.object(tr, "plan_market_buy_qty", return_value=(28, "자금풀")), \
         patch.object(tr, "buy_limit_order",
                      return_value={"output": {"ODNO": "4072600", "KRX_FWDG_ORD_ORGNO": "91252"}}), \
         patch.object(tr, "get_order_execution", return_value=None), \
         patch.object(tr, "cancel_order", side_effect=cancel_effect):
        trader._short_term_enter(dict(BASE), 111_050, "상승 판정")


trader2 = tr.Trader.__new__(tr.Trader)
trader = trader2
run_entry(lambda o, g, **k: cancels.append(o))
slot = store2["short_term_trade"]
check("걸려 있던 잔량을 취소한다", cancels == ["4072600"], str(cancels))
check("원장에는 기록하지 않고 진입 의도만 남긴다",
      position_qty(slot) == 0 and entry_intent(slot) is not None)

with patch.object(tr, "set_setting", side_effect=lambda k, v: store2.__setitem__(k, v)), \
     patch.object(tr, "log", lambda *a, **k: None):
    s_wait = trader2._reconcile_short_term_ledger(slot, holdings2())
check("1분 뒤 잔고 0 → '외부 청산' 이 아니라 정산 대기 (재진입 없음)",
      entry_intent(s_wait) is not None and position_qty(s_wait) == 0)

# 취소 직전에 체결돼 버린 경우 — 취소는 실패하고 잔고가 늘어난다
store2["short_term_trade"] = dict(BASE)
held2["qty"] = 0


def cancel_too_late(o, g, **k):
    held2["qty"] = 28
    raise RuntimeError("APBK0915 취소 가능 수량 없음")


run_entry(cancel_too_late)
with patch.object(tr, "set_setting", side_effect=lambda k, v: store2.__setitem__(k, v)), \
     patch.object(tr, "log", lambda *a, **k: None):
    trader2._reconcile_short_term_ledger(store2["short_term_trade"], holdings2())
check("취소 전에 체결됐으면 다음 주기에 28주 편입 (고아 없음)",
      position_qty(store2["short_term_trade"]) == 28
      and entry_intent(store2["short_term_trade"]) is None)

print("\n── 3-c. 진입 직후 '잔고에 없음' 유예 ──")
fresh = {**BASE, "qty": 28, "entry_price": 111_065, "entry_at": datetime.now().isoformat()}
stale = {**fresh, "entry_at": (datetime.now() - timedelta(minutes=10)).isoformat()}
out = {}
with patch.object(tr, "set_setting", side_effect=lambda k, v: out.__setitem__(k, v)), \
     patch.object(tr, "log", lambda *a, **k: None):
    r1 = trader2._reconcile_short_term_ledger(dict(fresh), {})
    r2 = trader2._reconcile_short_term_ledger(dict(stale), {})
check("진입 5분 이내면 잔고에 없어도 원장을 지우지 않는다", position_qty(r1) == 28)
check("유예가 지나면 기존대로 외부 청산으로 정리", position_qty(r2) == 0)


print("\n── 4. set_value 잠금 — 두 프로세스 동시 쓰기 ──")


def writer(path, key, n):
    cs.SETTINGS_FILE, cs._LOCK_FILE = path, path + ".lock"
    for i in range(n):
        cs.set_value(f"{key}_{i}", i)


tmpdir = tempfile.mkdtemp()
path = os.path.join(tmpdir, "settings.json")
ctx = mp.get_context("fork")   # spawn 은 이 테스트 모듈을 다시 실행한다
procs = [ctx.Process(target=writer, args=(path, k, 150)) for k in ("trader", "dashboard")]
for p in procs:
    p.start()
for p in procs:
    p.join()
cs.SETTINGS_FILE, cs._LOCK_FILE = path, path + ".lock"
final = cs.load_settings()
lost = [f"{k}_{i}" for k in ("trader", "dashboard") for i in range(150) if f"{k}_{i}" not in final]
check("동시 쓰기 300건 중 유실 0", not lost, f"유실 {len(lost)}건")
check("임시 파일이 남지 않는다", [f for f in os.listdir(tmpdir) if f.endswith(".tmp")] == [])

print()
if fails:
    print(f"❌ 실패 {len(fails)}건: {fails}")
    sys.exit(1)
print("✅ 전부 통과")
