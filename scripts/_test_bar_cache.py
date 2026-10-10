"""일봉 구간 조회 · 분봉 캐시 수정주가 기준 점검 검증 (API 호출 없음).

검증 대상
  1. `get_daily_ohlcv_range` — 100행씩 거슬러 받아 시작일이 고정되는가
  2. `stale_minute_keys` — 분배락 뒤 낡은 분봉만 정확히 골라내는가
"""
import sys
from datetime import datetime, timedelta
from unittest.mock import patch

from core import kis_api as k
from scripts._bar_cache import stale_minute_keys

fails = []


def check(name, cond, detail=""):
    print(f"  {'✅' if cond else '❌'} {name}" + (f" — {detail}" if detail else ""))
    if not cond:
        fails.append(name)


def trading_days(start: str, count: int) -> list[str]:
    """`start` 부터 평일만 `count` 개."""
    day, out = datetime.strptime(start, "%Y%m%d"), []
    while len(out) < count:
        if day.weekday() < 5:
            out.append(day.strftime("%Y%m%d"))
        day += timedelta(days=1)
    return out


class FakeKis:
    """KIS 일봉 조회 흉내 — 구간 안에서 **최근 100행만** 최신순으로 돌려준다."""

    def __init__(self, dates):
        self.dates = sorted(dates)
        self.calls = []

    def request(self, method, url, tr_id, params=None, **kwargs):
        lo, hi = params["FID_INPUT_DATE_1"], params["FID_INPUT_DATE_2"]
        self.calls.append((lo, hi))
        rows = [d for d in self.dates if lo <= d <= hi][-100:]
        return {"output2": [
            {"stck_bsop_date": d, "stck_clpr": str(1000 + self.dates.index(d)),
             "stck_oprc": "1000", "stck_hgpr": "1100", "stck_lwpr": "900", "acml_vol": "10"}
            for d in reversed(rows)
        ]}


def fetch(dates, start, end=None):
    fake = FakeKis(dates)
    with patch.object(k, "_request", fake.request):
        return k.get_daily_ohlcv_range("069500", start, end), fake


print("── 1. get_daily_ohlcv_range ──")
ALL = trading_days("20260102", 250)

bars, fake = fetch(ALL, ALL[0], ALL[-1])
got = [b["date"] for b in bars]
check("250거래일을 전부 받는다 (기존 방식은 100행에서 끊김)", len(bars) == 250, f"{len(bars)}행")
check("최신순 · 중복 없음", got == sorted(ALL, reverse=True))
check("조회 3회 (100 + 100 + 50)", len(fake.calls) == 3, str(fake.calls))
his = [hi for _, hi in fake.calls]
check("다음 조회는 앞서 받은 가장 오래된 날의 전날에서 끝난다 (겹치지 않음)",
      his[0] == ALL[-1] and ALL[149] <= his[1] < ALL[150] and ALL[49] <= his[2] < ALL[50], str(his))

bars, _ = fetch(ALL, ALL[40], ALL[-1])
check("시작일이 고정된다 — 시작일 이전은 받지 않는다",
      bars[-1]["date"] == ALL[40] and len(bars) == 210, f"{bars[-1]['date']} · {len(bars)}행")

# 실행 날짜가 하루 지나도 표본 시작일은 그대로여야 한다.
day1, _ = fetch(ALL[:240], ALL[40], ALL[239])
day2, _ = fetch(ALL[:241], ALL[40], ALL[240])
check("실행 날짜가 하루 지나도 시작일이 밀리지 않는다",
      day1[-1]["date"] == day2[-1]["date"] == ALL[40] and len(day2) == len(day1) + 1,
      f"{day1[-1]['date']} → {day2[-1]['date']}")
old1 = sorted(ALL[:240])[-100:][0]
old2 = sorted(ALL[:241])[-100:][0]
check("(대조) 최근 100행 방식은 하루 지나면 시작일이 하루 밀린다", old1 != old2, f"{old1} → {old2}")

bars, fake = fetch(ALL[:200], ALL[0], ALL[199])
check("딱 100의 배수여도 전부 받고, 시작일을 지나면 더 조회하지 않는다",
      len(bars) == 200 and len(fake.calls) == 2, f"{len(bars)}행 · 조회 {len(fake.calls)}회")
bars, fake = fetch(ALL[:60], ALL[0], ALL[59])
check("100행 미만이면 1회로 끝난다", len(bars) == 60 and len(fake.calls) == 1)
bars, fake = fetch([], "20260101", "20260301")
check("데이터가 없으면 빈 목록", bars == [] and len(fake.calls) == 1)
bars, _ = fetch(ALL, ALL[10], ALL[30])
check("종료일을 주면 그 날까지만", bars[0]["date"] == ALL[30] and bars[-1]["date"] == ALL[10])


class StuckKis(FakeKis):
    """구간을 무시하고 늘 같은 100행을 주는 고장 난 응답."""

    def request(self, method, url, tr_id, params=None, **kwargs):
        self.calls.append(1)
        return {"output2": [{"stck_bsop_date": d, "stck_clpr": "1000"} for d in reversed(self.dates[-100:])]}


stuck = StuckKis(ALL)
with patch.object(k, "_request", stuck.request):
    bars = k.get_daily_ohlcv_range("069500", ALL[0], ALL[-1])
