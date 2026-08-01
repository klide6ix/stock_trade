"""정규화 기준 산정 — 각 신호의 실제 분포를 일간 실현변동성(vol) 대비 배수로 측정.

절대 % 상수 대신 `vol × 배수` 로 두면 시장이 진정돼도 포화율이 유지된다.
배수는 무차원이라 국면이 바뀌어도 절대값보다 훨씬 안정적이다.
"""
import statistics as st

from core.kis_api import get_daily_ohlcv
from core.market_direction import MA_LONG, MA_SHORT, MOMENTUM_DAYS
from core.strategy.buy._indicators import sma

VOL_WINDOW = 20

bars = list(reversed(get_daily_ohlcv("069500", days=120)))
rows = []
for i in range(MA_LONG + 2, len(bars)):
    closes = [b["close"] for b in reversed(bars[:i])]  # 최신순
    ma_s, ma_l = sma(closes, MA_SHORT), sma(closes, MA_LONG)
    if not ma_s or not ma_l:
        continue
    rets = [
        (closes[j] - closes[j + 1]) / closes[j + 1] * 100
        for j in range(min(VOL_WINDOW, len(closes) - 1))
    ]
    vol = st.pstdev(rets)
    if vol <= 0:
        continue
    rows.append({
        "vol": vol,
        "이평선": (ma_s - ma_l) / ma_l * 100,
        "전일": (closes[0] - closes[1]) / closes[1] * 100,
        "3일": (closes[0] - closes[MOMENTUM_DAYS]) / closes[MOMENTUM_DAYS] * 100,
        "갭": (bars[i]["open"] - closes[0]) / closes[0] * 100,
    })

N = len(rows)
vols = [r["vol"] for r in rows]
print(f"표본 {N}일 · 일간 실현변동성(20일) 중앙값 {st.median(vols):.2f}% "
      f"(최소 {min(vols):.2f}% ~ 최대 {max(vols):.2f}%)\n")

print(f"{'신호':<8}{'|값| 중앙':>10}{'표준편차':>10}{'σ/vol 배수':>12}{'|값|/vol 중앙':>13}")
ratios = {}
for name in ("이평선", "전일", "3일", "갭"):
    vals = [r[name] for r in rows]
    sd = st.pstdev(vals)
    per_vol = [abs(r[name]) / r["vol"] for r in rows]
    ratio = sd / st.median(vols)
    ratios[name] = ratio
    print(f"{name:<8}{st.median(abs(v) for v in vals):>9.2f}%{sd:>9.2f}%"
          f"{ratio:>12.2f}{st.median(per_vol):>13.2f}")

print("\n── 배수 후보별 포화율 (|정규화 점수| ≥ 1 인 날의 비율) ──")
print(f"{'신호':<8}" + "".join(f"{f'×{k:g}σ':>9}" for k in (1.0, 1.5, 2.0, 2.5)))
for name in ("이평선", "전일", "3일", "갭"):
    line = f"{name:<8}"
    for k in (1.0, 1.5, 2.0, 2.5):
        scale_mult = ratios[name] * k
        sat = sum(1 for r in rows if abs(r[name]) >= r["vol"] * scale_mult) / N * 100
        line += f"{sat:>8.0f}%"
    print(line)

print("\n── 권장 배수 (vol 대비) — 포화율 10~20% 목표 ──")
for name in ("이평선", "전일", "3일", "갭"):
    for k in (1.0, 1.5, 2.0, 2.5, 3.0):
        m = ratios[name] * k
        sat = sum(1 for r in rows if abs(r[name]) >= r["vol"] * m) / N * 100
        if sat <= 20:
            print(f"  {name:<8} 배수 {m:>5.2f} × vol  (포화율 {sat:.0f}%) "
                  f"→ 현 변동성 {st.median(vols):.1f}% 기준 {m * st.median(vols):.1f}%")
            break
