from core.strategy.base import BuyStrategy
from core.kis_api import get_market_cap_rank, get_quote_snapshot
from core.logger import log


class LowPerBuyStrategy(BuyStrategy):
    """시가총액 상위 N 중 저PER 가치주 (모멘텀 무관).

    필터: EPS ≥ 0 ∧ 0 < PER ≤ per_max ∧ 0 < PBR ≤ pbr_max.
    정렬: PER 오름차순 단일 기준.
    """

    def __init__(
        self,
        market_cap_top_n: int = 100,
        scan_n: int = 60,
        pick_n: int = 4,
        per_max: float = 15.0,
        pbr_max: float = 2.0,
    ) -> None:
        self.market_cap_top_n = market_cap_top_n
        self.scan_n = scan_n
        self.pick_n = pick_n
        self.per_max = per_max
        self.pbr_max = pbr_max

    @property
    def display_name(self) -> str:
        return "저PER 가치주"

    def find_candidates(self) -> list[dict]:
        top_cap = get_market_cap_rank(top_n=self.market_cap_top_n)
        scan = top_cap[:self.scan_n]

        candidates: list[dict] = []
        drop_value = 0
        for item in scan:
            code = item["종목코드"]
            try:
                snap = get_quote_snapshot(code)
            except Exception:
                continue

            per = snap["per"]
            eps = snap["eps"]
            pbr = snap["pbr"]
            current = snap["현재가"]

            if eps < 0 or per <= 0 or per > self.per_max or pbr <= 0 or pbr > self.pbr_max:
                drop_value += 1
                continue

            candidates.append({
                "종목코드": code,
                "종목명": item["종목명"],
                "현재가": current,
                "거래량": item["거래량"],
                "PER": per,
                "PBR": pbr,
                "EPS": eps,
            })

        candidates.sort(key=lambda x: x["PER"])
        log(
            f"[매수후보][low_per] PER≤{self.per_max}·PBR≤{self.pbr_max}·EPS≥0 통과 "
            f"{len(candidates)}개 / 스캔 {len(scan)} (탈락 가치 {drop_value})"
        )
        return candidates[:self.pick_n]
