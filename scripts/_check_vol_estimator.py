"""σ 추정치 비교 — 표준편차 vs MAD(중앙값 절대편차).

왜 바꾸려 하는가: 청산선이 `배수 × σ` 인데, 표준편차는 편차를 **제곱**해 평균하므로
이상치 하나가 결과를 지배한다. 실측으로 2026-07-31 의 +24.17% 하루가 σ 를
5.16% → 7.50%(+45%) 로 밀어올렸고, 20거래일 창에 남아 있는 동안 청산선을 그만큼 넓힌
채 방치한다. MAD 는 편차의 **중앙값**이라 표본의 절반이 오염돼야 무너진다.

다만 두 추정치는 **척도가 다르다**. 정규분포에서는 1.4826×MAD ≈ σ 로 맞지만, 실제
수익률은 꼬리가 두꺼워 MAD 기반 추정이 체계적으로 작게 나온다. 그래서 배수를 그대로
두고 갈아끼우면 **청산선이 조용히 좁아지는 부작용**이 생긴다 — 좁은 청산선은 이미
whipsaw 로 손해가 확인된 방향이다. 따라서 두 가지를 함께 본다.
  A. 배수 그대로 (2.5 / 2.0) — 실질적으로 더 좁은 청산선
  B. 배수 재보정 — 평균 청산선이 표준편차 방식과 같아지도록 배수를 키움

조회 전용. 분봉·일봉은 캐시를 재사용한다.
"""
import statistics as st

from config import SHORT_TERM_PEAK_DROP_MULT, SHORT_TERM_STOP_LOSS_MULT
from core.market_direction import realized_vol, realized_vol_mad
from core.short_term import EtfDayTradeStrategy
from scripts._simulate_recent import (
    DAYS_BACK,
    LAST_DAY,
    SEED,
    daily_vols,
    run,
)
from scripts._check_open_drift import _load_cache, _save_cache, proxy_bars, proxy_dates


def summarize(name: str, result: dict, vols: dict, days: list[str]) -> dict:
    rows, trades = result["rows"], result["trades"]
    exits = [t for t in trades if "최고가" in t["사유"] or "손절" in t["사유"]]
    wins = [t for t in trades if t["손익"] > 0]
    used = [vols[d] for d in days]
    lines = [r["청산선"] for r in rows if "청산선" in r]
    return {
        "name": name,
        "equity": result["equity"],
        "pool": result["pool"],
        "vol_mean": st.mean(used),
        "line_mean": st.mean(lines) if lines else 0,
        "line_min": min(lines) if lines else 0,
        "line_max": max(lines) if lines else 0,
        "intraday": len(exits),
        "trades": len(trades),
        "win": len(wins) / len(trades) * 100 if trades else 0,
        "avg": st.mean(t["수익률"] for t in trades) if trades else 0,
    }


