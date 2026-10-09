"""한국 증시 개장일 판별 — KIS 국내휴장일조회(`chk-holiday`, CTCA0903R)를 하루 1회 캐시.

트레이더는 평일이면 장이 열린 것으로 봤다. 그래서 공휴일에도 개장 직후 재판정을 5번씩
시도하고 잔고를 조회했다(2026-10-05 개천절 대체공휴일 · 10-09 한글날 실측). 보유 중인
날이면 거부될 청산 주문까지 시도할 수 있다.

설계
  - API 는 기준일부터 약 24일치의 `opnd_yn`(개장일 여부)을 준다. KIS 는 원장 서비스와
    연관돼 **1일 1회 호출**을 권장하므로, 결과를 `data/market_calendar.json` 에 누적하고
    오늘 이미 받았으면 다시 부르지 않는다. 트레이더·대시보드가 이 파일을 공유한다.
  - **모르면 평일 = 개장** (가용성 우선). 조회 실패 · 범위 밖 날짜 · 모의투자(API 미지원)는
    기존 동작 그대로다. 휴장일 판별 때문에 거래일을 놓치는 일은 없어야 한다.
  - 조회 실패 시 30분 동안 재시도하지 않는다 — 매 주기(60초) API 를 두드리지 않게.

이 모듈은 `core.logger` 가 읽으므로 최상단에서 `kis_api`·`logger` 를 import 하지 않는다
(순환 import 회피 — 필요할 때 함수 안에서 가져온다).
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import date, datetime

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CALENDAR_FILE = os.path.join(_BASE_DIR, "data", "market_calendar.json")
_RETRY_AFTER_SEC = 1800

# 프로세스 내 캐시 — {"fetched_on": "YYYY-MM-DD" | None, "days": {"YYYYMMDD": bool}}
_mem: dict = {"fetched_on": None, "days": {}}
_last_failed_at = 0.0


def _read_file() -> dict:
    try:
        with open(CALENDAR_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("days"), dict):
            return data
    except (OSError, ValueError):
        pass
    return {"fetched_on": None, "days": {}}


def _write_file(data: dict) -> None:
    directory = os.path.dirname(CALENDAR_FILE)
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".calendar.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
        os.replace(tmp, CALENDAR_FILE)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def _fetch(base: date) -> dict[str, bool]:
    """기준일부터 KIS 가 주는 범위(약 24일)의 개장 여부."""
    from core.kis_api import BASE_URL, _request

    data = _request(
        "GET",
        f"{BASE_URL}/uapi/domestic-stock/v1/quotations/chk-holiday",
        "CTCA0903R",
        params={"BASS_DT": base.strftime("%Y%m%d"), "CTX_AREA_NK": "", "CTX_AREA_FK": ""},
    )
    days = {}
    for row in data.get("output") or []:
        key = str(row.get("bass_dt") or "")
        if len(key) == 8:
            days[key] = str(row.get("opnd_yn") or "").upper() == "Y"
    return days


def refresh(today: date | None = None) -> None:
    """오늘 달력을 아직 받지 않았으면 받는다 (파일에 다른 프로세스가 받아 둔 게 있으면 그걸 쓴다)."""
    global _last_failed_at
    from config import IS_MOCK

    today = today or date.today()
    stamp = today.isoformat()
    if _mem["fetched_on"] == stamp:
        return
    on_disk = _read_file()
    if on_disk.get("fetched_on") == stamp:
        _mem.update(on_disk)
        return
    _mem["days"] = {**on_disk.get("days", {}), **_mem["days"]}
    if IS_MOCK or time.time() - _last_failed_at < _RETRY_AFTER_SEC:
        return
    try:
        fresh = _fetch(today)
    except Exception as e:
        _last_failed_at = time.time()
        from core.logger import log
        log(f"[휴장일] 개장일 조회 실패 — 평일은 개장으로 간주 (30분 뒤 재시도): {e}")
        return
    if not fresh:
        _last_failed_at = time.time()
        return
    merged = {"fetched_on": stamp, "days": {**_mem["days"], **fresh}}
    _mem.update(merged)
    try:
        _write_file(merged)
    except OSError:
        pass


def is_open_day(day: date | datetime, *, fetch: bool = True) -> bool:
    """개장일인지. 주말은 항상 False, 평일은 달력에 없으면 True(기존 동작).

    Args:
        fetch: False 면 API 를 부르지 않고 저장된 달력만 본다(로그 정리 등 부수 경로용).
    """
    if isinstance(day, datetime):
        day = day.date()
    if day.weekday() >= 5:
        return False
    if fetch:
        refresh()
    elif not _mem["days"]:
        _mem["days"] = _read_file().get("days", {})
    known = _mem["days"].get(day.strftime("%Y%m%d"))
    return True if known is None else bool(known)
