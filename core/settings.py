"""앱 사용자 설정 (매수 on/off 등) — data/settings.json 에 영속화."""
import json
import os
from typing import Any

from config import (
    PRE_MARKET_OPEN,
    SHORT_TERM_PEAK_DROP_PCT,
    SHORT_TERM_STOP_LOSS_PCT,
    STOP_LOSS_PCT,
)

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA_DIR = os.path.join(_BASE_DIR, "data")
os.makedirs(_DATA_DIR, exist_ok=True)

SETTINGS_FILE = os.path.join(_DATA_DIR, "settings.json")

DEFAULTS: dict[str, Any] = {
    "buy_enabled": False,  # 안전을 위해 기본 비활성
    "auto_refresh": True,
    "refresh_interval": 60,
    "stop_loss_pct": STOP_LOSS_PCT,
    "primary_buy_strategy": "quality_trend",
    "view_buy_strategies": ["high_proximity", "technical_momentum"],
    "sell_strategy": "trailing_stop",
    "max_holdings": 5,  # 동시 보유 종목 상한 — 초과 시 매수 스킵
    "auto_sell_enabled_codes": [],  # 자동 매도 활성화 종목 코드 (체크된 종목만 매도 실행, 미체크는 조건 충족해도 보류)
    # 매수 주문 유형 — "limit"(지정가, 기본) | "market"(시장가).
    # 시장가는 KIS 가 상한가(+30%) 기준으로 증거금을 계산해 같은 현금으로 살 수 있는
    # 수량이 30% 줄고 체결가도 예측 불가다. 지정가를 매도호가에 걸면 즉시 체결되면서
    # 두 문제가 모두 없다. 매도는 청산 속도가 우선이라 항상 시장가.
    "buy_order_type": "limit",
    "short_term_buy_delay_min": 0,  # 단기 매매 실매수 지연(분) — 개장(09:00) 후 이 시간 경과 뒤 매수 (0=개장 즉시)
    "pre_market_open_time": PRE_MARKET_OPEN,  # 장 전 준비 시작 시각("HH:MM") — 이 시각부터 매매 없이 매수·단기매매 후보를 미리 선정
    # ── 일 단위 단기 매매 (지수/인버스 ETF 방향 매매) ──────────────────────────
    # 장 전에 시장 방향을 판정해 상승이면 지수 ETF, 하락이면 인버스 ETF 를 개장 시 매수하고
    # 손절 / 최고가 대비 하락 / 1일 보유 만료로 청산한다. 자세한 설계는 core/short_term.py 참고.
    # 배정 자금(씨드, 원) — 이 금액으로 자금 풀을 시작한다. 사이드바에서 바꾸면 풀도 재설정.
    "short_term_budget": 3_000_000,
    # 자금 풀 잔액(원) — 청산할 때마다 실현손익이 누적되는 실제 운용 자금.
    # 이익이 나면 다음 진입 금액이 커지고(복리), 손실이 나면 줄어든 금액으로 들어간다.
    # None = 미초기화 → 배정액으로 시작. 일반 매수 자금과 서로 보충하지 않는다.
    "short_term_pool": None,
    "short_term_stop_loss_pct": SHORT_TERM_STOP_LOSS_PCT,  # 매수가 대비 손절 하락률 %
    "short_term_peak_drop_pct": SHORT_TERM_PEAK_DROP_PCT,  # 매수 이후 최고가 대비 청산 하락률 %
    "short_term_close_at_market_end": False, # True 면 당일 15:15 강제청산 (오버나이트 미보유)
    # 후보 목록 — 오늘 방향에 맞는 ETF(1순위 + 대체). selected_at 날짜가 오늘과 다르면 재선정.
    "short_term_candidates": {
        "selected_at": None,            # ISO 시각 — 날짜 부분이 오늘과 다르면 후보 재선정 트리거
        "items": [],                    # find_targets() 결과 리스트 (최대 SHORT_TERM_CANDIDATE_COUNT 종)
        "direction": None,              # judge_direction() 결과 (방향·점수·신호 근거)
    },
    # 활성 슬롯 — 후보 중 1종을 자동매매. `core/short_term.py::EMPTY_TARGET` 이 원본 정의이며
    # 여기서는 파일 최초 생성 시의 기본값으로 같은 구조를 유지한다 (설정 모듈을 leaf 로 두기 위해 중복).
    "short_term_trade": {
        "code": None,
        "name": None,
        "selected_at": None,            # 활성 종목으로 지정된 시각
        "selection_reason": None,       # 선정 사유 (예: "📈 상승 판정 (점수 +0.42) · ...")
        "direction": None,              # 선정 당시 시장 방향 ("up" | "down")
        "auto_enabled": False,          # 자동매매 ON/OFF (매수·매도 모두 제어)
        # ── 자체 원장 — 증권사 평단과 독립적으로 단기 매매 포지션만 추적 ──
        # (자금은 슬롯이 아니라 위의 `short_term_pool` 이 들고 있다)
        "entry_price": None,            # 단기 매매 진입가 (체결 조회로 확인한 실제 체결 평균가)
        "qty": 0,                       # 단기 매매 보유 수량 (매도 시 이 수량만 매도)
        "invested": None,               # 진입에 실제로 나간 현금 (체결금액 + 매수 제비용)
        "entry_at": None,               # 진입 시각(ISO) — 보유기간 만료 판정 기준
        "peak": None,                   # 진입 이후 최고가 — 최고가 대비 청산 기준
        "blocked_date": None,           # 손절·최고가 청산이 난 날짜 — 같은 날 재진입 금지
        # 보유 중 다른 후보를 고르면 즉시 갈아타지 않고 여기 대기 — 트레이더가 매도 후 전환.
        "pending_target": None,         # 교체 예약 후보 (find_targets 항목, 한글 키) | None
        "pending_action": None,         # "switch" → 트레이더가 이전 보유 전량 매도 후 pending 으로 전환
    },
}


def load_settings() -> dict[str, Any]:
    """설정 파일 로드. 누락된 키는 DEFAULTS 로 보충."""
    data = {}
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
    return {**DEFAULTS, **data}


def save_settings(settings: dict[str, Any]) -> None:
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)


def get(key: str) -> Any:
    return load_settings().get(key, DEFAULTS.get(key))


def set_value(key: str, value: Any) -> None:
    settings = load_settings()
    settings[key] = value
    save_settings(settings)
