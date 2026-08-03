"""보유 방식 비교 — 1일 보유(오버나이트) vs 당일 마감 청산.

질문: "매일 장 마감 전에 청산하는 편이 다음날까지 들고 가는 것보다 유리한가?"

리스크만 보면 자명해 보인다. 진입(09:00) → 익일 09:00 수익률의 변동 중 **오버나이트 구간이
70%** 를 차지하고, 청산선은 장중 폴링에서만 작동해 **갭에는 무력**하다. 그런데 수익도 같은
구간에서 나오므로 실제 손익으로 판정해야 한다.

이 스크립트는 [_simulate_recent.py](_simulate_recent.py) 의 `run()` 본체를 그대로 쓰고
**전략 인스턴스만 바꿔** 두 모드를 돌린다 — 청산 판정은 구현체 `EtfDayTradeStrategy.should_sell`
에 위임되므로 현행 청산선(진입 시점 σ 의 배수: 손절 2.5σ · 트레일링 2.0σ, 5~15% 클램프)이
양쪽에 동일하게 적용된다. 규칙을 스크립트에서 재구현하지 않으므로 코드와 시뮬레이션이
어긋날 수 없다.

  A. 1일 보유 (현행)   — close_at_market_end=False, 익일 09:00 개장 첫 폴링에 청산 후 재진입
  B. 당일 마감 청산    — close_at_market_end=True, 15:15 전량 청산 (오버나이트 미보유)

장중은 1분봉 종가를 폴링 가격으로 써서 `CHECK_INTERVAL=60s` 루프를 재현한다.
조회 전용. 분봉 캐시가 없으면 [_check_open_drift.py](_check_open_drift.py) 를 먼저 실행한다.
"""
import statistics as st

from core.short_term import EtfDayTradeStrategy
from scripts._check_open_drift import (
    DAILY,
    DOWN_CODE,
    UP_CODE,
    _load_cache,
    _save_cache,
    fetch_minutes,
    price_at,
    proxy_bars,
    proxy_dates,
)
from scripts._simulate_recent import SEED, daily_vols, judge_at_open, run

FIRST_DAY = "20260310"      # 분봉 캐시가 덮는 첫 거래일
LAST_DAY = "20260731"

# 변동성이 극단적이라 결론을 왜곡할 수 있는 구간 — 이 날짜부터 표본에서 뺀 결과를 함께 낸다.
# 이 5거래일(07-27~31)은 표본의 **마지막 주**라 제외 = 단순 절단이다. 중간 구간을 도려내면
# 그 앞뒤가 이어붙어 존재하지 않던 오버나이트가 생기므로, 그 경우엔 이 방식을 쓸 수 없다.
EXCLUDE_FROM = "20260727"


def sharpe_from_curve(rows: list[dict]) -> float:
    """평가자산 곡선의 **일별** 수익률 기준 연환산 Sharpe.

    거래당 수익률로 계산하면 두 모드의 거래 빈도가 달라질 때 비교가 흔들린다.
    자산 곡선은 매 거래일 한 점씩이라 빈도에 중립적이다.
    """
    vals = [r["자산"] for r in rows]
    rets = [(b - a) / a for a, b in zip(vals, vals[1:]) if a > 0]
    if len(rets) < 3 or not st.stdev(rets):
        return 0.0
    return st.mean(rets) / st.stdev(rets) * (250 ** 0.5)


def mdd(rows: list[dict]) -> float:
    peak, worst = -1e18, 0.0
    for r in rows:
        peak = max(peak, r["자산"])
        if peak > 0:
            worst = min(worst, (r["자산"] - peak) / peak * 100)
    return worst


def report(name: str, result: dict) -> None:
    rows, trades = result["rows"], result["trades"]
    final = result["equity"]
    rets = [t["수익률"] for t in trades]
    wins = [r for r in rets if r > 0]
    kinds: dict[str, int] = {}
    for t in trades:
        k = t["사유"].split("(")[0]
        kinds[k] = kinds.get(k, 0) + 1
    print(f"\n{name}")
    print(f"  최종 자금   {final:>12,.0f}원  ({(final / SEED - 1) * 100:+.2f}%) · "
          f"실현 풀 {result['pool']:,.0f}원")
    print(f"  거래당 손익 평균 {st.mean(rets):+.2f}% · σ {st.stdev(rets):.2f}% · "
          f"승률 {len(wins) / len(rets) * 100:.0f}% ({len(rets)}회) · 최악 {min(rets):+.2f}%")
    print(f"  연환산 Sharpe {sharpe_from_curve(rows):+.2f} (일별 자산곡선 기준) · "
          f"MDD {mdd(rows):.2f}%")
    print(f"  청산 사유   {' '.join(f'{k}{v}' for k, v in sorted(kinds.items()))}")


