"""보유 방식 비교 — 1일 보유(오버나이트) vs 당일 마감 청산.

배경: 진입(09:00 시가) → 익일 09:00 시가 수익률의 σ 4.69% 중 **오버나이트 구간(당일 종가
→ 익일 시가)이 σ 3.28% 로 70%** 를 차지한다. 게다가 손절 -10% 는 장중 폴링에서만 작동해
갭에는 무력하다(실측: 78일 중 장중 발동 2일, 갭으로 우회 1일 — 2026-06-11 인버스가 장중
최저 -4.47% 였는데 익일 시가 -10.98%). 그렇다면 `close_at_market_end` 를 켜서 매일 청산하는
편이 나은가?

리스크만 보면 자명해 보이지만 **수익도 같이 사라지므로** 실제 손익으로 판정해야 한다.
`data/.minute_bars_cache.json` 의 1분봉으로 트레이더의 1분 폴링을 그대로 재현해 두 모드를
같은 날짜·같은 방향 판정으로 돌린다.

  A. 1일 보유 (현행)      — 익일 09:00 개장 첫 폴링에 청산 후 그날 방향으로 재진입
  B. 당일 마감 청산       — 15:15 전량 청산, 다음 거래일 09:00 재진입 (오버나이트 미보유)

조회 전용. 분봉 캐시가 없으면 [_check_open_drift.py](_check_open_drift.py) 를 먼저 실행한다.
"""
import statistics as st

from scripts._check_open_drift import (
    DAILY,
    DOWN_CODE,
    END,
    FEE_RATE,
    PEAK_PCT,
    SEED,
    START,
    STOP_PCT,
    UP_CODE,
    fetch_minutes,
    judge,
    price_at,
    proxy_dates,
)

FORCE_CLOSE_AT = "1515"     # core/short_term.py::FORCE_CLOSE_TIME


