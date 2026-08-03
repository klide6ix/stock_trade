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

print("\n── 5-b. MAD 기반 변동성 (realized_vol_mad) ──")
import random as _random


def _series(returns):
    """등락률 리스트(%)로 최신순 종가 시계열 생성."""
    px = [100.0]
    for r in returns:
        px.append(px[-1] * (1 + r / 100))
    return list(reversed(px))


_rng = _random.Random(0)
_normal = _series([_rng.gauss(0, 1.0) for _ in range(30)])   # 정규분포 ±1%
_closes = _normal
check("등락 없으면 하한 적용", md.realized_vol_mad(FLAT) == md.VOL_FLOOR_PCT)
check("표본 부족 시 하한", md.realized_vol_mad([100.0]) == md.VOL_FLOOR_PCT)
_v_std, _v_mad = md.realized_vol(_closes), md.realized_vol_mad(_closes)
check("정규분포 표본에서는 표준편차와 근사", abs(_v_mad - _v_std) / _v_std < 0.25,
      f"σ {_v_std:.2f}% vs MAD {_v_mad:.2f}%")

# 1.4826 은 정규분포 전제 상수다. 등락폭이 고르게 큰(양봉단조·꼬리 얇은) 표본에서는
# MAD 기반이 오히려 **과대** 추정된다 — 2026-07 실데이터에서 MAD 가 표준편차보다
# 30~39% 크게 나온 원인이므로 성질로 못박아 둔다.
_bimodal = _series([1.0, -1.0] * 15)
check("꼬리 얇은 표본에서는 MAD 가 과대 추정",
      md.realized_vol_mad(_bimodal) > md.realized_vol(_bimodal) * 1.3,
      f"σ {md.realized_vol(_bimodal):.2f}% vs MAD {md.realized_vol_mad(_bimodal):.2f}%")

# 이상치 1개 주입 — 표준편차는 크게 흔들리고 MAD 는 거의 그대로여야 한다.
_spiked = list(_closes)
_spiked[0] = _spiked[0] * 1.25              # 최근 하루 +25%
_s_std, _s_mad = md.realized_vol(_spiked), md.realized_vol_mad(_spiked)
check("이상치에 표준편차는 크게 반응", _s_std / _v_std > 1.5, f"{_v_std:.2f}% → {_s_std:.2f}%")
check("이상치에 MAD 는 거의 불변", _s_mad / _v_mad < 1.2, f"{_v_mad:.2f}% → {_s_mad:.2f}%")
check("MAD 도 하한을 지킨다", md.realized_vol_mad([100.0, 100.0, 100.0]) >= md.VOL_FLOOR_PCT)

print("\n── 5-c. 장전 placeholder 봉 판별 (갭 신호 경로 선택) ──")
# KIS 는 개장 전에도 오늘 날짜 봉을 전일 종가·거래량 0 으로 채워서 준다.
# 이걸 장중으로 오인하면 갭(가중치 0.50)이 +0.00% 로 들어가 판정이 절반으로 희석된다.
_TODAY = "20260803"
_NOW_PRE = datetime(2026, 8, 3, 8, 40)      # 장전
_NOW_OPEN = datetime(2026, 8, 3, 10, 0)     # 장중


_walk_rng = _random.Random(7)
_walk = [100.0]
for _ in range(25):                      # 일간 σ 약 2% 인 임의보행 — 신호가 포화되지 않게
    _walk.append(_walk[-1] * (1 + _walk_rng.gauss(0, 2.0) / 100))
_WALK_CLOSES = list(reversed(_walk))     # 최신순


def _bars_with_today(volume):
    """오늘 봉(거래량 지정) + 확정 과거봉 25개. 최신순."""
    past = [{"date": f"202607{28 - i:02d}" if i < 28 else f"202606{56 - i:02d}",
             "open": c, "high": c, "low": c, "close": c, "volume": 1000}
            for i, c in enumerate(_WALK_CLOSES)]
    return [{"date": _TODAY, "open": past[0]["close"], "high": past[0]["close"],
             "low": past[0]["close"], "close": past[0]["close"],
             "volume": volume}] + past


def _judge_with(bars, now):
    """실제 `_gap_signal` 을 태워 어느 경로로 갔는지 본다."""
    calls = []
    def fake_snapshot(code):
        calls.append("realtime")
        return {"전일대비등락률(%)": 0.0}
    def fake_expected(code):
        calls.append("expected")
        return {"예상체결가": 0, "기준가": 0, "예상거래량": 0}
    with patch.object(md, "get_daily_ohlcv", return_value=bars), \
         patch.object(md, "get_quote_snapshot", side_effect=fake_snapshot), \
         patch.object(md, "get_expected_open_quote", side_effect=fake_expected):
        v = md.judge_direction(now=now)
    return v, calls


check("오늘 봉 거래량 0 + 장전 → 예상체결가 경로",
      _judge_with(_bars_with_today(0), _NOW_PRE)[1] == ["expected"])
check("오늘 봉 거래량 0 + 장중 시각 → 예상체결가 경로 (휴장일 대응)",
      _judge_with(_bars_with_today(0), _NOW_OPEN)[1] == ["expected"])
check("오늘 봉 거래량 > 0 + 장전 → 예상체결가 경로 (시각 보강)",
      _judge_with(_bars_with_today(5000), _NOW_PRE)[1] == ["expected"])
check("오늘 봉 거래량 > 0 + 장중 → 실시간 등락률 경로",
      _judge_with(_bars_with_today(5000), _NOW_OPEN)[1] == ["realtime"])
check("오늘 봉 자체가 없으면 예상체결가 경로",
      _judge_with(_bars_with_today(0)[1:], _NOW_PRE)[1] == ["expected"])

# placeholder 를 장중으로 오인하면 갭이 0.00% 로 편입되어 분모만 2배가 된다.
# 갭을 미사용 처리하면 나머지 가중치(0.50)로 재정규화되므로 점수가 정확히 2배가 되어야 한다.
_v_fixed, _ = _judge_with(_bars_with_today(0), _NOW_PRE)      # 갭 미사용 → 재정규화
_v_bug, _ = _judge_with(_bars_with_today(5000), _NOW_OPEN)    # 갭 0.00% 로 편입
check("0% 갭 편입은 확신도를 정확히 절반으로 희석시킨다",
      abs(_v_bug["score"]) > 0.01 and abs(_v_fixed["score"] - 2 * _v_bug["score"]) < 1e-6,
      f"수정 후 {_v_fixed['score']:+.4f} = 2 × {_v_bug['score']:+.4f}(0% 편입)")
check("갭 미사용이면 gap_source 가 None", _v_fixed["gap_source"] is None)
check("placeholder 봉은 과거봉에서 제외되어 전일 종가가 어긋나지 않는다",
      _v_fixed["prev_close"] == _WALK_CLOSES[0],
      f"{_v_fixed['prev_close']:.2f} (직전 확정 종가 {_WALK_CLOSES[0]:.2f})")

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
