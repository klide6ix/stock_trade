"""장 전(개장 30분 전) 시장 방향 판정 — 상승이면 지수 ETF, 하락이면 인버스 ETF.

판정 대상은 코스피200 프록시(KODEX 200)의 일봉과 개장 전 예상체결가다.
개별 신호를 [-1, +1] 로 정규화한 뒤 가중 평균해 하나의 방향 점수(score)로 합치고,
점수의 부호로 상승/하락을 가른다.

  신호                       가중  근거
  ─────────────────────────  ────  ────────────────────────────────────────────
  갭 신호 (예상체결/실시간)  0.50  개장 직전 정보. 다른 세 신호와 상관 ≈ 0 인 유일한 독립 신호.
  전일 등락률 (평균회귀)     0.25  **부호를 뒤집어 쓴다** — 전일이 내렸으면 오늘 오를 쪽에 건다.
  이평선 추세 (5MA vs 20MA)  0.15  중기 추세. 지속성이 커서 표본당 정보량이 적다(아래 참고).
  최근 3일 누적 수익률       0.10  이평선보다 짧은 호흡의 가속/감속.

**전일 등락률을 왜 평균회귀로 쓰는가** (2026-03~07 KODEX 200 78영업일 실측):
전일 등락률과 '시가 진입 → 익일 시가 청산' 수익의 상관이 **-0.297**(약 2.6σ)로, 전일이
오를수록 다음 날 수익이 낮아지는 단조 관계가 확인됐다. 구간별 평균 수익도 전일 -10~-5%
구간 +2.29% / 전일 +5~+10% 구간 -2.44% 로 방향이 뚜렷하다. 무작위 가중치 1만 개로 부호만
바꿔 비교했을 때 누적손익 중앙값이 -36.3% → +37.7% 로 역전됐다. 순방향(모멘텀)으로 쓰던
이전 버전은 이 신호에서 구조적으로 손실을 냈다.
주의: 평균회귀는 고변동 국면의 특징이므로 시장이 진정되면 재검증이 필요하다
(`scripts/_check_reversion.py` 재실행).

**이평선 가중치가 낮은 이유**: 78영업일 동안 5MA/20MA 부호가 4번밖에 바뀌지 않아
(평균 지속 15.6일) 독립 관측이 5개뿐이다. 유효 표준오차 ±22.4%p 로 성능 판정 자체가
불가능하므로, 검증되지 않은 신호에 큰 가중을 주지 않는다.

갭 신호는 개장 전에만 얻을 수 있고 실패할 수 있으므로(아래 stale 판정), 사용 불가 시
가중치를 나머지 신호에 재분배한다 — 신호가 빠졌다고 점수가 0 쪽으로 끌려가지 않게 한다.
다만 갭이 빠지면 나머지 셋만으로는 실측 누적손익이 -2.8% 로 사실상 우위가 사라진다.

**예상체결가 stale 판정**: `inquire-asking-price-exp-ccn` 은 장 시간 외에도 직전 세션의
잔존값을 그대로 반환한다(일요일 호출 시 금요일 데이터 확인). 응답의 `기준가` 는 그 세션의
전일 종가이므로, **기준가 == 일봉 기준 전일 종가** 일 때만 오늘 세션의 데이터로 인정한다.
"""
from __future__ import annotations

import statistics
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
# 배분 근거는 모듈 docstring 참고 — 실측 검증된 순서대로 갭 > 전일(평균회귀) > 이평선 > 3일.
W_GAP = 0.50
W_PREV_DAY_REVERSION = 0.25
W_MA_TREND = 0.15
W_MOMENTUM_3D = 0.10

