from core.strategy.base import BuyStrategy
from core.strategy.buy._pool import select_momentum_universe
from core.strategy.buy._indicators import sma, rsi
from core.kis_api import get_daily_ohlcv
from core.logger import log


class TechnicalMomentumBuyStrategy(BuyStrategy):
    """일봉 시계열 기반 모멘텀 매수 전략.

    필터: 5MA > 20MA (단기 추세 우상향) + RSI(14) <= rsi_max (과매수 제외).
    시그널점수 = 100 × (1 - rank합(거래량폭증 50% + 20일수익률 50%) / (N-1)).
    """

    def __init__(
        self,
        market_cap_top_n: int = 100,
        pool_size: int = 50,
        pick_n: int = 4,
        rsi_max: float = 80.0,
        history_days: int = 60,
    ) -> None:
        self.market_cap_top_n = market_cap_top_n
        self.pool_size = pool_size
        self.pick_n = pick_n
        self.rsi_max = rsi_max
        self.history_days = history_days

    @property
    def display_name(self) -> str:
        return "기술 모멘텀"

    def find_candidates(self) -> list[dict]:
        pool = select_momentum_universe(self.market_cap_top_n, self.pool_size)

        candidates: list[dict] = []
        for item in pool:
            code = item["종목코드"]
            try:
                bars = get_daily_ohlcv(code, days=self.history_days)
            except Exception:
                continue

            if len(bars) < 21:
                continue

            closes = [b["close"] for b in bars]
            volumes = [b["volume"] for b in bars]

            ma5 = sma(closes, 5)
            ma20 = sma(closes, 20)
            if ma5 is None or ma20 is None:
                continue
            if not (ma5 > ma20):
                continue

            rsi_val = rsi(closes, 14)
            if rsi_val is None or rsi_val > self.rsi_max:
                continue

            today_vol = volumes[0]
            avg_vol_20 = sum(volumes[1:21]) / 20
            if avg_vol_20 <= 0:
                continue
            vol_surge = today_vol / avg_vol_20

            past_close = closes[20]
            if past_close <= 0:
                continue
            return_20d = (closes[0] - past_close) / past_close * 100

            candidates.append({
                "종목코드": code,
                "종목명": item["종목명"],
                "현재가": closes[0],
                "거래량": today_vol,
                "시그널점수": 0.0,  # 아래에서 rank 계산 후 채움
                "5MA": round(ma5, 2),
                "20MA": round(ma20, 2),
                "RSI(14)": round(rsi_val, 1),
                "거래량폭증배수": round(vol_surge, 2),
                "20일수익률(%)": round(return_20d, 2),
            })

        by_vol = sorted(candidates, key=lambda x: x["거래량폭증배수"], reverse=True)
        by_ret = sorted(candidates, key=lambda x: x["20일수익률(%)"], reverse=True)

        rank_vol = {c["종목코드"]: i for i, c in enumerate(by_vol)}
        rank_ret = {c["종목코드"]: i for i, c in enumerate(by_ret)}

        max_rank = max(len(candidates) - 1, 1)
        for c in candidates:
            code = c["종목코드"]
            rank_sum = rank_vol[code] * 0.5 + rank_ret[code] * 0.5
            c["시그널점수"] = round(100.0 * (1.0 - rank_sum / max_rank), 1)

        candidates.sort(key=lambda x: x["시그널점수"], reverse=True)
        log(f"[매수후보][technical] 5MA>20MA + RSI≤{self.rsi_max} 통과 {len(candidates)}개 / 풀 {len(pool)}")
        return candidates[:self.pick_n]
