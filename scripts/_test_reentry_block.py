"""재진입 차단 규칙 검증 — 그날 산 포지션의 손실성 청산만 막는가 (API 호출 없음).

검증 대상
  1. `blocks_reentry` — 사유 × 진입일 조합 · 진입일 미상 fallback
  2. 2026-10-19 재현 — 전 거래일 TIGER 200 이 개장 갭으로 최고가 청산(보유기간 만료와 동시)
     → 차단하지 않는다
  3. 트레이더 사이클 — 전일분 청산이면 오늘 후보(인버스)로 갈아타고 다음 주기에 진입,
     오늘 산 포지션의 손실성 청산이면 기존대로 차단

시각에 의존하지 않는다 — 코드 갱신 게이트는 08:20 부팅 때 돈다. 진입일은 실행 시각 기준
상대값으로 만들고, 시각이 걸리는 판정(매수 창 · 진입 마감)은 patch 한다.
"""
import sys
from datetime import datetime, timedelta
from unittest.mock import patch

from core import trader as tr
from core.short_term import (
    SELL_HOLDING_PERIOD,
    SELL_MARKET_END,
    SELL_PEAK_DROP,
    SELL_STOP_LOSS,
    EtfDayTradeStrategy,
    SellDecision,
    blocks_reentry,
    is_blocked,
    position_qty,
)

fails = []


def check(name, cond, detail=""):
    print(f"  {'✅' if cond else '❌'} {name}" + (f" — {detail}" if detail else ""))
    if not cond:
        fails.append(name)


def slot_entered(at: datetime | None) -> dict:
    return {"entry_at": at.isoformat() if at else None}


NOW = datetime(2026, 10, 19, 9, 0, 18)
FRI = datetime(2026, 10, 16, 9, 5, 30)          # 주말을 건넌 전 거래일

print("── 1. blocks_reentry ──")
cases = [
    (SELL_HOLDING_PERIOD, FRI, False, "보유기간 만료 → 재진입"),
    (SELL_PEAK_DROP, NOW.replace(hour=10), True, "오늘 산 포지션 최고가 청산 → 차단"),
    (SELL_STOP_LOSS, NOW.replace(hour=9, minute=5), True, "오늘 산 포지션 손절 → 차단"),
    (SELL_MARKET_END, NOW.replace(hour=9, minute=5), True, "오늘 산 포지션 마감 청산 → 차단"),
    (SELL_PEAK_DROP, NOW - timedelta(days=1), False, "어제 산 포지션 최고가 청산 → 재진입"),
    (SELL_STOP_LOSS, FRI, False, "금요일 포지션 월요일 개장 손절 → 재진입"),
]
for kind, entered, expect, label in cases:
    got = blocks_reentry(SellDecision(True, "", kind), slot_entered(entered), NOW)
    check(label, got is expect, f"{got}")
check("진입일 미상이면 보수적으로 차단",
      blocks_reentry(SellDecision(True, "", SELL_PEAK_DROP), slot_entered(None), NOW) is True)
check("진입일이 깨진 값이어도 차단",
      blocks_reentry(SellDecision(True, "", SELL_PEAK_DROP), {"entry_at": "garbage"}, NOW) is True)
check("보유기간 만료는 진입일 미상이어도 재진입",
      blocks_reentry(SellDecision(True, "", SELL_HOLDING_PERIOD), slot_entered(None), NOW) is False)

print("\n── 2. 2026-10-19 재현 ──")
# 실로그: 최고가 91,375원 대비 -5.55% (기준 -5.41% · σ 2.71%) → 35주 시장가 매도 (수익률 -2.86%)
TIGER = {"code": "102110", "name": "TIGER 200", "auto_enabled": True, "vol": 2.71,
         "entry_price": 88_844.0, "qty": 35, "invested": 3_109_530.0,
         "entry_at": FRI.isoformat(), "peak": 91_375.0, "blocked_date": None}
