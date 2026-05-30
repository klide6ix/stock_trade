"""앱 사용자 설정 (매수 on/off 등) — data/settings.json 에 영속화."""
import json
import os
from typing import Any

from config import STOP_LOSS_PCT

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
    "short_term_buy_delay_min": 10,  # 단타 실매수 지연(분) — 개장(09:00) 후 이 시간 경과 뒤 매수 시작 (0=즉시)
    # 단기 매매 (단타) — 단일 종목 자동 매수/매도. ShortTermStrategy 가 자동 선정.
    # 매도 발생 시 즉시 재선정(실시간 회전)하되, 다음 매수 예산은 직전 회수 금액으로 캡해
    # 단타 자금 풀이 일반 자금으로 손실을 보충받지 않도록 한다.
    # 단타 후보 목록 — 콤보 박스에 노출할 상위 N종. selected_at 날짜가 오늘과 다르면 재선정.
    "short_term_candidates": {
        "selected_at": None,            # ISO 시각 — 날짜 부분이 오늘과 다르면 후보 재선정 트리거
        "items": [],                    # find_targets() 결과 리스트 (최대 SHORT_TERM_CANDIDATE_COUNT 종)
    },
    # 단타 활성 슬롯 — 후보 중 콤보 박스로 고른 1종을 자동매매(매수/매도).
    "short_term_trade": {
        "code": None,
        "name": None,
        "selected_at": None,            # 활성 종목으로 지정된 시각
        "selection_reason": None,       # 선정 사유 (예: "등락률 N위 · 거래량 M위 ...")
        "auto_enabled": False,          # 자동매매 ON/OFF (매수·매도 모두 제어)
        "last_realized_amount": None,   # 직전 매도 회수 금액(체결가×수량). 다음 매수 예산 상한으로 사용.
        # 보유 중 콤보로 다른 종목을 고르면 즉시 갈아타지 않고 여기 대기 — 트레이더가 매도 후 전환.
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
