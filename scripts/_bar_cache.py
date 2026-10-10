"""검증 스크립트 공용 시세 로더 — 일봉 표본 고정 + 분봉 캐시의 수정주가 기준 점검.

일봉은 **캐시하지 않는다**. KIS 가 과거 구간을 날짜 범위로 그대로 내주므로(2회 조회면
03-10 이후 전부) 매번 새로 받아도 비용이 없고, 그 편이 안전하다 — 시세가 수정주가라
분배락이 생기면 그 이전 날짜의 값이 전부 다시 계산되기 때문이다(실측 KODEX 200:
2026-04-29 · 07-30 두 번, 누적 0.64%). 받아 둔 일봉을 묵히면 새로 받은 값과 기준이
어긋난 채 섞인다.

분봉은 하루 4회 조회라 캐시가 필요하고(`data/.minute_bars_cache.json`), 그래서 같은
문제가 생긴다. 분배락 뒤에는 **캐시된 분봉(옛 기준)과 새로 받은 일봉(새 기준)** 이
어긋나 갭 신호가 분배율만큼 한쪽으로 쏠린다. 분봉 마감가는 그날 일봉 종가와 같아야
하므로(2026-10-10 실측: 216일 전부 ±1원 이내) 그 등식으로 낡은 항목을 골라 버린다.
"""
from datetime import datetime

from core.kis_api import get_daily_ohlcv_range

# 일봉 표본 시작일. 지금까지의 검증이 전부 이 날부터의 일봉 위에서 이뤄졌다 — 당시
# `get_daily_ohlcv` 가 준 100행의 첫 날이다. 20일 이평선 warm-up 때문에 실제 매매는
# 04-07 부터다. 앞당기면 표본은 늘지만 README 의 과거 수치와 직접 비교할 수 없게 된다.
DAILY_START = "20260310"

# 분봉 마감가와 일봉 종가가 '다르다' 고 보는 기준. 수정주가는 원 단위로 반올림돼 1원까지는
# 어긋날 수 있고, 분배락은 가장 작았던 것도 0.2% 였다.
_BASIS_TOL_RATIO = 0.001
_BASIS_TOL_WON = 1.5


def load_daily(code: str, start: str = DAILY_START) -> list[dict]:
    """`start` 부터 오늘까지의 일봉. 최신순 — `get_daily_ohlcv` 와 같은 모양이다."""
    return get_daily_ohlcv_range(code, start)


def stale_minute_keys(
    cache: dict[str, dict],
    daily: dict[str, dict[str, dict]],
    today: str | None = None,
) -> dict[str, list[str]]:
    """수정주가 기준이 일봉과 어긋난 분봉 캐시 키를 종목별로 돌려준다.

    분배락은 그 이전 **모든** 날짜의 값을 같은 비율로 바꾼다. 그래서 어긋난 날이 하나라도
    있으면 그 종목의 그날 이전 항목은 전부 낡은 것이다 — 마감 봉이 없어 직접 대조할 수
    없는 항목(개장 30분만 받은 것)도 함께 버린다.

    오늘 받은 항목은 버리지 않는다. 방금 받은 값이 어긋난다면 다시 받아도 같으므로,
    실행할 때마다 전부 다시 받는 일을 막는다.

    Args:
        cache: `{"종목:YYYYMMDD": {"scope": ..., "bars": {HHMM: 종가}, "fetched": YYYYMMDD}}`.
        daily: `{종목: {YYYYMMDD: 일봉}}` — 방금 받은 것.
        today: 오늘 날짜 YYYYMMDD (기본 지금).
    """
    today = today or datetime.now().strftime("%Y%m%d")
    newest_stale: dict[str, str] = {}
    for key, entry in cache.items():
        code, _, date = key.partition(":")
        bar = (daily.get(code) or {}).get(date)
        bars = entry.get("bars") or {}
        # 오늘 일봉은 아직 종가가 아니고, 마감 봉(15:30)이 없으면 마지막 분봉이 종가가 아니다.
        if not bar or date >= today or not bars or max(bars) < "1530":
            continue
        close = bar["close"]
        if abs(bars[max(bars)] - close) > max(close * _BASIS_TOL_RATIO, _BASIS_TOL_WON):
            newest_stale[code] = max(newest_stale.get(code, ""), date)

    stale: dict[str, list[str]] = {}
    for key, entry in cache.items():
        code, _, date = key.partition(":")
        if code in newest_stale and date <= newest_stale[code] and entry.get("fetched") != today:
            stale.setdefault(code, []).append(key)
    return {code: sorted(keys) for code, keys in stale.items()}