def analyze(days: list[str], vols: dict[str, float], title: str) -> dict:
    """한 표본에 대해 A/B 비교 + 구간 분해 + train/test 분할을 출력.

    Returns:
        {"A": result, "B": result} — 호출자가 표본 간 비교에 쓴다.
    """
    base = EtfDayTradeStrategy()
    print("\n" + "#" * 78)
    print(f"# {title}")
    print("#" * 78)
    print(f"분석 구간 {days[0]} ~ {days[-1]} ({len(days)}영업일) · 시드 {SEED:,}원")
    print(f"청산선 {base.display_name.split(' · ', 2)[-1]} — 두 모드 동일 적용")
    print("=" * 78)

    results = {}
    for label, flag in (("A. 1일 보유 (현행 — 오버나이트 보유)", False),
                        ("B. 당일 마감 청산 (15:15, 오버나이트 미보유)", True)):
        strategy = EtfDayTradeStrategy(close_at_market_end=flag)
        results[label] = run(days, vols, strategy)
        report(label, results[label])

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
    for i, d in enumerate(days):
        proxy_open = price_at(fetch_minutes(UP_CODE, d), "0900")
        score = judge_at_open(d, proxy_open[1]) if proxy_open else None
        if not score:
            continue
        code = UP_CODE if score > 0 else DOWN_CODE
        bars = fetch_minutes(code, d)
        o, c = price_at(bars, "0900"), price_at(bars, "1515")
        if not (o and c):
            continue
        intraday.append((c[1] - o[1]) / o[1] * 100)
        later = days[i + 1:]
        nxt = DAILY[code].get(later[0]) if later else None
        if nxt and nxt.get("open"):
            overnight.append((nxt["open"] - c[1]) / c[1] * 100)

    def line(label, v):
        se = st.stdev(v) / len(v) ** 0.5
        print(f"  {label} 평균 {st.mean(v):+.2f}% · σ {st.stdev(v):.2f}% · "
              f"승률 {sum(1 for x in v if x > 0) / len(v) * 100:.0f}% · "
              f"Sharpe(일) {st.mean(v) / st.stdev(v):+.3f} · "
              f"t {st.mean(v) / se:+.2f} (n={len(v)})")

    line("장중       (09:00 → 15:15)     ", intraday)
    line("오버나이트 (15:15 → 익일 09:00)", overnight)
    print(f"  최악 오버나이트 {min(overnight):+.2f}% · "
          f"5% 분위 {st.quantiles(overnight, n=20)[0]:+.2f}%")
    # 두 구간의 우열은 짝지어 봐야 한다 — 같은 날의 두 leg 는 같은 국면을 공유하므로
    # 독립 표본 검정보다 짝지은 차이(장중 - 오버나이트)의 t 가 검정력이 높다.
    pairs = [a - b for a, b in zip(intraday, overnight)]
    se_p = st.stdev(pairs) / len(pairs) ** 0.5
    print(f"  짝지은 차이(장중 − 오버나이트) 평균 {st.mean(pairs):+.2f}%p · "
          f"t {st.mean(pairs) / se_p:+.2f} (n={len(pairs)}) — "
          f"{'유의' if abs(st.mean(pairs) / se_p) > 2 else '유의하지 않음'}")

    # ── 표본 외 확인: 앞뒤 절반으로 갈라도 순위가 유지되는가 ──
    print("\n" + "=" * 78)
    print("구간 분할 (train 2026-03~05 / test 2026-06~07)")
    print("=" * 78)
    splits = {"train (03~05)": [d for d in days if d < "20260601"],
              "test  (06~07)": [d for d in days if d >= "20260601"]}
    print(f"{'구간':>14} {'영업일':>6} {'A. 1일 보유':>13} {'B. 마감 청산':>13} {'차이':>10}")
    for label, sub in splits.items():
        a = run(sub, vols, EtfDayTradeStrategy(close_at_market_end=False))
        b = run(sub, vols, EtfDayTradeStrategy(close_at_market_end=True))
        ra_ = (a["equity"] / SEED - 1) * 100
        rb_ = (b["equity"] / SEED - 1) * 100
        print(f"{label:>14} {len(sub):>6} {ra_:>+12.2f}% {rb_:>+12.2f}% {ra_ - rb_:>+9.2f}%p")

    # ── 동일 변동성 환산: A 를 B 만큼 줄여도 기대수익이 남는가 ──
    ra = [t["수익률"] for t in results["A. 1일 보유 (현행 — 오버나이트 보유)"]["trades"]]
    rb = [t["수익률"] for t in results["B. 당일 마감 청산 (15:15, 오버나이트 미보유)"]["trades"]]
    scale = st.stdev(rb) / st.stdev(ra)
    print(f"\n동일 변동성 환산: A 를 ×{scale:.3f} 로 축소하면 거래당 σ 가 B 와 같아진다 → "
          f"기대수익 {st.mean(ra) * scale:+.2f}% vs B {st.mean(rb):+.2f}%")
    return {"A": results["A. 1일 보유 (현행 — 오버나이트 보유)"],
            "B": results["B. 당일 마감 청산 (15:15, 오버나이트 미보유)"]}


