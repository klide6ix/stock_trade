"""개장 직후 진입 지연(0~30분)이 진입가·손익에 미치는 영향 — 분봉 실측.

질문: "개장 후 N분을 기다리면 그 사이 지수가 이미 움직여서 불리한 가격에 사는 것 아닌가?"

일봉만 쓰던 기존 검증([_simulate_july.py](_simulate_july.py))과 달리 **1분봉**을 받아
  ① 09:00 시가 대비 첫 10분 드리프트의 실제 크기와 방향성
  ② 매매 방향(정방향/인버스) 기준으로 지연이 진입가를 얼마나 불리하게 만드는지
  ③ 지연별 자금 곡선 (실제 4중 청산 규칙 + 분 단위 폴링 재현)
를 함께 본다.

분 단위 폴링을 재현하므로 일봉 시뮬레이션의 최대 한계였던 **장중 고가·저가 순서 가정
(보수/낙관 경로)** 이 사라진다 — 트레이더가 `CHECK_INTERVAL=60` 로 1분마다 현재가를
보는 것과 같게, 각 분봉 **종가**를 그 시점의 폴링 가격으로 쓴다.

조회 전용 — 주문은 하지 않는다. 분봉은 `data/.minute_bars_cache.json` 에 캐시한다
(호출 약 500회 / 재실행 시 0회).
"""
import json
import os
import statistics as st
from datetime import datetime

from core.kis_api import BASE_URL, _request, get_daily_ohlcv
from core.market_direction import (
    MA_LONG,
    MA_SHORT,
    MOMENTUM_DAYS,
    NORM_GAP_MULT,
    NORM_MA_TREND_MULT,
    NORM_MOMENTUM_MULT,
    NORM_PREV_DAY_MULT,
    W_GAP,
    W_MA_TREND,
    W_MOMENTUM_3D,
    W_PREV_DAY_REVERSION,
    _clip,
    _norm,
    realized_vol,
)
from core.strategy.buy._indicators import sma

UP_CODE, DOWN_CODE = "069500", "114800"     # KODEX 200 / KODEX 인버스
START, END = "20260302", "20260731"
SEED = 3_000_000
FEE_RATE = 0.000042                          # 0.0042% 편도 (실측 위탁수수료)
STOP_PCT, PEAK_PCT = 10.0, 10.0              # 현행 기본값
DELAYS = [0, 1, 3, 5, 10, 15, 30]            # 개장 후 진입 지연(분)
CACHE_PATH = "data/.minute_bars_cache.json"

# 한 번에 120행 → 09:00~15:30(391분)을 덮는 조회 기준시각.
FULL_DAY_HOURS = ("153000", "133000", "113000", "093000")
OPEN_HOURS = ("093000",)                     # 첫 30분만 필요할 때

W = {"ma": W_MA_TREND, "prev": W_PREV_DAY_REVERSION, "mom": W_MOMENTUM_3D, "gap": W_GAP}


# ── 분봉 수집 (캐시) ──────────────────────────────────────────────────────────

_cache: dict = {}


def _load_cache() -> None:
    global _cache
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH, encoding="utf-8") as f:
            _cache = json.load(f)


def _save_cache() -> None:
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(_cache, f)


def fetch_minutes(code: str, date: str, hours=FULL_DAY_HOURS) -> dict[str, float]:
    """분봉 종가 시계열 {HHMM: close}. 이미 캐시에 있으면 호출하지 않는다."""
    key = f"{code}:{date}"
    cached = _cache.get(key)
    need = "full" if hours == FULL_DAY_HOURS else "open"
    if cached and (cached.get("scope") == "full" or need == "open"):
        return cached["bars"]

    url = f"{BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice"
    bars: dict[str, float] = {}
    for hour in hours:
        rows = _request("GET", url, "FHKST03010230", params={
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": code,
            "FID_INPUT_DATE_1": date,
            "FID_INPUT_HOUR_1": hour,
            "FID_PW_DATA_INCU_YN": "N",
            "FID_FAKE_TICK_INCU_YN": "N",
        }).get("output2", [])
        for r in rows:
            hhmmss = r.get("stck_cntg_hour") or ""
            try:
                close = float(r.get("stck_prpr") or 0)
            except (TypeError, ValueError):
                continue
            if len(hhmmss) >= 4 and close > 0:
                bars[hhmmss[:4]] = close
    _cache[key] = {"scope": need, "bars": bars}
    return bars


