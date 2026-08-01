"""2026년 7월 단기 매매 시뮬레이션 — 7/1 에 300만원으로 시작했다면?

실제 매매 규칙을 그대로 재현한다.
  - 08:30 방향 판정 (judge_direction 과 동일한 신호·가중치·정규화)
  - 09:00 개장가로 진입 (상승 → KODEX 200 / 하락 → KODEX 인버스), 지정가 즉시 체결 가정
  - 4중 청산: 손절 -5% / 최고가 대비 -5% / 보유기간 만료(익일 개장) / 마감청산(OFF)
  - 손절·최고가 청산이면 **그날 재진입 차단**, 보유기간 만료면 같은 날 재진입
  - 자금 풀: 청산할 때마다 `풀 += 회수 - 투입`, 다음 진입 예산 = 풀 잔액
  - 수수료 0.0042% 양방향 (실측 온라인 위탁수수료, 국내 주식형 ETF 매도 거래세 면제)

일봉만으로는 장중 고가·저가의 **순서**를 알 수 없다. 이 순서가 최고가 청산 발동을
좌우하므로 두 경로를 모두 돌려 결과를 범위로 제시한다.
  - 보수: 시가 → 고가 → 저가 → 종가 (고점을 먼저 찍어 최고가 청산이 잘 걸림)
  - 낙관: 시가 → 저가 → 고가 → 종가

한계: 갭 신호를 08:30 예상체결가가 아니라 **실제 시가**로 대용했다. 예상체결가가 시가를
정확히 맞히지는 않으므로 방향 판정이 실제보다 유리할 수 있다.
"""
import statistics as st
from datetime import datetime

from core.kis_api import get_daily_ohlcv
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
from core.strategy.buy._indicators import sma

SEED = 3_000_000
FEE_RATE = 0.000042          # 0.0042%
STOP_LOSS_PCT = 5.0
PEAK_DROP_PCT = 5.0
UP_CODE, DOWN_CODE = "069500", "114800"
START, END = "20260701", "20260731"

NEW_W = {"ma": W_MA_TREND, "prev": W_PREV_DAY_REVERSION, "mom": W_MOMENTUM_3D, "gap": W_GAP}
OLD_W = {"ma": 0.35, "prev": -0.25, "mom": 0.20, "gap": 0.20}  # prev 음수 = 순방향(이전)


def load(code):
    bars = get_daily_ohlcv(code, days=120)
    return {b["date"]: b for b in bars}, sorted(b["date"] for b in bars)


proxy_by_date, proxy_dates = load(UP_CODE)
inv_by_date, _ = load(DOWN_CODE)
BARS = {UP_CODE: proxy_by_date, DOWN_CODE: inv_by_date}


def judge(date, weights):
    """해당 날짜 08:30 시점의 방향 점수. 확정 과거봉 + 당일 시가 갭."""
    idx = proxy_dates.index(date)
    past = [proxy_by_date[d] for d in reversed(proxy_dates[:idx])]  # 최신순
    if len(past) < MA_LONG:
        return None
    closes = [b["close"] for b in past]
    vol = realized_vol(closes)
    prev_close = closes[0]
    total = wsum = 0.0

    def add(score, w):
        nonlocal total, wsum
        wsum += score * w
        total += abs(w)

    gap = (proxy_by_date[date]["open"] - prev_close) / prev_close * 100
    add(_norm(gap, NORM_GAP_MULT * vol), weights["gap"])
    prev_pct = (closes[0] - closes[1]) / closes[1] * 100
    add(-_norm(prev_pct, NORM_PREV_DAY_MULT * vol), weights["prev"])
    ma_s, ma_l = sma(closes, MA_SHORT), sma(closes, MA_LONG)
    if ma_s and ma_l:
        add(_norm((ma_s - ma_l) / ma_l * 100, NORM_MA_TREND_MULT * vol), weights["ma"])
    if len(closes) > MOMENTUM_DAYS:
        mom = (closes[0] - closes[MOMENTUM_DAYS]) / closes[MOMENTUM_DAYS] * 100
        add(_norm(mom, NORM_MOMENTUM_MULT * vol), weights["mom"])
    return _clip(wsum / total) if total else None


