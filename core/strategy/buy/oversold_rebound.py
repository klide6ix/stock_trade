from core.strategy.base import BuyStrategy
from core.strategy.buy._pool import select_momentum_universe
from core.strategy.buy._indicators import rsi
from core.kis_api import get_daily_ohlcv
from core.logger import log


class OversoldReboundBuyStrategy(BuyStrategy):
    """과매도(RSI≤30) 후 반등 시그널 — 역추세 매수.

    필터:
        직전 영업일 RSI(14) ≤ rsi_oversold (과매도)
        오늘 종가 > 직전 영업일 종가 (반등 시작)
        오늘 RSI(14) > 직전 RSI (회복 추세)
    정렬: 직전 RSI 오름차순 (가장 과매도였던 종목 우선).
    """

    def __init__(
        self,
        market_cap_top_n: int = 100,
        pool_size: int = 50,
        pick_n: int = 4,
        rsi_oversold: float = 30.0,
        history_days: int = 40,
    ) -> None:
        self.market_cap_top_n = market_cap_top_n
        self.pool_size = pool_size
        self.pick_n = pick_n
        self.rsi_oversold = rsi_oversold
        self.history_days = history_days

    @property
    def display_name(self) -> str:
        return "과매도 반등"

    def find_candidates(self) -> list[dict]:
        pool = select_momentum_universe(self.market_cap_top_n, self.pool_size)

        candidates: list[dict] = []
        drop_not_oversold = drop_no_rebound = 0
        for item in pool:
            code = item["종목코드"]
            try:
                bars = get_daily_ohlcv(code, days=self.history_days)
            except Exception:
                continue

            if len(bars) < 17:
                continue

            closes = [b["close"] for b in bars]
            today_rsi = rsi(closes, 14)
            prev_rsi = rsi(closes[1:], 14)
            if today_rsi is None or prev_rsi is None:
                continue

            if prev_rsi > self.rsi_oversold:
                drop_not_oversold += 1
                continue

            if closes[0] <= closes[1] or today_rsi <= prev_rsi:
                drop_no_rebound += 1
                continue

            candidates.append({
                "종목코드": code,
                "종목명": item["종목명"],
                "현재가": closes[0],
                "거래량": item["거래량"],
                "직전RSI(14)": round(prev_rsi, 1),
                "오늘RSI(14)": round(today_rsi, 1),
                "반등률(%)": round((closes[0] - closes[1]) / closes[1] * 100, 2),
            })

        candidates.sort(key=lambda x: x["직전RSI(14)"])
        log(
            f"[매수후보][oversold_rebound] 직전RSI≤{self.rsi_oversold} + 반등 통과 "
            f"{len(candidates)}개 / 풀 {len(pool)} (탈락 비과매도 {drop_not_oversold} · 미반등 {drop_no_rebound})"
        )
        return candidates[:self.pick_n]