def main() -> None:
    _load_cache()
    days_all = [d for d in proxy_dates if d <= LAST_DAY]
    full = [d for d in days_all if d >= FIRST_DAY]
    trimmed = [d for d in full if d < EXCLUDE_FROM]
    vols = daily_vols(days_all)

    # 제외 구간이 표본 끝에 붙어 있어야 절단으로 처리할 수 있다.
    assert trimmed == full[:len(trimmed)], "제외 구간이 표본 중간이면 절단이 성립하지 않는다"

    describe_excluded(days_all)
    out = {
        "제외 후": analyze(trimmed, vols,
                        f"제외 후 — {EXCLUDE_FROM}~{LAST_DAY} 5거래일 제외 ({len(trimmed)}영업일)"),
        "전체": analyze(full, vols, f"전체 {len(full)}영업일 (참고 — 제외 전)"),
    }
    _save_cache()

    print("\n" + "=" * 78)
    print("표본 간 비교 — 제외 구간이 결론을 만들고 있었나")
    print("=" * 78)
    print(f"{'표본':>10} {'영업일':>6} {'A. 1일 보유':>13} {'B. 마감 청산':>13} {'차이':>10} "
          f"{'A Sharpe':>9} {'B Sharpe':>9}")
    for label, res in out.items():
        ra_ = (res["A"]["equity"] / SEED - 1) * 100
        rb_ = (res["B"]["equity"] / SEED - 1) * 100
        n = len(res["A"]["rows"])
        print(f"{label:>10} {n:>6} {ra_:>+12.2f}% {rb_:>+12.2f}% {ra_ - rb_:>+9.2f}%p "
              f"{sharpe_from_curve(res['A']['rows']):>+9.2f} "
              f"{sharpe_from_curve(res['B']['rows']):>+9.2f}")


def describe_excluded(days_all: list[str]) -> None:
    """제외 구간이 실제로 얼마나 격했는지 — '변동성이 심하다' 는 전제를 수치로 확인."""
    print("=" * 78)
    print(f"제외 구간 {EXCLUDE_FROM} ~ {LAST_DAY} 실측 (KODEX 200 일봉)")
    print("=" * 78)
    body = [d for d in days_all if d >= EXCLUDE_FROM]
    rest = [d for d in days_all if FIRST_DAY <= d < EXCLUDE_FROM]

    def moves(ds):
        out = []
        for d in ds:
            i = proxy_dates.index(d)
            prev = proxy_bars[proxy_dates[i - 1]]["close"]
            out.append((proxy_bars[d]["close"] - prev) / prev * 100)
        return out

    ex, keep = moves(body), moves(rest)
    for d, m in zip(body, ex):
        print(f"  {d[:4]}-{d[4:6]}-{d[6:]}  전일대비 {m:+7.2f}%")
    print(f"  제외 5일 평균 |등락| {st.mean(map(abs, ex)):.2f}% · σ {st.stdev(ex):.2f}%")
    print(f"  나머지 {len(keep)}일 평균 |등락| {st.mean(map(abs, keep)):.2f}% · "
          f"σ {st.stdev(keep):.2f}%  → 제외 구간이 {st.stdev(ex) / st.stdev(keep):.1f}배 격함")


if __name__ == "__main__":
    main()
