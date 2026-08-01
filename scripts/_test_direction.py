"""방향 판정 순수 로직 검증 (API 호출 없음 — 일봉·갭을 주입해 계산식만 확인)."""
import sys
from datetime import datetime
from unittest.mock import patch

from core import market_direction as md
from core.etf_universe import DIRECTION_DOWN, DIRECTION_NEUTRAL, DIRECTION_UP

fails = []


def check(name, cond, detail=""):
    print(f"  {'✅' if cond else '❌'} {name}" + (f" — {detail}" if detail else ""))
    if not cond:
        fails.append(name)


def make_bars(closes, opens=None):
    """최신순 종가 리스트로 일봉 생성 (판정은 종가만 쓰므로 나머지는 종가로 채움)."""
    opens = opens or closes
    return [
        {"date": f"2026070{i}" if i < 10 else f"202607{i}", "open": o,
         "high": c, "low": c, "close": c, "volume": 1000}
        for i, (c, o) in enumerate(zip(closes, opens))
    ]


def judge(closes, gap=None, **kw):
    """일봉·갭 신호를 주입해 판정. gap=None 이면 갭 미사용 경로."""
    bars = make_bars(closes)
    gap_ret = (gap, "테스트 갭", "") if gap is not None else (None, "테스트 미사용", "")
    with patch.object(md, "get_daily_ohlcv", return_value=bars), \
         patch.object(md, "_gap_signal", return_value=gap_ret):
        return md.judge_direction(now=datetime(2026, 7, 20, 8, 30), **kw)


FLAT = [100.0] * 30  # 변동성 0 → VOL_FLOOR 로 방어되는지 확인용

print("── 1. 실현변동성 산출 ──")
check("등락 없으면 하한 적용", md.realized_vol(FLAT) == md.VOL_FLOOR_PCT,
      f"{md.realized_vol(FLAT)}% == VOL_FLOOR {md.VOL_FLOOR_PCT}%")
check("표본 부족 시 하한", md.realized_vol([100.0]) == md.VOL_FLOOR_PCT)
rising = [100 * (1.05 ** (20 - i)) for i in range(25)]  # 매일 +5% (최신순)
check("일정 등락이면 vol ≈ 해당 등락률", abs(md.realized_vol(rising)) < 0.5,
      f"{md.realized_vol(rising):.3f}% (등락이 균일하면 표준편차 0 → 하한)")
mixed = [100, 95, 100, 95, 100, 95, 100, 95, 100, 95, 100, 95, 100, 95, 100,
         95, 100, 95, 100, 95, 100, 95, 100, 95, 100]
check("교대 등락이면 vol > 0", md.realized_vol(mixed) > 4,
      f"{md.realized_vol(mixed):.2f}%")

print("\n── 2. 전일 등락률이 평균회귀로 쓰이는가 (부호 반전) ──")
# 최신 종가가 직전보다 크게 하락 → 평균회귀는 '상승' 쪽 점수를 줘야 한다.
drop = [90.0, 100.0] + [100.0 + i * 0.01 for i in range(28)]
v = judge(drop)
prev_sig = next(s for s in v["signals"] if "전일" in s["신호"])
check("전일 하락 → 평균회귀 점수 양수", prev_sig["점수"] > 0,
      f"관측 {prev_sig['값']} → 점수 {prev_sig['점수']:+.3f}")
check("라벨에 평균회귀 명시", "평균회귀" in prev_sig["신호"], prev_sig["신호"])

rise = [110.0, 100.0] + [100.0 - i * 0.01 for i in range(28)]
v = judge(rise)
prev_sig = next(s for s in v["signals"] if "전일" in s["신호"])
check("전일 상승 → 평균회귀 점수 음수", prev_sig["점수"] < 0,
      f"관측 {prev_sig['값']} → 점수 {prev_sig['점수']:+.3f}")

