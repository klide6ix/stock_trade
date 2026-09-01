"""청산선 σ 의 오염·지연 문제 — 후보 해법 비교.

문제(2026-08 실측): 20일 표준편차는 극단 하루에 오염되고 그 효과가 **20거래일 유지**된다.
07-28(-11.19%)·07-31(+24.17%) 두 날이 σ 를 5.16% → 7.50% 로 밀어올린 탓에, 일간 등락이
평균 2.81% 로 조용했던 8월 내내 청산선이 손절 15%(상한 클램프)·트레일링 12.8~14.3% 에
붙박여 **장중 청산이 20건 중 0건** 이었다. 국면 적응을 목표로 한 배수 방식이 정확히 그
목적에서 실패한 것이다.

여기서 비교하는 것은 σ **추정 방식**과 **클램프 상한** 뿐이고, 배수(2.5σ/2.0σ)·방향 판정·
진입 규칙은 건드리지 않는다. 청산 판정은 구현체 `EtfDayTradeStrategy.should_sell` 에
위임하고 `_simulate_recent.run()` 으로 돌린다.

판정 기준: **두 국면 모두에서 견디는가.** 8월만 고치고 고변동 구간을 망가뜨리면 의미가 없다.
조회 전용. 분봉 캐시를 재사용한다.
"""
import statistics as st

from core.market_direction import realized_vol, realized_vol_mad
from core.short_term import EtfDayTradeStrategy
from scripts._check_open_drift import SEED, _load_cache, _save_cache, proxy_bars, proxy_dates
from scripts._simulate_recent import daily_vols, run

START, SPLIT, END = "20260507", "20260803", "20260901"   # SPLIT 부터 저변동 국면(8월)
ENTRY_AT = "0905"


def vol_min(short_window: int = 5):
    """장·단기 σ 중 **작은 쪽** — 진정 국면에 빠르게 좁아지되 급등 시엔 넓히지 않는다."""
    def fn(closes: list[float]) -> float:
        return min(realized_vol(closes), realized_vol(closes, window=short_window))
    return fn


def windowed(window: int):
    def fn(closes: list[float]) -> float:
        return realized_vol(closes, window=window)
    return fn


CANDIDATES = [
    ("현행 (20일 σ · 5~15%)",        realized_vol,        5.0, 15.0),
    ("상한 12% ",                     realized_vol,        5.0, 12.0),
    ("상한 10% ",                     realized_vol,        5.0, 10.0),
    ("창 10일 (5~15%)",               windowed(10),        5.0, 15.0),
    ("창 10일 + 상한 12%",            windowed(10),        5.0, 12.0),
    ("min(20일,5일) (5~15%)",         vol_min(5),          5.0, 15.0),
    ("min(20일,5일) + 상한 12%",      vol_min(5),          5.0, 12.0),
    ("MAD 20일 (5~15%)",              realized_vol_mad,    5.0, 15.0),
]


def metrics(r: dict) -> dict:
    curve = [x["자산"] for x in r["rows"]]
    drets = [(b - a) / a for a, b in zip(curve, curve[1:]) if a > 0]
    peak, mdd = -1e18, 0.0
    for v in curve:
        peak = max(peak, v)
        mdd = min(mdd, (v - peak) / peak * 100) if peak > 0 else mdd
    intraday = sum(1 for t in r["trades"] if t["사유"] != "보유만료")
    return {
        "ret": (r["pool"] / SEED - 1) * 100,
        "sharpe": (st.mean(drets) / st.stdev(drets) * (250 ** 0.5)
                   if len(drets) > 2 and st.stdev(drets) else 0),
        "mdd": mdd, "intraday": intraday, "n": len(r["trades"]),
    }


def main() -> None:
    _load_cache()
    days_all = [d for d in proxy_dates if d <= END]
    days = [d for d in days_all if d >= START]
    hi = [d for d in days if d < SPLIT]     # 고변동 (5~7월)
    lo = [d for d in days if d >= SPLIT]    # 저변동 (8월)

    def dvol(closes_fn):
        return daily_vols(days_all, vol_fn=closes_fn)

    print(f"구간 {days[0]}~{days[-1]} ({len(days)}일) · 시드 {SEED:,}원 · 09:{ENTRY_AT[2:]} 진입")
    print(f"  고변동 {hi[0]}~{hi[-1]} ({len(hi)}일) / 저변동 {lo[0]}~{lo[-1]} ({len(lo)}일)")
    print("  배수는 손절 2.5σ · 트레일링 2.0σ 로 고정 — σ 추정과 클램프만 바꾼다")
    print("=" * 100)
    head = (f"{'후보':<26} {'고변동 수익':>11} {'장중청산':>7} | {'저변동 수익':>11} {'장중청산':>7} | "
            f"{'전체 수익':>10} {'Sharpe':>7} {'MDD':>8}")
    print(head)
    print("─" * len(head))

    for label, fn, lo_pct, hi_pct in CANDIDATES:
        vols = dvol(fn)
        s = EtfDayTradeStrategy(exit_min_pct=lo_pct, exit_max_pct=hi_pct)
        mh = metrics(run(hi, vols, s, entry_at=ENTRY_AT))
        ml = metrics(run(lo, vols, s, entry_at=ENTRY_AT))
        ma = metrics(run(days, vols, s, entry_at=ENTRY_AT))
        print(f"{label:<26} {mh['ret']:>+10.2f}% {mh['intraday']:>7} | "
              f"{ml['ret']:>+10.2f}% {ml['intraday']:>7} | "
              f"{ma['ret']:>+9.2f}% {ma['sharpe']:>+7.2f} {ma['mdd']:>7.2f}%")

    # ── σ 자체의 거동: 8월에 각 추정치가 얼마였나 ──
    print("\n" + "=" * 100)
    print("σ 추정치 거동 — 7월 극단 2일 이후 8월에 얼마나 빨리 내려오나 (트레일링 = 2.0σ)")
    print("=" * 100)
    print(f"{'날짜':>10} {'실제 |등락|':>10} {'20일 σ':>8} {'10일 σ':>8} {'min(20,5)':>10} {'MAD20':>8}")
    for d in [x for x in days if x >= "20260728"][:16]:
        i = proxy_dates.index(d)
        closes = [proxy_bars[x]["close"] for x in reversed(proxy_dates[:i])]
        prev = proxy_bars[proxy_dates[i - 1]]["close"]
        chg = abs((proxy_bars[d]["close"] - prev) / prev * 100)
        print(f"{d:>10} {chg:>9.2f}% {realized_vol(closes):>7.2f}% "
              f"{realized_vol(closes, window=10):>7.2f}% {vol_min(5)(closes):>9.2f}% "
              f"{realized_vol_mad(closes):>7.2f}%")
    _save_cache()


if __name__ == "__main__":
    main()
