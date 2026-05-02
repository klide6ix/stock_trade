"""활성 매수 전략 구성. `main.py` · `ui/dashboard.py` 양쪽에서 공유.

전략 교체 시 이 파일 한 곳만 수정한다.
"""
from core.strategy.base import BuyStrategy
from core.strategy.buy import (
    HighProximityBuyStrategy,
    TechnicalMomentumBuyStrategy,
    QualityTrendBuyStrategy,
)


def primary_buy_strategy() -> BuyStrategy:
    """매수 실행에 사용되는 메인 전략."""
    return QualityTrendBuyStrategy(market_cap_top_n=100, pick_n=4)


def view_buy_strategies() -> list[BuyStrategy]:
    """대시보드 비교용 보조 전략 (매수 실행하지 않음)."""
    return [
        HighProximityBuyStrategy(market_cap_top_n=100, pick_n=4),
        TechnicalMomentumBuyStrategy(market_cap_top_n=100, pick_n=4),
    ]
