"""청산선 배수(손절 2.5σ · 트레일링 2.0σ) 재보정 검토.

배경: 이 배수들은 σ 추정이 **20일 표준편차**이던 시절에 정해졌다. 그 뒤 σ 오염·지연을
고치며 청산선 기준을 `realized_vol_adaptive`(= min(20일, 5일))로 바꿨는데, 이 값은 20일 σ
보다 **평균 20.6% 작다**. 즉 배수를 그대로 두면 청산선이 의도보다 그만큼 좁아진 셈이라
배수 자체를 다시 봐야 한다.

`_check_vol_lag.py` 가 σ **추정 방식**을 비교했다면, 이 스크립트는 σ 를 현행(adaptive)으로
고정한 채 **배수만** 비교한다. 방향 판정·진입 규칙·클램프(5~15%)는 건드리지 않는다.

판정 기준은 동일하다 — **세 국면 모두에서 견디는가.** 특정 구간만 좋아지는 값은 채택하지
않는다. 9월은 σ 수정 이후 처음 생긴 **진짜 표본 외** 구간이다.

조회 전용. 분봉은 `data/.minute_bars_cache.json` 캐시를 재사용/보강한다.
"""
import statistics as st

from core.market_direction import realized_vol_adaptive
from core.short_term import EtfDayTradeStrategy
from scripts._check_open_drift import SEED, _load_cache, _save_cache, proxy_dates
from scripts._simulate_recent import daily_vols, run

START, END = "20260507", "20260911"
ENTRY_AT = "0905"
REGIMES = [("고변동 5~7월", "20260507", "20260801"),
           ("저변동 8월", "20260803", "20260901"),
           ("신규 9월", "20260901", "20269999")]

# (손절 배수, 트레일링 배수). 현행은 (2.5, 2.0).
PAIRS = [(2.5, 1.5), (2.5, 1.75), (2.5, 2.0), (2.5, 2.25), (2.5, 2.5),
         (2.5, 3.0), (3.0, 2.0), (3.0, 2.5), (3.5, 2.5), (3.5, 3.0),
         (4.0, 3.0), (10.0, 2.0), (10.0, 2.5), (10.0, 3.0)]


def metrics(r: dict) -> dict:
    curve = [x["자산"] for x in r["rows"]]
    drets = [(b - a) / a for a, b in zip(curve, curve[1:]) if a > 0]
    peak, mdd = -1e18, 0.0
    for v in curve:
        peak = max(peak, v)
        mdd = min(mdd, (v - peak) / peak * 100) if peak > 0 else mdd
    kinds: dict[str, int] = {}
    for t in r["trades"]:
        kinds[t["사유"].split(" ")[0]] = kinds.get(t["사유"].split(" ")[0], 0) + 1
    return {
        "ret": (r["pool"] / SEED - 1) * 100,
        "sharpe": (st.mean(drets) / st.stdev(drets) * (250 ** 0.5)
                   if len(drets) > 2 and st.stdev(drets) else 0),
        "mdd": mdd,
        "stop": kinds.get("손절", 0),
        "trail": kinds.get("최고가", 0),
        "n": len(r["trades"]),
    }


def main() -> None:
    _load_cache()
    days_all = [d for d in proxy_dates if d <= END]
    days = [d for d in days_all if d >= START]
    vols = daily_vols(days_all, vol_fn=realized_vol_adaptive)
    subs = [(nm, [d for d in days if a <= d < b]) for nm, a, b in REGIMES]

    print(f"구간 {days[0]}~{days[-1]} ({len(days)}일) · 시드 {SEED:,}원 · 09:{ENTRY_AT[2:]} 진입")
    print(f"σ = realized_vol_adaptive(min(20일,5일)) 고정 · 클램프 5~15% 고정 — 배수만 비교")
    for nm, sub in subs:
        print(f"  {nm}: {sub[0]}~{sub[-1]} ({len(sub)}일)")
    print("=" * 104)
    head = (f"{'손절':>5} {'트레일':>6} | " + " | ".join(f"{nm:>11}" for nm, _ in subs)
            + f" | {'전체':>9} {'Sharpe':>7} {'MDD':>8} {'손절':>5} {'트레일':>6}")
    print(head)
    print("─" * len(head))

    for stop_m, peak_m in PAIRS:
        s = EtfDayTradeStrategy(stop_loss_mult=stop_m, peak_drop_mult=peak_m)
        cells = [metrics(run(sub, vols, s, entry_at=ENTRY_AT))["ret"] for _, sub in subs]
        m = metrics(run(days, vols, s, entry_at=ENTRY_AT))
        mark = " ←현행" if (stop_m, peak_m) == (2.5, 2.0) else ""
        print(f"{stop_m:>5.1f} {peak_m:>6.2f} | "
              + " | ".join(f"{c:>+10.2f}%" for c in cells)
              + f" | {m['ret']:>+8.2f}% {m['sharpe']:>+7.2f} {m['mdd']:>7.2f}% "
                f"{m['stop']:>5} {m['trail']:>6}{mark}")

    print("\n※ 손절 배수 10.0 = 하드 손절을 사실상 비활성(트레일링 단독) — 손절선이 실제로")
    print("  일을 하는지 보는 대조군이다. 트레일링이 항상 먼저 걸리면 결과가 같아야 한다.")
    _save_cache()


if __name__ == "__main__":
    main()
