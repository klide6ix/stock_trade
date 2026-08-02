"""청산 규칙 비교 — "초반에 오르다 폭락 / 초반에 내리다 폭등" 을 어떻게 다룰 것인가.

문제 인식
  ① 초반에 올랐다가 폭락 → 벌어 둔 이익을 그대로 반납한다.
  ② 초반에 내렸다가 폭등 → 손절로 나간 뒤 반등을 놓친다 (손절 5% 시절의 손해 원인).
두 케이스는 처방이 반대다. ①은 '이익을 지키는 청산' 을, ②는 '섣불리 자르지 않는 인내' 를
요구하므로, 단일 손절 % 를 조이거나 넓히는 것만으로는 동시에 잡을 수 없다.

그래서 손절·트레일링을 **분리된 축**으로 보고 아래 계열을 같은 데이터로 비교한다.
  - 고정 손절/트레일링 격자 (현행 10/10 포함)
  - **무장(arm) 트레일링** — 수익 +a% 를 찍은 뒤에만 트레일링을 켠다. 이익이 난 적 없는
    포지션은 건드리지 않으므로 ②를 피하면서 ①만 막는다.
  - **변동성 배수** — 청산선을 `k × 일간 실현변동성` 으로 두어 국면에 자동 적응한다.
  - **진입 유예** — 진입 후 N분은 청산 판정을 하지 않는다 (개장 직후 노이즈 회피).
  - 익일 개장 청산만 (장중 청산 없음) — 장중 청산이 정말 값을 하는지 보는 기준선.

과최적화 방지: 표본을 **train(2026-03~05) / test(2026-06~07)** 로 나눠 따로 집계한다.
train 에서 좋고 test 에서 무너지는 규칙은 채택하지 않는다.

조회 전용. 분봉은 `data/.minute_bars_cache.json` 캐시를 재사용한다.
"""
import statistics as st
from typing import Callable, NamedTuple

from core.market_direction import realized_vol
from scripts._check_open_drift import (
    DAILY,
    DOWN_CODE,
    FEE_RATE,
    SEED,
    UP_CODE,
    _load_cache,
    _save_cache,
    fetch_minutes,
    judge,
    price_at,
    proxy_bars,
    proxy_dates,
)

TRAIN_END = "20260531"      # 이 날짜까지 train, 이후 test
START, END = "20260310", "20260731"


class State(NamedTuple):
    """청산 판정에 필요한 포지션 상태 (모두 % 단위)."""
    gain: float         # 진입가 대비 현재 손익률
    drop_from_peak: float   # 진입 이후 최고가 대비 하락률
    peak_gain: float    # 진입 이후 최고 손익률 (트레일링 무장 판정용)
    minutes: int        # 진입 후 경과 분
    vol: float          # 그날의 일간 실현변동성(%)


Rule = Callable[[State], str]


def fixed(stop: float, trail: float, grace: int = 0) -> Rule:
    """고정 손절 + 고정 트레일링. `grace` 분 동안은 판정하지 않는다."""
    def rule(s: State) -> str:
        if s.minutes < grace:
            return ""
        if stop and -s.gain >= stop:
            return "손절"
        if trail and s.drop_from_peak >= trail:
            return "최고가"
        return ""
    return rule


def armed(arm: float, trail: float, stop: float = 0.0) -> Rule:
    """무장 트레일링 — 수익이 +arm% 를 찍은 뒤에만 트레일링을 켠다."""
    def rule(s: State) -> str:
        if stop and -s.gain >= stop:
            return "손절"
        if s.peak_gain >= arm and s.drop_from_peak >= trail:
            return "트레일링"
        return ""
    return rule


def vol_scaled(stop_k: float, trail_k: float) -> Rule:
    """청산선을 그날 실현변동성의 배수로 — 조용한 장에선 좁게, 거친 장에선 넓게."""
    def rule(s: State) -> str:
        if stop_k and -s.gain >= stop_k * s.vol:
            return "손절"
        if trail_k and s.drop_from_peak >= trail_k * s.vol:
            return "최고가"
        return ""
    return rule


def none_rule() -> Rule:
    return lambda s: ""


