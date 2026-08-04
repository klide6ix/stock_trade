"""보유 이월 방식 비교 — 매일 청산 후 재매수(현행) vs 방향이 같으면 보유 유지.

현행은 보유기간 만료(1일)에 **방향과 무관하게** 전량 청산하고 그날 방향으로 재진입한다
([core/trader.py](../core/trader.py) `_short_term_exit` — "같은 종목이어도 무방"). 실측상
보유만료 청산 63건 중 33건이 **같은 종목 재매수**였다. 그럼 방향이 같은 날은 그냥 들고
가는 편이 나은가?

단순한 거래비용 문제가 아니라 **전략 변경**이다. 이월하면
  ① 트레일링 최고가(peak)가 며칠에 걸쳐 누적된다 (현행은 매 진입마다 매수가로 리셋)
  ② 손절선이 **최초 진입가** 기준이 되어 여러 날에 걸친 하락에도 발동할 수 있다
  ③ 청산선 σ 가 최초 진입일 값으로 고정된다 (현행은 매일 그날 σ 로 갱신)
  ④ 09:00 청산 → 09:05 재매수 사이의 5분 공백과 그 구간 평균회귀 이득이 사라진다

두 모드를 **같은 루프**(`simulate(carry=…)`)로 돌리고, `carry=False` 가
[_simulate_recent.py](_simulate_recent.py) `run()` 과 동일한 결과를 내는지 검증한다 —
서로 다른 코드 경로로 비교하면 차이가 모드 때문인지 구현 차이 때문인지 알 수 없다.
청산 판정은 두 모드 모두 구현체 `EtfDayTradeStrategy.should_sell` 에 위임한다.

조회 전용. 분봉 캐시(`data/.minute_bars_cache.json`)를 재사용한다.
"""
import argparse
import statistics as st
from datetime import datetime

from core.short_term import SELL_HOLDING_PERIOD, EtfDayTradeStrategy, mark_entry
from scripts._check_open_drift import (
    DOWN_CODE,
    FEE_RATE,
    UP_CODE,
    _load_cache,
    _save_cache,
    fetch_minutes,
    price_at,
)
from scripts._simulate_recent import (
    INTRADAY_EXITS,
    NAMES,
    SEED,
    daily_vols,
    judge_at_open,
    proxy_dates,
    run,
)

FIRST_DAY, LAST_DAY = "20260310", "20260724"     # 07-27~31(극단 변동 5일) 제외
ENTRY_AT = "0905"                                 # 현재 운영값 = 개장 후 5분


