"""단기 매매용 ETF 유니버스 — 방향별 후보와 대체 ETF 우선순위.

단기 매매는 개별주가 아니라 **지수를 통째로 사는 ETF** 로 제한한다. 개별주는 실적·수급·
공시 같은 종목 고유 리스크가 하루 안에 터질 수 있지만, 지수 ETF 는 '오늘 시장이 오르냐
내리냐' 라는 단일 베팅으로 단순화되기 때문이다.

  - 상승 판정 → 코스피200 정방향 ETF (KODEX 200 등)
  - 하락 판정 → 코스피200 인버스 ETF (-1배, KODEX 인버스 등)

각 방향마다 **같은 지수를 추종하는 대체 ETF** 를 유동성 순으로 나열한다. 1순위 ETF 를
이미 일반 매수 슬롯이 보유 중이면 증권사 계좌에서 평단이 섞여 단기 매매 수익률 추적이
오염되므로, 그 코드는 건너뛰고 다음 대체 ETF 를 고른다 (`pick_etfs(exclude_codes=...)`).
같은 지수를 추종하므로 추적 성과는 사실상 동일하고, 종목코드가 달라 계좌 레벨에서도
포지션이 완전히 분리된다.

종목코드·종목명은 KIS `search-stock-info`(CTPF1002R) 실호출로 확인했다.
레버리지/인버스2X 는 의도적으로 제외 — 일단위 보유에 -5% 손절을 걸면 2배 상품은
지수 2.5% 변동만으로 손절되어 전략 의도(하루 방향 베팅)와 맞지 않는다.
"""
from __future__ import annotations

from typing import NamedTuple


class EtfSpec(NamedTuple):
    code: str
    name: str
    note: str


# 방향 라벨 — market_direction 과 공유하는 문자열 상수.
DIRECTION_UP = "up"
DIRECTION_DOWN = "down"
DIRECTION_NEUTRAL = "neutral"

# 코스피200 정방향(1배) — 상승 판정 시 매수 대상.
UP_ETFS: list[EtfSpec] = [
    EtfSpec("069500", "KODEX 200", "코스피200 정방향 · 국내 최대 유동성"),
    EtfSpec("102110", "TIGER 200", "코스피200 정방향 · 대체 1순위"),
    EtfSpec("148020", "RISE 200", "코스피200 정방향 · 대체 2순위"),
    EtfSpec("152100", "PLUS 200", "코스피200 정방향 · 대체 3순위"),
    EtfSpec("069660", "KIWOOM 200", "코스피200 정방향 · 대체 4순위"),
]

# 코스피200 인버스(-1배) — 하락 판정 시 매수 대상.
DOWN_ETFS: list[EtfSpec] = [
    EtfSpec("114800", "KODEX 인버스", "코스피200 -1배 · 국내 최대 유동성"),
    EtfSpec("123310", "TIGER 인버스", "코스피200 -1배 · 대체 1순위"),
    EtfSpec("145670", "ACE 인버스", "코스피200 -1배 · 대체 2순위"),
]

# 방향 판정에 쓰는 지수 프록시 — 코스피200 정방향 대표 ETF.
# 지수(업종) API 대신 ETF 일봉을 쓰는 이유: 이미 검증된 `get_daily_ohlcv` 를 그대로
# 재사용할 수 있고, 실제로 매수하는 상품 자체의 가격 흐름을 보므로 괴리가 없다.
INDEX_PROXY = UP_ETFS[0]


def etf_pool(direction: str) -> list[EtfSpec]:
    """방향에 해당하는 ETF 우선순위 목록. 알 수 없는 방향이면 빈 리스트."""
    if direction == DIRECTION_UP:
        return list(UP_ETFS)
    if direction == DIRECTION_DOWN:
        return list(DOWN_ETFS)
    return []


def pick_etfs(
    direction: str,
    exclude_codes: set[str] | None = None,
    limit: int | None = None,
) -> list[EtfSpec]:
    """방향에 맞는 ETF 를 우선순위대로 반환. `exclude_codes` 는 건너뛴다.

    Args:
        direction: DIRECTION_UP | DIRECTION_DOWN.
        exclude_codes: 일반 매수 슬롯이 이미 보유 중인 종목코드 — 평단 혼입을 피하기 위해
            제외하고 다음 대체 ETF 를 고른다.
        limit: 최대 개수. None 이면 전체.
    """
    exclude = set(exclude_codes or ())
    pool = [e for e in etf_pool(direction) if e.code not in exclude]
    return pool[:limit] if limit else pool


def direction_of(code: str) -> str:
    """종목코드가 어느 방향의 ETF 인지. 유니버스 밖이면 DIRECTION_NEUTRAL."""
    if any(e.code == code for e in UP_ETFS):
        return DIRECTION_UP
    if any(e.code == code for e in DOWN_ETFS):
        return DIRECTION_DOWN
    return DIRECTION_NEUTRAL
