"""최근 30거래일 시뮬레이션 — 300만원으로 시작했다면 지금 얼마인가 (일자별 표).

현재 알고리즘을 그대로 재현한다.
  - 방향 판정: 현행 가중치(갭 .50 / 전일 평균회귀 .25 / 이평선 .15 / 3일 .10) + 실현변동성 정규화
  - **갭 신호는 09:00 첫 폴링 가격**을 쓴다 — 개장 직후 최종 재판정(`trader.open_rejudge_window`)이
    실시간 등락률로 방향을 확정하므로, 예상체결가(추정)가 아니라 실제 개장가가 판정 근거다.
  - 진입: 판정과 같은 사이클(09:00 첫 폴링)에 그 가격으로 매수, 예산 = 자금 풀 전액
  - 청산(4중): **구현된 `EtfDayTradeStrategy.should_sell` 을 그대로 호출**한다 — 청산선은
    진입 시점 σ 의 배수(손절 2.5σ / 트레일링 2.0σ, 5~15% 클램프)로 산출된다
  - 손절·최고가 청산이면 그날 재진입 차단, 보유기간 만료는 같은 날 재진입
  - 자금 풀 복리 + 수수료 0.0042% 편도

장중은 1분봉 **종가**를 폴링 가격으로 써서 트레이더의 `CHECK_INTERVAL=60s` 루프를 그대로
재현한다 — 일봉 시뮬레이션과 달리 고가·저가 순서를 가정하지 않는다.

한계: 지정가 매수의 호가 스프레드(약 1틱)와 시장가 매도의 슬리피지는 반영하지 않는다.
조회 전용(주문 없음). 분봉은 `data/.minute_bars_cache.json` 캐시를 재사용한다.
"""
import statistics as st
from datetime import datetime

from core.market_direction import (
    MA_LONG,
    MA_SHORT,
    MOMENTUM_DAYS,
    NORM_GAP_MULT,
    NORM_MA_TREND_MULT,
    NORM_MOMENTUM_MULT,
    NORM_PREV_DAY_MULT,
    W_GAP,
    W_MA_TREND,
    W_MOMENTUM_3D,
    W_PREV_DAY_REVERSION,
    _clip,
    _norm,
    realized_vol,
)
from core.short_term import EtfDayTradeStrategy, mark_entry
from core.strategy.buy._indicators import sma
from scripts._check_open_drift import (
    DAILY,
    DOWN_CODE,
    FEE_RATE,
    PEAK_PCT,
    STOP_PCT,
    UP_CODE,
    _load_cache,
    _save_cache,
    fetch_minutes,
    price_at,
    proxy_bars,
    proxy_dates,
)

SEED = 3_000_000
DAYS_BACK = 30
STRATEGY = EtfDayTradeStrategy()      # 실제 구현체 — 청산 판정을 그대로 위임한다
LAST_DAY = "20260731"        # 분봉 캐시가 덮는 마지막 거래일
NAMES = {UP_CODE: "KODEX 200", DOWN_CODE: "KODEX 인버스"}


def judge_at_open(date: str, open_price: float) -> float | None:
    """09:00 첫 폴링 가격을 갭 신호로 써서 그날 방향 점수를 낸다 (확정 과거봉 + 실측 갭)."""
    idx = proxy_dates.index(date)
    past = [proxy_bars[d] for d in reversed(proxy_dates[:idx])]
    if len(past) < MA_LONG:
        return None
    closes = [b["close"] for b in past]
    vol = realized_vol(closes)
    total = wsum = 0.0

    def add(score, w):
        nonlocal total, wsum
        wsum += score * w
        total += abs(w)

    add(_norm((open_price - closes[0]) / closes[0] * 100, NORM_GAP_MULT * vol), W_GAP)
    add(-_norm((closes[0] - closes[1]) / closes[1] * 100, NORM_PREV_DAY_MULT * vol),
        W_PREV_DAY_REVERSION)
    ma_s, ma_l = sma(closes, MA_SHORT), sma(closes, MA_LONG)
    if ma_s and ma_l:
        add(_norm((ma_s - ma_l) / ma_l * 100, NORM_MA_TREND_MULT * vol), W_MA_TREND)
    if len(closes) > MOMENTUM_DAYS:
        add(_norm((closes[0] - closes[MOMENTUM_DAYS]) / closes[MOMENTUM_DAYS] * 100,
                  NORM_MOMENTUM_MULT * vol), W_MOMENTUM_3D)
    return _clip(wsum / total) if total else None


def daily_vols(days_all: list[str], vol_fn=realized_vol) -> dict[str, float]:
    """각 날짜의 진입 시점 σ — 그날 이전 확정 종가만 사용 (알고리즘과 동일)."""
    vols = {}
    for d in days_all:
        idx = proxy_dates.index(d)
        closes = [proxy_bars[x]["close"] for x in reversed(proxy_dates[:idx])]
        vols[d] = vol_fn(closes) if len(closes) > 2 else 1.0
    return vols


