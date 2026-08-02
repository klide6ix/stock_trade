"""변동성 배수 청산선 순수 로직 검증 (API 호출 없음).

검증 대상
  1. `EtfDayTradeStrategy.exit_thresholds` — 배수 산출 · 클램프 · fallback · 고정 모드
  2. `should_sell` 이 그 청산선을 실제로 적용하는지 (경계값)
  3. σ 가 후보 → 슬롯 → 청산 판정까지 전달되는지
"""
import sys
from datetime import datetime

from config import (
    SHORT_TERM_EXIT_MAX_PCT,
    SHORT_TERM_EXIT_MIN_PCT,
    SHORT_TERM_PEAK_DROP_MULT,
    SHORT_TERM_STOP_LOSS_MULT,
)
from core.short_term import (
    SELL_PEAK_DROP,
    SELL_STOP_LOSS,
    EtfDayTradeStrategy,
    mark_entry,
    target_to_settings,
)

fails = []


def check(name, cond, detail=""):
    print(f"  {'✅' if cond else '❌'} {name}" + (f" — {detail}" if detail else ""))
    if not cond:
        fails.append(name)


S = EtfDayTradeStrategy()          # 기본 = 변동성 배수 모드
FIXED = EtfDayTradeStrategy(exit_mode="fixed")

print("── 1. 배수 산출 ──")
stop, peak, basis = S.exit_thresholds({"vol": 4.0})
check("손절 = 2.5σ", abs(stop - 2.5 * 4.0) < 1e-9, f"{stop:.2f}%")
check("트레일링 = 2.0σ", abs(peak - 2.0 * 4.0) < 1e-9, f"{peak:.2f}%")
check("근거 라벨에 σ 표기", basis == "σ 4.00%", basis)
check("기본 배수가 config 와 일치",
      (S.stop_loss_mult, S.peak_drop_mult) == (SHORT_TERM_STOP_LOSS_MULT, SHORT_TERM_PEAK_DROP_MULT))

print("\n── 2. 클램프 (검증된 범위 밖으로 나가지 않기) ──")
stop, peak, _ = S.exit_thresholds({"vol": 1.0})     # 2.5 / 2.0 → 하한
check("저변동: 하한 적용", (stop, peak) == (SHORT_TERM_EXIT_MIN_PCT, SHORT_TERM_EXIT_MIN_PCT),
      f"{stop:.2f}/{peak:.2f}")
stop, peak, _ = S.exit_thresholds({"vol": 12.0})    # 30 / 24 → 상한
check("고변동: 상한 적용", (stop, peak) == (SHORT_TERM_EXIT_MAX_PCT, SHORT_TERM_EXIT_MAX_PCT),
      f"{stop:.2f}/{peak:.2f}")
stop, peak, _ = S.exit_thresholds({"vol": 5.16})    # 12.90 / 10.32 → 둘 다 범위 안
check("중간 변동: 그대로 통과", abs(stop - 12.9) < 0.01 and abs(peak - 10.32) < 0.01,
      f"{stop:.2f}/{peak:.2f}")

print("\n── 3. fallback · 고정 모드 ──")
for slot, label in (({}, "vol 없음"), ({"vol": 0}, "vol 0"),
                    ({"vol": "abc"}, "vol 문자열"), ({"vol": -3}, "vol 음수")):
    stop, peak, basis = S.exit_thresholds(slot)
    check(f"{label} → 고정 % fallback",
          (stop, peak) == (S.stop_loss_pct, S.peak_drop_pct) and "고정" in basis, basis)
stop, peak, basis = FIXED.exit_thresholds({"vol": 7.5})
check("고정 모드는 σ 를 무시", (stop, peak) == (10.0, 10.0) and basis == "고정", basis)

print("\n── 4. should_sell 경계값 (σ 4% → 손절 10% · 트레일링 8%) ──")
NOW = datetime(2026, 8, 3, 10, 0)
base = {"code": "069500", "vol": 4.0, "entry_price": 10_000.0, "qty": 10,
        "entry_at": NOW.isoformat(), "peak": 10_000.0}

d = S.should_sell(base, 9_010.0, now=NOW)       # -9.9% → 손절 미달, 최고가 -9.9% ≥ 8% → 청산
check("트레일링이 손절보다 먼저 걸린다", d.sell and d.kind == SELL_PEAK_DROP, d.reason)

flat = {**base, "peak": 10_000.0}
d = S.should_sell(flat, 9_250.0, now=NOW)       # -7.5% → 트레일링 8% 미달
check("트레일링 경계 직전은 보유", not d.sell, d.reason)
d = S.should_sell(flat, 9_200.0, now=NOW)       # -8.0% 도달
check("트레일링 경계 도달 시 청산", d.sell and d.kind == SELL_PEAK_DROP, d.reason)

# 최고가를 진입가와 같게 두고 손절만 남기려면 트레일링을 끄는 편이 명확하다.
no_trail = EtfDayTradeStrategy(peak_drop_mult=99.0, exit_max_pct=100.0, exit_min_pct=0.5)
d = no_trail.should_sell(base, 9_000.0, now=NOW)   # -10.0% = 2.5σ
check("손절 경계 도달 시 손절", d.sell and d.kind == SELL_STOP_LOSS, d.reason)
d = no_trail.should_sell(base, 9_050.0, now=NOW)   # -9.5%
check("손절 경계 직전은 보유", not d.sell)
check("청산 사유에 근거(σ) 노출", "σ 4.00%" in (
    no_trail.should_sell(base, 9_000.0, now=NOW).reason))

print("\n── 5. σ 전달 경로 (후보 → 슬롯 → 진입 원장) ──")
target = {"종목코드": "114800", "종목명": "KODEX 인버스", "방향": "down",
          "선정사유": "하락 판정", "변동성(%)": 5.16}
slot = target_to_settings(target, auto_enabled=True)
check("후보의 변동성이 슬롯으로 복사", slot["vol"] == 5.16, str(slot["vol"]))
entered = mark_entry(slot, price=1_000.0, qty=100, now=NOW)
check("진입 후에도 σ 유지", entered["vol"] == 5.16)
stop, peak, _ = S.exit_thresholds(entered)
check("진입 슬롯으로 청산선 산출", abs(stop - 12.9) < 0.01 and abs(peak - 10.32) < 0.01,
      f"손절 {stop:.2f}% · 트레일링 {peak:.2f}%")
check("σ 없는 구버전 슬롯도 동작", S.exit_thresholds({"entry_price": 100})[0] == S.stop_loss_pct)

print("\n── 6. display_name ──")
check("배수 모드 표기", "σ" in S.display_name, S.display_name)
check("고정 모드 표기", "%" in FIXED.display_name and "σ" not in FIXED.display_name,
      FIXED.display_name)

print()
if fails:
    print(f"❌ 실패 {len(fails)}건: {fails}")
    sys.exit(1)
print("✅ 전부 통과")
