import json
import os
from datetime import datetime

from core.logger import log
from core.strategy.base import SellStrategy

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
_DATA_DIR = os.path.join(_BASE_DIR, "data")
PEAK_PRICES_FILE = os.path.join(_DATA_DIR, "peak_prices.json")


class TrailingStopSellStrategy(SellStrategy):
    """최고가 대비 일정 % 이상 하락 시 매도 (트레일링 스탑).

    최고가(peak) 상태는 이 전략이 직접 소유·영속화한다. `update_peak` 은 범용
    인터페이스가 아닌 이 전략의 내부 동작으로만 존재한다.
    """

    def __init__(self, stop_loss_pct: float) -> None:
        self.stop_loss_pct = stop_loss_pct
        self.peak_prices: dict[str, float] = {}

    # ── 내부 상태 ─────────────────────────────────────────────────────────────

    def _update_peak(self, code: str, price: float) -> bool:
        """최고가 갱신. 변경되었으면 True."""
        prev = self.peak_prices.get(code)
        if prev is None or price > prev:
            self.peak_prices[code] = price
            return True
        return False

    def peak_of(self, code: str) -> float | None:
        return self.peak_prices.get(code)

    # ── SellStrategy 훅 ───────────────────────────────────────────────────────

    def observe(self, code: str, current_price: float) -> None:
        if self._update_peak(code, current_price):
            self.save()

    def on_buy(self, code: str, buy_price: float) -> None:
        if code not in self.peak_prices and buy_price > 0:
            self.peak_prices[code] = buy_price
            self.save()

    def should_sell(self, code: str, current_price: float) -> tuple[bool, str]:
        peak = self.peak_prices.get(code)
        if peak is None or peak <= 0:
            return False, ""
        drop_pct = (peak - current_price) / peak * 100
        if drop_pct >= self.stop_loss_pct:
            return True, f"손절 ({drop_pct:.1f}% 하락)"
        return False, ""

    def describe(self, code: str, current_price: float) -> str:
        peak = self.peak_prices.get(code)
        if peak is None or peak <= 0:
            return ""
        drop_pct = (peak - current_price) / peak * 100
        return f"최고가: {peak:,.0f}원 | 하락률: {drop_pct:.1f}%"

    # ── 영속화 ────────────────────────────────────────────────────────────────

    def load(self) -> None:
        if not os.path.exists(PEAK_PRICES_FILE):
            return
        try:
            with open(PEAK_PRICES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.peak_prices = {k: float(v) for k, v in data.get("prices", {}).items()}
            log(f"[최고가] {len(self.peak_prices)}개 종목 복원 완료")
        except Exception as e:
            log(f"[최고가] 복원 실패: {e}")

    def save(self) -> None:
        try:
            os.makedirs(_DATA_DIR, exist_ok=True)
            with open(PEAK_PRICES_FILE, "w", encoding="utf-8") as f:
                json.dump(
                    {"updated_at": datetime.now().isoformat(), "prices": self.peak_prices},
                    f, ensure_ascii=False, indent=2,
                )
        except Exception as e:
            log(f"[최고가] 저장 실패: {e}")