# 정규화 기준 — 각 신호가 `일간 실현변동성 × 배수` 에 도달하면 점수 ±1 로 포화(saturate)한다.
#
# 절대 %(이전 방식: 1.0~3.0%)로 고정하면 변동성 국면이 바뀔 때마다 어긋난다. 실제로 2026년
# 상반기 KODEX 200 은 일간 σ 가 4% 수준인데 기준이 1.5% 여서 이평선 신호의 **92%가 포화**됐고,
# 점수가 신호 강도를 잃고 사실상 '부호 투표' 로 붕괴했다. 배수(무차원)로 두면 시장이 진정돼도
# 포화율이 유지된다.
#
# 각 배수 = (신호 자체의 표준편차 ÷ 일간 vol) × 여유계수. 78영업일 실측 기준 포화율 10~20%.
# 3일/전일 배수비가 1.69 로 확률보행 스케일링 √3(≈1.73) 과 일치해, 임의 curve-fit 이 아님이
# 교차 확인된다.
NORM_MA_TREND_MULT = 3.5    # 이평선 스프레드는 지속성이 커 일간 vol 대비 분산이 크다
NORM_PREV_DAY_MULT = 1.6    # 1일 수익률 — vol 정의 그 자체에 가깝다
NORM_MOMENTUM_MULT = 2.7    # 3일 누적 ≈ vol × √3
NORM_GAP_MULT = 1.2         # 갭은 야간 구간만이라 전일 등락률보다 분산이 작다

# 실현변동성 산출 기간(영업일) 과 하한. 하한이 없으면 초저변동 구간에서 정규화가 발산해
# 모든 신호가 즉시 포화된다.
VOL_WINDOW = 20
# 청산선 전용 단기 창 — `realized_vol_adaptive` 가 장기 창과 비교해 **작은 쪽**을 쓴다.
# 1거래주(5일). 실측 plateau 가 4~10일로 넓어 in-sample 최대값(7~8일)을 피해 중앙을 택했다.
VOL_SHORT_WINDOW = 5
VOL_FLOOR_PCT = 0.3

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


def realized_vol(closes: list[float], window: int = VOL_WINDOW) -> float:
    """최근 일간 수익률의 표준편차(%) — 모든 정규화 기준의 스케일.

    Args:
        closes: 종가 시계열 (최신순, index 0 = 가장 최근).

    Returns:
        일간 변동성(%). 표본이 부족하거나 0 에 수렴하면 `VOL_FLOOR_PCT`.
    """
    rets: list[float] = []
    for i in range(min(window, len(closes) - 1)):
        prev = closes[i + 1]
        if prev > 0:
            rets.append((closes[i] - prev) / prev * 100)
    if len(rets) < 2:
        return VOL_FLOOR_PCT
    return max(VOL_FLOOR_PCT, statistics.pstdev(rets))


def realized_vol_adaptive(
    closes: list[float],
    window: int = VOL_WINDOW,
    short_window: int = VOL_SHORT_WINDOW,
) -> float:
    """청산선 산출용 일간 변동성(%) — 장기·단기 창 중 **작은 쪽**.

    20일 표준편차는 극단 하루에 오염되고 그 효과가 **20거래일 유지**된다. 실측(2026-08):
    07-28(-11.19%)·07-31(+24.17%) 두 날이 σ 를 5.16% → 7.50% 로 밀어올려, 일간 등락이
    평균 2.81% 로 조용했던 8월 내내 청산선이 손절 15%(상한 클램프)·트레일링 12.8~14.3% 에
    붙박였다. 그 결과 **장중 청산이 20건 중 0건** — 국면 적응을 목표로 한 배수 방식이
    정확히 그 목적에서 실패했다.

    `min` 을 쓰는 것은 **비대칭이 의도된 것**이다.
      - 최근 5일이 조용하면 → 즉시 좁혀 보호장치를 되살린다 (지연 해소).
      - 최근 5일이 격하면 → 짧은 표본의 큰 값에 휘둘려 청산선을 **넓히지 않는다**.
        표본 5개짜리 추정치로 안전장치를 느슨하게 푸는 것은 근거가 약하기 때문이다.

    **신호 정규화에는 쓰지 않는다.** 정규화 배수(`NORM_*_MULT`)는 20일 σ 를 전제로
    보정된 값이라 스케일을 바꾸면 방향 판정 자체가 달라진다 — `judge_direction` 은
    정규화에 `realized_vol`, 청산선에 이 함수를 각각 쓴다.

    Args:
        closes: 종가 시계열 (최신순, index 0 = 가장 최근).

    Returns:
        일간 변동성(%). 두 창 모두 `VOL_FLOOR_PCT` 하한이 걸린 뒤 작은 쪽이 선택된다.
    """
    return min(realized_vol(closes, window), realized_vol(closes, short_window))


