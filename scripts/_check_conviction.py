"""'확신 없는 날은 쉬기' 검증 — 방향 점수의 크기가 적중률을 예측하는가.

방향 판정은 [-1, +1] 점수를 낸다. |점수| 가 클수록 확신이 크다는 뜻이니, 확신이 낮은 날은
진입하지 않거나 금액을 줄이는 게 타당해 보인다. 이 스크립트는 그 **원리 자체**를 본다 —
특정 임계값의 수익률이 아니라(그건 과최적화되기 쉽다) |점수| 와 결과의 관계를 직접 잰다.

  1. |점수| 5분위별 적중률·평균수익 — 단조 관계가 있는가
  2. 국면별 분해 — 고변동/저변동에서 모두 성립하는가
  3. train(5~7월) / test(8~9월) 분할 — 표본 외에서 재현되는가
  4. **대조군 비교** — 확신 사이징이 '단순히 돈을 덜 넣은 것' 과 다른가.
     고정 비율 축소는 Sharpe 를 바꾸지 못하므로(스케일 불변), 확신 사이징이 같은 평균
     투입비율의 고정 규칙보다 Sharpe 가 높아야 정보를 실제로 쓴 것이다.

조회 전용. 분봉 캐시 재사용.
"""
import statistics as st

from core.market_direction import realized_vol_adaptive
from core.short_term import EtfDayTradeStrategy
from scripts._check_open_drift import (
    DOWN_CODE,
    UP_CODE,
    _load_cache,
    _save_cache,
    fetch_minutes,
    price_at,
    proxy_dates,
)
from scripts._check_trade_frequency import ENTRY_AT, END, SPLIT, metrics
from scripts._compare_carry_mode import simulate
from scripts._simulate_recent import daily_vols, judge_at_open

BAND = 0.20                                   # 5분위 분석에서 드러난 자연스러운 분기점
TWO_STEP = lambda sc: 0.5 if abs(sc) <= BAND else 1.0   # noqa: E731


def outcomes(days: list[str]) -> list[tuple[str, float, float]]:
    """(날짜, |점수|, 진입→익일개장 수익률%) — 청산 규칙 없는 순수 신호 성과."""
    out = []
    for i, d in enumerate(days[:-1]):
        po = price_at(fetch_minutes(UP_CODE, d), "0900")
        sc = judge_at_open(d, po[1]) if po else None
        if not sc:
            continue
        code = UP_CODE if sc > 0 else DOWN_CODE
        a = price_at(fetch_minutes(code, d), ENTRY_AT)
        b = price_at(fetch_minutes(code, days[i + 1]), "0900")
        if a and b:
            out.append((d, abs(sc), (b[1] - a[1]) / a[1] * 100))
    return out


def split_report(name: str, seg: list, band: float = BAND) -> None:
    lo = [x for x in seg if x[1] <= band]
    hi = [x for x in seg if x[1] > band]
    if not lo or not hi:
        return
    ml, mh = st.mean([x[2] for x in lo]), st.mean([x[2] for x in hi])
    print(f"  {name:<16} 건너뜀 {len(lo):>2}건 적중 {sum(1 for x in lo if x[2] > 0) / len(lo) * 100:>3.0f}%"
          f" 평균 {ml:>+6.2f}%  |  진입 {len(hi):>2}건 "
          f"적중 {sum(1 for x in hi if x[2] > 0) / len(hi) * 100:>3.0f}% 평균 {mh:>+6.2f}%"
          f"  | 차이 {mh - ml:>+6.2f}%p")


def main() -> None:
    _load_cache()
    days_all = [d for d in proxy_dates if d <= END]
    days = days_all[20:]
    vols = daily_vols(days_all, vol_fn=realized_vol_adaptive)
    tr = [d for d in days if d < SPLIT]
    te = [d for d in days if d >= SPLIT]
    rows = outcomes(days)

    print(f"표본 {len(rows)}거래일 ({days[0]}~{days[-1]})")
    print("=" * 78)
    print("1. |방향점수| 5분위별 성과 — 확신이 적중률을 예측하는가")
    rows.sort(key=lambda r: r[1])
    n = len(rows)
    print(f"{'분위':>6} {'|점수| 범위':>16} {'거래':>4} {'적중률':>7} {'평균수익':>9}")
    for q in range(5):
        seg = rows[n * q // 5:n * (q + 1) // 5]
        print(f"  Q{q + 1:<3} {seg[0][1]:>6.3f}~{seg[-1][1]:<8.3f} {len(seg):>4} "
              f"{sum(1 for x in seg if x[2] > 0) / len(seg) * 100:>6.0f}% "
              f"{st.mean([x[2] for x in seg]):>+8.2f}%")
    xs, ys = [x[1] for x in rows], [x[2] for x in rows]
    c = st.correlation(xs, ys)
    se = (1 - c * c) ** 0.5 / (n - 2) ** 0.5
    print(f"  corr(|점수|, 수익률) = {c:+.3f} · t = {c / se:+.2f}")

    print("\n2. 국면별 분해 — 어디서 성립하는가")
    split_report("고변동 5~7월", [x for x in rows if x[0] < SPLIT])
    split_report("저변동 8~9월", [x for x in rows if x[0] >= SPLIT])

    print("\n3. 대조군 비교 — 확신 사이징 vs 같은 평균비율의 고정 축소")
    frac = st.mean([TWO_STEP(x[1]) for x in rows])
    print(f"   2단계 규칙(|점수|≤{BAND} 면 절반)의 평균 투입비율 = {frac * 100:.0f}%")
    print(f"   고정 축소는 Sharpe 를 못 바꾼다(스케일 불변) — 확신이 정보를 쓰면 Sharpe 가 올라야 한다")
    s = EtfDayTradeStrategy()
    print(f"\n{'구간':>8} {'규칙':<20} {'수익률':>9} {'Sharpe':>8} {'MDD':>8}")
    for nm, seg in (("train", tr), ("test", te), ("전체", days)):
        for lab, f in (("고정 100% (현행)", None), ("고정 75% (대조군)", lambda sc: 0.75),
                       ("확신 2단계 사이징", TWO_STEP)):
            m = metrics(simulate(seg, vols, s, ENTRY_AT, False, True, f))
            print(f"{nm:>8} {lab:<20} {m['ret']:>+8.2f}% {m['sharpe']:>+8.2f} {m['mdd']:>7.2f}%")
        print()
    _save_cache()


if __name__ == "__main__":
    main()
