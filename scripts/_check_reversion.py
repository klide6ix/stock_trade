"""사용자 가설 검증 (조회 전용, 주문 없음).

  가설 1: 변동성이 커서 이평선(5MA/20MA)이 의미 없다.
  가설 2: 전일 대폭락 후 다음날 크게 상승한다 (평균회귀) → 전일보다 당일 등락률이 중요.

가설 2 가 맞다면 W_PREV_DAY 는 '줄일' 게 아니라 '음수' 여야 한다. 그 구분을 확인한다.
"""
import statistics as st

from core.kis_api import get_daily_ohlcv
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

# 주의: 아래 '전일' 은 **원신호**(부호 반전 전)다. 반전 여부는 가중치 부호로 표현한다
# — ④⑤ 에서 음수 가중치가 곧 현재 구현의 평균회귀 사용에 해당한다.
bars = list(reversed(get_daily_ohlcv("069500", days=120)))
rows = []
for i in range(MA_LONG + 1, len(bars) - 1):
    closes = [b["close"] for b in reversed(bars[:i])]
    ma_s, ma_l = sma(closes, MA_SHORT), sma(closes, MA_LONG)
    if not ma_s or not ma_l:
        continue
    prev_close = closes[0]
    today, tomorrow = bars[i], bars[i + 1]
    vol = realized_vol(closes)
    rows.append({
        "date": today["date"],
        "이평선": _norm((ma_s - ma_l) / ma_l * 100, NORM_MA_TREND_MULT * vol),
        "전일": _norm((closes[0] - closes[1]) / closes[1] * 100, NORM_PREV_DAY_MULT * vol),
        "3일": _norm((closes[0] - closes[MOMENTUM_DAYS]) / closes[MOMENTUM_DAYS] * 100,
                    NORM_MOMENTUM_MULT * vol),
        "갭": _norm((today["open"] - prev_close) / prev_close * 100, NORM_GAP_MULT * vol),
        # 원값
        "전일_raw": (closes[0] - closes[1]) / closes[1] * 100,
        "갭_raw": (today["open"] - prev_close) / prev_close * 100,
        # 목표
        "시가→익일시가": (tomorrow["open"] - today["open"]) / today["open"] * 100,
        "종가등락": (today["close"] - prev_close) / prev_close * 100,
    })
N = len(rows)
print(f"표본 {N}일 ({rows[0]['date']} ~ {rows[-1]['date']})\n")

# ── ① 신호 부호 전환 횟수 → 유효 표본 ────────────────────────────────────────
print("── ① 신호가 실제로 방향을 바꾼 횟수 (유효 표본) ──")
print(f"{'신호':<8}{'부호전환':>9}{'유효표본':>9}{'평균지속일':>11}{'적중률':>9}{'유효표준오차':>12}")
for name in ("이평선", "전일", "3일", "갭"):
    signs = [1 if r[name] > 0 else -1 for r in rows]
    flips = sum(1 for i in range(1, N) if signs[i] != signs[i - 1])
    eff = flips + 1
    hit = sum(1 for r in rows if (r[name] > 0) == (r["시가→익일시가"] > 0)) / N * 100
    se = (0.25 / eff) ** 0.5 * 100
    print(f"{name:<8}{flips:>9}{eff:>9}{N / eff:>11.1f}{hit:>8.1f}%{se:>11.1f}%p")

# ── ② 전일 대폭락 후 무슨 일이 벌어지는가 ────────────────────────────────────
print("\n── ② 전일 등락률 구간별, 다음 날 실제 성과 ──")
buckets = [
    ("전일 -10% 이하", lambda x: x <= -10),
    ("전일 -10 ~ -5%", lambda x: -10 < x <= -5),
    ("전일 -5 ~ 0%", lambda x: -5 < x < 0),
    ("전일 0 ~ +5%", lambda x: 0 <= x < 5),
    ("전일 +5 ~ +10%", lambda x: 5 <= x < 10),
    ("전일 +10% 이상", lambda x: x >= 10),
]
print(f"{'구간':<16}{'n':>4}{'갭(시가)':>10}{'당일종가':>10}{'시가→익일시가':>14}{'상승비율':>9}")
for label, cond in buckets:
    sel = [r for r in rows if cond(r["전일_raw"])]
    if not sel:
        print(f"{label:<16}{0:>4}{'—':>10}")
        continue
    gap = st.mean(r["갭_raw"] for r in sel)
    cc = st.mean(r["종가등락"] for r in sel)
    oo = st.mean(r["시가→익일시가"] for r in sel)
    up = sum(1 for r in sel if r["시가→익일시가"] > 0) / len(sel) * 100
    print(f"{label:<16}{len(sel):>4}{gap:>+9.2f}%{cc:>+9.2f}%{oo:>+13.2f}%{up:>8.0f}%")

