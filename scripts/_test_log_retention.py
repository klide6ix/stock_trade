"""로그 보존 정리 검증 — 운영일(평일) 기준으로 자르는가 (파일 시스템만, API 없음).

검증 대상 `core.logger.cleanup_old_logs`
  1. 평일 N일치 보존 — 달력 일수가 아니라 평일 개수로 컷오프를 잡는가
  2. 컷오프 구간의 주말 파일은 함께 남는가 (연속으로 읽혀야 한다)
  3. 보관 한도 미달이면 아무것도 지우지 않는가
  4. 레거시 `trader.log`·비패턴 파일은 건드리지 않는가
"""
import os
import sys
import tempfile
from datetime import date, timedelta
from unittest.mock import patch

from core import logger as lg

fails = []


def check(name, cond, detail=""):
    print(f"  {'✅' if cond else '❌'} {name}" + (f" — {detail}" if detail else ""))
    if not cond:
        fails.append(name)


def setup(days_back, extra=()):
    """오늘부터 `days_back` 일 전까지 매일 로그 파일을 만든 임시 디렉터리."""
    d = tempfile.mkdtemp()
    today = date(2026, 9, 25)          # 금요일 — 주말 경계가 걸리도록 고정
    made = {}
    for i in range(days_back):
        day = today - timedelta(days=i)
        name = lg._LOG_PATTERN.format(date=day.isoformat())
        path = os.path.join(d, name)
        open(path, "w").close()
        made[day] = path
    for name in extra:
        open(os.path.join(d, name), "w").close()
    return d, made


def remaining(d):
    return sorted(os.listdir(d))


print("── 1. 평일 기준 컷오프 ──")
# 30일치(평일 22개 + 주말 8개)에서 평일 14일치만 남긴다.
d, made = setup(30)
with patch.object(lg, "_LOG_DIR", d):
    removed = lg.cleanup_old_logs(retention_days=14)
left = remaining(d)
left_days = sorted(date.fromisoformat(f[7:17]) for f in left)
left_weekdays = [x for x in left_days if x.weekday() < 5]
check("평일은 정확히 14개 남는다", len(left_weekdays) == 14, f"{len(left_weekdays)}개")
check("삭제된 파일이 있다", len(removed) > 0, f"{len(removed)}개 삭제")
check("남은 구간이 연속이다 (중간에 구멍 없음)",
      left_days == [left_days[0] + timedelta(days=i) for i in range(len(left_days))],
      f"{left_days[0]} ~ {left_days[-1]}")

print("\n── 2. 컷오프 구간의 주말 보존 ──")
cutoff = min(left_weekdays)
weekend_in_range = [x for x in left_days if x.weekday() >= 5]
check("컷오프 이후 주말 파일도 남는다", len(weekend_in_range) > 0,
      f"주말 {len(weekend_in_range)}개 보존 (컷오프 {cutoff})")
check("컷오프보다 이전 파일은 전부 삭제됐다", all(x >= cutoff for x in left_days),
      f"최소 {min(left_days)} ≥ 컷오프 {cutoff}")
check("달력 일수로는 14일보다 길게 남는다 (주말만큼)",
      (max(left_days) - min(left_days)).days + 1 > 14,
      f"{(max(left_days) - min(left_days)).days + 1}일치")

print("\n── 3. 보관 한도 미달 ──")
d2, _ = setup(10)      # 평일 8개뿐
with patch.object(lg, "_LOG_DIR", d2):
    removed2 = lg.cleanup_old_logs(retention_days=14)
check("평일이 한도 이하면 아무것도 지우지 않는다",
      removed2 == [] and len(remaining(d2)) == 10, f"{len(remaining(d2))}개 유지")

print("\n── 4. 비대상 파일 ──")
d3, _ = setup(30, extra=["trader.log", "startup.log", "trader-bogus.log"])
with patch.object(lg, "_LOG_DIR", d3):
    lg.cleanup_old_logs(retention_days=14)
left3 = remaining(d3)
check("레거시 trader.log 보존", "trader.log" in left3)
check("startup.log 보존", "startup.log" in left3)
check("패턴에 안 맞는 trader-bogus.log 보존", "trader-bogus.log" in left3)

print()
if fails:
    print(f"❌ 실패 {len(fails)}건: {fails}")
    sys.exit(1)
print("✅ 전부 통과")
