from core.strategy.base import BuyStrategy
from core.strategy.buy._pool import select_momentum_universe
from core.strategy.buy._indicators import sma, rsi
from core.kis_api import get_quote_snapshot, get_daily_ohlcv
from core.logger import log


class QualityTrendBuyStrategy(BuyStrategy):
    """우량(가치) + 우상향(모멘텀) 결합 전략.

    필터:
        EPS ≥ 0
        0 < PER ≤ per_max          (적자/거품 차단)
        0 < PBR ≤ pbr_max          (자산 대비 거품 차단, EPS 일시 왜곡 보완)
        20MA > 60MA                 (중기 우상향)
        현재가 > 20MA               (단기 추세 유지)
        RSI(14) ≤ rsi_max          (과열 회피)

    정렬: window_days(기본 4주) 신고가 근접도 내림차순.
    """

    def __init__(
        self,
        market_cap_top_n: int = 100,
        pool_size: int = 50,
        pick_n: int = 4,
        per_max: float = 50.0,
        pbr_max: float = 5.0,
        rsi_max: float = 70.0,
        window_days: int = 20,
        history_days: int = 80,
    ) -> None:
        self.market_cap_top_n = market_cap_top_n
        self.pool_size = pool_size
        self.pick_n = pick_n
        self.per_max = per_max
        self.pbr_max = pbr_max
        self.rsi_max = rsi_max
        self.window_days = window_days
        self.history_days = history_days

    @property
    def display_name(self) -> str:
        return "우량+우상향"

    def find_candidates(self) -> list[dict]:
        pool = select_momentum_universe(self.market_cap_top_n, self.pool_size)

        filtered: list[dict] = []
        drop_value = drop_trend = drop_rsi = 0
        for item in pool:
            code = item["종목코드"]
            try:
                snap = get_quote_snapshot(code)
                bars = get_daily_ohlcv(code, days=self.history_days)
            except Exception:
                continue

            current = snap["현재가"]
            per = snap["per"]
            eps = snap["eps"]
            pbr = snap["pbr"]

            if eps < 0 or per <= 0 or per > self.per_max or pbr <= 0 or pbr > self.pbr_max:
                drop_value += 1
                continue

            if len(bars) < 60:
                continue

            closes = [b["close"] for b in bars]
            ma20 = sma(closes, 20)
            ma60 = sma(closes, 60)
            if ma20 is None or ma60 is None:
                continue
            if not (ma20 > ma60 and current > ma20):
                drop_trend += 1
                continue

            rsi_val = rsi(closes, 14)
            if rsi_val is None or rsi_val > self.rsi_max:
                drop_rsi += 1
                continue

            window = bars[:self.window_days]
            high_w = max(b["high"] for b in window)
            low_w = min(b["low"] for b in window)
            range_w = high_w - low_w
            if range_w <= 0:
                continue
            proximity = (current - low_w) / range_w

            weeks = max(1, round(self.window_days / 5))
            filtered.append({
                "종목코드": code,
                "종목명": item["종목명"],
                "현재가": current,
                "거래량": item["거래량"],
                "시그널점수": round(proximity * 100, 1),
                f"{weeks}주신고가근접도": round(proximity, 3),
                "20MA": round(ma20, 2),
                "60MA": round(ma60, 2),
                "RSI(14)": round(rsi_val, 1),
                "PER": per,
                "PBR": pbr,
            })

        filtered.sort(key=lambda x: x["시그널점수"], reverse=True)
        log(
            f"[매수후보][quality_trend] PER≤{self.per_max}·PBR≤{self.pbr_max}·20MA>60MA·현재가>20MA·RSI≤{self.rsi_max} "
            f"통과 {len(filtered)}개 / 풀 {len(pool)} (탈락 가치 {drop_value} · 추세 {drop_trend} · RSI {drop_rsi})"
        )
        return filtered[:self.pick_n]
