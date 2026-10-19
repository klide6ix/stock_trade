"""재진입 차단 규칙 비교 — 사유만 보고 차단(옛 규칙) vs 그날 산 포지션만 차단(현행).

2026-10-19 운영에서 드러난 문제: 10-16 에 산 TIGER 200 이 개장 갭 -3.14% 로 09:00 첫
폴링에 최고가 청산(-5.55%, 청산선 -5.41%) 됐다. 보유기간 만료와 동시에 참이었지만
`should_sell` 이 최고가를 먼저 판정해 '손실성' 으로 분류됐고, 옛 규칙은 사유만 보고
그날 재진입을 막았다 — 하락 판정이 맞은 날 인버스를 사지 못했다.

현행 규칙(`core.short_term.blocks_reentry`)은 **오늘 진입한 포지션**의 손절·최고가 청산만
막는다. 이 스크립트는 두 규칙을 **같은 루프**(`_simulate_recent.run`)에 넣어 비교한다 —
달라지는 것은 차단 판정 함수 하나뿐이다.

보는 것
  ① 전 기간 자금 곡선 · 거래 수 · 승률 · Sharpe · MDD (09:00 즉시 / 09:05 지연 진입)
  ② **규칙이 갈린 날** 하나하나 — 옛 규칙이 막은 날 현행이 산 포지션의 결말
  ③ 구간 분할 — 앞 절반 / 뒤 절반을 각각 새 시드로 돌려 부호가 유지되는가
     (이 규칙에는 맞춘 파라미터가 없어 train/test 의 의미는 '시기를 바꿔도 같은가' 다)
  ④ **청산선 여유별 재진입 손익** — ②는 표본이 작고, 시뮬레이션의 최고가는 1분봉 종가라
     실제 체결 고가보다 낮아 이런 날을 **과소 계상**한다(10-19 실계좌 TIGER 200 은 -5.55% 로
     걸렸지만 시뮬 KODEX 200 은 분봉 -5.32% · 일봉 고가로 잡아도 -5.39% 로 청산선 -5.41% 에
     못 미쳤다). 그래서 전일 포지션의 개장 청산을 '청산선까지 남은 거리' 로 나누고, 각 그룹에서
     그날 새로 산 포지션의 손익을 본다. 옛 규칙의 전제('개장 갭이 어제 포지션을 친 날은 오늘
     판단도 틀린다')가 맞다면 경계·차단 그룹의 손익이 나머지보다 나빠야 한다.

조회 전용(주문 없음). 분봉은 `data/.minute_bars_cache.json` 캐시를 재사용하고 없는 날만 받는다.
"""
import argparse
import statistics as st

from scripts._check_open_drift import DAILY, DOWN_CODE, UP_CODE, _load_cache, _save_cache
from scripts._simulate_recent import SEED, daily_vols, proxy_dates, run

FIRST_DAY = "20260407"          # 20일 이평선 warm-up 이 끝난 첫 매매일
ENTRIES = ("0900", "0905")


def legacy_rule(decision, slot, now) -> bool:
    """옛 규칙 — 진입일과 무관하게 손절·최고가·마감 사유면 차단."""
    return not decision.allows_reentry_today


def stats(result: dict, seed: float = SEED) -> dict:
    curve = [r["자산"] for r in result["rows"]]
    drets = [(b - a) / a for a, b in zip(curve, curve[1:]) if a > 0]
    peak, mdd = -1e18, 0.0
    for v in curve:
        peak = max(peak, v)
        mdd = min(mdd, (v - peak) / peak * 100) if peak > 0 else mdd
    rets = [t["수익률"] for t in result["trades"]]
    return {
        "ret": (result["equity"] / seed - 1) * 100,
        "sharpe": (st.mean(drets) / st.stdev(drets) * (250 ** 0.5)
                   if len(drets) > 2 and st.stdev(drets) else 0.0),
        "mdd": mdd,
        "n": len(rets),
        "win": sum(1 for x in rets if x > 0) / len(rets) * 100 if rets else 0.0,
        "mean": st.mean(rets) if rets else 0.0,
    }


def line(label: str, s: dict) -> str:
    return (f"{label:<26} {s['ret']:>+9.2f}% {s['n']:>5} {s['win']:>5.0f}% "
            f"{s['mean']:>+7.2f}% {s['sharpe']:>+7.2f} {s['mdd']:>8.2f}%")


def diverged_days(old: dict, new: dict) -> list[dict]:
    """옛 규칙은 막았는데 현행은 진입한 날 — 현행 포지션의 결말을 붙여 돌려준다."""
    out = []
    for o, n in zip(old["rows"], new["rows"]):
        if o.get("비고") == "청산 후 당일 재진입 차단" and n.get("종목"):
            out.append({"date": n["date"], "방향": n.get("방향", ""), "종목": n["종목"],
                        "사유": n.get("사유", "보유 중"), "손익": n.get("손익"),
                        "수익률": n.get("수익률"), "trigger": n.get("비고", "")})
    return out


CODES = {"KODEX 200": UP_CODE, "KODEX 인버스": DOWN_CODE}
MARGIN_GROUPS = (("차단권 (여유 ≥ 0)", 0.0), ("경계 (여유 -1~0%p)", -1.0), ("나머지", -1e9))


def exit_margin(row: dict) -> float:
    """전일 포지션이 개장가에서 청산선을 얼마나 넘었나(%p, 양수면 청산). 최고가는 일봉 고가 —
    분봉 종가보다 높아 실제 체결 고가에 가깝다(상한 쪽 근사)."""
    entry, px = row["진입가"], row["청산가"]
    peak = max(DAILY[CODES[row["종목"]]][row["date"]]["high"], entry)
    return max((peak - px) / peak * 100 - row["청산선"],
               (entry - px) / entry * 100 - row["손절선"])


