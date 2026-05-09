from core.strategy.base import BuyStrategy
from core.strategy.buy._pool import select_momentum_universe
from core.strategy.buy._indicators import sma
from core.kis_api import get_daily_ohlcv
from core.logger import log


class GoldenCrossBuyStrategy(BuyStrategy):
    """5MA가 20MA를 상향 돌파한 직후 종목 (단기 추세 전환 진입).

    오늘: 5MA > 20MA, 그리고 직전 `max_days_after_cross`영업일 내 어느 날에
    5MA ≤ 20MA 였던 적이 있어야 함 (즉 최근 골든크로스 발생).
    정렬: 교차 후 일수 오름차순 (최근 발생 우선).
    """

    def __init__(
        self,
        market_cap_top_n: int = 100,
        pool_size: int = 50,
        pick_n: int = 4,
        max_days_after_cross: int = 5,
        history_days: int = 60,
    ) -> None:
        self.market_cap_top_n = market_cap_top_n
        self.pool_size = pool_size
        self.pick_n = pick_n
        self.max_days_after_cross = max_days_after_cross
        self.history_days = history_days

    @property
    def display_name(self) -> str:
        return "골든크로스"

    def find_candidates(self) -> list[dict]:
        pool = select_momentum_universe(self.market_cap_top_n, self.pool_size)

        candidates: list[dict] = []
        drop_no_cross = 0
        for item in pool:
            code = item["종목코드"]
            try:
                bars = get_daily_ohlcv(code, days=self.history_days)
            except Exception:
                continue

            if len(bars) < 25:
                continue

            closes = [b["close"] for b in bars]
            ma5 = sma(closes, 5)
            ma20 = sma(closes, 20)
            if ma5 is None or ma20 is None or ma5 <= ma20:
                continue

            days_since_cross: int | None = None
            for d in range(1, self.max_days_after_cross + 1):
                ma5_past = sma(closes[d:], 5)
                ma20_past = sma(closes[d:], 20)
                if ma5_past is None or ma20_past is None:
                    break
                if ma5_past <= ma20_past:
                    days_since_cross = d
                    break

            if days_since_cross is None:
                drop_no_cross += 1
                continue

            candidates.append({
                "종목코드": code,
                "종목명": item["종목명"],
                "현재가": closes[0],
                "거래량": item["거래량"],
                "5MA": round(ma5, 2),
                "20MA": round(ma20, 2),
                "교차후일수": days_since_cross,
            })

        candidates.sort(key=lambda x: x["교차후일수"])
        log(
            f"[매수후보][golden_cross] 5MA>20MA + 최근 {self.max_days_after_cross}일 내 교차 통과 "
            f"{len(candidates)}개 / 풀 {len(pool)} (탈락 비교차 {drop_no_cross})"
        )
        return candidates[:self.pick_n]
