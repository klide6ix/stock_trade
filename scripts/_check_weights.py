"""방향 판정 4개 신호의 가중치 검증 (조회 전용, 주문 없음).

market_direction.judge_direction() 과 동일한 계산식을 과거 일봉에 재현해,
각 신호가 '다음 방향' 을 실제로 맞혔는지 적중률을 센다. 갭 신호는 예상체결가를
과거로 되돌릴 수 없으므로 실제 시가 갭((시가 - 전일종가)/전일종가) 으로 대체한다.

'전일' 신호는 구현과 동일하게 **평균회귀(부호 반전) 적용 후** 점수다.
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
    W_GAP,
    W_MA_TREND,
    W_MOMENTUM_3D,
    W_PREV_DAY_REVERSION,
    _norm,
    realized_vol,
)
from core.strategy.buy._indicators import sma

CODE = "069500"

bars = list(reversed(get_daily_ohlcv(CODE, days=120)))  # 오래된 순
print(f"표본: {len(bars)}개 일봉 ({bars[0]['date']} ~ {bars[-1]['date']})\n")

rows = []
for i in range(MA_LONG + 1, len(bars) - 1):
    closes = [b["close"] for b in reversed(bars[:i])]  # 최신순 (판정 시점의 확정 과거봉)
    ma_s, ma_l = sma(closes, MA_SHORT), sma(closes, MA_LONG)
    if not ma_s or not ma_l:
        continue
    prev_close = closes[0]
    today, tomorrow = bars[i], bars[i + 1]
    vol = realized_vol(closes)

    raw = {
        "이평선": (ma_s - ma_l) / ma_l * 100,
        "전일": (closes[0] - closes[1]) / closes[1] * 100,
        "3일": (closes[0] - closes[MOMENTUM_DAYS]) / closes[MOMENTUM_DAYS] * 100,
        "갭": (today["open"] - prev_close) / prev_close * 100,
    }
    score = {
        "이평선": _norm(raw["이평선"], NORM_MA_TREND_MULT * vol),
        "전일": -_norm(raw["전일"], NORM_PREV_DAY_MULT * vol),
        "3일": _norm(raw["3일"], NORM_MOMENTUM_MULT * vol),
        "갭": _norm(raw["갭"], NORM_GAP_MULT * vol),
    }
    rows.append({
        "raw": raw,
        "score": score,
        # 실제 전략 손익에 대응하는 목표: 시가 진입 → 익일 시가 청산
        "target_oo": (tomorrow["open"] - today["open"]) / today["open"] * 100,
        # 참고: 전일종가 → 당일종가 (판정문의 '오늘 오르냐 내리냐')
        "target_cc": (today["close"] - prev_close) / prev_close * 100,
    })

N = len(rows)
print(f"검증 가능 구간: {N}일\n")

# "전일" 점수는 이미 평균회귀로 부호가 뒤집힌 값이므로 가중치는 양수 그대로 쓴다.
WEIGHTS = {"이평선": W_MA_TREND, "전일": W_PREV_DAY_REVERSION,
           "3일": W_MOMENTUM_3D, "갭": W_GAP}


def hit(pred, actual):
    return (pred > 0) == (actual > 0)


print("── ① 신호별 단독 적중률 (부호 일치) ──")
print(f"{'신호':<8}{'가중치':>7}{'익일시가기준':>13}{'당일종가기준':>13}{'포화율':>9}")
for name, w in WEIGHTS.items():
    oo = sum(1 for r in rows if hit(r["score"][name], r["target_oo"])) / N * 100
    cc = sum(1 for r in rows if hit(r["score"][name], r["target_cc"])) / N * 100
    sat = sum(1 for r in rows if abs(r["score"][name]) >= 0.999) / N * 100
    print(f"{name:<8}{w:>7.2f}{oo:>12.1f}%{cc:>12.1f}%{sat:>8.0f}%")

print("\n── ② 신호 간 상관계수 (중복 여부) ──")
names = list(WEIGHTS)
print(f"{'':<8}" + "".join(f"{n:>9}" for n in names))
for a in names:
    line = f"{a:<8}"
    for b in names:
        c = st.correlation([r["raw"][a] for r in rows], [r["raw"][b] for r in rows])
        line += f"{c:>9.2f}"
    print(line)

print("\n── ③ 가중 합산 점수의 적중률 ──")


def combined(weights, r):
    tot = sum(weights.values())
    return sum(r["score"][n] * w for n, w in weights.items()) / tot if tot else 0


def evaluate(label, weights):
    oo = sum(1 for r in rows if hit(combined(weights, r), r["target_oo"])) / N * 100
    cc = sum(1 for r in rows if hit(combined(weights, r), r["target_cc"])) / N * 100
    # 방향대로 매매했을 때의 누적 수익률 (익일시가 청산, 비용 제외)
    pnl = sum(
        r["target_oo"] if combined(weights, r) > 0 else -r["target_oo"] for r in rows
    )
    print(f"{label:<26}{oo:>8.1f}%{cc:>10.1f}%{pnl:>12.1f}%")


print(f"{'가중치 조합':<26}{'익일시가':>8}{'당일종가':>10}{'누적손익':>12}")
evaluate("현재 (활성 가중치)", WEIGHTS)
evaluate("갭 제외 (판정 실패 시)", {k: v for k, v in WEIGHTS.items() if k != "갭"})
evaluate("갭 단독", {"갭": 1.0})
evaluate("갭 0.5 + 나머지 균등", {"이평선": 1 / 6, "전일": 1 / 6, "3일": 1 / 6, "갭": 0.5})
evaluate("이평선 단독", {"이평선": 1.0})
evaluate("전일 단독 (평균회귀)", {"전일": 1.0})
evaluate("4개 균등", {n: 0.25 for n in names})

print("\n── ④ 갭 신호 사용 가능성 ──")
zero_gap = sum(1 for r in rows if abs(r["raw"]["갭"]) < 0.01)
print(f"시가 갭이 사실상 0인 날: {zero_gap}/{N}")
print(f"갭 평균 절대값: {st.mean(abs(r['raw']['갭']) for r in rows):.2f}% "
      f"(정규화 배수 {NORM_GAP_MULT} × 일간변동성)")