# MAD(중앙값 절대편차)를 표준편차와 같은 척도로 맞추는 상수.
# 정규분포에서 MAD ≈ 0.6745σ 이므로 1/0.6745 = 1.4826 을 곱하면 σ 와 직접 비교된다.
_MAD_TO_SIGMA = 1.4826


def realized_vol_mad(closes: list[float], window: int = VOL_WINDOW) -> float:
    """MAD 기반 일간 변동성(%) — 급등락 하루에 덜 흔들리는 강건(robust) 추정치.

    표준편차는 편차를 **제곱**해서 평균하므로 이상치 하나가 결과를 지배한다. 실측:
    2026-07-31 의 +24.17% 하루가 σ 를 5.16% → 7.50%(+45%) 로 밀어올렸고, 그 값이 20거래일
    동안 유지되면서 청산선을 그만큼 넓힌 채 방치했다. MAD 는 편차의 **중앙값**이라 표본의
    절반이 오염돼야 무너지므로(breakdown point 50%), 그런 하루는 순위 하나로만 반영된다.

    Args:
        closes: 종가 시계열 (최신순, index 0 = 가장 최근).

    Returns:
        일간 변동성(%). `realized_vol()` 과 같은 척도가 되도록 1.4826 을 곱한다.
        표본이 부족하거나 0 에 수렴하면 `VOL_FLOOR_PCT`.
    """
    rets: list[float] = []
    for i in range(min(window, len(closes) - 1)):
        prev = closes[i + 1]
        if prev > 0:
            rets.append((closes[i] - prev) / prev * 100)
    if len(rets) < 2:
        return VOL_FLOOR_PCT
    center = statistics.median(rets)
    mad = statistics.median([abs(r - center) for r in rets])
    return max(VOL_FLOOR_PCT, mad * _MAD_TO_SIGMA)


def _signal(name: str, raw: str, score: float, weight: float) -> dict[str, Any]:
    return {"신호": name, "값": raw, "점수": round(score, 3), "가중치": weight}


# 정규장 개장 시각 — 오늘 일봉을 '장중 봉' 으로 인정하는 시간 조건.
_MARKET_OPEN = "09:00"