print("\n── ③ 상관계수 (평균회귀 = 음수) ──")
for a, b in (("전일_raw", "종가등락"), ("전일_raw", "갭_raw"), ("전일_raw", "시가→익일시가")):
    c = st.correlation([r[a] for r in rows], [r[b] for r in rows])
    print(f"  전일 등락률 ↔ {b:<14} {c:+.3f}")

# ── ④ 가중치 조합 (음수 허용) ────────────────────────────────────────────────
print("\n── ④ 가중치 조합 비교 (음수 = 역방향 사용) ──")


def evaluate(label, w):
    denom = sum(abs(v) for v in w.values())
    hits = pnl = 0
    for r in rows:
        score = sum(r[n] * v for n, v in w.items()) / denom
        if (score > 0) == (r["시가→익일시가"] > 0):
            hits += 1
        pnl += r["시가→익일시가"] if score > 0 else -r["시가→익일시가"]
    print(f"{label:<34}{hits / N * 100:>8.1f}%{pnl:>11.1f}%")


print(f"{'조합 (이평선/전일/3일/갭)':<34}{'적중률':>8}{'누적손익':>11}")
evaluate("이전  .35 / .25 / .20 / .20", {"이평선": .35, "전일": .25, "3일": .20, "갭": .20})
evaluate("현재  .15 / -.25 / .10 / .50", {"이평선": .15, "전일": -.25, "3일": .10, "갭": .50})
evaluate("전일만 반전  .35 / -.25 / .20 / .20", {"이평선": .35, "전일": -.25, "3일": .20, "갭": .20})
evaluate("갭 상향만  .35 / .25 / .20 / .50", {"이평선": .35, "전일": .25, "3일": .20, "갭": .50})
evaluate("이평선 제거  0 / -.25 / .10 / .50", {"이평선": 0, "전일": -.25, "3일": .10, "갭": .50})
evaluate("갭 단독  0 / 0 / 0 / 1.0", {"이평선": 0, "전일": 0, "3일": 0, "갭": 1.0})
evaluate("이평선 단독  1.0 / 0 / 0 / 0", {"이평선": 1.0, "전일": 0, "3일": 0, "갭": 0})


# ── ⑤ 한계효과 검증 — 특정 조합이 아니라 '가중치를 바꾸면 평균적으로 어떻게 되는가' ──
#
# ④ 처럼 조합 몇 개를 비교하면 표본 노이즈에서 최고값을 골라내는 과최적화가 된다.
# 무작위 가중치 1만 개를 뽑아, 한 신호의 가중치(또는 부호)만 다른 그룹끼리
# 중앙값을 비교한다. 나머지 신호가 무작위로 섞이므로 그 신호 고유의 기여만 남는다.
import random

random.seed(0)
NAMES = ("이평선", "전일", "3일", "갭")


def run(w):
    denom = sum(abs(v) for v in w.values()) or 1
    hits = pnl = 0
    for r in rows:
        score = sum(r[n] * w[n] for n in NAMES) / denom
        if (score > 0) == (r["시가→익일시가"] > 0):
            hits += 1
        pnl += r["시가→익일시가"] if score > 0 else -r["시가→익일시가"]
    return hits / N * 100, pnl


trials = []
for _ in range(10000):
    w = {n: random.uniform(-1, 1) for n in NAMES}
    hit, pnl = run(w)
    trials.append((w, hit, pnl))


def group(label, cond):
    sel = [(h, p) for w, h, p in trials if cond(w)]
    if not sel:
        return
    hits = sorted(h for h, _ in sel)
    pnls = sorted(p for _, p in sel)
    print(f"{label:<28}{len(sel):>7}{st.median(hits):>10.1f}%{st.median(pnls):>12.1f}%"
          f"{pnls[len(pnls) // 10]:>10.0f}%{pnls[len(pnls) * 9 // 10]:>9.0f}%")


print("\n── ⑤ 무작위 가중치 10,000개로 본 각 신호의 한계효과 ──")
print(f"{'그룹':<28}{'n':>7}{'적중률중앙':>10}{'손익중앙':>12}{'하위10%':>10}{'상위10%':>9}")
print("[전일 등락률의 부호]")
group("  전일 가중치 > 0 (현행)", lambda w: w["전일"] > 0)
group("  전일 가중치 < 0 (반전)", lambda w: w["전일"] < 0)
print("[이평선 가중치 크기]")
group("  이평선 |w| < 0.2 (거의 무시)", lambda w: abs(w["이평선"]) < 0.2)
group("  이평선 w > 0.5 (강하게 사용)", lambda w: w["이평선"] > 0.5)
print("[갭 가중치 크기]")
group("  갭 w < 0.2", lambda w: w["갭"] < 0.2)
group("  갭 w > 0.5", lambda w: w["갭"] > 0.5)
print("[3일 모멘텀]")
group("  3일 w > 0.5", lambda w: w["3일"] > 0.5)
group("  3일 w < -0.5", lambda w: w["3일"] < -0.5)
