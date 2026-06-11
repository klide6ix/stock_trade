from core.strategy.base import BuyStrategy
from core.kis_api import (
    get_market_cap_rank,
    get_fluctuation_rank,
    get_per_eps,
    get_roe,
    get_weekly_price_change,
)
from core.logger import log

# ── ROE 적정 범위 (자기자본이익률, %) ──────────────────────────────────────────
# ROE 는 '높을수록 무조건 좋은' 지표가 아니다. 일반적 가치투자 합의:
#   - 10~20% : 자본을 효율적으로 이익화하면서도 과도한 레버리지 의존이 아닌 '적정' 구간.
#   - <10%   : 자본 효율/수익성 미흡 (한국시장 평균 ROE 가 8~10%대라 그 이하는 평범 이하).
#   - >20%   : 우수해 보이지만, 과도한 부채(레버리지)·자사주 소각·일회성 이익으로
#              부풀려졌을 수 있어 지속가능성 우려. 무조건 배제하진 않되 가점은 낮춘다.
# 따라서 적정 구간은 만점, 미만은 선형 감점, 초과는 '완만한' 감점(잔여 점수 유지)으로
# 밴드 근접도 점수를 매겨 가중에 사용한다.
ROE_IDEAL_LOW = 10.0     # 적정 구간 하한
ROE_IDEAL_HIGH = 20.0    # 적정 구간 상한
ROE_UPPER_CAP = 50.0     # 이 이상이면 초과 감점 최저치 적용
ROE_UPPER_FLOOR = 0.3    # 과도한 ROE 의 잔여 점수 (완만한 페널티 — 0 까지 깎지 않음)


def _roe_band_score(roe: float) -> float:
    """ROE(%) 를 적정 범위 근접도 점수(0~1)로 변환. 1 = 적정 구간(만점).

    - roe ≤ 0 (적자): 0 (호출부에서 사전 배제하지만 방어적으로 0 반환).
    - 0 < roe < LOW : LOW 에서 1, 0 에서 0 으로 선형 증가 (낮을수록 감점).
    - LOW ≤ roe ≤ HIGH : 1.0 (적정 구간 만점).
    - roe > HIGH : HIGH 에서 1, CAP 에서 FLOOR 로 선형 감소 (완만한 페널티).
    """
    if roe <= 0:
        return 0.0
    if roe < ROE_IDEAL_LOW:
        return roe / ROE_IDEAL_LOW
    if roe <= ROE_IDEAL_HIGH:
        return 1.0
    if roe >= ROE_UPPER_CAP:
        return ROE_UPPER_FLOOR
    ratio = (roe - ROE_IDEAL_HIGH) / (ROE_UPPER_CAP - ROE_IDEAL_HIGH)
    return 1.0 - ratio * (1.0 - ROE_UPPER_FLOOR)


class VolumeMomentumBuyStrategy(BuyStrategy):
    """시가총액 상위 N ∩ 일간등락률 상위 → 주간등락률·PER·ROE 가중 티어 → 상위 K 종목.

    가치 신호로 PER 와 EPS 를 함께 쓰던 기존 방식은, PER=주가/EPS 라 두 지표가 같은
    축(주가 대비 이익)을 중복 평가해 사실상 무의미했다. EPS 를 **ROE(자기자본이익률)**
    로 교체해, PER(밸류에이션)·주간등락률(모멘텀)과 직교하는 '자본 효율성' 신호를 더한다.
    ROE 는 높을수록 무조건 좋은 게 아니므로(레버리지·일회성 이익 우려) 적정 범위
    (`ROE_IDEAL_LOW`~`ROE_IDEAL_HIGH`) 근접도로 점수화해 가중한다.
    """

    def __init__(
        self,
        market_cap_top_n: int = 100,
        pool_size: int = 20,
        pick_n: int = 4,
    ) -> None:
        self.market_cap_top_n = market_cap_top_n
        self.pool_size = pool_size
        self.pick_n = pick_n

    @property
    def display_name(self) -> str:
        return "거래량+주간등락·PER·ROE"

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

        # 3단계: 풀 각 종목 주간등락률 · PER · ROE 조회
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
                per = get_per_eps(code)["per"]
            except Exception:
                per = 0.0

            roe = get_roe(code)

            # PER ≤ 0 (적자/이상치) · ROE 없음/적자(≤0) 종목은 가치 신호 부재로 제외.
            if per <= 0 or roe is None or roe <= 0:
                continue

            candidates.append({
                "종목코드": code,
                "종목명": item["종목명"],
                "현재가": item["현재가"],
                "거래량": item["거래량"],
                "시그널점수": 0.0,  # 아래에서 rank 계산 후 채움
                "주간등락률(%)": round(weekly_change, 2),
                "PER": per,
                "ROE(%)": round(roe, 2),
                "_roe_score": _roe_band_score(roe),  # 정렬용 내부 필드 (표시 전 제거)
            })

        # 4단계: 가중 순위 합산 (주간등락률 50%, PER 25%, ROE 적정범위 25%) → 시그널점수 0~100
        #   - PER : 오름차순(낮을수록 저평가 = 상위)
        #   - ROE : 적정범위 근접도(_roe_score) 내림차순(높을수록 상위)
        #   - 주간등락률 : 내림차순(높을수록 상위)
        by_per = sorted(candidates, key=lambda x: x["PER"])
        by_roe = sorted(candidates, key=lambda x: x["_roe_score"], reverse=True)
        by_weekly = sorted(candidates, key=lambda x: x["주간등락률(%)"], reverse=True)

        rank_per = {c["종목코드"]: i for i, c in enumerate(by_per)}
        rank_roe = {c["종목코드"]: i for i, c in enumerate(by_roe)}
        rank_weekly = {c["종목코드"]: i for i, c in enumerate(by_weekly)}

        max_rank = max(len(candidates) - 1, 1)
        for c in candidates:
            code = c["종목코드"]
            rank_sum = (
                rank_weekly[code] * 0.5
                + rank_per[code] * 0.25
                + rank_roe[code] * 0.25
            )
            c["시그널점수"] = round(100.0 * (1.0 - rank_sum / max_rank), 1)

        candidates.sort(key=lambda x: x["시그널점수"], reverse=True)
        top = candidates[:self.pick_n]
        for c in top:
            c.pop("_roe_score", None)  # 내부 정렬 필드는 표시/저장 전 제거
        return top
