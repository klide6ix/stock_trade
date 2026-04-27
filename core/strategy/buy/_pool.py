from core.kis_api import get_market_cap_rank, get_fluctuation_rank
from core.logger import log


def select_momentum_universe(
    market_cap_top_n: int = 100,
    pool_size: int = 20,
) -> list[dict]:
    """모멘텀 전략의 공통 1차 풀.

    시가총액 상위 N ∩ 일간등락률 상위 → pool_size 종목.
    교집합이 부족하면 시총 상위로 보충.
    """
    top_cap = get_market_cap_rank(top_n=market_cap_top_n)
    cap_by_code = {item["종목코드"]: item for item in top_cap}

    try:
        daily_rank = get_fluctuation_rank(top_n=30)
    except Exception as e:
        log(f"[매수후보] 일간등락률 조회 실패: {e}")
        daily_rank = []

    pool = [cap_by_code[d["종목코드"]] for d in daily_rank if d["종목코드"] in cap_by_code]
    log(f"[매수후보] 시총 {len(top_cap)} ∩ 일간등락률 {len(daily_rank)} = 교집합 {len(pool)}")

    pool = pool[:pool_size]
    if len(pool) < pool_size:
        seen = {p["종목코드"] for p in pool}
        for item in top_cap:
            if item["종목코드"] not in seen:
                pool.append(item)
                if len(pool) >= pool_size:
                    break
        log(f"[매수후보] 시총 상위로 보충 → 풀 {len(pool)}개")

    return pool
