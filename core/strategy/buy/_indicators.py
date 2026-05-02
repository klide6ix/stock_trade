"""일봉 시계열 기반 기술 지표 헬퍼. 최신순(index 0 = 오늘) 입력 가정."""


def sma(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    return sum(values[:period]) / period


def rsi(closes: list[float], period: int = 14) -> float | None:
    """Wilder RSI."""
    if len(closes) < period + 1:
        return None
    chrono = list(reversed(closes[:period + 1]))
    gains = 0.0
    losses = 0.0
    for i in range(1, len(chrono)):
        diff = chrono[i] - chrono[i - 1]
        if diff >= 0:
            gains += diff
        else:
            losses += -diff
    if losses == 0:
        return 100.0
    rs = (gains / period) / (losses / period)
    return 100 - 100 / (1 + rs)