check("같은 응답이 반복되면 무한히 돌지 않는다", len(stuck.calls) == 2 and len(bars) == 100,
      f"조회 {len(stuck.calls)}회")

# 기존 함수는 오늘 기준으로 구간을 잡으므로 오늘까지 이어지는 날짜로 본다.
past = [d for d in trading_days((datetime.now() - timedelta(days=90)).strftime("%Y%m%d"), 80)
        if d <= datetime.now().strftime("%Y%m%d")]
with patch.object(k, "_request", FakeKis(past).request):
    recent = k.get_daily_ohlcv("069500", days=20)
check("기존 get_daily_ohlcv 는 그대로 (최신순 N행 · 같은 필드)",
      len(recent) == 20 and recent[0]["date"] == past[-1] and set(recent[0]) ==
      {"date", "open", "high", "low", "close", "volume"},
      f"{len(recent)}행 · {recent[0]['date'] if recent else '-'}")

print("\n── 2. stale_minute_keys ──")
DAYS = trading_days("20260601", 60)
TODAY = "20261010"
EX_DATE = DAYS[40]          # 분배락일 — 그 이전 날짜의 수정주가가 전부 바뀐다
FACTOR = 0.998              # 실측 KODEX 200 2026-07-30 분배락과 같은 크기


def minute(close, scope="full", fetched=None):
    bars = {"0900": close * 0.99, "1200": close * 1.01, "1530": close}
    if scope == "open":
        bars = {"0900": close * 0.99, "0929": close * 1.002}
    entry = {"scope": scope, "bars": bars}
    return {**entry, "fetched": fetched} if fetched else entry


daily_old = {d: {"close": 100_000.0 + i * 100} for i, d in enumerate(DAYS)}
inverse = {d: {"close": 1_500.0 + i} for i, d in enumerate(DAYS)}
cache_old = {f"069500:{d}": minute(b["close"]) for d, b in daily_old.items()}
cache_old.update({f"114800:{d}": minute(b["close"]) for d, b in inverse.items()})

check("기준이 같으면 버릴 것이 없다",
      stale_minute_keys(cache_old, {"069500": daily_old, "114800": inverse}, TODAY) == {})

# 분배락 발생 — 새로 받은 일봉은 락일 이전 값이 FACTOR 만큼 낮아져 온다.
daily_new = {d: {"close": round(b["close"] * FACTOR) if d < EX_DATE else b["close"]}
             for d, b in daily_old.items()}
stale = stale_minute_keys(cache_old, {"069500": daily_new, "114800": inverse}, TODAY)
want = [f"069500:{d}" for d in DAYS if d < EX_DATE]
check("분배락 이전 날짜의 분봉만 낡은 것으로 고른다", stale.get("069500") == want,
      f"{len(stale.get('069500', []))}일 (기대 {len(want)}일)")
check("락일 이후 분봉은 남긴다", f"069500:{EX_DATE}" not in stale.get("069500", []))
check("분배가 없던 종목(인버스)은 건드리지 않는다", "114800" not in stale)

rounded = {d: {"close": b["close"] + 1} for d, b in daily_old.items()}
check("수정주가 반올림(1원)은 기준 변경으로 보지 않는다",
      stale_minute_keys(cache_old, {"069500": rounded}, TODAY) == {})
check("저가 종목(1,500원대)의 1원 차이도 허용한다",
      stale_minute_keys(cache_old, {"114800": {d: {"close": b["close"] + 1}
                                               for d, b in inverse.items()}}, TODAY) == {})

mixed = dict(cache_old)
mixed[f"069500:{DAYS[5]}"] = minute(daily_old[DAYS[5]]["close"], scope="open")
stale = stale_minute_keys(mixed, {"069500": daily_new}, TODAY)
check("마감 봉이 없어 대조 못 하는 항목도 락일 이전이면 함께 버린다",
      f"069500:{DAYS[5]}" in stale["069500"] and len(stale["069500"]) == len(want))
only_open = {f"069500:{d}": minute(daily_old[d]["close"], scope="open") for d in DAYS}
check("마감 봉이 하나도 없으면 판정하지 않는다 (근거 없이 버리지 않음)",
      stale_minute_keys(only_open, {"069500": daily_new}, TODAY) == {})

refetched = {key: {**v, "fetched": TODAY} for key, v in cache_old.items()}
check("오늘 받은 항목은 어긋나도 버리지 않는다 (매 실행 재수신 방지)",
      stale_minute_keys(refetched, {"069500": daily_new}, TODAY) == {})
yesterday = {key: {**v, "fetched": "20261009"} for key, v in cache_old.items()}
check("어제 받은 항목은 버린다",
      len(stale_minute_keys(yesterday, {"069500": daily_new}, TODAY).get("069500", [])) == len(want))

live = dict(cache_old)
live[f"069500:{TODAY}"] = minute(120_000.0)
check("오늘 날짜는 일봉이 아직 종가가 아니므로 대조하지 않는다",
      stale_minute_keys(live, {"069500": {**daily_old, TODAY: {"close": 110_000.0}}}, TODAY) == {})
check("일봉에 없는 날짜의 분봉은 판정하지 않는다",
      stale_minute_keys(cache_old, {"069500": {}}, TODAY) == {})

print()
if fails:
    print(f"❌ 실패 {len(fails)}건: {fails}")
    sys.exit(1)
print("✅ 전부 통과")