print("\n── 3. 가중치 재정규화 (갭 미사용 시) ──")
v_gap = judge(drop, gap=2.0)
v_nogap = judge(drop)
check("갭 사용 시 신호 4개", len(v_gap["signals"]) == 4, f"{len(v_gap['signals'])}개")
check("갭 미사용 시 신호 3개", len(v_nogap["signals"]) == 3, f"{len(v_nogap['signals'])}개")
w_sum = sum(s["가중치"] for s in v_nogap["signals"])
check("남은 가중치 합 = 1 - W_GAP", abs(w_sum - (1 - md.W_GAP)) < 1e-9,
      f"{w_sum} vs {1 - md.W_GAP}")
# 재정규화가 되면 갭 없이도 점수가 0 쪽으로 끌려가지 않는다.
manual = sum(s["점수"] * s["가중치"] for s in v_nogap["signals"]) / w_sum
check("점수 = 가중합 ÷ 남은 가중치 합", abs(v_nogap["score"] - round(manual, 4)) < 1e-3,
      f"{v_nogap['score']} vs {manual:.4f}")
check("점수가 [-1,1] 범위", -1 <= v_nogap["score"] <= 1)

print("\n── 4. 음수 가중치 안전성 (weight_total = Σ|w|) ──")
# 향후 어떤 신호를 음수 가중으로 바꿔도 분모가 줄어 점수가 발산하지 않아야 한다.
with patch.object(md, "W_MA_TREND", -0.15):
    v_neg = judge(drop, gap=2.0)
w_abs = sum(abs(s["가중치"]) for s in v_neg["signals"])
check("음수 가중치여도 점수 [-1,1]", -1 <= v_neg["score"] <= 1, f"{v_neg['score']}")
check("분모는 절대값 합", abs(w_abs - 1.0) < 1e-9, f"Σ|w| = {w_abs}")

print("\n── 5. 정규화가 변동성에 따라 스케일되는가 ──")
# 같은 전일 등락률이라도 고변동 국면에서는 점수(절대값)가 작아야 한다.
calm = [98.0, 100.0] + [100.0 + (i % 2) * 0.2 for i in range(28)]
wild = [98.0, 100.0] + [100.0 + (i % 2) * 15.0 for i in range(28)]
s_calm = next(s for s in judge(calm)["signals"] if "전일" in s["신호"])["점수"]
s_wild = next(s for s in judge(wild)["signals"] if "전일" in s["신호"])["점수"]
check("동일 등락률 → 고변동 국면에서 점수 절대값 감소", abs(s_wild) < abs(s_calm),
      f"저변동 {s_calm:+.3f} vs 고변동 {s_wild:+.3f}")

print("\n── 6. 방향 분기 · 중립 밴드 ──")
v = judge(drop, gap=5.0)
check("종합 상승 → DIRECTION_UP", v["direction"] == DIRECTION_UP, f"{v['score']:+.3f}")
v = judge(rise, gap=-5.0)
check("종합 하락 → DIRECTION_DOWN", v["direction"] == DIRECTION_DOWN, f"{v['score']:+.3f}")
v = judge(drop, gap=5.0, neutral_band=0.99)
check("중립 밴드 안이면 NEUTRAL", v["direction"] == DIRECTION_NEUTRAL, f"{v['score']:+.3f}")

print("\n── 7. 판정 불가 경로 ──")
v = judge([100.0] * 5)  # 일봉 부족
check("일봉 부족 → 중립", v["direction"] == DIRECTION_NEUTRAL)
check("판정 불가 시 vol 필드 존재", "vol" in v, f"vol={v.get('vol')}")
check("판정 불가 시 점수 0", v["score"] == 0.0)

print("\n── 8. 결과 계약 (대시보드 소비 필드) ──")
v = judge(drop, gap=2.0)
for key in ("direction", "score", "signals", "summary", "prev_close", "vol",
            "gap_source", "gap_detail", "judged_at", "proxy_code", "proxy_name"):
    check(f"필드 {key}", key in v)

print()
if fails:
    print(f"❌ 실패 {len(fails)}건: {fails}")
    sys.exit(1)
print("✅ 전부 통과")