def price_at(bars: dict[str, float], hhmm: str) -> tuple[str, float] | None:
    """해당 시각 이후 가장 이른 분봉 종가 (그 분에 체결이 없으면 다음 분으로 밀림)."""
    later = sorted(t for t in bars if t >= hhmm)
    return (later[0], bars[later[0]]) if later else None


def minute_label(delay: int) -> str:
    return f"09:{delay:02d}" if delay < 60 else "10:00"


# ── 방향 판정 (실제 로직과 동일) ──────────────────────────────────────────────

proxy_bars = {b["date"]: b for b in get_daily_ohlcv(UP_CODE, days=140)}
inv_bars = {b["date"]: b for b in get_daily_ohlcv(DOWN_CODE, days=140)}
DAILY = {UP_CODE: proxy_bars, DOWN_CODE: inv_bars}
proxy_dates = sorted(proxy_bars)


def judge(date: str) -> float | None:
    """08:30 시점의 방향 점수. 확정 과거봉 + 당일 시가를 갭 신호로 대용."""
    idx = proxy_dates.index(date)
    past = [proxy_bars[d] for d in reversed(proxy_dates[:idx])]
    if len(past) < MA_LONG:
        return None
    closes = [b["close"] for b in past]
    vol = realized_vol(closes)
    total = wsum = 0.0

    def add(score, w):
        nonlocal total, wsum
        wsum += score * w
        total += abs(w)

    gap = (proxy_bars[date]["open"] - closes[0]) / closes[0] * 100
    add(_norm(gap, NORM_GAP_MULT * vol), W["gap"])
    add(-_norm((closes[0] - closes[1]) / closes[1] * 100, NORM_PREV_DAY_MULT * vol), W["prev"])
    ma_s, ma_l = sma(closes, MA_SHORT), sma(closes, MA_LONG)
    if ma_s and ma_l:
        add(_norm((ma_s - ma_l) / ma_l * 100, NORM_MA_TREND_MULT * vol), W["ma"])
    if len(closes) > MOMENTUM_DAYS:
        mom = (closes[0] - closes[MOMENTUM_DAYS]) / closes[MOMENTUM_DAYS] * 100
        add(_norm(mom, NORM_MOMENTUM_MULT * vol), W["mom"])
    return _clip(wsum / total) if total else None


# ── 시뮬레이션 (지연별) ───────────────────────────────────────────────────────


