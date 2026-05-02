from core.strategy.base import BuyStrategy
from core.strategy.buy._pool import select_momentum_universe
from core.kis_api import get_quote_snapshot, get_daily_ohlcv
from core.logger import log


class HighProximityBuyStrategy(BuyStrategy):
    """N주 신고가 근접도 기반 매수 전략 (모멘텀).

    근접도 = (현재가 - 기간최저) / (기간최고 - 기간최저), 1.0 = 신고가.
    필터: EPS ≥ 0 + 0 < PER ≤ per_max (적자·거품 종목 차단).
    정렬: 근접도 내림차순 단일 기준.
    """

    def __init__(
        self,
        market_cap_top_n: int = 100,
        pool_size: int = 50,
        pick_n: int = 4,
        per_max: float = 30.0,
        window_days: int = 20,
    ) -> None:
        self.market_cap_top_n = market_cap_top_n
        self.pool_size = pool_size
        self.pick_n = pick_n
        self.per_max = per_max
        self.window_days = window_days

    @property
    def display_name(self) -> str:
        weeks = max(1, round(self.window_days / 5))
        return f"{weeks}주 신고가 근접"

    def find_candidates(self) -> list[dict]:
        pool = select_momentum_universe(self.market_cap_top_n, self.pool_size)

        candidates: list[dict] = []
        for item in pool:
            code = item["종목코드"]
            try:
                snap = get_quote_snapshot(code)
                bars = get_daily_ohlcv(code, days=self.window_days)
            except Exception:
                continue

            current = snap["현재가"]
            per = snap["per"]
            eps = snap["eps"]

            if eps < 0 or per <= 0 or per > self.per_max:
                continue

            if len(bars) < self.window_days:
                continue

            high_n = max(b["high"] for b in bars)
            low_n = min(b["low"] for b in bars)
            range_n = high_n - low_n
            if range_n <= 0 or current <= 0:
                continue

            proximity = (current - low_n) / range_n
            weeks = max(1, round(self.window_days / 5))

            candidates.append({
                "종목코드": code,
                "종목명": item["종목명"],
                "현재가": current,
                "거래량": item["거래량"],
                f"{weeks}주신고가근접도": round(proximity, 3),
                "PER": per,
            })

        weeks = max(1, round(self.window_days / 5))
        candidates.sort(key=lambda x: x[f"{weeks}주신고가근접도"], reverse=True)
        log(f"[매수후보][high_proximity] {weeks}주·PER≤{self.per_max} 통과 {len(candidates)}개 / 풀 {len(pool)}")
        return candidates[:self.pick_n]
