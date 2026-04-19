"""앱 사용자 설정 (매수 on/off 등) — data/settings.json 에 영속화."""
import json
import os
from typing import Any

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA_DIR = os.path.join(_BASE_DIR, "data")
os.makedirs(_DATA_DIR, exist_ok=True)

SETTINGS_FILE = os.path.join(_DATA_DIR, "settings.json")

DEFAULTS: dict[str, Any] = {
    "buy_enabled": False,  # 안전을 위해 기본 비활성
    "auto_refresh": True,
    "refresh_interval": 60,
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