def main() -> None:
    _load_cache()
    days_all = [d for d in proxy_dates if d <= LAST_DAY]
    days = days_all[-DAYS_BACK:]

    v_std = daily_vols(days_all, realized_vol)
    v_mad = daily_vols(days_all, realized_vol_mad)

    # ── ① 추정치 자체 비교 ──
    print("=" * 92)
    print("① σ 추정치 비교 — 표준편차 vs MAD(×1.4826)")
    print("=" * 92)
    ratios = [v_mad[d] / v_std[d] for d in days_all if v_std[d] > 0]
    print(f"  전체 {len(ratios)}일 · MAD/표준편차 비율 평균 {st.mean(ratios):.3f} "
          f"· 중앙 {st.median(ratios):.3f} · 최소 {min(ratios):.3f} · 최대 {max(ratios):.3f}")
    print(f"  → MAD 기반이 평균 {(1 - st.mean(ratios)) * 100:.1f}% 작게 나온다 "
          f"(수익률 꼬리가 두꺼워 정규분포 환산 상수로는 다 못 맞춘다)\n")

    print(f"  {'날짜':>10} {'σ(표준편차)':>12} {'σ(MAD)':>10} {'차이':>9}   최근 30거래일")
    for d in days:
        diff = (v_mad[d] - v_std[d]) / v_std[d] * 100
        print(f"  {d[:4]}-{d[4:6]}-{d[6:]} {v_std[d]:>11.2f}% {v_mad[d]:>9.2f}% {diff:>+8.1f}%")

    # 7/31 급등일이 두 추정치에 남긴 흔적 — 그 하루가 표본에 **편입된 뒤**(= 다음 거래일
    # 아침) 값과 편입 전(7/31 아침) 값을 비교해야 한다. 이것이 MAD 도입의 원래 명분이다.
    idx_last = proxy_dates.index(days_all[-1])
    before = [proxy_bars[x]["close"] for x in reversed(proxy_dates[:idx_last])]      # 7/31 아침
    after = [proxy_bars[x]["close"] for x in reversed(proxy_dates[:idx_last + 1])]   # 다음 거래일 아침
    print(f"\n  [7/31 의 +24.17% 하루가 표본에 편입되면] — MAD 도입의 원래 명분 검증")
    for label, fn in (("표준편차", realized_vol), ("MAD     ", realized_vol_mad)):
        b, a = fn(before), fn(after)
        print(f"    {label}: {b:.2f}% → {a:.2f}%  ({(a / b - 1) * 100:+.1f}%)  "
              f"· 트레일링 2.0σ 환산 {2 * b:.1f}% → {2 * a:.1f}%")

    # ── ② 30거래일 시뮬레이션 ──
    print("\n" + "=" * 92)
    print("② 최근 30거래일 시뮬레이션 (같은 방향 판정 · 청산선만 다름)")
    print("=" * 92)

    # 배수 재보정: 평균 청산선이 표준편차 방식과 같아지도록
    scale = st.mean(v_std[d] for d in days) / st.mean(v_mad[d] for d in days)
    rescaled_stop = SHORT_TERM_STOP_LOSS_MULT * scale
    rescaled_peak = SHORT_TERM_PEAK_DROP_MULT * scale

    cases = [
        ("표준편차 (현행) 2.5σ/2.0σ", v_std, EtfDayTradeStrategy()),
        ("MAD · 배수 그대로 2.5σ/2.0σ", v_mad, EtfDayTradeStrategy()),
        (f"MAD · 배수 재보정 {rescaled_stop:.2f}σ/{rescaled_peak:.2f}σ", v_mad,
         EtfDayTradeStrategy(stop_loss_mult=rescaled_stop, peak_drop_mult=rescaled_peak)),
    ]

    results = []
    for name, vols, strategy in cases:
        results.append(summarize(name, run(days, vols, strategy), vols, days))

    head = (f"{'방식':<30} {'평가자산':>12} {'수익률':>9} {'실현풀':>12} "
            f"{'평균σ':>7} {'청산선 평균':>11} {'범위':>15} {'장중청산':>8}")
    print(head)
    print("─" * len(head))
    for r in results:
        print(f"{r['name']:<30} {r['equity']:>12,.0f} "
              f"{(r['equity'] / SEED - 1) * 100:>+8.2f}% {r['pool']:>12,.0f} "
              f"{r['vol_mean']:>6.2f}% {r['line_mean']:>10.2f}% "
              f"{r['line_min']:>6.1f}~{r['line_max']:>5.1f}% {r['intraday']:>6}회")

    print(f"\n  거래당 평균 손익 · 승률")
    for r in results:
        print(f"    {r['name']:<30} {r['avg']:+.2f}% · {r['win']:.0f}% ({r['trades']}회)")

    # ── ③ 전체 기간 train/test — 30일 결과가 우연인지 확인 ──
    print("\n" + "=" * 92)
    print("③ 전체 기간 train(2026-03~05) / test(2026-06~07) — 30일 결과가 우연인지 확인")
    print("=" * 92)
    train = [d for d in days_all if d <= "20260531"]
    test = [d for d in days_all if d > "20260531"]
    head3 = (f"{'방식':<30} {'train':>10} {'test':>10} {'전체':>10} "
             f"{'장중청산(전체)':>14} {'청산선 σ 변동폭':>16}")
    print(head3)
    print("─" * len(head3))
    for name, vols, strategy in cases:
        out = {}
        for label, dd in (("train", train), ("test", test), ("all", days_all)):
            r = run(dd, vols, strategy)
            out[label] = (r["equity"] / SEED - 1) * 100
            if label == "all":
                lines = [row["청산선"] for row in r["rows"] if "청산선" in row]
                intraday = sum(1 for t in r["trades"]
                               if "최고가" in t["사유"] or "손절" in t["사유"])
        # 인접일 청산선이 얼마나 튀는가 (추정치의 안정성)
        seq = [vols[d] for d in days_all]
        jumps = [abs(seq[i] - seq[i - 1]) / seq[i - 1] * 100 for i in range(1, len(seq))]
        print(f"{name:<30} {out['train']:>+9.2f}% {out['test']:>+9.2f}% {out['all']:>+9.2f}% "
              f"{intraday:>12}회 {st.mean(jumps):>14.2f}%")
    print("  ※ 마지막 열 = 인접 거래일 사이 σ 변화율의 평균 (작을수록 청산선이 안정적)")

    _save_cache()


if __name__ == "__main__":
    main()
