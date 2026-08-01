"""표본 외(out-of-sample) 검증 — 3~6월로 정한 판정 기준을 7월에 적용해 본다.

현재 가중치는 3~7월 전체(78영업일)로 정했으므로 7월이 학습 표본에 포함돼 있다.
여기서는 **7월을 완전히 제외한 3~6월(train)** 에서 결론이 그대로 도출되는지 확인하고,
그 결론을 **7월(test)** 에 적용했을 때 성립하는지 본다.

교차 확인을 위해 두 종목(계열)을 함께 돌린다.
  - KODEX 200 ETF (069500)  : 실제 매매 대상
  - 코스피200 지수 (U/2001) : ETF 추적오차·분배금 영향이 없는 원 데이터
"""
import statistics as st
import sys
from datetime import datetime, timedelta

from core.kis_api import BASE_URL, _request, get_daily_ohlcv
from core.market_direction import (
    MA_LONG,
    MA_SHORT,
    MOMENTUM_DAYS,
    NORM_GAP_MULT,
    NORM_MA_TREND_MULT,
    NORM_MOMENTUM_MULT,
    NORM_PREV_DAY_MULT,
    _norm,
    realized_vol,
)
from core.strategy.buy._indicators import sma

TRAIN_END = "20260630"   # 이 날짜까지 train, 이후 test(7월)


def fetch_index_bars(iscd: str, start: str, end: str) -> list[dict]:
    """지수 일봉 — 한 번에 50행 한도라 구간을 나눠 받아 합친다 (최신순 반환)."""
    url = f"{BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-daily-indexchartprice"
    merged: dict[str, dict] = {}
    cur_end = datetime.strptime(end, "%Y%m%d")
    start_dt = datetime.strptime(start, "%Y%m%d")
    while cur_end >= start_dt:
        cur_start = max(start_dt, cur_end - timedelta(days=68))
        out = _request("GET", url, "FHKUP03500100", params={
            "FID_COND_MRKT_DIV_CODE": "U",
            "FID_INPUT_ISCD": iscd,
            "FID_INPUT_DATE_1": cur_start.strftime("%Y%m%d"),
            "FID_INPUT_DATE_2": cur_end.strftime("%Y%m%d"),
            "FID_PERIOD_DIV_CODE": "D",
        }).get("output2", [])
        if not out:
            break
        for b in out:
            d = b.get("stck_bsop_date")
            try:
                close = float(b.get("bstp_nmix_prpr", 0) or 0)
                open_ = float(b.get("bstp_nmix_oprc", 0) or 0)
            except (TypeError, ValueError):
                continue
            if d and close > 0 and open_ > 0:
                merged[d] = {"date": d, "open": open_, "close": close}
        oldest = min(b.get("stck_bsop_date", "99999999") for b in out)
        nxt = datetime.strptime(oldest, "%Y%m%d") - timedelta(days=1)
        if nxt >= cur_end:
            break
        cur_end = nxt
    return sorted(merged.values(), key=lambda b: b["date"], reverse=True)


def build_rows(bars_desc: list[dict]) -> list[dict]:
    """최신순 일봉 → 판정 시점별 신호·목표 레코드 (오래된 순)."""
    bars = list(reversed(bars_desc))
    rows = []
    for i in range(MA_LONG + 1, len(bars) - 1):
        closes = [b["close"] for b in reversed(bars[:i])]
        ma_s, ma_l = sma(closes, MA_SHORT), sma(closes, MA_LONG)
        if not ma_s or not ma_l:
            continue
        prev_close, today, tomorrow = closes[0], bars[i], bars[i + 1]
        vol = realized_vol(closes)
        rows.append({
            "date": today["date"],
            "이평선": _norm((ma_s - ma_l) / ma_l * 100, NORM_MA_TREND_MULT * vol),
            # 구현과 동일하게 부호를 뒤집어 저장 (평균회귀)
            "전일": -_norm((closes[0] - closes[1]) / closes[1] * 100, NORM_PREV_DAY_MULT * vol),
            "3일": _norm((closes[0] - closes[MOMENTUM_DAYS]) / closes[MOMENTUM_DAYS] * 100,
                        NORM_MOMENTUM_MULT * vol),
            "갭": _norm((today["open"] - prev_close) / prev_close * 100, NORM_GAP_MULT * vol),
            "전일_raw": (closes[0] - closes[1]) / closes[1] * 100,
            "목표": (tomorrow["open"] - today["open"]) / today["open"] * 100,
        })
    return rows


NEW = {"이평선": .15, "전일": .25, "3일": .10, "갭": .50}      # 현재 (전일은 이미 반전됨)
OLD = {"이평선": .35, "전일": -.25, "3일": .20, "갭": .20}     # 이전 (전일 순방향 = 반전값의 -)


def run(rows, w):
    if not rows:
        return 0.0, 0.0, 0
    denom = sum(abs(v) for v in w.values())
    hits = pnl = 0
    for r in rows:
        score = sum(r[n] * w[n] for n in w) / denom
        if (score > 0) == (r["목표"] > 0):
            hits += 1
        pnl += r["목표"] if score > 0 else -r["목표"]
    return hits / len(rows) * 100, pnl, len(rows)