def simulate(weights, path="보수", stop_pct=None, peak_pct=None):
    """하루 단위 시뮬레이션. Returns (풀 잔액, 거래 로그)."""
    stop_pct = STOP_LOSS_PCT if stop_pct is None else stop_pct
    peak_pct = PEAK_DROP_PCT if peak_pct is None else peak_pct
    pool = float(SEED)
    pos = None          # {code, entry, qty, invested, peak}
    blocked = None
    log = []
    days = [d for d in proxy_dates if START <= d <= END]

    for date in days:
        # ── 09:00 개장: 보유분 청산 판정 (손절 > 최고가 > 보유기간 순) ──
        if pos:
            bar = BARS[pos["code"]][date]
            price = bar["open"]
            drop_entry = (pos["entry"] - price) / pos["entry"] * 100
            drop_peak = (pos["peak"] - price) / pos["peak"] * 100
            if drop_entry >= stop_pct:
                kind = "손절"
            elif drop_peak >= peak_pct:
                kind = "최고가"
            else:
                kind = "보유만료"
            proceeds = price * pos["qty"] * (1 - FEE_RATE)
            pnl = proceeds - pos["invested"]
            pool += pnl
            log.append((date, "청산", pos["code"], kind, price, pos["qty"], pnl, pool))
            if kind != "보유만료":
                blocked = date      # 손실성 청산 → 당일 재진입 금지
            pos = None

        # ── 09:00 진입 ──
        if pos is None and blocked != date:
            score = judge(date, weights)
            if score is not None and score != 0:
                code = UP_CODE if score > 0 else DOWN_CODE
                entry = BARS[code][date]["open"]
                qty = int(pool // (entry * (1 + FEE_RATE)))
                if qty > 0:
                    invested = entry * qty * (1 + FEE_RATE)
                    pos = {"code": code, "entry": entry, "qty": qty,
                           "invested": invested, "peak": entry}
                    log.append((date, "진입", code, f"점수 {score:+.3f}",
                                entry, qty, 0.0, pool))

        # ── 장중: 최고가 갱신 + 손절/최고가 청산 ──
        if pos:
            bar = BARS[pos["code"]][date]
            hi, lo = bar["high"], bar["low"]
            stop_px = pos["entry"] * (1 - stop_pct / 100)
            exit_px = kind = None
            if path == "보수":
                # 고가 먼저 → 최고가 갱신 후 저가로 하락
                peak = max(pos["peak"], hi)
                peak_px = peak * (1 - peak_pct / 100)
                if lo <= max(stop_px, peak_px):
                    # 둘 다 걸리면 더 높은 가격(먼저 닿는 쪽)에서 청산
                    exit_px = max(stop_px, peak_px)
                    kind = "손절" if exit_px == stop_px and stop_px >= peak_px else "최고가"
                pos["peak"] = peak
            else:
                # 저가 먼저 → 손절만 먼저 판정, 이후 고가로 최고가 갱신
                if lo <= stop_px:
                    exit_px, kind = stop_px, "손절"
                else:
                    peak = max(pos["peak"], hi)
                    pos["peak"] = peak
                    peak_px = peak * (1 - peak_pct / 100)
                    if bar["close"] <= peak_px:
                        exit_px, kind = peak_px, "최고가"
            if exit_px:
                proceeds = exit_px * pos["qty"] * (1 - FEE_RATE)
                pnl = proceeds - pos["invested"]
                pool += pnl
                log.append((date, "장중청산", pos["code"], kind, exit_px,
                            pos["qty"], pnl, pool))
                blocked = date
                pos = None

    # 7/31 종가로 평가 (미청산분)
    equity = pool
    if pos:
        bar = BARS[pos["code"]][days[-1]]
        equity = pool + bar["close"] * pos["qty"] * (1 - FEE_RATE) - pos["invested"]
    return pool, equity, log, pos


def summarize(label, weights):
    print(f"\n{'=' * 78}\n### {label}\n{'=' * 78}")
    for path in ("보수", "낙관"):
        pool, equity, log, pos = simulate(weights, path)
        closed = [r for r in log if r[1] in ("청산", "장중청산")]
        wins = [r for r in closed if r[6] > 0]
        kinds = {}
        for r in closed:
            kinds[r[3]] = kinds.get(r[3], 0) + 1
        ret = (equity - SEED) / SEED * 100
        print(f"\n  [{path} 경로]  최종 평가액 {equity:>12,.0f}원  "
              f"({ret:+.2f}%, {equity - SEED:+,.0f}원)")
        print(f"    거래 {len(closed)}회 · 승 {len(wins)}회 ({len(wins) / max(1, len(closed)) * 100:.0f}%) "
              f"· 청산사유 {kinds}")
        if pos:
            print(f"    7/31 미청산 보유: {pos['code']} {pos['qty']}주 (종가 평가 반영)")
    return simulate(weights, "보수")


print(f"2026년 7월 시뮬레이션 — 시드 {SEED:,}원")
print(f"기간: {START} ~ {END} ({len([d for d in proxy_dates if START <= d <= END])}거래일)")
print(f"수수료 {FEE_RATE * 100:.4f}% 양방향 · 손절 -{STOP_LOSS_PCT:g}% · 최고가 -{PEAK_DROP_PCT:g}%")

pool_new, eq_new, log_new, _ = summarize("현재 가중치 (갭.50 / 전일평균회귀.25 / 이평선.15 / 3일.10)", NEW_W)
summarize("이전 가중치 (이평선.35 / 전일순방향.25 / 3일.20 / 갭.20)", OLD_W)

# ── 벤치마크 ──
print(f"\n{'=' * 78}\n### 벤치마크 (같은 기간, 300만원)\n{'=' * 78}")
days = [d for d in proxy_dates if START <= d <= END]
for name, code in (("KODEX 200 매수 후 보유", UP_CODE), ("KODEX 인버스 매수 후 보유", DOWN_CODE)):
    o, c = BARS[code][days[0]]["open"], BARS[code][days[-1]]["close"]
    qty = int(SEED // (o * (1 + FEE_RATE)))
    eq = SEED - qty * o * (1 + FEE_RATE) + qty * c * (1 - FEE_RATE)
    print(f"  {name:<26} {eq:>12,.0f}원  ({(eq - SEED) / SEED * 100:+.2f}%)")

print(f"\n{'=' * 78}\n### 현재 가중치 · 보수 경로 — 일별 내역\n{'=' * 78}")
print(f"{'일자':<10}{'구분':<10}{'종목':<10}{'사유':<14}{'가격':>10}{'수량':>7}"
      f"{'손익':>12}{'풀잔액':>13}")
for date, act, code, why, px, qty, pnl, pool in log_new:
    nm = "KODEX200" if code == UP_CODE else "인버스"
    print(f"{date:<10}{act:<10}{nm:<10}{why:<14}{px:>10,.0f}{qty:>7}"
          f"{(f'{pnl:+,.0f}' if act != '진입' else '-'):>12}{pool:>13,.0f}")


# ── 청산선 민감도 — 실손익을 좌우하는 진짜 변수 ────────────────────────────────
print(f"\n{'=' * 78}\n### 청산선 민감도 (현재 가중치, 시드 300만원)\n{'=' * 78}")
print("  최고가 청산선을 넓히면 정상 변동폭에서 잘려나가는 거래가 줄어든다.")
print(f"\n  {'최고가 청산':<12}{'손절':<8}{'보수 경로':>14}{'낙관 경로':>14}{'거래수(보수)':>13}")
for peak_pct in (5, 8, 10, 15, 20, 100):
    for stop_pct in (5, 10):
        _, eq_c, log_c, _ = simulate(NEW_W, "보수", stop_pct, peak_pct)
        _, eq_o, _, _ = simulate(NEW_W, "낙관", stop_pct, peak_pct)
        n = len([r for r in log_c if r[1] in ("청산", "장중청산")])
        lbl = "없음" if peak_pct >= 100 else f"-{peak_pct}%"
        print(f"  {lbl:<12}{f'-{stop_pct}%':<8}"
              f"{(eq_c - SEED) / SEED * 100:>+13.2f}%{(eq_o - SEED) / SEED * 100:>+13.2f}%{n:>13}")

print(f"\n{'=' * 78}\n### 참고: 청산선 완화 시 가중치 비교 (최고가 -15% / 손절 -10%)\n{'=' * 78}")
for label, w in (("현재 가중치", NEW_W), ("이전 가중치", OLD_W)):
    _, eq_c, _, _ = simulate(w, "보수", 10, 15)
    _, eq_o, _, _ = simulate(w, "낙관", 10, 15)
    print(f"  {label:<14} 보수 {(eq_c - SEED) / SEED * 100:>+7.2f}%  "
          f"낙관 {(eq_o - SEED) / SEED * 100:>+7.2f}%")

# ── 경로 독립 구간(-15%/-10%)의 일별 내역 — 방향 판정만이 결과를 좌우 ──────────
print(f"\n{'=' * 78}\n### 최고가 -15% / 손절 -10% · 현재 가중치 — 일별 내역\n{'=' * 78}")
_, eq, lg, _ = simulate(NEW_W, "보수", 10, 15)
print(f"{'일자':<10}{'구분':<8}{'종목':<10}{'사유':<14}{'가격':>10}{'수량':>7}{'손익':>12}{'풀잔액':>13}")
longs = shorts = 0
for date, act, code, why, px, qty, pnl, pool in lg:
    nm = "KODEX200" if code == UP_CODE else "인버스"
    if act == "진입":
        longs += code == UP_CODE
        shorts += code == DOWN_CODE
    print(f"{date:<10}{act:<8}{nm:<10}{why:<14}{px:>10,.0f}{qty:>7}"
          f"{(f'{pnl:+,.0f}' if act != '진입' else '-'):>12}{pool:>13,.0f}")
print(f"\n  진입 방향: 정방향(KODEX200) {longs}회 · 인버스 {shorts}회")
wins = [r for r in lg if r[1] != "진입" and r[6] > 0]
closed = [r for r in lg if r[1] != "진입"]
print(f"  청산 {len(closed)}회 중 이익 {len(wins)}회 ({len(wins)/max(1,len(closed))*100:.0f}%) "
      f"· 최대 이익 {max((r[6] for r in closed), default=0):+,.0f}원 "
      f"· 최대 손실 {min((r[6] for r in closed), default=0):+,.0f}원")

# ── 갭 신호 낙관 편향의 하한 — 갭을 아예 못 쓰는 경우 ─────────────────────────
# 시뮬레이션은 갭에 '실제 시가' 를 썼지만 실전 08:30 에는 예상체결가뿐이다.
# 예상체결가가 시가를 전혀 못 맞히는 극단(갭 미사용)을 하한으로 잡는다.
NO_GAP = {**NEW_W, "gap": 0.0}
print(f"\n{'=' * 78}\n### 갭 신호 신뢰도에 따른 결과 범위 (최고가 -15% / 손절 -10%)\n{'=' * 78}")
for label, w in (("갭 = 실제 시가 (상한, 위 결과)", NEW_W),
                 ("갭 미사용 (하한)", NO_GAP)):
    _, eq, _, _ = simulate(w, "보수", 10, 15)
    print(f"  {label:<30}{eq:>13,.0f}원  ({(eq - SEED) / SEED * 100:+.2f}%)")
_, eq_r, lg_r, pos_r = simulate(NEW_W, "보수", 10, 15)
realized = lg_r[-1][7] if lg_r else SEED
print(f"\n  참고: 7/31 미청산분을 뺀 **실현 손익만** 집계하면 "
      f"{realized:,.0f}원 ({(realized - SEED) / SEED * 100:+.2f}%)")
print(f"        (7/31 은 코스피200 이 +20% 급등한 날이라 미실현 평가액이 결과를 크게 키운다)")
