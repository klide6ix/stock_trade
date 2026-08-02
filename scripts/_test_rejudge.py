"""장전 매분 재판정 + 개장 직후 최종 재판정 순수 로직 검증 (API 호출 없음).

검증 대상
  1. `keeps_previous_verdict` — 갭을 쓴 판정이 갭 없는 판정에 덮이지 않는가
  2. `open_rejudge_window`   — 개장 직후 재판정 창(평일 09:00~09:05) 경계
  3. `_short_term_refresh_candidates` — 사용자 선택 보존 · 오늘 차단 유지 · 불필요한 쓰기 생략
"""
import sys
from datetime import datetime
from unittest.mock import patch

from core import trader as tr
from core.short_term import keeps_previous_verdict

fails = []


def check(name, cond, detail=""):
    print(f"  {'✅' if cond else '❌'} {name}" + (f" — {detail}" if detail else ""))
    if not cond:
        fails.append(name)


NOW = datetime(2026, 8, 3, 8, 45)
TODAY = NOW.date().isoformat()


def container(gap_source, selected_at=TODAY + "T08:30:00"):
    return {"selected_at": selected_at, "items": [], "direction": {"gap_source": gap_source}}


def verdict(gap_source):
    return {"direction": "up", "score": 0.5, "gap_source": gap_source}


print("── 1. 갭 우선 규칙 (keeps_previous_verdict) ──")
check("새 판정이 갭을 썼으면 갱신",
      not keeps_previous_verdict(container("장전 예상체결가"), verdict("장중 실시간 등락률"), NOW))
check("새 판정에 갭이 없고 오늘 갭 판정이 있으면 유지",
      keeps_previous_verdict(container("장전 예상체결가"), verdict(None), NOW))
check("둘 다 갭이 없으면 갱신",
      not keeps_previous_verdict(container(None), verdict(None), NOW))
check("저장된 갭 판정이 어제 것이면 갱신",
      not keeps_previous_verdict(container("장전 예상체결가", "2026-08-02T08:30:00"), verdict(None), NOW))
check("컨테이너가 없으면 갱신",
      not keeps_previous_verdict(None, verdict(None), NOW))
check("컨테이너에 direction 이 없으면 갱신",
      not keeps_previous_verdict({"selected_at": TODAY + "T08:30:00", "items": []}, verdict(None), NOW))
check("selected_at 이 깨져 있으면 갱신",
      not keeps_previous_verdict(container("장전 예상체결가", "not-a-date"), verdict(None), NOW))

print("\n── 2. 개장 직후 재판정 창 (open_rejudge_window) ──")
for hhmm, expect in (("08:59", False), ("09:00", True), ("09:03", True),
                     ("09:05", True), ("09:06", False), ("14:00", False)):
    h, m = map(int, hhmm.split(":"))
    got = tr.open_rejudge_window(datetime(2026, 8, 3, h, m))
    check(f"평일 {hhmm} → {expect}", got == expect)
check("주말은 항상 False", not tr.open_rejudge_window(datetime(2026, 8, 1, 9, 1)))  # 토요일


print("\n── 3. 활성 슬롯 갱신 규칙 ──")


def item(code, name, reason="상승 판정"):
    return {"종목코드": code, "종목명": name, "선정사유": reason, "방향": "up"}


def refresh(slot, items, *, stored=None, quiet=True):
    """`_short_term_refresh_candidates` 를 settings·전략을 가짜로 물려 실행."""
    written = {}
    strategy = type("S", (), {"find_targets": lambda self, n, exclude_codes: (items, verdict("장전 예상체결가"))})()
    trader = tr.Trader.__new__(tr.Trader)
    trader.short_term_strategy = strategy

    def fake_get(key):
        return stored if key == "short_term_candidates" else None

    with patch.object(tr, "get_setting", side_effect=fake_get), \
         patch.object(tr, "set_setting", side_effect=lambda k, v: written.__setitem__(k, v)):
        result = trader._short_term_refresh_candidates(slot, {}, force=True, quiet=quiet)
    return result, written


A, B = item("069500", "KODEX 200"), item("102110", "TIGER 200")

# 사용자가 #2 를 골라 둔 상태 — 재판정해도 유지되어야 한다.
slot = {"code": "102110", "name": "TIGER 200", "selection_reason": "상승 판정",
        "auto_enabled": True, "qty": 0, "blocked_date": None}
result, written = refresh(slot, [A, B])
check("사용자 선택 종목이 후보에 남아 있으면 유지", result.get("code") == "102110", result.get("code"))
check("변화 없으면 settings 쓰기 생략", "short_term_trade" not in written, list(written))

# 방향이 뒤집혀 사용자 선택이 후보에서 사라짐 → #1 로 교체.
inv = item("114800", "KODEX 인버스", "하락 판정")
result, written = refresh(slot, [inv])
check("후보에서 사라지면 #1 로 교체", result.get("code") == "114800", result.get("code"))
check("교체 시 settings 기록", written.get("short_term_trade", {}).get("code") == "114800")
check("자동매매 플래그 보존", written["short_term_trade"]["auto_enabled"] is True)

# 오늘 손절로 차단된 상태에서 재판정 → 차단 유지.
blocked = {**slot, "code": "069500", "name": "KODEX 200",
           "blocked_date": datetime.now().date().isoformat()}
result, written = refresh(blocked, [inv])
check("오늘 진입 차단은 재판정으로 풀리지 않음",
      written["short_term_trade"]["blocked_date"] == datetime.now().date().isoformat(),
      str(written["short_term_trade"]["blocked_date"]))