def simulate(delay: int, days: list[str], trade_code: dict[str, str]):
    """개장 후 `delay` 분에 진입했을 때의 자금 곡선. 분 단위 폴링으로 청산 재현."""
    pool = float(SEED)
    pos = None
    blocked = None
    trades = []

    for i, date in enumerate(days):
        # ── 1. 다음 거래일 첫 폴링 = 보유분 청산 (손절 > 최고가 > 보유기간) ──
        if pos:
            bars = fetch_minutes(pos["code"], date)
            hit = price_at(bars, "0900")
            if hit:
                _, price = hit
                drop_entry = (pos["entry"] - price) / pos["entry"] * 100
                drop_peak = (pos["peak"] - price) / pos["peak"] * 100
                kind = ("손절" if drop_entry >= STOP_PCT
                        else "최고가" if drop_peak >= PEAK_PCT else "보유만료")
                proceeds = price * pos["qty"] * (1 - FEE_RATE)
                pool += proceeds - pos["invested"]
                trades.append((date, "청산", kind, proceeds - pos["invested"]))
                if kind != "보유만료":
                    blocked = date
                pos = None

        code = trade_code.get(date)
        if not code or blocked == date or pool <= 0:
            continue

        # ── 2. 진입 (개장 + delay 분 폴링 시점) ──
        bars = fetch_minutes(code, date)
        hit = price_at(bars, f"09{delay:02d}")
        if not hit:
            continue
        entry_time, entry = hit
        qty = int(pool // (entry * (1 + FEE_RATE)))
        if qty <= 0:
            continue
        # 자금 풀은 청산 시 실현손익(`회수 - 투입`)으로만 갱신한다 — 진입 때 차감하면
        # 청산 시 투입액이 두 번 빠진다.
        invested = qty * entry * (1 + FEE_RATE)
        pos = {"code": code, "entry": entry, "qty": qty, "invested": invested, "peak": entry}
        trades.append((date, "진입", code, entry))

        # ── 3. 장중 폴링 — 매 분봉 종가로 최고가 갱신 + 청산 판정 ──
        for t in sorted(bars):
            if t <= entry_time:
                continue
            price = bars[t]
            pos["peak"] = max(pos["peak"], price)
            drop_entry = (pos["entry"] - price) / pos["entry"] * 100
            drop_peak = (pos["peak"] - price) / pos["peak"] * 100
            if drop_entry >= STOP_PCT or drop_peak >= PEAK_PCT:
                kind = "손절" if drop_entry >= STOP_PCT else "최고가"
                proceeds = price * pos["qty"] * (1 - FEE_RATE)
                pool += proceeds - pos["invested"]
                trades.append((date, "청산", kind, proceeds - pos["invested"]))
                blocked = date
                pos = None
                break

    # 마지막 날 미청산분은 종가 평가손익만 얹는다 (풀에는 투입액이 그대로 들어 있다).
    equity = pool
    if pos:
        bars = fetch_minutes(pos["code"], days[-1])
        last = max(bars) if bars else None
        if last:
            equity += bars[last] * pos["qty"] * (1 - FEE_RATE) - pos["invested"]
    return pool, equity, trades


# ── 실행 ──────────────────────────────────────────────────────────────────────


def main() -> None:
    _load_cache()
    days = [d for d in proxy_dates if START <= d <= END]
    print(f"분석 구간 {days[0]} ~ {days[-1]} ({len(days)}영업일)\n")

    # 방향 판정 → 그날 매매할 종목
    trade_code: dict[str, str] = {}
    for d in days:
        score = judge(d)
        if score is None or score == 0:
            continue
        trade_code[d] = UP_CODE if score > 0 else DOWN_CODE
    ups = sum(1 for c in trade_code.values() if c == UP_CODE)
    print(f"방향 판정: 상승(정방향 ETF) {ups}일 · 하락(인버스 ETF) {len(trade_code) - ups}일\n")

    # 분봉 수집 (매매 종목은 전일, 프록시는 첫 30분)
    for n, d in enumerate(days, 1):
        code = trade_code.get(d)
        if code:
            fetch_minutes(code, d)
        fetch_minutes(UP_CODE, d, OPEN_HOURS)
        if n % 20 == 0:
            print(f"  분봉 수집 {n}/{len(days)}일...")
            _save_cache()
    _save_cache()
    print()

    # ── ① 프록시(KODEX 200) 개장 직후 드리프트 ──
    print("=" * 78)
    print("① KODEX 200 — 09:00 시가 대비 드리프트 (지수 자체가 얼마나 움직이나)")
    print("=" * 78)
    print(f"{'시각':>6} {'평균':>8} {'중앙':>8} {'평균|x|':>8} {'표준편차':>8} "
          f"{'|x|>1%':>7} {'|x|>2%':>7} {'p10':>8} {'p90':>8}")
    drift_series: dict[int, dict[str, float]] = {}
    for delay in DELAYS[1:]:
        vals = {}
        for d in days:
            bars = fetch_minutes(UP_CODE, d, OPEN_HOURS)
            open_px = proxy_bars[d]["open"]
            hit = price_at(bars, f"09{delay:02d}")
            if hit and open_px > 0:
                vals[d] = (hit[1] - open_px) / open_px * 100
        drift_series[delay] = vals
        v = list(vals.values())
        q = st.quantiles(v, n=10)
        print(f"{minute_label(delay):>6} {st.mean(v):+8.2f}% {st.median(v):+8.2f}% "
              f"{st.mean(map(abs, v)):8.2f}% {st.stdev(v):8.2f}% "
              f"{sum(1 for x in v if abs(x) > 1) / len(v) * 100:6.0f}% "
              f"{sum(1 for x in v if abs(x) > 2) / len(v) * 100:6.0f}% "
              f"{q[0]:+8.2f}% {q[-1]:+8.2f}%")

    # ── ② 매매 방향 기준 진입가 페널티 ──
    print()
    print("=" * 78)
    print("② 매매 방향 기준 진입가 변화 (+ = 지연 때문에 더 비싸게 삼 = 불리)")
    print("=" * 78)
    print("   진입가가 그대로 손익이 된다 — 청산가는 지연과 무관하므로 이 표가 곧 일별 손익 차이다.")
    print(f"{'지연':>6} {'평균':>8} {'중앙':>8} {'불리한날':>8} {'평균불리':>8} {'평균유리':>8} "
          f"{'표준편차':>8} {'표준오차':>8} {'t':>6} {'표본':>5}")
    penalty: dict[int, dict[str, float]] = {}
    for delay in DELAYS[1:]:
        vals = {}
        for d, code in trade_code.items():
            bars = fetch_minutes(code, d)
            base = price_at(bars, "0900")
            hit = price_at(bars, f"09{delay:02d}")
            if base and hit and base[1] > 0:
                vals[d] = (hit[1] - base[1]) / base[1] * 100
        penalty[delay] = vals
        v = list(vals.values())
        bad = [x for x in v if x > 0]
        good = [x for x in v if x < 0]
        sd = st.stdev(v)
        se = sd / len(v) ** 0.5
        print(f"{minute_label(delay):>6} {st.mean(v):+8.2f}% {st.median(v):+8.2f}% "
              f"{len(bad) / len(v) * 100:7.0f}% {st.mean(bad):+8.2f}% {st.mean(good):+8.2f}% "
              f"{sd:8.2f}% {se:8.2f}% {st.mean(v) / se:+6.2f} {len(v):5d}")

    # ── ③ 드리프트가 이어지는가 (지연이 '확인' 역할을 하는지) ──
    print()
    print("=" * 78)
    print("③ 첫 10분 드리프트와 그 이후 수익률의 관계 (매매 종목 기준)")
    print("=" * 78)
    xs, ys = [], []
    for d, code in trade_code.items():
        bars = fetch_minutes(code, d)
        base = price_at(bars, "0900")
        p10 = price_at(bars, "0910")
        if not base or not p10:
            continue
        last = max(bars)
        xs.append((p10[1] - base[1]) / base[1] * 100)
        ys.append((bars[last] - p10[1]) / p10[1] * 100)
    if len(xs) > 2:
        corr = st.correlation(xs, ys)
        print(f"  corr(09:00→09:10 드리프트, 09:10→종가 수익률) = {corr:+.3f}  (n={len(xs)})")
        up = [y for x, y in zip(xs, ys) if x > 0]
        dn = [y for x, y in zip(xs, ys) if x <= 0]
        print(f"  첫 10분 상승한 날({len(up)}일) 이후 평균 {st.mean(up):+.2f}% · "
              f"하락한 날({len(dn)}일) 이후 평균 {st.mean(dn):+.2f}%")

    # ── ④ 지연별 자금 곡선 ──
    print()
    print("=" * 78)
    print(f"④ 지연별 자금 곡선 (시드 {SEED:,}원 · 손절 -{STOP_PCT:g}% · 최고가 -{PEAK_PCT:g}%)")
    print("=" * 78)
    print(f"{'지연':>6} {'실현풀':>13} {'평가포함':>13} {'수익률':>9} {'거래':>5} {'승률':>6} {'청산사유'}")
    for delay in DELAYS:
        pool, equity, trades = simulate(delay, days, trade_code)
        exits = [t for t in trades if t[1] == "청산"]
        wins = sum(1 for t in exits if t[3] > 0)
        kinds: dict[str, int] = {}
        for t in exits:
            kinds[t[2]] = kinds.get(t[2], 0) + 1
        kind_str = " ".join(f"{k}{v}" for k, v in sorted(kinds.items()))
        print(f"{minute_label(delay):>6} {pool:13,.0f} {equity:13,.0f} "
              f"{(equity / SEED - 1) * 100:+8.2f}% {len(exits):5d} "
              f"{(wins / len(exits) * 100 if exits else 0):5.0f}% {kind_str}")

    _save_cache()


if __name__ == "__main__":
    main()