def simulate(days: list[str], trade_code: dict[str, str], close_at_market_end: bool):
    """분 단위 폴링으로 한 모드를 재현. Returns (equity_curve, trades, daily_returns)."""
    pool = float(SEED)
    pos = None
    blocked = None
    trades: list[tuple] = []
    curve: list[tuple[str, float]] = []
    rets: list[float] = []

    def close_out(price: float, date: str, kind: str) -> None:
        nonlocal pool, pos
        proceeds = price * pos["qty"] * (1 - FEE_RATE)
        pnl = proceeds - pos["invested"]
        rets.append(pnl / pos["invested"] * 100)
        pool += pnl
        trades.append((date, kind, pnl))
        pos = None

    for date in days:
        bars_cache: dict[str, dict[str, float]] = {}

        def bars_of(code: str) -> dict[str, float]:
            if code not in bars_cache:
                bars_cache[code] = fetch_minutes(code, date)
            return bars_cache[code]

        # ── 1. 개장 첫 폴링 — 1일 보유 모드는 여기서 전날 포지션을 청산한다 ──
        if pos:
            hit = price_at(bars_of(pos["code"]), "0900")
            if hit:
                _, price = hit
                drop_entry = (pos["entry"] - price) / pos["entry"] * 100
                drop_peak = (pos["peak"] - price) / pos["peak"] * 100
                kind = ("손절" if drop_entry >= STOP_PCT
                        else "최고가" if drop_peak >= PEAK_PCT else "보유만료")
                close_out(price, date, kind)
                if kind != "보유만료":
                    blocked = date

        code = trade_code.get(date)
        if not code or blocked == date or pool <= 0:
            curve.append((date, pool))
            continue

        # ── 2. 진입 (09:00 첫 폴링) ──
        bars = bars_of(code)
        hit = price_at(bars, "0900")
        if not hit:
            curve.append((date, pool))
            continue
        entry_time, entry = hit
        qty = int(pool // (entry * (1 + FEE_RATE)))
        if qty <= 0:
            curve.append((date, pool))
            continue
        pos = {"code": code, "entry": entry, "qty": qty,
               "invested": qty * entry * (1 + FEE_RATE), "peak": entry}

        # ── 3. 장중 폴링 — 최고가 갱신 + 청산 판정 (+ 마감 강제청산) ──
        for t in sorted(bars):
            if t <= entry_time:
                continue
            price = bars[t]
            pos["peak"] = max(pos["peak"], price)
            drop_entry = (pos["entry"] - price) / pos["entry"] * 100
            drop_peak = (pos["peak"] - price) / pos["peak"] * 100
            if drop_entry >= STOP_PCT or drop_peak >= PEAK_PCT:
                close_out(price, date, "손절" if drop_entry >= STOP_PCT else "최고가")
                blocked = date
                break
            if close_at_market_end and t >= FORCE_CLOSE_AT:
                close_out(price, date, "마감청산")
                blocked = date
                break

        equity = pool
        if pos:    # 보유 중이면 평가액을 얹어 곡선을 연속으로 만든다
            last = max(bars)
            equity += bars[last] * pos["qty"] * (1 - FEE_RATE) - pos["invested"]
        curve.append((date, equity))

    return curve, trades, rets


def mdd(curve: list[tuple[str, float]]) -> float:
    peak = -1e18
    worst = 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            worst = min(worst, (v - peak) / peak * 100)
    return worst


def report(name: str, curve, trades, rets) -> None:
    final = curve[-1][1]
    wins = [r for r in rets if r > 0]
    kinds: dict[str, int] = {}
    for _, kind, _pnl in trades:
        kinds[kind] = kinds.get(kind, 0) + 1
    sharpe = (st.mean(rets) / st.stdev(rets) * (250 ** 0.5)) if len(rets) > 2 and st.stdev(rets) else 0
    print(f"\n{name}")
    print(f"  최종 자금   {final:>12,.0f}원  ({(final / SEED - 1) * 100:+.2f}%)")
    print(f"  거래당 손익 평균 {st.mean(rets):+.2f}% · σ {st.stdev(rets):.2f}% · "
          f"승률 {len(wins) / len(rets) * 100:.0f}% ({len(rets)}회) · 최악 {min(rets):+.2f}%")
    print(f"  연환산 Sharpe {sharpe:+.2f} · MDD {mdd(curve):.2f}%")
    print(f"  청산 사유   {' '.join(f'{k}{v}' for k, v in sorted(kinds.items()))}")


def main() -> None:
    days = [d for d in proxy_dates if START <= d <= END]
    trade_code = {}
    for d in days:
        s = judge(d)
        if s:
            trade_code[d] = UP_CODE if s > 0 else DOWN_CODE

    print(f"분석 구간 {days[0]} ~ {days[-1]} ({len(days)}영업일 / 판정 성립 {len(trade_code)}일)")
    print(f"손절 -{STOP_PCT:g}% · 최고가 -{PEAK_PCT:g}% · 시드 {SEED:,}원 · 수수료 {FEE_RATE * 100:.4f}% 편도")
    print("=" * 78)

    results = {}
    for label, flag in (("A. 1일 보유 (현행 — 오버나이트 보유)", False),
                        ("B. 당일 마감 청산 (15:15, 오버나이트 미보유)", True)):
        curve, trades, rets = simulate(days, trade_code, flag)
        report(label, curve, trades, rets)
        results[label] = (curve, trades, rets)

    # ── 구간 분해: 수익이 장중에서 나오나, 밤사이에 나오나 ──
    print("\n" + "=" * 78)
    print("구간 분해 (청산 규칙 없이 순수 보유 수익률)")
    print("=" * 78)
    # 주의: '다음 날도 같은 방향이라 종목이 유지되는 날' 로 좁히면 안 된다. 다음 날 방향은
    # 갭 신호(가중치 0.50)가 그날 시가로 결정하므로, 그 조건은 곧 '익일 시가가 유리하게
    # 움직인 날' 을 고르는 look-ahead 선택 편향이 된다(그렇게 집계하면 오버나이트 승률이
    # 93%까지 부풀었다). 보유 종목을 **다음 날 방향과 무관하게** 그대로 들고 있었다고 보고
    # 익일 시가까지의 수익률을 전부 집계한다.
    intraday, overnight = [], []
    ordered = [d for d in days if d in trade_code]
    for i, d in enumerate(ordered):
        code = trade_code[d]
        bars = fetch_minutes(code, d)
        o, c = price_at(bars, "0900"), price_at(bars, "1515")
        if not (o and c):
            continue
        intraday.append((c[1] - o[1]) / o[1] * 100)
        # 익일 시가는 방향과 무관하게 같은 종목의 일봉에서 가져온다.
        later = [x for x in days if x > d]
        nxt_bar = DAILY[code].get(later[0]) if later else None
        if nxt_bar and nxt_bar.get("open"):
            overnight.append((nxt_bar["open"] - c[1]) / c[1] * 100)

    def line(label, v):
        print(f"  {label} 평균 {st.mean(v):+.2f}% · σ {st.stdev(v):.2f}% · "
              f"승률 {sum(1 for x in v if x > 0) / len(v) * 100:.0f}% · "
              f"Sharpe(일) {st.mean(v) / st.stdev(v):+.3f} (n={len(v)})")

    line("장중       (09:00 → 15:15)     ", intraday)
    line("오버나이트 (15:15 → 익일 09:00)", overnight)
    print(f"  최악 오버나이트 {min(overnight):+.2f}% · 5% 분위 {st.quantiles(overnight, n=20)[0]:+.2f}%")


if __name__ == "__main__":
    main()