def report(title, bars):
    rows = build_rows(bars)
    if len(rows) < 25:
        print(f"\n### {title} — 표본 부족 ({len(rows)}일), 생략")
        return
    train = [r for r in rows if r["date"] <= TRAIN_END]
    test = [r for r in rows if r["date"] > TRAIN_END]
    print(f"\n### {title}")
    print(f"전체 {len(rows)}일 | train(~6월) {len(train)}일 | test(7월) {len(test)}일")
    if len(test) < 5 or len(train) < 20:
        print("  구간 분할 불가 — 생략")
        return

    print("\n  [A] 평균회귀가 train 만으로도 관측되는가 (7월 배제)")
    for label, sel in (("train(3~6월)", train), ("test(7월)", test), ("전체", rows)):
        c = st.correlation([r["전일_raw"] for r in sel], [r["목표"] for r in sel])
        se = (1 / max(1, len(sel) - 3)) ** 0.5
        print(f"    {label:<14} 상관 {c:+.3f}  (n={len(sel)}, ±{se:.3f}, {abs(c) / se:.1f}σ)")

    print("\n  [B] 신호별 단독 적중률")
    print(f"    {'신호':<8}{'train':>9}{'test(7월)':>12}")
    for n in ("갭", "전일", "이평선", "3일"):
        tr = sum(1 for r in train if (r[n] > 0) == (r["목표"] > 0)) / len(train) * 100
        te = sum(1 for r in test if (r[n] > 0) == (r["목표"] > 0)) / len(test) * 100
        print(f"    {n:<8}{tr:>8.1f}%{te:>11.1f}%")

    print("\n  [C] 가중치 조합 — train 에서 정하고 test 에 적용")
    print(f"    {'조합':<14}{'train 적중':>11}{'train 손익':>11}"
          f"{'test 적중':>11}{'test 손익':>11}")
    for label, w in (("이전 가중치", OLD), ("현재 가중치", NEW)):
        h1, p1, _ = run(train, w)
        h2, p2, _ = run(test, w)
        print(f"    {label:<14}{h1:>10.1f}%{p1:>10.1f}%{h2:>10.1f}%{p2:>10.1f}%")

    print("\n  [D] 7월 일별 (현재 가중치) — 방향 적중 여부")
    denom = sum(abs(v) for v in NEW.values())
    line = []
    for r in test:
        score = sum(r[n] * NEW[n] for n in NEW) / denom
        ok = (score > 0) == (r["목표"] > 0)
        line.append(f"{r['date'][4:]}{'○' if ok else '✕'}")
    for i in range(0, len(line), 6):
        print("    " + "  ".join(line[i:i + 6]))


print("표본 외 검증 — 3~6월(train) / 7월(test)")
report("KODEX 200 ETF (069500) — 실제 매매 대상", get_daily_ohlcv("069500", days=120))
report("코스피200 지수 (2001) — 원 데이터 교차 확인",
       fetch_index_bars("2001", "20260101", "20260731"))
report("코스피 지수 (0001) — 참고", fetch_index_bars("0001", "20260101", "20260731"))


# ── [E] train 만으로 가중치를 다시 도출하면 어디로 수렴하는가 ──────────────────
#
# [C] 의 test 열은 '가중치를 전체 표본(7월 포함)으로 정한 뒤 7월에 적용' 한 것이라
# 가중치 자체의 표본 외 검증은 아니다. 여기서는 7월을 전혀 보지 않은 train 만으로
# 한계효과를 다시 계산해, 현재 가중치와 같은 결론이 나오는지 확인한다.
import random


def marginal(rows, label):
    random.seed(0)
    names = ("이평선", "전일", "3일", "갭")
    trials = []
    for _ in range(10000):
        w = {n: random.uniform(-1, 1) for n in names}
        trials.append((w, *run(rows, w)[:2]))
    print(f"\n### [E] {label} — 무작위 가중치 10,000개 한계효과 (train 만)")
    print(f"    {'그룹':<26}{'적중 중앙':>10}{'손익 중앙':>11}")

    def grp(name, cond):
        sel = [(h, p) for w, h, p in trials if cond(w)]
        if sel:
            print(f"    {name:<26}{st.median(h for h, _ in sel):>9.1f}%"
                  f"{st.median(p for _, p in sel):>10.1f}%")

    grp("전일(원신호) 순방향", lambda w: w["전일"] < 0)   # 저장값이 이미 반전이므로 부호 주의
    grp("전일(원신호) 평균회귀", lambda w: w["전일"] > 0)
    grp("갭 w < 0.2", lambda w: w["갭"] < 0.2)
    grp("갭 w > 0.5", lambda w: w["갭"] > 0.5)
    grp("이평선 |w| < 0.2", lambda w: abs(w["이평선"]) < 0.2)
    grp("이평선 w > 0.5", lambda w: w["이평선"] > 0.5)
    grp("3일 w > 0.5", lambda w: w["3일"] > 0.5)


for title, bars in (("KODEX 200 ETF", get_daily_ohlcv("069500", days=120)),
                    ("코스피200 지수", fetch_index_bars("2001", "20260101", "20260731"))):
    rows = build_rows(bars)
    marginal([r for r in rows if r["date"] <= TRAIN_END], title)

sys.exit(0)
