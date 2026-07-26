"""장 전(개장 30분 전) 시장 방향 판정 — 상승이면 지수 ETF, 하락이면 인버스 ETF.

판정 대상은 코스피200 프록시(KODEX 200)의 일봉과 개장 전 예상체결가다.
개별 신호를 [-1, +1] 로 정규화한 뒤 가중 평균해 하나의 방향 점수(score)로 합치고,
점수의 부호로 상승/하락을 가른다.

  신호                       가중  근거
  ─────────────────────────  ────  ────────────────────────────────────────────
  이평선 추세 (5MA vs 20MA)  0.35  중기 추세의 방향. 단발 노이즈에 가장 덜 흔들린다.
  전일 등락률                0.25  직전 세션의 관성 — 한국 시장은 전일 방향이 시가에 이어지는 경향.
  최근 3일 누적 수익률       0.20  이평선보다 짧은 호흡의 가속/감속.
  갭 신호 (예상체결/실시간)  0.20  개장 직전 정보. 08:30~09:00 예상체결가, 장중이면 실시간 등락률.

갭 신호는 개장 전에만 얻을 수 있고 실패할 수 있으므로(아래 stale 판정), 사용 불가 시
가중치를 나머지 신호에 재분배한다 — 신호가 빠졌다고 점수가 0 쪽으로 끌려가지 않게 한다.

**예상체결가 stale 판정**: `inquire-asking-price-exp-ccn` 은 장 시간 외에도 직전 세션의
잔존값을 그대로 반환한다(일요일 호출 시 금요일 데이터 확인). 응답의 `기준가` 는 그 세션의
전일 종가이므로, **기준가 == 일봉 기준 전일 종가** 일 때만 오늘 세션의 데이터로 인정한다.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from core.etf_universe import (
    DIRECTION_DOWN,
    DIRECTION_NEUTRAL,
    DIRECTION_UP,
    INDEX_PROXY,
    EtfSpec,
)
from core.kis_api import get_daily_ohlcv, get_expected_open_quote, get_quote_snapshot
from core.logger import log
from core.strategy.buy._indicators import sma

# 신호 가중치 (합 1.0). 갭 신호를 못 쓰면 나머지 가중치로 재정규화한다.
W_MA_TREND = 0.35
W_PREV_DAY = 0.25
W_MOMENTUM_3D = 0.20
W_GAP = 0.20

# 정규화 기준 — 각 신호가 이 값(%)에 도달하면 점수 ±1 로 포화(saturate)한다.
# 코스피200 의 일반적 일간 변동폭을 기준으로 잡았다. 값이 작을수록 신호가 예민해진다.
NORM_MA_TREND_PCT = 1.5     # 5MA 가 20MA 보다 1.5% 위 → 추세 신호 만점
NORM_PREV_DAY_PCT = 1.5     # 전일 +1.5% → 만점
NORM_MOMENTUM_PCT = 3.0     # 3일 누적 +3% → 만점
NORM_GAP_PCT = 1.0          # 갭 +1.0% → 만점

MA_SHORT = 5
MA_LONG = 20
MOMENTUM_DAYS = 3

# 기준가 ↔ 전일 종가 일치 판정 허용 오차 (%). 호가단위 반올림·권리락 보정 여지.
_BASE_PRICE_TOLERANCE_PCT = 0.05


def _clip(value: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _norm(pct: float, scale: float) -> float:
    """등락률(%)을 [-1, 1] 점수로 정규화. scale(%) 에서 포화."""
    if scale <= 0:
        return 0.0
    return _clip(pct / scale)


def _signal(name: str, raw: str, score: float, weight: float) -> dict[str, Any]:
    return {"신호": name, "값": raw, "점수": round(score, 3), "가중치": weight}


def _gap_signal(
    proxy: EtfSpec,
    prev_close: float,
    has_today_bar: bool,
    now: datetime,
) -> tuple[float | None, str, str]:
    """갭(개장 방향) 신호 — (등락률%, 출처 라벨, 상세). 사용 불가 시 (None, 사유, "").

    장중(오늘 일봉이 이미 생성됨)이면 실시간 등락률이 가장 정확한 방향 신호이므로 그것을 쓰고,
    개장 전이면 동시호가 예상체결가를 쓴다. 예상체결가는 stale 잔존값이 올 수 있어
    기준가 대조 + 예상거래량 > 0 을 함께 검사한다.
    """
    if has_today_bar:
        try:
            snap = get_quote_snapshot(proxy.code)
        except Exception as e:
            return None, "장중 등락률 조회 실패", str(e)
        chg = float(snap.get("전일대비등락률(%)", 0) or 0)
        return chg, "장중 실시간 등락률", f"{proxy.name} {chg:+.2f}%"

    try:
        exp = get_expected_open_quote(proxy.code)
    except Exception as e:
        return None, "예상체결가 조회 실패", str(e)

    expected = exp.get("예상체결가") or 0
    base = exp.get("기준가") or 0
    volume = exp.get("예상거래량") or 0

    if expected <= 0 or prev_close <= 0:
        return None, "예상체결가 없음", ""
    # 기준가가 오늘 세션의 전일 종가와 다르면 직전 세션 잔존값 — 신뢰 불가.
    if base <= 0 or abs(base - prev_close) / prev_close * 100 > _BASE_PRICE_TOLERANCE_PCT:
        return None, "예상체결가 stale (기준가 불일치)", (
            f"기준가 {base:,.0f} ≠ 전일종가 {prev_close:,.0f}"
        )
    if volume <= 0:
        return None, "예상체결 거래량 0 (동시호가 미형성)", ""

    gap_pct = (expected - prev_close) / prev_close * 100
    return gap_pct, "장전 예상체결가", (
        f"예상 {expected:,.0f}원 (전일종가 {prev_close:,.0f}원 대비 {gap_pct:+.2f}%, "
        f"예상거래량 {volume:,}주)"
    )


def judge_direction(
    proxy: EtfSpec = INDEX_PROXY,
    *,
    neutral_band: float = 0.0,
    now: datetime | None = None,
) -> dict[str, Any]:
    """시장 방향 판정. 지수 프록시 일봉 + 갭 신호를 가중 합산한다.

    Args:
        proxy: 방향 판정에 쓸 지수 프록시 ETF (default KODEX 200).
        neutral_band: |score| 가 이 값 이하이면 '중립'(진입 보류). 0 이면 항상 상승/하락 이분.
        now: 판정 기준 시각 (테스트 주입용).

    Returns:
        {direction, score, signals[], summary, prev_close, gap_source, judged_at}
        조회 실패 등으로 판정 불가하면 direction=neutral, score=0, summary 에 사유.

    호출 수: 일봉 1 + 갭 신호 1 = 2회.
    """
    now = now or datetime.now()

    try:
        bars = get_daily_ohlcv(proxy.code, days=MA_LONG + 5)
    except Exception as e:
        log(f"[방향판정] {proxy.name} 일봉 조회 실패: {e}")
        return _unavailable(f"일봉 조회 실패: {e}", now)

    today_str = now.strftime("%Y%m%d")
    has_today_bar = bool(bars) and bars[0].get("date") == today_str
    # 오늘 봉은 아직 진행 중이라 '확정 종가' 가 아니다. 추세·전일등락·모멘텀은 모두
    # 확정된 과거 봉으로만 계산하고, 오늘의 움직임은 갭 신호가 담당한다.
    past = [b for b in bars if b.get("date") != today_str]
    if len(past) < MA_LONG:
        return _unavailable(f"일봉 부족 ({len(past)}개 < {MA_LONG}개)", now)

    closes = [b["close"] for b in past]
    prev_close = closes[0]

    signals: list[dict[str, Any]] = []
    weighted_sum = 0.0
    weight_total = 0.0

    ma_s = sma(closes, MA_SHORT)
    ma_l = sma(closes, MA_LONG)
    if ma_s and ma_l:
        gap_pct = (ma_s - ma_l) / ma_l * 100
        score = _norm(gap_pct, NORM_MA_TREND_PCT)
        signals.append(_signal(
            f"이평선 추세 ({MA_SHORT}MA vs {MA_LONG}MA)", f"{gap_pct:+.2f}%", score, W_MA_TREND
        ))
        weighted_sum += score * W_MA_TREND
        weight_total += W_MA_TREND

    if len(closes) >= 2 and closes[1] > 0:
        prev_pct = (closes[0] - closes[1]) / closes[1] * 100
        score = _norm(prev_pct, NORM_PREV_DAY_PCT)
        signals.append(_signal("전일 등락률", f"{prev_pct:+.2f}%", score, W_PREV_DAY))
        weighted_sum += score * W_PREV_DAY
        weight_total += W_PREV_DAY

    if len(closes) > MOMENTUM_DAYS and closes[MOMENTUM_DAYS] > 0:
        mom_pct = (closes[0] - closes[MOMENTUM_DAYS]) / closes[MOMENTUM_DAYS] * 100
        score = _norm(mom_pct, NORM_MOMENTUM_PCT)
        signals.append(_signal(
            f"최근 {MOMENTUM_DAYS}일 수익률", f"{mom_pct:+.2f}%", score, W_MOMENTUM_3D
        ))
        weighted_sum += score * W_MOMENTUM_3D
        weight_total += W_MOMENTUM_3D

    gap_pct, gap_source, gap_detail = _gap_signal(proxy, prev_close, has_today_bar, now)
    if gap_pct is not None:
        score = _norm(gap_pct, NORM_GAP_PCT)
        signals.append(_signal(f"갭 ({gap_source})", f"{gap_pct:+.2f}%", score, W_GAP))
        weighted_sum += score * W_GAP
        weight_total += W_GAP
    else:
        # 갭을 못 쓰면 남은 신호끼리 재정규화 — 아래 weight_total 나눗셈이 그 역할을 한다.
        log(f"[방향판정] 갭 신호 미사용 — {gap_source}" + (f" ({gap_detail})" if gap_detail else ""))

    if weight_total <= 0:
        return _unavailable("사용 가능한 신호 없음", now)

    score = _clip(weighted_sum / weight_total)
    if score > neutral_band:
        direction = DIRECTION_UP
    elif score < -neutral_band:
        direction = DIRECTION_DOWN
    else:
        direction = DIRECTION_NEUTRAL

    summary = " · ".join(f"{s['신호']} {s['값']}" for s in signals)
    result = {
        "direction": direction,
        "score": round(score, 4),
        "signals": signals,
        "summary": summary,
        "prev_close": prev_close,
        "gap_source": gap_source if gap_pct is not None else None,
        "gap_detail": gap_detail,
        "judged_at": now.isoformat(),
        "proxy_code": proxy.code,
        "proxy_name": proxy.name,
    }
    log(
        f"[방향판정] {direction_label(direction)} (점수 {score:+.3f}) — {summary}"
        + (f" | 갭 출처: {gap_source}" if gap_pct is not None else f" | 갭 미사용: {gap_source}")
    )
    return result


def _unavailable(reason: str, now: datetime) -> dict[str, Any]:
    """판정 불가 결과 — 중립으로 두어 진입하지 않게 한다."""
    log(f"[방향판정] 판정 불가 — {reason}")
    return {
        "direction": DIRECTION_NEUTRAL,
        "score": 0.0,
        "signals": [],
        "summary": f"판정 불가 ({reason})",
        "prev_close": 0.0,
        "gap_source": None,
        "gap_detail": "",
        "judged_at": now.isoformat(),
        "proxy_code": INDEX_PROXY.code,
        "proxy_name": INDEX_PROXY.name,
    }


def direction_label(direction: str) -> str:
    return {
        DIRECTION_UP: "📈 상승",
        DIRECTION_DOWN: "📉 하락",
    }.get(direction, "➖ 중립")