def simulate(
    rule: Rule,
    days: list[str],
    trade_code: dict[str, str],
    vols: dict[str, float],
    take_profit: tuple[float, float] | None = None,
):
    """분 단위 폴링으로 한 청산 규칙을 재현. Returns (수익률%, 포지션별 손익률, 사유 분포, MDD).

    Args:
        take_profit: (익절선%, 청산 비율). 예 (5.0, 0.5) = +5% 도달 시 절반만 익절하고
            나머지는 규칙대로 계속 굴린다. None 이면 부분 익절 없음.
    """
    pool = float(SEED)
    pos = None
    blocked = None
    rets: list[float] = []
    kinds: dict[str, int] = {}
    curve = [pool]

    for date in days:
        # 익일 개장 첫 폴링 — 남은 포지션 청산 (보유기간 만료)
        if pos:
            hit = price_at(fetch_minutes(pos["code"], date), "0900")
            if hit:
                proceeds = hit[1] * pos["qty"] * (1 - FEE_RATE)
                pool += proceeds - pos["invested"]
                rets.append((pos.get("pnl", 0.0) + proceeds - pos["invested"])
                            / pos.get("cost", pos["invested"]) * 100)
                kinds["보유만료"] = kinds.get("보유만료", 0) + 1
                pos = None

        code = trade_code.get(date)
        if not code or blocked == date or pool <= 0:
            curve.append(pool)
            continue

        bars = fetch_minutes(code, date)
        hit = price_at(bars, "0900")
        if not hit:
            curve.append(pool)
            continue
        entry_time, entry = hit
        qty = int(pool // (entry * (1 + FEE_RATE)))
        if qty <= 0:
            curve.append(pool)
            continue
        pos = {"code": code, "entry": entry, "qty": qty,
               "invested": qty * entry * (1 + FEE_RATE), "peak": entry}

        pos["pnl"] = 0.0          # 부분 익절분까지 합산한 포지션 총손익
        pos["cost"] = pos["invested"]   # 승률·수익률 계산용 최초 투입액
        times = [t for t in sorted(bars) if t > entry_time]
        for i, t in enumerate(times):
            price = bars[t]
            pos["peak"] = max(pos["peak"], price)
            state = State(
                gain=(price - entry) / entry * 100,
                drop_from_peak=(pos["peak"] - price) / pos["peak"] * 100,
                peak_gain=(pos["peak"] - entry) / entry * 100,
                minutes=i + 1,
                vol=vols[date],
            )
            # 부분 익절 — 한 번만, 지정 비율만 팔고 나머지는 계속 굴린다.
            if take_profit and not pos.get("tp_done") and state.gain >= take_profit[0]:
                sell_qty = int(pos["qty"] * take_profit[1])
                if 0 < sell_qty <= pos["qty"]:
                    part_cost = pos["invested"] * sell_qty / pos["qty"]
                    proceeds = price * sell_qty * (1 - FEE_RATE)
                    pool += proceeds - part_cost
                    pos["pnl"] += proceeds - part_cost
                    pos["qty"] -= sell_qty
                    pos["invested"] -= part_cost
                    kinds["부분익절"] = kinds.get("부분익절", 0) + 1
                pos["tp_done"] = True
                if pos["qty"] <= 0:
                    rets.append(pos["pnl"] / pos["cost"] * 100)
                    pos = None
                    break

            kind = rule(state)
            if kind:
                proceeds = price * pos["qty"] * (1 - FEE_RATE)
                pool += proceeds - pos["invested"]
                pos["pnl"] += proceeds - pos["invested"]
                rets.append(pos["pnl"] / pos["cost"] * 100)
                kinds[kind] = kinds.get(kind, 0) + 1
                blocked = date       # 손실성 청산 → 당일 재진입 차단
                pos = None
                break
        curve.append(pool)

    if pos:     # 마지막 날 미청산분은 종가 평가
        bars = fetch_minutes(pos["code"], days[-1])
        pool += bars[max(bars)] * pos["qty"] * (1 - FEE_RATE) - pos["invested"]

    peak = -1e18
    mdd = 0.0
    for v in curve:
        peak = max(peak, v)
        mdd = min(mdd, (v - peak) / peak * 100)
    return (pool / SEED - 1) * 100, rets, kinds, mdd


def stats(rets: list[float]) -> tuple[float, float, float]:
    if len(rets) < 2:
        return 0.0, 0.0, 0.0
    sd = st.stdev(rets)
    sharpe = (st.mean(rets) / sd * (250 ** 0.5)) if sd else 0.0
    win = sum(1 for r in rets if r > 0) / len(rets) * 100
    return st.mean(rets), sharpe, win


def main() -> None:
    _load_cache()
    days = [d for d in proxy_dates if START <= d <= END]

    trade_code, vols = {}, {}
    for d in days:
        s = judge(d)
        if s:
            trade_code[d] = UP_CODE if s > 0 else DOWN_CODE
        idx = proxy_dates.index(d)
        closes = [proxy_bars[x]["close"] for x in reversed(proxy_dates[:idx])]
        vols[d] = realized_vol(closes) if len(closes) > 2 else 1.0

    train = [d for d in days if d <= TRAIN_END]
    test = [d for d in days if d > TRAIN_END]

    # ── 진단: 이익을 얼마나 반납하는가 (장중 청산 없이 익일 개장까지 보유했을 때) ──
    print("=" * 96)
    print("① 진단 — 장중 최고 이익(MFE) 대비 얼마나 반납하는가 (청산 규칙 없음 기준)")
    print("=" * 96)
    give_backs, mfes, maes = [], [], []
    for d, code in trade_code.items():
        bars = fetch_minutes(code, d)
        hit = price_at(bars, "0900")
        if not hit:
            continue
        entry_time, entry = hit
        after = [bars[t] for t in sorted(bars) if t > entry_time]
        if not after:
            continue
        mfe = (max(after) - entry) / entry * 100
        mae = (min(after) - entry) / entry * 100
        close = (after[-1] - entry) / entry * 100
        mfes.append(mfe)
        maes.append(mae)
        give_backs.append(mfe - close)
    print(f"  거래일 {len(mfes)}일 · 장중 최고 이익(MFE) 평균 {st.mean(mfes):+.2f}% "
          f"· 장중 최대 손실(MAE) 평균 {st.mean(maes):+.2f}%")
    print(f"  종가까지 반납한 이익 평균 {st.mean(give_backs):.2f}% · 중앙 {st.median(give_backs):.2f}%")
    for thr in (3, 5, 10):
        hit_up = [g for m, g in zip(mfes, give_backs) if m >= thr]
        print(f"  장중 +{thr}% 이상 찍은 날 {len(hit_up):>2}일 → 그중 평균 {st.mean(hit_up):.2f}%p 반납"
              if hit_up else f"  장중 +{thr}% 이상 찍은 날 없음")
    deep = [m for m in maes if m <= -5]
    print(f"  장중 -5% 이상 밀린 날 {len(deep)}일 · 그중 종가까지 회복해 플러스로 끝난 날 "
          f"{sum(1 for m, g, mm in zip(mfes, give_backs, maes) if mm <= -5 and (m - g) > 0)}일")

    # ── 규칙 비교 ──
    rules: list[tuple[str, Rule]] = [
        ("익일 개장 청산만 (장중 청산 없음)", none_rule()),
        ("고정 5 / 5 (예전 기본값)", fixed(5, 5)),
        ("고정 10 / 10 (현행)", fixed(10, 10)),
        ("고정 15 / 10", fixed(15, 10)),
        ("고정 10 / 15", fixed(10, 15)),
        ("고정 15 / 15", fixed(15, 15)),
        ("손절만 10 (트레일링 없음)", fixed(10, 0)),
        ("트레일링만 10 (손절 없음)", fixed(0, 10)),
        ("무장 트레일링 arm+3 / trail 3", armed(3, 3)),
        ("무장 트레일링 arm+5 / trail 3", armed(5, 3)),
        ("무장 트레일링 arm+5 / trail 5", armed(5, 5)),
        ("무장 트레일링 arm+8 / trail 5", armed(8, 5)),
        ("무장 arm+5 / trail 5 + 손절 15", armed(5, 5, stop=15)),
        ("변동성 배수 stop 2.0σ / trail 1.5σ", vol_scaled(2.0, 1.5)),
        ("변동성 배수 stop 2.5σ / trail 2.0σ", vol_scaled(2.5, 2.0)),
        ("현행 10/10 + 진입 후 30분 유예", fixed(10, 10, grace=30)),
        ("현행 10/10 + 진입 후 60분 유예", fixed(10, 10, grace=60)),
    ]
    # (이름, 규칙, 부분익절) — 부분 익절은 '이익 반납' 만 직접 겨냥한다.
    partials: list[tuple[str, Rule, tuple[float, float]]] = [
        ("부분익절 +3% 절반 + 익일청산", none_rule(), (3.0, 0.5)),
        ("부분익절 +5% 절반 + 익일청산", none_rule(), (5.0, 0.5)),
        ("부분익절 +5% 전량 (하드 익절)", none_rule(), (5.0, 1.0)),
        ("부분익절 +8% 절반 + 익일청산", none_rule(), (8.0, 0.5)),
        ("부분익절 +5% 절반 + 현행 10/10", fixed(10, 10), (5.0, 0.5)),
    ]

    print("\n" + "=" * 96)
    print("② 규칙별 성과 — train(2026-03~05) / test(2026-06~07) 분리")
    print("=" * 96)
    header = (f"{'규칙':<34} {'train':>9} {'Sh':>6} {'MDD':>7} │ "
              f"{'test':>9} {'Sh':>6} {'MDD':>7} │ {'전체':>9} {'Sh':>6} {'MDD':>7} {'장중':>5}")
    print(header)
    print("─" * len(header))
    for entry in rules + partials:
        name, rule = entry[0], entry[1]
        tp = entry[2] if len(entry) > 2 else None
        tr_ret, tr_rets, _, tr_mdd = simulate(rule, train, trade_code, vols, tp)
        te_ret, te_rets, _, te_mdd = simulate(rule, test, trade_code, vols, tp)
        al_ret, al_rets, al_kinds, al_mdd = simulate(rule, days, trade_code, vols, tp)
        _, tr_sharpe, _ = stats(tr_rets)
        _, te_sharpe, _ = stats(te_rets)
        _, al_sharpe, _ = stats(al_rets)
        intraday = sum(v for k, v in al_kinds.items() if k != "보유만료")
        print(f"{name:<34} {tr_ret:>+8.2f}% {tr_sharpe:>+6.2f} {tr_mdd:>6.1f}% │ "
              f"{te_ret:>+8.2f}% {te_sharpe:>+6.2f} {te_mdd:>6.1f}% │ "
              f"{al_ret:>+8.2f}% {al_sharpe:>+6.2f} {al_mdd:>6.1f}% {intraday:>4}회")

    # ── ③ 장중 청산이 실제로 돈을 아꼈는지 개별 검증 ──
    print("\n" + "=" * 96)
    print("③ 장중 청산 개별 검증 — 그때 팔지 않았다면(익일 개장까지 보유) 어땠나")
    print("=" * 96)
    for label, rule in (("현행 10/10", fixed(10, 10)),
                        ("변동성 2.0σ/1.5σ", vol_scaled(2.0, 1.5)),
                        ("변동성 2.5σ/2.0σ", vol_scaled(2.5, 2.0))):
        print(f"\n  [{label}]")
        saved = 0.0
        found = False
        for i, date in enumerate(days):
            code = trade_code.get(date)
            if not code:
                continue
            bars = fetch_minutes(code, date)
            hit = price_at(bars, "0900")
            if not hit:
                continue
            entry_time, entry = hit
            peak = entry
            for t in [x for x in sorted(bars) if x > entry_time]:
                price = bars[t]
                peak = max(peak, price)
                kind = rule(State(gain=(price - entry) / entry * 100,
                                  drop_from_peak=(peak - price) / peak * 100,
                                  peak_gain=(peak - entry) / entry * 100,
                                  minutes=1, vol=vols[date]))
                if not kind:
                    continue
                # 팔지 않았다면 받았을 가격 = 다음 거래일 09:00
                later = [d for d in days if d > date]
                nxt = DAILY[code].get(later[0]) if later else None
                if not nxt:
                    break
                diff = (price - nxt["open"]) / entry * 100   # + 면 판 게 이득
                saved += diff
                found = True
                print(f"    {date} {kind:>4} {t[:2]}:{t[2:]} 청산 {price:>9,.0f}원 "
                      f"(진입 {entry:>9,.0f} · {(price - entry) / entry * 100:+.2f}%) → "
                      f"익일 시가 {nxt['open']:>9,.0f}원 · 판 것이 {diff:+.2f}%p "
                      f"{'이득' if diff > 0 else '손해'}")
                break
        print(f"    → 장중 청산의 순효과 합계 {saved:+.2f}%p" if found else "    → 장중 청산 없음")

    recent_vol = vols[days[-1]]
    print(f"\n[현재 변동성 환산] 최근 일간 실현변동성 {recent_vol:.2f}% 기준 청산선:")
    for k_s, k_t in ((2.0, 1.5), (2.5, 2.0)):
        print(f"    {k_s}σ / {k_t}σ → 손절 -{k_s * recent_vol:.1f}% · 트레일링 -{k_t * recent_vol:.1f}% "
              f"(현행 고정 10% / 10%)")

    print(f"\ntrain {len(train)}일 · test {len(test)}일 · 시드 {SEED:,}원 · "
          f"수수료 {FEE_RATE * 100:.4f}% 편도 · 손실성 장중 청산 시 당일 재진입 차단")
    _save_cache()


if __name__ == "__main__":
    main()
