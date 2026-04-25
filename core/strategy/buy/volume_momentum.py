from core.strategy.base import BuyStrategy
from core.kis_api import (
    get_market_cap_rank,
    get_fluctuation_rank,
    get_per_eps,
    get_weekly_price_change,
)
from core.logger import log


class VolumeMomentumBuyStrategy(BuyStrategy):
    """시가총액 상위 N ∩ 일간등락률 상위 → 주간등락률·PER·EPS 가중 티어 → 상위 K 종목"""

    def __init__(
        self,
        market_cap_top_n: int = 100,
        pool_size: int = 20,
        pick_n: int = 4,
    ) -> None:
        self.market_cap_top_n = market_cap_top_n
        self.pool_size = pool_size
        self.pick_n = pick_n

    def find_candidates(self) -> list[dict]:
        # 1단계: 시가총액 상위 종목 조회
        top_cap = get_market_cap_rank(top_n=self.market_cap_top_n)
        cap_by_code = {item["종목코드"]: item for item in top_cap}

        # 2단계: 일간등락률 상위 (단일 호출) ∩ 시총 상위 → 등락률 순 상위 pool_size
        try:
            daily_rank = get_fluctuation_rank(top_n=30)
        except Exception as e:
            log(f"[매수후보] 일간등락률 조회 실패: {e}")
            daily_rank = []

        pool = [cap_by_code[d["종목코드"]] for d in daily_rank if d["종목코드"] in cap_by_code]
        log(f"[매수후보] 시총 {len(top_cap)} ∩ 일간등락률 {len(daily_rank)} = 교집합 {len(pool)}")

        pool = pool[:self.pool_size]
        if len(pool) < self.pool_size:
            # 교집합 부족 시 시총 상위로 풀 보충 (보통 일간 상위 상승률 = 중·소형주라 교집합이 빌 때 발생)
            seen = {p["종목코드"] for p in pool}
            for item in top_cap:
                if item["종목코드"] not in seen:
                    pool.append(item)
                    if len(pool) >= self.pool_size:
                        break
            log(f"[매수후보] 시총 상위로 보충 → 풀 {len(pool)}개")

        # 3단계: 풀 각 종목 주간등락률 및 PER·EPS 조회
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

            if eps < 0 or per <= 0:
                continue

            candidates.append({
                "종목코드": code,
                "종목명": item["종목명"],
                "현재가": item["현재가"],
                "거래량": item["거래량"],
                "주간등락률(%)": round(weekly_change, 2),
                "PER": per,
                "EPS": eps,
            })

        # 4단계: 가중 순위 합산 (주간등락률 50%, PER 25%, EPS 25%)
        by_per = sorted(candidates, key=lambda x: x["PER"])
        by_eps = sorted(candidates, key=lambda x: x["EPS"], reverse=True)
        by_weekly = sorted(candidates, key=lambda x: x["주간등락률(%)"], reverse=True)

        rank_per = {c["종목코드"]: i for i, c in enumerate(by_per)}
        rank_eps = {c["종목코드"]: i for i, c in enumerate(by_eps)}
        rank_weekly = {c["종목코드"]: i for i, c in enumerate(by_weekly)}

        for c in candidates:
            code = c["종목코드"]
            c["종합티어"] = round(
                rank_weekly[code] * 0.5
                + rank_per[code] * 0.25
                + rank_eps[code] * 0.25,
                2,
            )

        candidates.sort(key=lambda x: x["종합티어"])
        return candidates[:self.pick_n]
