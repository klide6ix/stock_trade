from core.strategy.base import BuyStrategy
from core.kis_api import get_market_cap_rank, get_per_eps, get_weekly_price_change


class VolumeMomentumBuyStrategy(BuyStrategy):
    """시가총액 상위 N → 거래량 상위 M → 주간 상승률 상위 K 종목 선정"""

    def __init__(
        self,
        market_cap_top_n: int = 100,
        volume_top_n: int = 20,
        pick_n: int = 5,
    ) -> None:
        self.market_cap_top_n = market_cap_top_n
        self.volume_top_n = volume_top_n
        self.pick_n = pick_n

    def find_candidates(self) -> list[dict]:
        # 1단계: 시가총액 상위 종목 조회
        top_cap = get_market_cap_rank(top_n=self.market_cap_top_n)

        # 2단계: 거래량 내림차순 정렬 후 상위 volume_top_n 추출
        top_cap.sort(key=lambda x: x["거래량"], reverse=True)
        pool = top_cap[:self.volume_top_n]

        # 3단계: 각 종목 주간 등락률 및 PER·EPS 계산
        candidates = []
        for item in pool:
            code = item["종목코드"]
            try:
                weekly_change = get_weekly_price_change(code)
            except Exception:
                weekly_change = None

            if weekly_change is None:
                continue

            try:
                fundamental = get_per_eps(code)
                per = fundamental["per"]
                eps = fundamental["eps"]
            except Exception:
                per, eps = 0.0, 0.0

            if eps < 0:
                continue

            per_x_eps = round(per * eps, 2)

            candidates.append({
                "종목코드": code,
                "종목명": item["종목명"],
                "현재가": item["현재가"],
                "거래량": item["거래량"],
                "주간등락률(%)": round(weekly_change, 2),
                "PER": per,
                "EPS": eps,
                "PER*EPS": per_x_eps,
            })

        # 4단계: PER*EPS 순위 + 주간등락률 순위 합산 점수로 정렬
        by_per_eps = sorted(candidates, key=lambda x: x["PER*EPS"], reverse=True)
        by_weekly = sorted(candidates, key=lambda x: x["주간등락률(%)"], reverse=True)

        rank_per_eps = {c["종목코드"]: i for i, c in enumerate(by_per_eps)}
        rank_weekly = {c["종목코드"]: i for i, c in enumerate(by_weekly)}

        for c in candidates:
            c["종합순위점수"] = rank_per_eps[c["종목코드"]] + rank_weekly[c["종목코드"]]

        candidates.sort(key=lambda x: x["종합순위점수"])
        return candidates[:self.pick_n]
