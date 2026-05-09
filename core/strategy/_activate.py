"""활성 전략 구성 — settings.json 의 사용자 선택을 반영해 인스턴스를 생성한다.

`main.py` · `ui/dashboard.py` 양쪽에서 동일 모듈을 import 하므로,
사용자가 사이드바에서 view 매수 전략 / 매도 전략을 변경하면 자동 반영된다.
"""
from typing import Callable

from core.settings import get as get_setting
from core.strategy.base import BuyStrategy, SellStrategy
from core.strategy.buy import (
    GoldenCrossBuyStrategy,
    HighProximityBuyStrategy,
    LowPerBuyStrategy,
    OversoldReboundBuyStrategy,
    QualityTrendBuyStrategy,
    TechnicalMomentumBuyStrategy,
    VolumeMomentumBuyStrategy,
)
from core.strategy.sell import (
    MaDeadCrossSellStrategy,
    RsiSellStrategy,
    TrailingStopSellStrategy,
)


# ── 매수 전략 ────────────────────────────────────────────────────────────────

DEFAULT_PRIMARY_BUY_KEY = "quality_trend"

BUY_STRATEGY_FACTORIES: dict[str, Callable[[], BuyStrategy]] = {
    "quality_trend": lambda: QualityTrendBuyStrategy(market_cap_top_n=100, pick_n=4),
    "high_proximity": lambda: HighProximityBuyStrategy(market_cap_top_n=100, pick_n=4),
    "technical_momentum": lambda: TechnicalMomentumBuyStrategy(market_cap_top_n=100, pick_n=4),
    "golden_cross": lambda: GoldenCrossBuyStrategy(market_cap_top_n=100, pick_n=4),
    "low_per": lambda: LowPerBuyStrategy(market_cap_top_n=100, pick_n=4),
    "oversold_rebound": lambda: OversoldReboundBuyStrategy(market_cap_top_n=100, pick_n=4),
    "volume_momentum": lambda: VolumeMomentumBuyStrategy(market_cap_top_n=100, pick_n=4),
}

DEFAULT_VIEW_BUY_KEYS = ["high_proximity", "technical_momentum"]


def primary_buy_key() -> str:
    """settings.json 의 현재 활성 매수 전략 키. 등록되지 않은 키면 default 반환.

    호출부(view 필터, 옵션 빌더 등)에서 항상 유효한 키만 받도록 검증을 여기서 일괄 처리한다.
    """
    key = get_setting("primary_buy_strategy")
    if not isinstance(key, str) or key not in BUY_STRATEGY_FACTORIES:
        return DEFAULT_PRIMARY_BUY_KEY
    return key


def buy_strategy_options() -> list[tuple[str, str]]:
    """전체 매수 전략 (key, display_name) — primary selectbox 용."""
    return [(key, factory().display_name) for key, factory in BUY_STRATEGY_FACTORIES.items()]


def view_buy_strategy_options() -> list[tuple[str, str]]:
    """view multiselect 용 — 현재 primary 키는 제외."""
    p = primary_buy_key()
    return [(k, f().display_name) for k, f in BUY_STRATEGY_FACTORIES.items() if k != p]


def primary_buy_strategy() -> BuyStrategy:
    """매수 실행에 사용되는 메인 전략. settings.json 의 `primary_buy_strategy` 키 반영."""
    key = primary_buy_key()
    factory = BUY_STRATEGY_FACTORIES.get(key) or BUY_STRATEGY_FACTORIES[DEFAULT_PRIMARY_BUY_KEY]
    return factory()


def view_buy_strategies() -> list[BuyStrategy]:
    """대시보드 비교용 보조 전략. settings.json 의 `view_buy_strategies` 키 반영.

    현재 primary 키와 겹치는 항목은 자동으로 제외해, 같은 전략이 두 번 표시되지 않게 한다.
    빈 리스트는 "view 전략 없음" 의 정상 상태로 보존 — `or` 패턴 대신 None 체크.
    """
    keys = get_setting("view_buy_strategies")
    if not isinstance(keys, list):
        keys = DEFAULT_VIEW_BUY_KEYS
    primary = primary_buy_key()
    result: list[BuyStrategy] = []
    seen: set[str] = set()
    for k in keys:
        if k == primary or k in seen:
            continue
        factory = BUY_STRATEGY_FACTORIES.get(k)
        if factory is None:
            continue
        result.append(factory())
        seen.add(k)
    return result


# ── 매도 전략 ────────────────────────────────────────────────────────────────

DEFAULT_SELL_KEY = "trailing_stop"

SELL_STRATEGY_FACTORIES: dict[str, Callable[[], SellStrategy]] = {
    "trailing_stop": lambda: TrailingStopSellStrategy(stop_loss_pct=float(get_setting("stop_loss_pct"))),
    "rsi_overbought": lambda: RsiSellStrategy(rsi_max=75.0),
    "ma_dead_cross": lambda: MaDeadCrossSellStrategy(short=5, long=20),
}

SELL_STRATEGY_KEY_BY_CLASS: dict[type[SellStrategy], str] = {
    TrailingStopSellStrategy: "trailing_stop",
    RsiSellStrategy: "rsi_overbought",
    MaDeadCrossSellStrategy: "ma_dead_cross",
}


def sell_strategy_key_of(strategy: SellStrategy) -> str:
    """SellStrategy 인스턴스의 registry key 반환."""
    return SELL_STRATEGY_KEY_BY_CLASS.get(type(strategy), DEFAULT_SELL_KEY)


def sell_strategy_options() -> list[tuple[str, str]]:
    """사이드바 selectbox 표시용 (key, display_name) 목록."""
    return [(key, factory().display_name) for key, factory in SELL_STRATEGY_FACTORIES.items()]


def primary_sell_strategy() -> SellStrategy:
    """현재 활성 매도 전략. settings.json 의 `sell_strategy` 키 반영."""
    key = get_setting("sell_strategy")
    if not isinstance(key, str) or not key:
        key = DEFAULT_SELL_KEY
    factory = SELL_STRATEGY_FACTORIES.get(key) or SELL_STRATEGY_FACTORIES[DEFAULT_SELL_KEY]
    return factory()


def build_sell_strategy(key: str) -> SellStrategy:
    """key 로 새 매도 전략 인스턴스 생성. 알 수 없으면 기본 전략 반환."""
    factory = SELL_STRATEGY_FACTORIES.get(key) or SELL_STRATEGY_FACTORIES[DEFAULT_SELL_KEY]
    return factory()
