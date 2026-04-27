from core.strategy.base import BuyStrategy
from core.strategy.buy._pool import select_momentum_universe
from core.kis_api import get_quote_snapshot
from core.logger import log


class HighProximityBuyStrategy(BuyStrategy):
    """52주 신고가 근접도 기반 매수 전략 (모멘텀).

    근접도 = (현재가 - 52주최저) / (52주최고 - 52주최저), 1.0 = 신고가.
    필터: EPS ≥ 0 + 0 < PER ≤ per_max (적자·거품 종목 차단).
    정렬: 근접도 내림차순 단일 기준.
    """

    def __init__(
        self,
        market_cap_top_n: int = 100,
        pool_size: int = 20,
        pick_n: int = 4,
        per_max: float = 30.0,
    ) -> None:
        self.market_cap_top_n = market_cap_top_n
        self.pool_size = pool_size
        self.pick_n = pick_n
        self.per_max = per_max

    @property
    def display_name(self) -> str:
        return "52주 신고가 근접"

    def find_candidates(self) -> list[dict]:
        pool = select_momentum_universe(self.market_cap_top_n, self.pool_size)

        candidates: list[dict] = []
        for item in pool:
            code = item["종목코드"]
            try:
                snap = get_quote_snapshot(code)
            except Exception:
                continue

            high52 = snap["52주최고"]
            low52 = snap["52주최저"]
            current = snap["현재가"]
            per = snap["per"]
            eps = snap["eps"]

            if eps < 0 or per <= 0 or per > self.per_max:
                continue

            range52 = high52 - low52
            if range52 <= 0 or current <= 0:
                continue

            proximity = (current - low52) / range52

            candidates.append({
                "종목코드": code,
                "종목명": item["종목명"],
                "현재가": current,
                "거래량": item["거래량"],
                "52주신고가근접도": round(proximity, 3),
                "PER": per,
            })

        candidates.sort(key=lambda x: x["52주신고가근접도"], reverse=True)
        log(f"[매수후보][high_proximity] PER≤{self.per_max} 통과 {len(candidates)}개 / 풀 {len(pool)}")
        return candidates[:self.pick_n]
