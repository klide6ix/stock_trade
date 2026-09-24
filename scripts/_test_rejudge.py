"""장전 매분 재판정 + 개장 직후 최종 재판정 순수 로직 검증 (API 호출 없음).

검증 대상
  1. `keeps_previous_verdict` — 갭을 쓴 판정이 갭 없는 판정에 덮이지 않는가
  2. `open_rejudge_window`   — 개장 직후 재판정 창(평일 09:00~09:05) 경계
  3. `_short_term_refresh_candidates` — 사용자 선택 보존 · 오늘 차단 유지 · 불필요한 쓰기 생략
  4. `today_gap_source` + 메인 루프 — 실측 갭이 반영될 때까지 창 안에서 재시도하는가
"""
import sys
from datetime import datetime
from unittest.mock import patch

from core import trader as tr
from core.market_direction import GAP_SOURCE_EXPECTED, GAP_SOURCE_LIVE
from core.short_term import keeps_previous_verdict, today_gap_source

fails = []


def check(name, cond, detail=""):
    print(f"  {'✅' if cond else '❌'} {name}" + (f" — {detail}" if detail else ""))
    if not cond:
        fails.append(name)


# 창 경계·요일 검증은 고정 평일(2026-08-03 월요일)을 기준으로 한다 — 실행 요일에
# 따라 결과가 달라지면 안 되기 때문이다. 반면 실제 `datetime.now()` 를 타는 경로는
# `REAL_TODAY` 를 써야 한다(아래 3절 주석 참조).
NOW = datetime(2026, 8, 3, 8, 45)
TODAY = NOW.date().isoformat()
REAL_TODAY = datetime.now().date().isoformat()


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
# `_short_term_refresh_candidates` 는 내부에서 실제 `datetime.now()` 를 쓰므로, 저장된
# 판정도 **실행 시점 기준 오늘**이어야 한다. 위 `keeps_previous_verdict` 블록은 `NOW` 를
# 명시로 넘겨 자기완결적이지만 이 경로는 아니다 — 고정 날짜를 쓰면 그 날짜가 지나는
# 순간 '어제 판정' 이 되어 테스트가 달력에 따라 깨진다(2026-08-04 실측).
gap_strategy_items = [inv]
stored_today = container("장전 예상체결가", REAL_TODAY + "T08:30:00")
written_holder = {}
strategy = type("S", (), {"find_targets": lambda self, n, exclude_codes: (gap_strategy_items, verdict(None))})()
trader = tr.Trader.__new__(tr.Trader)
trader.short_term_strategy = strategy
with patch.object(tr, "get_setting", side_effect=lambda k: stored_today if k == "short_term_candidates" else None), \
     patch.object(tr, "set_setting", side_effect=lambda k, v: written_holder.__setitem__(k, v)):
    result = trader._short_term_refresh_candidates(slot, {}, force=True, quiet=True)
check("갭 없는 판정은 오늘 갭 판정을 덮지 않음", written_holder == {}, list(written_holder))
check("이때 슬롯도 그대로", result.get("code") == "102110")

print("\n── 3.5 today_gap_source — '오늘 갭이 반영됐는가' 판별 ──")
check("오늘 실측 갭 → 라벨 반환",
      today_gap_source(container(GAP_SOURCE_LIVE), NOW) == GAP_SOURCE_LIVE)
check("오늘 장전 갭 → 라벨 반환 (실측과 구분은 호출부 몫)",
      today_gap_source(container(GAP_SOURCE_EXPECTED), NOW) == GAP_SOURCE_EXPECTED)
check("어제 갭 판정 → 빈 문자열",
      today_gap_source(container(GAP_SOURCE_LIVE, "2026-08-02T09:00:00"), NOW) == "")
check("갭 없는 판정 → 빈 문자열", today_gap_source(container(None), NOW) == "")
check("컨테이너 없음 → 빈 문자열", today_gap_source(None, NOW) == "")
check("selected_at 형식 불량 → 빈 문자열",
      today_gap_source(container(GAP_SOURCE_LIVE, "not-a-date"), NOW) == "")

print("\n── 4. 메인 루프 배선 (08:29 기동 → 09:06 까지 가상 시계) ──")


class FakeDT(datetime):
    """`datetime.now()` 만 테스트가 제어하는 시계 (strptime 등은 그대로)."""

    start = datetime(2026, 8, 3, 8, 29, 30)     # 월요일, 장전 시작 직전
    current = start

    @classmethod
    def now(cls, tz=None):
        return cls.current


class _Stop(Exception):
    pass


