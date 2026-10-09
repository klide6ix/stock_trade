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
     patch.object(tr, "short_term_buy_window_open", return_value=True):
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
                                                    "fee": 130, "remaining": 0, "exact": True}), \
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