def simulate(days: list[str], vols: dict[str, float], strategy,
             entry_at: str = ENTRY_AT, carry: bool = False) -> dict:
    """일자별 시뮬레이션. `carry=True` 면 오늘 방향이 보유 종목과 같을 때 청산을 건너뛴다.

    `carry=False` 는 `_simulate_recent.run()` 과 동일한 규칙이다(검증으로 확인).
    청산 판정은 `strategy.should_sell` 에 위임하고, 이 함수는 **보유기간 만료를
    건너뛸지만** 결정한다 — 손절·트레일링은 이월 중에도 그대로 작동해야 한다.
    """
    pool = float(SEED)
    pos = None
    blocked = None
    rows, trades = [], []

    def close_out(price: float, date: str, kind: str) -> None:
        nonlocal pool, pos
        proceeds = price * pos["qty"] * (1 - FEE_RATE)
        pnl = proceeds - pos["invested"]
        pool += pnl
        trades.append({"진입일": pos["date"], "청산일": date, "종목": NAMES[pos["code"]],
                       "진입가": pos["entry"], "청산가": price, "수량": pos["qty"],
                       "사유": kind, "손익": pnl, "수익률": pnl / pos["invested"] * 100,
                       "보유일수": days.index(date) - days.index(pos["date"])})
        pos = None

    for n, date in enumerate(days, start=1):
        row = {"n": n, "date": date}
        bars_cache: dict[str, dict] = {}

        def bars_of(code: str) -> dict:
            if code not in bars_cache:
                bars_cache[code] = fetch_minutes(code, date)
            return bars_cache[code]

        # ── 오늘 방향 판정 (09:00 실측 갭) — 이월 판단에 필요하므로 청산보다 먼저 ──
        proxy_open = price_at(bars_of(UP_CODE), "0900")
        score = judge_at_open(date, proxy_open[1]) if proxy_open else None
        today_code = (UP_CODE if score > 0 else DOWN_CODE) if score else None
        if score is not None:
            row["score"] = score
            row["방향"] = "📈 상승" if score > 0 else "📉 하락"

        # ── 1. 09:00 첫 폴링 — 보유분 청산 판정 ──
        if pos:
            hit = price_at(bars_of(pos["code"]), "0900")
            if hit:
                _, price = hit
                pos["slot"]["peak"] = pos["peak"]
                decision = strategy.should_sell(
                    pos["slot"], price,
                    now=datetime.strptime(date + " 0900", "%Y%m%d %H%M"))
                # 방향이 같으면 보유기간 만료만 건너뛴다. 손절·트레일링은 이월 중에도
                # 그대로 청산해야 한다 — 그것까지 미루면 안전장치가 사라진다.
                # 방향을 못 정한 날(판정불가)은 '같다' 고 볼 수 없으므로 청산한다.
                keep = (carry and decision.sell
                        and decision.kind == SELL_HOLDING_PERIOD
                        and today_code is not None and today_code == pos["code"])
                if decision.sell and not keep:
                    kind = INTRADAY_EXITS.get(decision.kind, "보유만료")
                    close_out(price, date, kind)
                    if kind != "보유만료":
                        blocked = date
                elif keep:
                    row["비고"] = "방향 동일 — 보유 이월"

        # ── 2. 진입 (미보유 + 미차단) ──
        entry_time = None
        if pos is None and today_code and blocked != date and pool > 0:
            hit = price_at(bars_of(today_code), entry_at)
            if hit:
                entry_time, entry = hit
                qty = int(pool // (entry * (1 + FEE_RATE)))
                if qty > 0:
                    slot = mark_entry({"code": today_code, "vol": vols[date]}, entry, qty,
                                      now=datetime.strptime(date, "%Y%m%d"))
                    stop_pct, peak_pct, _ = strategy.exit_thresholds(slot)
                    pos = {"code": today_code, "entry": entry, "qty": qty, "date": date,
                           "invested": qty * entry * (1 + FEE_RATE), "peak": entry,
                           "slot": slot}
                    row.update(종목=NAMES[today_code], 진입가=entry, 수량=qty,
                               vol=vols[date], 손절선=stop_pct, 청산선=peak_pct)
        elif blocked == date:
            row["비고"] = "청산 후 당일 재진입 차단"

        # ── 3. 장중 폴링 — 최고가 갱신 + 청산 판정 ──
        # 오늘 진입했으면 진입 시각 이후, 이월된 포지션이면 09:00 이후 전 구간을 본다.
        # (`run()` 은 진입 직후만 폴링해도 됐다 — 이월이 없어 포지션이 하루를 넘기지
        #  않았기 때문이다. 이월 모드에서는 이월된 날도 폴링해야 손절이 작동한다.)
        if pos:
            bars = bars_of(pos["code"])
            start = entry_time or "0900"
            for t in sorted(bars):
                if t <= start:
                    continue
                price = bars[t]
                pos["peak"] = max(pos["peak"], price)
                pos["slot"]["peak"] = pos["peak"]
                decision = strategy.should_sell(
                    pos["slot"], price,
                    now=datetime.strptime(date + " " + t, "%Y%m%d %H%M"))
                if decision.sell and decision.kind in INTRADAY_EXITS:
                    close_out(price, date, f"{INTRADAY_EXITS[decision.kind]} {t[:2]}:{t[2:]}")
                    blocked = date
                    break

        equity = pool
        if pos:
            bars = bars_of(pos["code"])
            last = max(bars)
            equity += bars[last] * pos["qty"] * (1 - FEE_RATE) - pos["invested"]
        row["자산"] = equity
        rows.append(row)

    return {"rows": rows, "trades": trades, "pool": pool,
            "equity": rows[-1]["자산"] if rows else float(SEED), "pos": pos}


def stats(result: dict) -> dict:
    curve = [r["자산"] for r in result["rows"]]
    drets = [(b - a) / a for a, b in zip(curve, curve[1:]) if a > 0]
    peak, mdd = -1e18, 0.0
    for v in curve:
        peak = max(peak, v)
        mdd = min(mdd, (v - peak) / peak * 100) if peak > 0 else mdd
    rets = [t["수익률"] for t in result["trades"]]
    return {
        "equity": result["equity"],
        "ret": (result["equity"] / SEED - 1) * 100,
        "sharpe": (st.mean(drets) / st.stdev(drets) * (250 ** 0.5)
                   if len(drets) > 2 and st.stdev(drets) else 0),
        "mdd": mdd,
        "n": len(rets),
        "win": sum(1 for x in rets if x > 0) / len(rets) * 100 if rets else 0,
        "mean": st.mean(rets) if rets else 0,
        "sd": st.stdev(rets) if len(rets) > 1 else 0,
        "worst": min(rets) if rets else 0,
        "best": max(rets) if rets else 0,
        "hold": st.mean(t["보유일수"] for t in result["trades"]) if rets else 0,
    }


def report(label: str, s: dict, result: dict) -> None:
    kinds: dict[str, int] = {}
    for t in result["trades"]:
        kinds[t["사유"].split(" ")[0]] = kinds.get(t["사유"].split(" ")[0], 0) + 1
    print(f"\n{label}")
    print(f"  최종 자금   {s['equity']:>12,.0f}원  ({s['ret']:+.2f}%) · "
          f"실현 풀 {result['pool']:,.0f}원")
    print(f"  거래 {s['n']}회 · 승률 {s['win']:.0f}% · 거래당 {s['mean']:+.2f}%(σ {s['sd']:.2f}%) · "
          f"평균 보유 {s['hold']:.2f}일")
    print(f"  연환산 Sharpe {s['sharpe']:+.2f} · MDD {s['mdd']:.2f}% · "
          f"최고 {s['best']:+.2f}% / 최악 {s['worst']:+.2f}%")
    print(f"  청산 사유   {' '.join(f'{k}{v}' for k, v in sorted(kinds.items()))}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="보유 이월 방식 비교")
    ap.add_argument("--entry", default=ENTRY_AT, help=f"진입 시각 HHMM (기본 {ENTRY_AT})")
    args = ap.parse_args(argv)

    _load_cache()
    days_all = [d for d in proxy_dates if d <= LAST_DAY]
    days = [d for d in days_all if d >= FIRST_DAY]
    vols = daily_vols(days_all)
    strategy = EtfDayTradeStrategy()

    print(f"분석 구간 {days[0]} ~ {days[-1]} ({len(days)}영업일) · 시드 {SEED:,}원 · "
          f"09:{args.entry[2:]} 진입")
    print(f"청산선 {strategy.display_name.split(' · ', 2)[-1]} · "
          f"극단 변동 5일(07-27~31) 제외")
    print("=" * 78)

    # 검증: carry=False 가 기존 run() 과 같은 결과여야 한다.
    base = simulate(days, vols, strategy, args.entry, carry=False)
    ref = run(days, vols, strategy, entry_at=args.entry)
    ok = (abs(base["equity"] - ref["equity"]) < 1
          and len(base["trades"]) == len(ref["trades"]))
    print(f"[검증] carry=False vs _simulate_recent.run(): "
          f"{'✅ 일치' if ok else '❌ 불일치'} "
          f"({base['equity']:,.0f} vs {ref['equity']:,.0f}원 · "
          f"거래 {len(base['trades'])} vs {len(ref['trades'])}회)")
    assert ok, "동일 규칙에서 결과가 갈리면 이월 비교가 성립하지 않는다"

    carried = simulate(days, vols, strategy, args.entry, carry=True)
    sa, sb = stats(base), stats(carried)
    report("A. 현행 — 매일 청산 후 재매수 (peak 매일 리셋)", sa, base)
    report("B. 방향 같으면 보유 유지 (peak 이월)", sb, carried)

    # ── 이월이 실제로 몇 번 일어났나 ──
    kept = sum(1 for r in carried["rows"] if r.get("비고") == "방향 동일 — 보유 이월")
    multi = [t for t in carried["trades"] if t["보유일수"] > 1]
    print(f"\n이월 발생 {kept}일 · 2일 이상 보유한 포지션 {len(multi)}건 "
          f"(최장 {max((t['보유일수'] for t in multi), default=0)}일)")
    print(f"A 거래 {sa['n']}회 → B {sb['n']}회 (왕복 {sa['n'] - sb['n']}회 감소)")

    # ── 구간 분할 ──
    print("\n" + "=" * 78)
    print("구간 분할 (train 2026-03~05 / test 2026-06~07)")
    print("=" * 78)
    print(f"{'구간':>14} {'영업일':>6} {'A. 현행':>12} {'B. 이월':>12} {'차이':>10} "
          f"{'A Sharpe':>9} {'B Sharpe':>9}")
    for label, sub in (("train (03~05)", [d for d in days if d < "20260601"]),
                       ("test  (06~07)", [d for d in days if d >= "20260601"])):
        a = stats(simulate(sub, vols, strategy, args.entry, carry=False))
        b = stats(simulate(sub, vols, strategy, args.entry, carry=True))
        print(f"{label:>14} {len(sub):>6} {a['ret']:>+11.2f}% {b['ret']:>+11.2f}% "
              f"{b['ret'] - a['ret']:>+9.2f}%p {a['sharpe']:>+9.2f} {b['sharpe']:>+9.2f}")

    _save_cache()


if __name__ == "__main__":
    main()