decision = EtfDayTradeStrategy().should_sell(TIGER, 86_304, now=NOW)
check("청산 판정 — 최고가 청산이 보유기간 만료보다 먼저 잡힌다", decision.sell and decision.kind == SELL_PEAK_DROP,
      decision.reason)
check("그래도 전 거래일 포지션이라 재진입 차단하지 않는다", blocks_reentry(decision, TIGER, NOW) is False)

print("\n── 3. 트레이더 사이클 ──")
INVERSE = {"종목코드": "114800", "종목명": "KODEX 인버스", "현재가": 1_241, "방향": "down",
           "변동성(%)": 2.81, "선정사유": "하락 판정"}
store: dict = {}
trader = tr.Trader.__new__(tr.Trader)
common = [
    patch.object(tr, "get_setting", side_effect=lambda k: store.get(k)),
    patch.object(tr, "set_setting", side_effect=lambda k, v: store.__setitem__(k, v)),
    patch.object(tr, "log", lambda *a, **k: None),
    patch.object(tr, "sell_market_order", return_value={"output": {"ODNO": "1"}}),
    patch.object(tr, "settle_order", side_effect=lambda r, code, side, price, qty: {
        "qty": qty, "price": price, "amount": price * qty, "fee": 0, "exact": True}),
    patch.object(tr, "apply_short_term_pnl", lambda *a, **k: 0),
    patch.object(trader, "log_trade", lambda *a, **k: None),
    patch.object(trader, "_short_term_pick_from_candidates", return_value=INVERSE),
]
for p in common:
    p.start()

# 실행 시각 기준 — 진입이 3일 전이면 전일분, 지금이면 오늘분
real_now = datetime.now()
carry = {**TIGER, "entry_at": (real_now - timedelta(days=3)).isoformat()}
trader._short_term_exit(carry, 86_304, decision, general={})
after = store["short_term_trade"]
check("전일분 청산 → 차단 안 함", not is_blocked(after), str(after.get("blocked_date")))
check("오늘 후보(인버스)로 갈아탄다", after.get("code") == "114800", str(after.get("code")))
check("포지션은 비워진다", position_qty(after) == 0)
check("자동매매 설정은 이어진다", after.get("auto_enabled") is True)

# 다음 주기 — 미보유 · 미차단이면 진입으로 간다
entered = []
with patch.object(trader, "_sync_short_term_settings", lambda: None), \
     patch.object(tr, "get_holdings", return_value={}), \
     patch.object(trader, "_short_term_refresh_candidates", side_effect=lambda s, g: s), \
     patch.object(tr, "get_quote_snapshot", return_value={"현재가": 1_241}), \
     patch.object(trader, "_short_term_enter", side_effect=lambda s, p, r: entered.append(s["code"])), \
     patch.object(tr, "short_term_buy_window_open", return_value=True), \
     patch.object(tr, "short_term_entry_closed", return_value=False):
    trader.short_term_strategy = type(
        "S", (), {"should_buy": lambda self, s, snap: (True, "인버스 ETF 진입")})()
    trader.check_short_term()
check("다음 주기에 인버스 진입 (10-19 에 막혔던 경로)", entered == ["114800"], str(entered))

store.clear()
same_day = {**TIGER, "entry_at": real_now.isoformat()}
peak_exit = SellDecision(True, "최고가 청산", SELL_PEAK_DROP)
trader._short_term_exit(same_day, 86_304, peak_exit, general={})
after = store["short_term_trade"]
check("오늘 산 포지션 최고가 청산 → 오늘 차단", is_blocked(after), str(after.get("blocked_date")))
check("차단 시 종목은 그대로 (후보로 갈아타지 않음)", after.get("code") == "102110")
check("포지션은 비워진다", position_qty(after) == 0)

for p in common:
    p.stop()

print()
if fails:
    print(f"❌ {len(fails)}건 실패: {fails}")
    sys.exit(1)
print("✅ 전부 통과")
