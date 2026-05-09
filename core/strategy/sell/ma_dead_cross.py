from core.kis_api import get_daily_ohlcv
from core.logger import log
from core.strategy.base import SellStrategy
from core.strategy.buy._indicators import sma


class MaDeadCrossSellStrategy(SellStrategy):
    """단기 이평선이 장기 이평선을 하향 돌파(데드크로스)하면 매도.

    매 주기 `observe` 시 일봉을 받아 short/long 이평을 캐시.
    `should_sell` 은 short < long 인 즉시 매도 신호.
    """

    def __init__(self, short: int = 5, long: int = 20, history_days: int = 40) -> None:
        if short >= long:
            raise ValueError("short period must be smaller than long period")
        self.short = short
        self.long = long
        self.history_days = history_days
        self._latest: dict[str, tuple[float, float]] = {}

    @property
    def display_name(self) -> str:
        return f"이평선 데드크로스 ({self.short}MA<{self.long}MA)"

    def observe(self, code: str, current_price: float) -> None:
        try:
            bars = get_daily_ohlcv(code, days=self.history_days)
        except Exception as e:
            log(f"[MA매도] {code} 일봉 조회 실패: {e}")
            return
        closes = [b["close"] for b in bars]
        if len(closes) < self.long:
            return
        closes[0] = current_price
        ma_s = sma(closes, self.short)
        ma_l = sma(closes, self.long)
        if ma_s is None or ma_l is None:
            return
        self._latest[code] = (ma_s, ma_l)

    def should_sell(self, code: str, current_price: float) -> tuple[bool, str]:
        latest = self._latest.get(code)
        if latest is None:
            return False, ""
        ma_s, ma_l = latest
        if ma_s < ma_l:
            return True, f"데드크로스 ({self.short}MA {ma_s:,.0f} < {self.long}MA {ma_l:,.0f})"
        return False, ""

    def describe(self, code: str, current_price: float) -> str:
        latest = self._latest.get(code)
        if latest is None:
            return ""
        ma_s, ma_l = latest
        diff_pct = (ma_s - ma_l) / ma_l * 100
        return f"{self.short}MA: {ma_s:,.0f} | {self.long}MA: {ma_l:,.0f} | 격차: {diff_pct:+.1f}%"