def run(days: list[str], vols: dict[str, float], strategy=None) -> dict:
    """시뮬레이션 본체 — 청산 판정은 `strategy.should_sell` 에 그대로 위임한다.

    Returns:
        {rows, trades, pool, equity} — rows 는 일자별 표, pool 은 실현 자금 풀.
    """
    strategy = strategy or STRATEGY
    pool = float(SEED)
    pos = None
    blocked = None
    rows, trades = [], []

    for n, date in enumerate(days, start=1):
        row = {"n": n, "date": date}

        # ── 1. 09:00 첫 폴링 — 보유분 청산 판정 (손절 > 최고가 > 보유기간) ──
        if pos:
            hit = price_at(fetch_minutes(pos["code"], date), "0900")
            if hit:
                _, price = hit
                pos["slot"]["peak"] = pos["peak"]
                decision = strategy.should_sell(
                    pos["slot"], price,
                    now=datetime.strptime(date + " 0900", "%Y%m%d %H%M"))
                kind = {"stop_loss": "손절", "peak_drop": "최고가"}.get(
                    decision.kind, "보유만료")
                proceeds = price * pos["qty"] * (1 - FEE_RATE)
                pnl = proceeds - pos["invested"]
                pool += pnl
                trades.append({"진입일": pos["date"], "청산일": date, "종목": NAMES[pos["code"]],
                               "진입가": pos["entry"], "청산가": price, "수량": pos["qty"],
                               "사유": kind, "손익": pnl,
                               "수익률": pnl / pos["invested"] * 100})
                # 손익은 '그 포지션을 산 날' 행에 붙인다 — 매수 종목 옆에 결말이 오게.
                pos["row"].update(청산일=date, 청산가=price, 사유=kind, 손익=pnl,
                                  수익률=pnl / pos["invested"] * 100)
                if kind != "보유만료":
                    blocked = date
                pos = None

        # ── 2. 방향 판정 (09:00 실측 갭) ──
        proxy_open = price_at(fetch_minutes(UP_CODE, date), "0900")
        score = judge_at_open(date, proxy_open[1]) if proxy_open else None
        if score is not None:
            row["score"] = score
            row["방향"] = "📈 상승" if score > 0 else "📉 하락"

        # ── 3. 진입 ──
        if score and blocked != date and pool > 0:
            code = UP_CODE if score > 0 else DOWN_CODE
            bars = fetch_minutes(code, date)
            hit = price_at(bars, "0900")
            if hit:
                entry_time, entry = hit
                qty = int(pool // (entry * (1 + FEE_RATE)))
                if qty > 0:
                    vol = vols[date]
                    slot = mark_entry({"code": code, "vol": vol}, entry, qty,
                                      now=datetime.strptime(date, "%Y%m%d"))
                    stop_pct, peak_pct, _ = strategy.exit_thresholds(slot)
                    pos = {"code": code, "entry": entry, "qty": qty, "date": date,
                           "invested": qty * entry * (1 + FEE_RATE), "peak": entry,
                           "row": row, "slot": slot}
                    row.update(종목=NAMES[code], 진입가=entry, 수량=qty,
                               투입액=pos["invested"], vol=vol,
                               손절선=stop_pct, 청산선=peak_pct)

                    # ── 4. 장중 1분 폴링 — 최고가 갱신 + 청산 판정 ──
                    for t in sorted(bars):
                        if t <= entry_time:
                            continue
                        price = bars[t]
                        pos["peak"] = max(pos["peak"], price)
                        pos["slot"]["peak"] = pos["peak"]
                        decision = strategy.should_sell(
                            pos["slot"], price,
                            now=datetime.strptime(date + " " + t, "%Y%m%d %H%M"))
                        if decision.sell and decision.kind in ("stop_loss", "peak_drop"):
                            kind = "손절" if decision.kind == "stop_loss" else "최고가"
                            proceeds = price * pos["qty"] * (1 - FEE_RATE)
                            pnl = proceeds - pos["invested"]
                            pool += pnl
                            trades.append({"진입일": date, "청산일": date, "종목": NAMES[code],
                                           "진입가": pos["entry"], "청산가": price,
                                           "수량": pos["qty"], "사유": f"{kind}({t[:2]}:{t[2:]})",
                                           "손익": pnl, "수익률": pnl / pos["invested"] * 100})
                            row.update(청산일=date, 청산가=price, 사유=f"{kind} {t[:2]}:{t[2:]}",
                                       손익=pnl, 수익률=pnl / pos["invested"] * 100)
                            blocked = date
                            pos = None
                            break
        elif blocked == date:
            row["비고"] = "청산 후 당일 재진입 차단"

        # ── 5. 종가 기준 평가자산 ──
        equity = pool
        if pos:
            bars = fetch_minutes(pos["code"], date)
            last = max(bars)
            row["종가"] = bars[last]
            equity += bars[last] * pos["qty"] * (1 - FEE_RATE) - pos["invested"]
        row["자산"] = equity
        rows.append(row)

    return {"rows": rows, "trades": trades, "pool": pool,
            "equity": rows[-1]["자산"] if rows else float(SEED), "pos": pos}


def main() -> None:
    _load_cache()
    days_all = [d for d in proxy_dates if d <= LAST_DAY]
    days = days_all[-DAYS_BACK:]
    result = run(days, daily_vols(days_all))
    rows, trades, pool, pos = (result["rows"], result["trades"],
                               result["pool"], result["pos"])
    _save_cache()

    # ── 출력 ──
    print(f"시드 {SEED:,}원 · {days[0]} ~ {days[-1]} ({len(days)}거래일) · "
          f"청산선 {STRATEGY.display_name.split(' · ', 2)[-1]} · "
          f"수수료 {FEE_RATE * 100:.4f}% 편도\n")
    head = (f"{'#':>2} {'날짜':>11} {'방향':>7} {'점수':>7} {'매수 종목':>13} {'매수가':>9} "
            f"{'수량':>6} {'σ':>6} {'손절선':>7} {'청산선':>7} {'청산일':>8} {'청산가':>9} {'사유':>11} "
            f"{'손익':>11} {'수익률':>8} {'평가자산':>12} {'누적':>8}")
    print(head)
    print("─" * len(head))
    for r in rows:
        d = r["date"]
        cd = r.get("청산일", "")
        print(
            f"{r['n']:>2} {d[:4]}-{d[4:6]}-{d[6:]:>2} {r.get('방향', '판정불가'):>6} "
            f"{r.get('score', 0):>+7.3f} {r.get('종목', '—'):>12} "
            f"{r.get('진입가', 0):>9,.0f} {r.get('수량', 0):>6,} "
            f"{r.get('vol', 0):>5.2f}% {r.get('손절선', 0):>6.1f}% {r.get('청산선', 0):>6.1f}% "
            f"{(cd[4:6] + '-' + cd[6:]) if cd else (r.get('비고') or '—'):>8} "
            f"{r.get('청산가', 0):>9,.0f} {r.get('사유', '보유 중' if r.get('종목') else '—'):>10} "
            f"{r.get('손익', 0):>+11,.0f} {r.get('수익률', 0):>+7.2f}% {r['자산']:>12,.0f} "
            f"{(r['자산'] / SEED - 1) * 100:>+7.2f}%"
        )

    final = rows[-1]["자산"]
    wins = [t for t in trades if t["손익"] > 0]
    print(f"\n최종 평가자산 {final:,.0f}원 ({(final / SEED - 1) * 100:+.2f}%) · "
          f"실현 자금 풀 {pool:,.0f}원")
    print(f"거래 {len(trades)}회 · 승 {len(wins)}회 ({len(wins) / len(trades) * 100:.0f}%) · "
          f"거래당 평균 {st.mean(t['수익률'] for t in trades):+.2f}%")
    kinds: dict[str, int] = {}
    for t in trades:
        k = t["사유"].split("(")[0]
        kinds[k] = kinds.get(k, 0) + 1
    print(f"청산 사유: {' · '.join(f'{k} {v}회' for k, v in sorted(kinds.items()))}")
    if pos:
        print(f"※ {days[-1]} 종가 기준 {NAMES[pos['code']]} {pos['qty']:,}주 보유 중 "
              f"(다음 거래일 개장에 청산 예정) — 위 평가자산에 반영됨")

    print("\n[거래 내역]")
    th = f"{'진입일':>10} {'청산일':>10} {'종목':>13} {'진입가':>9} {'청산가':>9} {'수량':>6} {'사유':>14} {'손익':>11} {'수익률':>8}"
    print(th)
    print("─" * len(th))
    for t in trades:
        print(f"{t['진입일']:>10} {t['청산일']:>10} {t['종목']:>12} {t['진입가']:>9,.0f} "
              f"{t['청산가']:>9,.0f} {t['수량']:>6,} {t['사유']:>14} {t['손익']:>+11,.0f} "
              f"{t['수익률']:>+7.2f}%")

    # 벤치마크
    up_ret = (proxy_bars[days[-1]]["close"] / proxy_bars[days[0]]["open"] - 1) * 100
    inv = DAILY[DOWN_CODE]
    dn_ret = (inv[days[-1]]["close"] / inv[days[0]]["open"] - 1) * 100
    print(f"\n[벤치마크] 같은 기간 KODEX 200 매수보유 {up_ret:+.2f}% · "
          f"KODEX 인버스 매수보유 {dn_ret:+.2f}% (실제 일봉 기준)")


if __name__ == "__main__":
    main()