def reentry_by_margin(result: dict) -> dict[str, list[tuple[str, float, float]]]:
    """다음 날 개장 청산된 포지션을 청산선 여유로 묶고, 그날 새로 산 포지션 손익을 붙인다.

    현행 규칙 결과를 넣는다 — 옛 규칙이라면 차단권 그룹은 진입하지 않았을 날이다.
    아직 안 닫힌 포지션(기간 마지막 날)은 그날 종가로 평가한다.
    """
    by_date = {r["date"]: r for r in result["rows"]}
    groups: dict[str, list] = {label: [] for label, _ in MARGIN_GROUPS}
    for r in result["rows"]:
        nxt = by_date.get(r.get("청산일") or "")
        if nxt is None or nxt is r or not nxt.get("종목"):
            continue
        ret = nxt.get("수익률")
        if ret is None:
            ret = (nxt["종가"] / nxt["진입가"] - 1) * 100
        m = exit_margin(r)
        label = next(lbl for lbl, floor in MARGIN_GROUPS if m >= floor)
        groups[label].append((nxt["date"], m, ret))
    return groups


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="재진입 차단 규칙 비교")
    ap.add_argument("--start", default=FIRST_DAY, help=f"시작일 YYYYMMDD (기본 {FIRST_DAY})")
    ap.add_argument("--end", default=proxy_dates[-1], help="종료일 YYYYMMDD (기본 마지막 일봉)")
    args = ap.parse_args(argv)

    _load_cache()
    days_all = [d for d in proxy_dates if d <= args.end]
    days = [d for d in days_all if d >= args.start]
    vols = daily_vols(days_all)
    half = len(days) // 2
    print(f"구간 {days[0]} ~ {days[-1]} ({len(days)}거래일) · 시드 {SEED:,}원 · "
          f"청산 판정·차단 판정 모두 운영 구현체 호출\n")

    for entry in ENTRIES:
        old = run(days, vols, entry_at=entry, reentry_rule=legacy_rule)
        new = run(days, vols, entry_at=entry)
        so, sn = stats(old), stats(new)
        print("=" * 78)
        print(f"09:{entry[2:]} 진입")
        print("=" * 78)
        print(f"{'규칙':<26} {'수익률':>10} {'거래':>5} {'승률':>6} {'거래당':>8} "
              f"{'Sharpe':>7} {'MDD':>9}")
        print(line("A. 옛 규칙 (사유만 보고 차단)", so))
        print(line("B. 현행 (그날 산 포지션만)", sn))
        print(f"{'B - A':<26} {sn['ret'] - so['ret']:>+9.2f}%p {sn['n'] - so['n']:>+5}")

        days_diff = diverged_days(old, new)
        print(f"\n규칙이 갈린 날 {len(days_diff)}일 (옛 규칙이 막고 현행이 진입)")
        closed = [d for d in days_diff if d["수익률"] is not None]
        for d in days_diff:
            res = (f"{d['수익률']:+6.2f}% ({d['손익']:+,.0f}원) {d['사유']}"
                   if d["수익률"] is not None else "보유 중 (기간 끝)")
            print(f"  {d['date']} {d['방향']} {d['trigger']:<18} → {d['종목']:<10} {res}")
        if closed:
            wins = sum(1 for d in closed if d["수익률"] > 0)
            rets = [d["수익률"] for d in closed]
            print(f"  → 결말 확정 {len(closed)}건 · 승 {wins}건 · 평균 {st.mean(rets):+.2f}% · "
                  f"중앙값 {st.median(rets):+.2f}%"
                  + (f" · 표준오차 {st.stdev(rets) / len(rets) ** 0.5:.2f}%p"
                     if len(rets) > 1 else ""))

        print(f"\n구간 분할 (각 구간 새 시드 {SEED:,}원)")
        for label, sub in ((f"앞 {days[0]}~{days[half - 1]}", days[:half]),
                           (f"뒤 {days[half]}~{days[-1]}", days[half:])):
            a = stats(run(sub, vols, entry_at=entry, reentry_rule=legacy_rule))
            b = stats(run(sub, vols, entry_at=entry))
            print(f"  {label}  A {a['ret']:>+8.2f}% · B {b['ret']:>+8.2f}% · "
                  f"차이 {b['ret'] - a['ret']:>+7.2f}%p · Sharpe {a['sharpe']:+.2f} → {b['sharpe']:+.2f}")

        print("\n청산선 여유별 — 전일 포지션 개장 청산 다음 그날 새 포지션 손익 (현행 규칙)")
        for label, items in reentry_by_margin(new).items():
            rets = [x[2] for x in items]
            if not rets:
                print(f"  {label:<16} 0건")
                continue
            se = st.stdev(rets) / len(rets) ** 0.5 if len(rets) > 1 else 0.0
            print(f"  {label:<16} {len(rets):>3}건 · 승 {sum(1 for x in rets if x > 0):>3} · "
                  f"평균 {st.mean(rets):+.2f}% (표준오차 {se:.2f}%p)")
            if label != MARGIN_GROUPS[-1][0]:
                print("    " + " · ".join(f"{d[4:6]}-{d[6:]} 여유 {m:+.2f} → {r:+.2f}%"
                                         for d, m, r in items))
        print()

    _save_cache()


if __name__ == "__main__":
    main()
