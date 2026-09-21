"""초당 한도 throttle 슬롯 검증 (실제 대기 없음 — 시계·sleep 을 주입).

검증 대상
  1. 게이트웨이 슬롯 — 모든 호출이 `_MIN_INTERVAL` 이상 간격
  2. 원장 슬롯 — 계좌 API(TTTC/VTTC)는 `_MIN_LEDGER_INTERVAL` 이상 간격 (EGW00215 회피)
  3. 비대칭 — 원장 호출 때문에 시세 조회가 원장 간격만큼 밀리지 않는다
  4. 레거시 단일 값 lock 파일 호환
"""
import os
import sys
import tempfile
from unittest.mock import patch

from core import kis_api as api

fails = []


def check(name, cond, detail=""):
    print(f"  {'✅' if cond else '❌'} {name}" + (f" — {detail}" if detail else ""))
    if not cond:
        fails.append(name)


class FakeTime:
    """throttle 이 보는 시계 — sleep 하면 그만큼 시각이 흐른다."""

    def __init__(self, start=1_000_000.0):
        self.t = start

    def time(self):
        return self.t

    def sleep(self, sec):
        self.t += max(0.0, sec)


def run(seq, seed_content=None):
    """tr_id 시퀀스를 throttle 에 통과시키고 각 호출이 실제로 나가는 시각을 반환."""
    ft = FakeTime()
    path = tempfile.mktemp(suffix=".lock")
    if seed_content is not None:
        with open(path, "w") as f:
            f.write(seed_content)
    times = []
    try:
        with patch.object(api, "time", ft), patch.object(api, "THROTTLE_FILE", path):
            for tr in seq:
                api._throttle(tr)
                times.append(round(ft.t - 1_000_000.0, 6))
    finally:
        if os.path.exists(path):
            os.remove(path)
    return times


def gaps(times):
    return [round(b - a, 6) for a, b in zip(times, times[1:])]


GW, LD = api._MIN_INTERVAL, api._MIN_LEDGER_INTERVAL
print(f"게이트웨이 간격 {GW:.2f}s · 원장 간격 {LD:.2f}s\n")

print("── 1. 게이트웨이 슬롯 (시세 조회) ──")
t = run(["FHKST01010100"] * 5)
check("시세 연속 호출은 게이트웨이 간격을 지킨다",
      all(g >= GW - 1e-9 for g in gaps(t)), str(gaps(t)))
check("원장 간격까지 기다리지는 않는다",
      all(g < LD - 1e-9 for g in gaps(t)), str(gaps(t)))

print("\n── 2. 원장 슬롯 (계좌 API) ──")
t = run(["TTTC8434R"] * 4)
check("잔고 연속 호출은 원장 간격을 지킨다",
      all(g >= LD - 1e-9 for g in gaps(t)), str(gaps(t)))
t = run(["TTTC8434R", "TTTC8908R", "TTTC0802U"])
check("잔고→매수가능→주문도 원장 간격 (EGW00215 회피)",
      all(g >= LD - 1e-9 for g in gaps(t)), str(gaps(t)))
t = run(["VTTC8434R"] * 3)
check("모의(VTTC) 도 원장으로 인식", all(g >= LD - 1e-9 for g in gaps(t)), str(gaps(t)))

print("\n── 3. 비대칭 — 원장이 시세를 밀지 않는다 ──")
t = run(["TTTC8434R", "FHKST01010100", "FHKST01010100"])
check("원장 직후 시세는 게이트웨이 간격만 기다린다",
      abs(gaps(t)[0] - GW) < 1e-9, f"{gaps(t)[0]:.2f}s (원장 간격 {LD:.2f}s 아님)")
check("그 뒤 시세도 게이트웨이 간격", abs(gaps(t)[1] - GW) < 1e-9, str(gaps(t)))
t = run(["FHKST01010100", "TTTC8434R"])
check("시세 직후 원장은 게이트웨이 간격만 지나면 된다 (원장 슬롯이 비어 있으므로)",
      abs(gaps(t)[0] - GW) < 1e-9, str(gaps(t)))

print("\n── 4. lock 파일 호환 ──")
t = run(["TTTC8434R", "TTTC8434R"], seed_content="0")
check("레거시 단일 값 파일도 읽힌다", all(g >= LD - 1e-9 for g in gaps(t)), str(gaps(t)))
t = run(["FHKST01010100"], seed_content="not-a-number")
check("깨진 파일이면 제약 없이 통과 (가용성 우선)", t == [0.0], str(t))

print()
if fails:
    print(f"❌ 실패 {len(fails)}건: {fails}")
    sys.exit(1)
print("✅ 전부 통과")
