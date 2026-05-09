from core.kis_api import get_daily_ohlcv
from core.logger import log
from core.strategy.base import SellStrategy
from core.strategy.buy._indicators import rsi


class RsiSellStrategy(SellStrategy):
    """RSI(14) ≥ rsi_max 일 때 매도 (과열 회피).

    매 주기 `observe` 시 일봉을 받아 RSI 를 캐시하고, `should_sell` 은 캐시값을 사용.
    내부 상태는 메모리 캐시뿐이며 영속화하지 않는다 (지표는 일봉으로 매번 재산출).
    """

    def __init__(self, rsi_max: float = 75.0, period: int = 14, history_days: int = 30) -> None:
        self.rsi_max = rsi_max
        self.period = period
        self.history_days = history_days
        self._latest: dict[str, float] = {}

    @property
    def display_name(self) -> str:
        return f"RSI 과열 매도 (≥{self.rsi_max:.0f})"

    def observe(self, code: str, current_price: float) -> None:
        try:
            bars = get_daily_ohlcv(code, days=self.history_days)
        except Exception as e:
            log(f"[RSI매도] {code} 일봉 조회 실패: {e}")
            return
        closes = [b["close"] for b in bars]
        if not closes:
            return
        # 일봉의 최신 종가를 현재가로 덮어 장중 RSI 근사
        closes[0] = current_price
        r = rsi(closes, self.period)
        if r is not None:
            self._latest[code] = r

    def should_sell(self, code: str, current_price: float) -> tuple[bool, str]:
        r = self._latest.get(code)
        if r is None:
            return False, ""
        if r >= self.rsi_max:
            return True, f"RSI 과열 ({r:.1f} ≥ {self.rsi_max:.0f})"
        return False, ""

    def describe(self, code: str, current_price: float) -> str:
        r = self._latest.get(code)
        if r is None:
            return ""
        return f"RSI(14): {r:.1f} | 매도 임계 ≥ {self.rsi_max:.0f}"