# 어제 차단은 해제.
stale_block = {**slot, "code": "069500", "name": "KODEX 200", "blocked_date": "2026-08-02"}
result, written = refresh(stale_block, [inv])
check("어제 차단은 해제", written["short_term_trade"]["blocked_date"] is None)

# 포지션 보유 중이면 슬롯 유지 (후보 목록만 갱신).
held = {**slot, "code": "069500", "name": "KODEX 200", "qty": 10, "entry_price": 100.0}
result, written = refresh(held, [inv])
check("보유 중이면 활성 슬롯 유지", result.get("code") == "069500")
check("보유 중에도 후보 목록은 갱신", "short_term_candidates" in written)

# 갭 없는 새 판정은 오늘의 갭 판정을 덮지 못한다 (후보 목록까지 그대로).
gap_strategy_items = [inv]
stored_today = container("장전 예상체결가")
written_holder = {}
strategy = type("S", (), {"find_targets": lambda self, n, exclude_codes: (gap_strategy_items, verdict(None))})()
trader = tr.Trader.__new__(tr.Trader)
trader.short_term_strategy = strategy
with patch.object(tr, "get_setting", side_effect=lambda k: stored_today if k == "short_term_candidates" else None), \
     patch.object(tr, "set_setting", side_effect=lambda k, v: written_holder.__setitem__(k, v)):
    result = trader._short_term_refresh_candidates(slot, {}, force=True, quiet=True)
check("갭 없는 판정은 오늘 갭 판정을 덮지 않음", written_holder == {}, list(written_holder))
check("이때 슬롯도 그대로", result.get("code") == "102110")

print("\n── 4. 메인 루프 배선 (08:29 기동 → 09:02 까지 가상 시계) ──")


class FakeDT(datetime):
    """`datetime.now()` 만 테스트가 제어하는 시계 (strptime 등은 그대로)."""

    current = datetime(2026, 8, 3, 8, 29, 30)   # 월요일, 장전 시작 직전

    @classmethod
    def now(cls, tz=None):
        return cls.current


class _Stop(Exception):
    pass


def run_loop(cycles=34):
    calls = []
    trader = tr.Trader.__new__(tr.Trader)
    trader.buy_strategy = trader.sell_strategy = trader.short_term_strategy = object()
    trader._known_holdings = set()

    def rec(name, **kw):
        calls.append((FakeDT.current.strftime("%H:%M"), name, kw))

    n = {"i": 0}

    def sleep(_):
        n["i"] += 1
        if n["i"] >= cycles:
            raise _Stop
        FakeDT.current = FakeDT.current + tr.timedelta(seconds=60)

    trader.prepare_market_open = lambda force_short_term=False: (
        rec("prepare_market_open", force=force_short_term) or [])
    trader._prepare_short_term = lambda force=False, quiet=False: rec(
        "_prepare_short_term", force=force, quiet=quiet)
    trader.execute_initial_buy = lambda c: rec("execute_initial_buy")
    trader.check_and_sell = lambda: rec("check_and_sell")
    trader.check_short_term = lambda: rec("check_short_term")
    trader._sync_sell_settings = lambda: None
    trader.general_holdings = lambda holdings=None: {}
    trader.sell_strategy = type("S", (), {
        "load": lambda self: None, "on_buy": lambda self, *a, **k: None,
        "reconcile": lambda self, c: None})()

    settings = {"pre_market_open_time": "08:30"}
    with patch.object(tr, "datetime", FakeDT), \
         patch.object(tr.time, "sleep", side_effect=sleep), \
         patch.object(tr, "log", lambda *a, **k: None), \
         patch.object(tr, "get_setting", side_effect=settings.get):
        try:
            trader.run()
        except _Stop:
            pass
    return calls


calls = run_loop()
heavy = [c for c in calls if c[1] == "prepare_market_open"]
quiet_judges = [c for c in calls if c[1] == "_prepare_short_term" and c[2]["quiet"]]
open_judges = [c for c in calls if c[1] == "_prepare_short_term" and not c[2]["quiet"]]
short_term = [c for c in calls if c[1] == "check_short_term"]

check("무거운 스캔은 기동 1회 + 장전 1회뿐", len(heavy) == 2, str([c[0] for c in heavy]))
check("장전 첫 사이클은 08:30", heavy[1][0] == "08:30", heavy[1][0])
check("장전 나머지는 방향만 재판정(quiet)", len(quiet_judges) == 29, str(len(quiet_judges)))
check("장전 재판정은 08:31~08:59",
      quiet_judges[0][0] == "08:31" and quiet_judges[-1][0] == "08:59",
      f"{quiet_judges[0][0]}~{quiet_judges[-1][0]}")
check("개장 직후 최종 재판정 1회", len(open_judges) == 1, str([c[0] for c in open_judges]))
check("최종 재판정은 09:00", open_judges and open_judges[0][0] == "09:00")
check("최종 재판정이 진입 판정보다 먼저",
      calls.index(open_judges[0]) < calls.index(short_term[0]))
check("09:01 이후엔 재판정 없음", all(c[0] == "09:00" for c in open_judges))
check("장전에는 매매 판정 없음", all(c[0] >= "09:00" for c in short_term), str(short_term[:1]))

print()
if fails:
    print(f"❌ 실패 {len(fails)}건: {fails}")
    sys.exit(1)
print("✅ 전부 통과")