def _today_bar_is_live(bars: list[dict], today_str: str, now: datetime) -> bool:
    """오늘 일봉이 **실제로 거래가 시작된** 봉인지 판정.

    KIS 는 개장 전에도 오늘 날짜 봉을 **전일 종가로 채워서** 돌려준다 (2026-08-03 08:25
    실측: `stck_bsop_date`=오늘 · 종가=전일종가 · 거래량 0). 이걸 장중으로 오인하면
    `_gap_signal` 이 장전 예상체결가 대신 **실시간 등락률 경로**를 타는데, 개장 전 등락률은
    +0.00% 이므로 **가중치 0.50 짜리 갭 신호가 '0' 이라는 값으로 점수에 들어가** 판정을 0 쪽으로
    희석시킨다. 실측된 점수 -0.247 은 갭을 빼고 재정규화하면 -0.493 으로, 확신도가 정확히
    절반이었다. 갭이 '미사용' 되는 것보다 나쁘다 — 미사용이면 나머지 신호로 재정규화되지만,
    0 으로 들어가면 그 0 이 전체 가중치의 절반을 차지하며 신호를 지워버리기 때문이다.

    그래서 **거래량 > 0** 과 **정규장 개장 이후**를 함께 요구한다. 거래량은 장전·휴장일의
    placeholder 봉을 모두 걸러내고, 시각 조건은 거래량 필드에 직전 세션 값이 남아 있는
    경우에 대한 보강이다.
    """
    if not bars or bars[0].get("date") != today_str:
        return False
    try:
        volume = int(bars[0].get("volume") or 0)
    except (TypeError, ValueError):
        volume = 0
    return volume > 0 and now.time() >= datetime.strptime(_MARKET_OPEN, "%H:%M").time()


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
        {direction, score, signals[], summary, prev_close, vol, gap_source, judged_at}
        `vol` 은 정규화 스케일로 쓴 일간 실현변동성(%).
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
    # 개장 전에도 오늘 날짜 봉이 전일 종가로 채워져 오므로 거래량·시각까지 확인한다.
    has_today_bar = _today_bar_is_live(bars, today_str, now)
    # 오늘 봉은 아직 진행 중이라 '확정 종가' 가 아니다. 추세·전일등락·모멘텀은 모두
    # 확정된 과거 봉으로만 계산하고, 오늘의 움직임은 갭 신호가 담당한다.
    # (placeholder 봉이어도 날짜 기준으로 제외해야 전일 종가가 어긋나지 않는다.)
    past = [b for b in bars if b.get("date") != today_str]
    if len(past) < MA_LONG:
        return _unavailable(f"일봉 부족 ({len(past)}개 < {MA_LONG}개)", now)

    closes = [b["close"] for b in past]
    prev_close = closes[0]
    # 모든 정규화 기준의 스케일. 이 값이 커지면(변동성 확대) 같은 등락률의 점수가 작아진다.
    vol = realized_vol(closes)
    # 청산선 배수의 기준은 **별도**다 — 정규화 배수는 20일 σ 를 전제로 보정돼 있어 스케일을
    # 바꾸면 방향 판정이 달라지지만, 청산선은 국면 전환에 빨리 반응해야 한다.
    exit_vol = realized_vol_adaptive(closes)

    signals: list[dict[str, Any]] = []
    weighted_sum = 0.0
    weight_total = 0.0

    def add(name: str, raw_pct: float, score: float, weight: float) -> None:
        """신호를 점수 합에 반영. 가중치 절대값으로 누적해 음수 가중치에도 안전하다."""
        nonlocal weighted_sum, weight_total
        signals.append(_signal(name, f"{raw_pct:+.2f}%", score, weight))
        weighted_sum += score * weight
        weight_total += abs(weight)

    gap_pct, gap_source, gap_detail = _gap_signal(proxy, prev_close, has_today_bar, now)
    if gap_pct is not None:
        add(f"갭 ({gap_source})", gap_pct, _norm(gap_pct, NORM_GAP_MULT * vol), W_GAP)
    else:
        # 갭을 못 쓰면 남은 신호끼리 재정규화 — 아래 weight_total 나눗셈이 그 역할을 한다.
        log(f"[방향판정] 갭 신호 미사용 — {gap_source}" + (f" ({gap_detail})" if gap_detail else ""))

    if len(closes) >= 2 and closes[1] > 0:
        prev_pct = (closes[0] - closes[1]) / closes[1] * 100
        # 평균회귀 — 부호를 뒤집어 쓴다. 전일이 내렸으면 오늘 오를 쪽에 건다.
        # 근거는 모듈 docstring (상관 -0.297, 구간별 단조 관계) 참고.
        add("전일 등락률 (평균회귀)", prev_pct,
            -_norm(prev_pct, NORM_PREV_DAY_MULT * vol), W_PREV_DAY_REVERSION)

    ma_s = sma(closes, MA_SHORT)
    ma_l = sma(closes, MA_LONG)
    if ma_s and ma_l:
        ma_pct = (ma_s - ma_l) / ma_l * 100
        add(f"이평선 추세 ({MA_SHORT}MA vs {MA_LONG}MA)", ma_pct,
            _norm(ma_pct, NORM_MA_TREND_MULT * vol), W_MA_TREND)

    if len(closes) > MOMENTUM_DAYS and closes[MOMENTUM_DAYS] > 0:
        mom_pct = (closes[0] - closes[MOMENTUM_DAYS]) / closes[MOMENTUM_DAYS] * 100
        add(f"최근 {MOMENTUM_DAYS}일 수익률", mom_pct,
            _norm(mom_pct, NORM_MOMENTUM_MULT * vol), W_MOMENTUM_3D)

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
        "vol": round(vol, 3),
        "exit_vol": round(exit_vol, 3),
        "gap_source": gap_source if gap_pct is not None else None,
        "gap_detail": gap_detail,
        "judged_at": now.isoformat(),
        "proxy_code": proxy.code,
        "proxy_name": proxy.name,
    }
    log(
        f"[방향판정] {direction_label(direction)} (점수 {score:+.3f}) — {summary} "
        f"| 일간변동성 {vol:.2f}%"
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
        "vol": 0.0,
        "exit_vol": 0.0,
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
