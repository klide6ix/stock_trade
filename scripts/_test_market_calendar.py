"""휴장일 달력 검증 (API 는 가짜로 주입 — 실제 호출 없음).

검증 대상
  1. `is_open_day` — 주말 · 달력의 휴장일 · 달력에 없는 평일(개장으로 간주)
  2. 하루 1회 조회 — 같은 날 다시 부르지 않고, 다른 프로세스가 받아 둔 파일을 쓴다
  3. 조회 실패 — 평일은 개장으로 보고, 30분 동안 재시도하지 않는다
  4. 모의투자 — API 를 부르지 않는다
  5. 트레이더 판정 — 휴장일엔 장 운영 · 장전 준비 · 개장 재판정 창이 모두 닫힌다
  6. 로그 보존 — 휴장일 파일은 운영일로 세지 않는다
"""
import os
import sys
import tempfile
from datetime import date, datetime
from unittest.mock import patch

import config
from core import logger as lg
from core import market_calendar as mc
from core import trader as tr

fails = []


def check(name, cond, detail=""):
    print(f"  {'✅' if cond else '❌'} {name}" + (f" — {detail}" if detail else ""))
    if not cond:
        fails.append(name)


TODAY = date(2026, 10, 2)
CAL = {"20261002": True, "20261005": False, "20261006": True, "20261009": False, "20261012": True}


def fresh(path):
    mc._mem.update({"fetched_on": None, "days": {}})
    mc._last_failed_at = 0.0
    return patch.object(mc, "CALENDAR_FILE", path)


tmp = tempfile.mkdtemp()
calls = []


def fake_fetch(base):
    calls.append(base)
    return dict(CAL)


print("── 1. is_open_day ──")
with fresh(os.path.join(tmp, "a.json")), patch.object(mc, "_fetch", fake_fetch), \
     patch.object(config, "IS_MOCK", False), patch.object(mc, "date", type("D", (date,), {"today": staticmethod(lambda: TODAY)})):
    check("주말은 휴장", not mc.is_open_day(date(2026, 10, 3)))
    check("달력의 공휴일(10-05 대체공휴일)은 휴장", not mc.is_open_day(date(2026, 10, 5)))
    check("달력의 평일 개장일은 개장", mc.is_open_day(date(2026, 10, 6)))
    check("달력에 없는 평일은 개장으로 간주 (기존 동작)", mc.is_open_day(date(2026, 11, 20)))

    print("\n── 2. 하루 1회 · 파일 공유 ──")
    check("여러 번 판정해도 조회는 1회", len(calls) == 1, f"{len(calls)}회")
    mc._mem.update({"fetched_on": None, "days": {}})       # 다른 프로세스 흉내 — 메모리 비움
    mc.is_open_day(date(2026, 10, 5))
    check("다른 프로세스가 받아 둔 파일이 있으면 다시 조회하지 않는다", len(calls) == 1, f"{len(calls)}회")
    check("파일에서 읽은 휴장일도 반영", not mc.is_open_day(date(2026, 10, 5)))

print("\n── 3. 조회 실패 ──")
fail_calls = []


def boom(base):
    fail_calls.append(base)
    raise RuntimeError("EGW00201")


with fresh(os.path.join(tmp, "b.json")), patch.object(mc, "_fetch", boom), \
     patch.object(config, "IS_MOCK", False), patch("core.logger.log", lambda *a, **k: None):
    check("조회 실패 시 평일은 개장으로 본다", mc.is_open_day(date(2026, 10, 5)))
    for _ in range(5):
        mc.is_open_day(date(2026, 10, 6))
    check("실패 후 30분 동안은 재시도하지 않는다", len(fail_calls) == 1, f"{len(fail_calls)}회")

print("\n── 4. 모의투자 ──")
mock_calls = []
with fresh(os.path.join(tmp, "c.json")), patch.object(mc, "_fetch", lambda b: mock_calls.append(b) or {}), \
     patch.object(config, "IS_MOCK", True):
    mc.is_open_day(date(2026, 10, 6))
    check("모의투자는 휴장일 API 를 부르지 않는다 (미지원)", mock_calls == [])

print("\n── 5. 트레이더 판정 — 휴장일엔 창이 닫힌다 ──")
holiday = lambda d, **k: d.weekday() < 5 and (d.date() if isinstance(d, datetime) else d) != date(2026, 10, 9)
with patch.object(tr, "is_open_day", holiday), patch.object(tr, "get_setting", lambda k: None):
    check("휴장일 09:02 는 개장 재판정 창이 아니다", not tr.open_rejudge_window(datetime(2026, 10, 9, 9, 2)))
    check("휴장일 08:45 는 장전 준비가 아니다", not tr.is_pre_market(datetime(2026, 10, 9, 8, 45)))
    check("다음 개장일 09:02 는 재판정 창", tr.open_rejudge_window(datetime(2026, 10, 12, 9, 2)))
    check("다음 개장일 08:45 는 장전 준비", tr.is_pre_market(datetime(2026, 10, 12, 8, 45)))
    with patch.object(tr, "datetime", type("F", (datetime,), {"now": classmethod(lambda c, tz=None: datetime(2026, 10, 9, 10, 0))})):
        check("휴장일 10:00 은 장 운영 시간이 아니다", not tr.is_market_open())

print("\n── 6. 로그 보존 — 휴장일은 운영일로 세지 않는다 ──")
logdir = tempfile.mkdtemp()
for d in ("2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09"):
    open(os.path.join(logdir, f"trader-{d}.log"), "w").close()
with fresh(os.path.join(tmp, "d.json")), patch.object(lg, "_LOG_DIR", logdir):
    mc._mem["days"] = {"20261005": False, "20261009": False}
    lg.cleanup_old_logs(retention_days=4)
left = sorted(f[7:17] for f in os.listdir(logdir))
# 운영일(최신순) 10-08 · 07 · 06 · 02 → 컷오프 10-02. 휴장일 10-05 · 10-09 는 세지 않는다.
check("운영일 4일치 = 10-02 부터 남는다 (휴장일 미산입)", left[0] == "2026-10-02", str(left))
check("컷오프 이후 휴장일 파일은 함께 남는다 (연속성)", "2026-10-05" in left and "2026-10-09" in left)

print()
if fails:
    print(f"❌ 실패 {len(fails)}건: {fails}")
    sys.exit(1)
print("✅ 전부 통과")