def run_loop(cycles=38, gap_at=None, start=None, log_sink=None):
    """가상 시계로 메인 루프를 돌리고 호출 순서를 기록한다.

    Args:
        start: 기동 시각 (기본 장전 직전). `log_sink` 를 주면 로그 문자열도 모은다.
    """
    # 시계는 클래스 변수라 이전 호출의 끝 시각이 남는다 — 매번 시작 시각으로 되감는다.
    FakeDT.current = start or FakeDT.start
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
    def prepare_short(force=False, quiet=False):
        rec("_prepare_short_term", force=force, quiet=quiet)
        # 실측 갭이 반영되는 시각을 테스트가 지정한다. 그 시각부터 저장된 판정의
        # gap_source 가 GAP_SOURCE_LIVE 가 되어 루프가 '오늘 완료' 로 마킹한다.
        if gap_at and FakeDT.current.strftime("%H:%M") >= gap_at:
            settings["short_term_candidates"] = {
                "selected_at": FakeDT.current.isoformat(),
                "direction": {"gap_source": GAP_SOURCE_LIVE},
            }

    trader._prepare_short_term = prepare_short
    trader.execute_initial_buy = lambda c: rec("execute_initial_buy")
    trader.check_and_sell = lambda: rec("check_and_sell")
    trader.check_short_term = lambda: rec("check_short_term")
    trader._sync_sell_settings = lambda: None
    trader.general_holdings = lambda holdings=None: {}
    trader.sell_strategy = type("S", (), {
        "load": lambda self: None, "on_buy": lambda self, *a, **k: None,
        "reconcile": lambda self, c: None})()

    settings = {"pre_market_open_time": "08:30"}
    def fake_log(msg, *a, **k):
        if log_sink is not None:
            log_sink.append(str(msg))

    with patch.object(tr, "datetime", FakeDT), \
         patch.object(tr.time, "sleep", side_effect=sleep), \
         patch.object(tr, "log", fake_log), \
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
check("최종 재판정은 09:00 에 시작", open_judges and open_judges[0][0] == "09:00")
check("최종 재판정이 진입 판정보다 먼저",
      calls.index(open_judges[0]) < calls.index(short_term[0]))

# 실측 갭이 반영되지 않는 한 창 안에서 계속 다시 시도한다. 성공 여부와 무관하게
# 하루치를 끝내버리면 그날 개장 갭이 영영 판정에 안 들어간다 (2026-08-12 실측 -13.56%p).
check("갭 미반영이면 창(09:00~09:05) 안에서 매 주기 재시도",
      len(open_judges) == 5 and open_judges[-1][0] == "09:04",
      str([c[0] for c in open_judges]))
check("창을 넘기면 재시도 중단", all(c[0] <= "09:05" for c in open_judges))

open_hit = [c for c in run_loop(gap_at="09:00")
            if c[1] == "_prepare_short_term" and not c[2]["quiet"]]
check("실측 갭이 첫 시도에 반영되면 1회로 끝", len(open_hit) == 1, str([c[0] for c in open_hit]))

open_late = [c for c in run_loop(gap_at="09:02")
             if c[1] == "_prepare_short_term" and not c[2]["quiet"]]
check("반영된 주기까지만 재시도하고 멈춤",
      len(open_late) == 3 and open_late[-1][0] == "09:02", str([c[0] for c in open_late]))
check("장전에는 매매 판정 없음", all(c[0] >= "09:00" for c in short_term), str(short_term[:1]))

print("\n── 5. 장 운영 시간 외 '대기 중' 로그 빈도 ──")
# 매 사이클(60초) 찍으면 하루 1,000줄이 넘어 매매 기록을 덮는다. 대기 진입 1회 +
# IDLE_LOG_INTERVAL(60분) 마다 한 줄만 남아야 한다.
_logs = []
run_loop(cycles=150, start=datetime(2026, 8, 3, 6, 0), log_sink=_logs)
_idle = [m for m in _logs if "대기 중" in m]
_expected = 1 + (149 * 60) // tr.IDLE_LOG_INTERVAL      # 06:00~08:29 = 149분 대기
check("대기 로그는 진입 1회 + 시간당 1회", len(_idle) == _expected,
      f"{len(_idle)}회 / 149분 (기대 {_expected}회)")
check("대기 로그에 다음 장전 준비 시각이 붙는다",
      _idle and "08:30" in _idle[0], _idle[0] if _idle else "(없음)")

# 장전·장중을 거친 뒤 다시 대기로 들어가면 heartbeat 타이머가 리셋돼 한 줄이 남아야 한다.
_logs2 = []
run_loop(cycles=600, start=datetime(2026, 8, 3, 8, 50), log_sink=_logs2)
_idle2 = [m for m in _logs2 if "대기 중" in m]
check("장 마감 후 대기 진입 시 다시 기록된다", len(_idle2) >= 1, f"{len(_idle2)}회")

print()
if fails:
    print(f"❌ 실패 {len(fails)}건: {fails}")
    sys.exit(1)
print("✅ 전부 통과")
