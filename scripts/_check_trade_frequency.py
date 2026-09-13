"""매매 빈도 대안 비교 — 저변동 국면에서 매일 회전이 수수료만 먹는가.

문제 제기: 8~9월처럼 지수가 조용한 구간(일평균 등락 2.25% · 고저폭 14.3%, 5~7월은
4.18% · 69.0%)에서는 매일 청산·재매수가 스프레드만 부담하고 수익은 미미해 보인다.

**핵심은 스프레드다.** 그동안의 시뮬레이션은 분봉 종가를 매수·매도 양쪽 체결가로 써서
호가 스프레드를 전혀 반영하지 않았다. 실제로는 매수가 지정가(매도호가)·매도가 시장가
(매수호가)라 왕복마다 스프레드 1틱을 온전히 부담한다 — 실측 틱은 KODEX 200 5원
(≈0.005%), 인버스 1원(≈0.098%)이라 **인버스 왕복이 KODEX 200 의 약 20배** 비싸다.

비교 대상 (모두 같은 루프 `_compare_carry_mode.simulate` 사용):
  A. 현행           — 매일 청산 후 재매수 (hold_days=1)
  B. 보유기간 확대  — hold_days 2~10일 (주단위 포함)
  C. 방향 이월      — 오늘 방향이 보유 종목과 같으면 청산 건너뛰기
  D. 중립 밴드      — |방향 점수| 가 밴드 안이면 그날 진입 자체를 보류

각 후보를 **스프레드 미반영/반영** 두 벌로 돌려 비용이 순위를 바꾸는지 본다.
조회 전용. 분봉 캐시 재사용.
"""
import statistics as st

from core.market_direction import realized_vol_adaptive
from core.short_term import EtfDayTradeStrategy
from scripts._check_open_drift import SEED, _load_cache, _save_cache, proxy_dates
from scripts._compare_carry_mode import simulate
from scripts._simulate_recent import daily_vols

ENTRY_AT = "0905"
END = "20260911"
SPLIT = "20260803"          # 이 날부터 저변동 국면(8~9월)


def metrics(r: dict) -> dict:
    curve = [x["자산"] for x in r["rows"]]
    drets = [(b - a) / a for a, b in zip(curve, curve[1:]) if a > 0]
    peak, mdd = -1e18, 0.0
    for v in curve:
        peak = max(peak, v)
        mdd = min(mdd, (v - peak) / peak * 100) if peak > 0 else mdd
    return {
        "ret": (r["pool"] / SEED - 1) * 100,
        "sharpe": (st.mean(drets) / st.stdev(drets) * (250 ** 0.5)
                   if len(drets) > 2 and st.stdev(drets) else 0),
        "mdd": mdd, "n": len(r["trades"]),
        "hold": (st.mean(t["보유일수"] for t in r["trades"]) if r["trades"] else 0),
    }


def main() -> None:
    _load_cache()
    days_all = [d for d in proxy_dates if d <= END]
    days = days_all[20:]                       # 20일 이평선 warm-up 이후만
    vols = daily_vols(days_all, vol_fn=realized_vol_adaptive)
    hi = [d for d in days if d < SPLIT]
    lo = [d for d in days if d >= SPLIT]

    cands = [("A. 현행 (매일 회전)", dict(), False)]
    cands += [(f"B. 보유 {n}일", dict(hold_days=n), False) for n in (2, 3, 5, 7, 10)]
    cands += [("C. 방향 이월", dict(), True)]
    cands += [(f"D. 중립밴드 {b:.2f}", dict(neutral_band=b), False)
              for b in (0.10, 0.20, 0.30)]

    print(f"구간 {days[0]}~{days[-1]} ({len(days)}일) · 시드 {SEED:,}원 · 09:{ENTRY_AT[2:]} 진입")
    print(f"  고변동 {hi[0]}~{hi[-1]} ({len(hi)}일) / 저변동 {lo[0]}~{lo[-1]} ({len(lo)}일)")
    print(f"  스프레드: KODEX 200 5원틱 · 인버스 1원틱 (왕복 1틱 부담)")
    print("=" * 108)

    for use_spread in (False, True):
        tag = "스프레드 반영" if use_spread else "스프레드 미반영 (기존 방식)"
        print(f"\n[{tag}]")
        head = (f"{'후보':<20} {'거래':>4} {'평균보유':>7} | {'고변동':>9} {'저변동':>9} | "
                f"{'전체':>9} {'Sharpe':>7} {'MDD':>8}")
        print(head)
        print("─" * len(head))
        for label, kw, carry in cands:
            s = EtfDayTradeStrategy(**kw)
            mh = metrics(simulate(hi, vols, s, ENTRY_AT, carry, use_spread))
            ml = metrics(simulate(lo, vols, s, ENTRY_AT, carry, use_spread))
            ma = metrics(simulate(days, vols, s, ENTRY_AT, carry, use_spread))
            print(f"{label:<20} {ma['n']:>4} {ma['hold']:>6.2f}일 | "
                  f"{mh['ret']:>+8.2f}% {ml['ret']:>+8.2f}% | "
                  f"{ma['ret']:>+8.2f}% {ma['sharpe']:>+7.2f} {ma['mdd']:>7.2f}%")

    # ── 스프레드가 실제로 얼마를 먹는가 ──
    print("\n" + "=" * 108)
    print("스프레드 비용 실측 — 같은 후보를 두 벌로 돌린 차이")
    print("=" * 108)
    print(f"{'후보':<20} {'거래':>4} {'미반영':>10} {'반영':>10} {'비용':>9} {'거래당':>8}")
    for label, kw, carry in cands:
        s = EtfDayTradeStrategy(**kw)
        a = metrics(simulate(days, vols, s, ENTRY_AT, carry, False))
        b = metrics(simulate(days, vols, s, ENTRY_AT, carry, True))
        cost = a["ret"] - b["ret"]
        print(f"{label:<20} {a['n']:>4} {a['ret']:>+9.2f}% {b['ret']:>+9.2f}% "
              f"{cost:>+8.2f}%p {cost / max(1, a['n']):>+7.3f}%p")
    _save_cache()


if __name__ == "__main__":
    main()
