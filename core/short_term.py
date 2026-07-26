"""일 단위 단기 매매 (단타) — 장 전 시장 방향 판정 → 지수/인버스 ETF 1종 자동 매매.

전략 요약
  1. **장 전 준비(개장 30분 전)** 에 `market_direction.judge_direction()` 으로 오늘 시장이
     오를지 내릴지 판정한다 (지수 프록시 일봉 추세 + 장전 예상체결가).
  2. 상승이면 코스피200 정방향 ETF, 하락이면 인버스 ETF 를 후보로 세운다. 1순위 ETF 를
     일반 매수 슬롯이 이미 보유 중이면 같은 지수를 추종하는 **대체 ETF** 로 자동 회피한다.
  3. **개장(09:00) 과 동시에 시장가 매수**한다 (지연은 사이드바에서 조절 가능, 기본 0분).
  4. 청산은 아래 4가지 — 먼저 충족되는 것으로 나간다.
       ① 손절: 매수가 대비 -stop_loss_pct (기본 5%)
       ② 최고가 청산: 매수 이후 최고가 대비 -peak_drop_pct (기본 5%)
       ③ 보유기간 만료: 매수 다음 거래일 개장 시 전량 청산 → 그날 방향으로 재진입
       ④ (옵션) 당일 마감 강제청산: `close_at_market_end` ON 이면 15:15 전량 청산

왜 ETF 인가: 개별주는 하루 안에 종목 고유 악재(실적·공시·수급)가 터질 수 있지만, 지수
ETF 는 '오늘 시장이 오르냐 내리냐' 라는 단일 베팅으로 리스크가 단순화된다. 하락장에서도
인버스로 같은 논리를 그대로 적용할 수 있어 방향에 관계없이 전략이 성립한다.

자체 원장(ledger) — 일반 매수 슬롯과의 분리
  증권사 잔고는 같은 종목코드를 하나의 평균단가로 합쳐서 보여준다. 일반 매수로 KODEX 200
  을 들고 있는데 단기 매매가 또 KODEX 200 을 사면 평단이 섞여 **양쪽 수익률이 모두 왜곡**된다.
  그래서 단기 매매 슬롯은 자기 진입가·수량·진입시각·최고가를 `settings.json` 에 직접 기록하고
  (`entry_price`/`qty`/`entry_at`/`peak`), 손익 판단과 매도 수량을 전부 이 원장 기준으로 한다.
  트레이더는 일반 매도 루프에서 원장 수량만큼을 잔고에서 차감해(`split_holdings`) 일반 슬롯이
  단기 매매 물량을 건드리지 못하게 한다. 종목 겹침 자체는 대체 ETF 로 우선 회피한다.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, NamedTuple

from core.etf_universe import (
    DIRECTION_DOWN,
    DIRECTION_NEUTRAL,
    DIRECTION_UP,
    INDEX_PROXY,
    EtfSpec,
    direction_of,
    pick_etfs,
)
from core.kis_api import get_quote_snapshot
from core.logger import log
from core.market_direction import direction_label, judge_direction

# 대시보드에 노출할 후보 ETF 최대 개수 (같은 방향의 대체 ETF 포함).
SHORT_TERM_CANDIDATE_COUNT = 3

# 당일 마감 강제청산 시각 — 종가 동시호가(15:20) 진입 전에 시장가로 정리한다.
FORCE_CLOSE_TIME = "15:15"

# 정규장 개장 시각 — 보유기간 만료 청산은 개장 이후에만 판정한다.
MARKET_OPEN_TIME = "09:00"


# ── 청산 사유 ─────────────────────────────────────────────────────────────────
SELL_STOP_LOSS = "stop_loss"
SELL_PEAK_DROP = "peak_drop"
SELL_HOLDING_PERIOD = "holding_period"
SELL_MARKET_END = "market_end"

# 청산 후 **같은 날 재진입을 허용**하는 사유. 보유기간 만료는 '어제 포지션을 정리하고
# 오늘 방향으로 새로 들어간다' 는 정상 회전이므로 재진입한다. 반대로 손절·최고가 청산은
# 오늘 판단이 틀렸다는 신호라 같은 날 다시 들어가지 않는다(재진입 차단 → 다음 거래일 재개).
REENTRY_ALLOWED_KINDS = {SELL_HOLDING_PERIOD}


class SellDecision(NamedTuple):
    sell: bool
    reason: str = ""
    kind: str = ""

    @property
    def allows_reentry_today(self) -> bool:
        return self.kind in REENTRY_ALLOWED_KINDS


def _parse_time(value: str):
    return datetime.strptime(value, "%H:%M").time()


class EtfDayTradeStrategy:
    """일 단위 ETF 방향 매매 — 상승이면 지수 ETF, 하락이면 인버스 ETF.

    Args:
        stop_loss_pct: 매수가 대비 손절 하락률 % (기본 5.0).
        peak_drop_pct: 매수 이후 최고가 대비 청산 하락률 % (기본 5.0).
        hold_days: 보유 기간(일). 진입일 + 이 일수가 지난 거래일 개장 시 청산 (기본 1).
        close_at_market_end: True 면 당일 `FORCE_CLOSE_TIME` 에 전량 청산 (오버나이트 미보유).
        neutral_band: |방향 점수| 가 이 값 이하이면 중립 → 당일 진입 보류 (기본 0 = 항상 진입).
        proxy: 방향 판정에 쓸 지수 프록시 ETF.
    """

    def __init__(
        self,
        stop_loss_pct: float = 5.0,
        peak_drop_pct: float = 5.0,
        hold_days: int = 1,
        close_at_market_end: bool = False,
        neutral_band: float = 0.0,
        proxy: EtfSpec = INDEX_PROXY,
    ) -> None:
        self.stop_loss_pct = stop_loss_pct
        self.peak_drop_pct = peak_drop_pct
        self.hold_days = max(0, int(hold_days))
        self.close_at_market_end = close_at_market_end
        self.neutral_band = neutral_band
        self.proxy = proxy

    @property
    def display_name(self) -> str:
        hold = "당일 마감 청산" if self.close_at_market_end else f"{self.hold_days}일 보유"
        return (
            f"지수/인버스 ETF 방향매매 · {hold} · "
            f"손절 -{self.stop_loss_pct:g}% · 최고가 -{self.peak_drop_pct:g}%"
        )

    # ── 종목 선정 ──────────────────────────────────────────────────────────────

    def find_targets(
        self,
        n: int = SHORT_TERM_CANDIDATE_COUNT,
        exclude_codes: set[str] | None = None,
        now: datetime | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """시장 방향을 판정하고 그 방향의 ETF 후보를 우선순위대로 반환.

        Args:
            n: 최대 후보 수 (1순위 + 대체 ETF).
            exclude_codes: 일반 매수 슬롯이 보유 중이라 평단 혼입을 피해야 하는 종목코드.
            now: 판정 기준 시각 (테스트 주입용).

        Returns:
            (후보 리스트, 방향 판정 결과). 중립 판정이거나 가용 ETF 가 없으면 후보는 빈 리스트.

        호출 수: 방향 판정 2회 + 후보 ETF 수만큼 시세 조회 (기본 최대 3회) ≈ 5회.
        """
        now = now or datetime.now()
        verdict = judge_direction(self.proxy, neutral_band=self.neutral_band, now=now)
        direction = verdict["direction"]

        if direction == DIRECTION_NEUTRAL:
            log(f"[단기매매] 방향 중립 — 진입 보류 ({verdict['summary']})")
            return [], verdict

        specs = pick_etfs(direction, exclude_codes=exclude_codes, limit=max(1, n))
        if not specs:
            log(
                f"[단기매매] {direction_label(direction)} 판정이나 매수 가능한 ETF 없음 "
                f"(제외 {sorted(exclude_codes or ())})"
            )
            return [], verdict

        score = verdict["score"]
        signal_score = round(abs(score) * 100, 1)
        candidates: list[dict[str, Any]] = []

        for rank, spec in enumerate(specs, start=1):
            try:
                snap = get_quote_snapshot(spec.code)
            except Exception as e:
                log(f"[단기매매] {spec.name}({spec.code}) 시세 조회 실패 — 후보 제외: {e}")
                continue
            price = float(snap.get("현재가", 0) or 0)
            if price <= 0:
                log(f"[단기매매] {spec.name}({spec.code}) 현재가 0 — 후보 제외")
                continue

            alt = "" if rank == 1 else " · 대체 ETF"
            candidates.append({
                "종목코드": spec.code,
                "종목명": spec.name,
                "현재가": price,
                "등락률(%)": round(float(snap.get("전일대비등락률(%)", 0) or 0), 2),
                "방향": direction,
                "방향라벨": direction_label(direction),
                "시그널점수": signal_score,
                "우선순위": rank,
                "선정사유": (
                    f"{direction_label(direction)} 판정 (점수 {score:+.2f}) · "
                    f"{spec.note}{alt} · {verdict['summary']}"
                ),
            })

        if not candidates:
            log("[단기매매] 방향은 정해졌으나 시세 조회 가능한 ETF 가 없음")
            return [], verdict

        names = ", ".join(f"{c['종목명']}({c['종목코드']})" for c in candidates)
        log(
            f"[단기매매] {direction_label(direction)} → ETF 후보 {len(candidates)}종: {names} "
            f"(방향 점수 {score:+.3f})"
        )
        return candidates, verdict

    # ── 매수 트리거 ────────────────────────────────────────────────────────────

    def should_buy(
        self,
        target: dict[str, Any],
        snapshot: dict[str, Any],
    ) -> tuple[bool, str]:
        """진입 판정 — 방향 판정이 곧 진입 신호이므로 시세 유효성만 확인한다.

        개별주 단타처럼 과열·눌림 게이트를 두지 않는 이유: 이 전략의 전제는 '장 전에 정한
        방향대로 개장과 함께 들어간다' 이고, 진입 시점에 추가 필터를 걸면 방향이 맞은 날
        오히려 못 들어가는 경우가 생긴다. 리스크는 진입이 아니라 청산(-5% 손절 / 최고가
        -5% / 1일 보유)에서 관리한다.

        Args:
            target: 활성 단기 매매 슬롯.
            snapshot: `get_quote_snapshot()` 결과.
        """
        price = float(snapshot.get("현재가", 0) or 0)
        if price <= 0:
            return False, "현재가 조회 실패"

        code = target.get("code") or ""
        direction = direction_of(code)
        label = {
            DIRECTION_UP: "지수 추종 ETF",
            DIRECTION_DOWN: "인버스 ETF",
        }.get(direction, "ETF")
        return True, f"{label} 진입 (현재가 {price:,.0f}원)"

    # ── 매도 트리거 ────────────────────────────────────────────────────────────

    def should_sell(
        self,
        slot: dict[str, Any],
        current_price: float,
        now: datetime | None = None,
    ) -> SellDecision:
        """4중 청산 판정 — 손절 / 최고가 하락 / 보유기간 만료 / (옵션) 마감 강제청산.

        모두 **자체 원장의 진입가**(`slot["entry_price"]`) 기준이다. 증권사 평균단가는
        같은 종목을 일반 매수로도 들고 있으면 섞이므로 쓰지 않는다.

        Args:
            slot: 활성 단기 매매 슬롯 (entry_price / entry_at / peak 참조).
            current_price: 현재가.
            now: 판정 기준 시각 (테스트 주입용).
        """
        now = now or datetime.now()
        entry = entry_price(slot)
        if not entry or entry <= 0 or current_price <= 0:
            return SellDecision(False)

        # 1. 하드 손절 — 매수가 대비 하락
        drop_from_entry = (entry - current_price) / entry * 100
        if drop_from_entry >= self.stop_loss_pct:
            return SellDecision(
                True,
                f"손절: 매수가 {entry:,.0f}원 대비 -{drop_from_entry:.2f}% "
                f"(기준 -{self.stop_loss_pct:g}%)",
                SELL_STOP_LOSS,
            )

        # 2. 최고가 대비 하락 — 매수 이후 고점에서 되밀린 폭
        peak = float(slot.get("peak") or 0)
        if peak > 0:
            drop_from_peak = (peak - current_price) / peak * 100
            if drop_from_peak >= self.peak_drop_pct:
                return SellDecision(
                    True,
                    f"최고가 청산: 최고가 {peak:,.0f}원 대비 -{drop_from_peak:.2f}% "
                    f"(기준 -{self.peak_drop_pct:g}%)",
                    SELL_PEAK_DROP,
                )

        # 3. 당일 마감 강제청산 (옵션) — 오버나이트 갭 리스크 회피
        if self.close_at_market_end and now.time() >= _parse_time(FORCE_CLOSE_TIME):
            return SellDecision(
                True,
                f"마감 강제청산 ({FORCE_CLOSE_TIME} 경과, 오버나이트 미보유 설정)",
                SELL_MARKET_END,
            )

        # 4. 보유기간 만료 — 진입일 + hold_days 가 지난 거래일의 개장 이후
        entry_day = entry_date(slot)
        if entry_day is not None and now.time() >= _parse_time(MARKET_OPEN_TIME):
            elapsed = (now.date() - entry_day).days
            if elapsed >= self.hold_days:
                return SellDecision(
                    True,
                    f"보유기간 만료: {entry_day.isoformat()} 매수 후 {elapsed}일 경과 "
                    f"(기준 {self.hold_days}일) — 개장 청산 후 오늘 방향으로 재진입",
                    SELL_HOLDING_PERIOD,
                )

        return SellDecision(False)


# ── 활성 슬롯 (자체 원장) ─────────────────────────────────────────────────────
#
# 단기 매매 슬롯은 증권사 잔고와 별개로 자기 포지션을 기록한다. 같은 종목을 일반 매수로도
# 보유하면 잔고의 평균단가·수량이 합쳐지므로, 손익 판단과 매도 수량은 이 원장을 신뢰한다.

EMPTY_TARGET: dict[str, Any] = {
    "code": None,
    "name": None,
    "selected_at": None,
    "selection_reason": None,
    "direction": None,              # "up" | "down" — 선정 당시 시장 방향
    "auto_enabled": False,
    # ── 자체 원장 (포지션) ──
    "entry_price": None,            # 단기 매매가 실제로 진입한 체결 평균가 (증권사 평단과 독립)
    "qty": 0,                       # 단기 매매가 보유 중인 수량 — 매도 시 이 수량만 판다
    "invested": None,               # 진입에 실제로 나간 현금 (체결금액 + 매수 제비용)
    "entry_at": None,               # 진입 시각(ISO) — 보유기간 만료 판정 기준
    "peak": None,                   # 진입 이후 최고가 — 최고가 대비 청산 기준
    # ── 진입 차단 ──
    # 손절·최고가 청산이 난 날짜(ISO date). 같은 날에는 재진입하지 않는다.
    "blocked_date": None,
    # ── 종목 교체 예약 ──
    "pending_target": None,         # 보유 중 다른 후보 선택 시 대기 (find_targets 항목)
    "pending_action": None,         # "switch" → 트레이더가 전량 매도 후 전환
}


def target_to_settings(
    target: dict[str, Any] | None,
    auto_enabled: bool,
    blocked_date: str | None = None,
) -> dict[str, Any]:
    """후보(`find_targets()` 항목) 를 활성 슬롯 저장 포맷으로 변환.

    항상 원장·pending 필드를 초기화한 새 슬롯을 반환하므로, 활성 종목이 바뀌면 이전
    포지션 기록과 교체 예약이 함께 정리된다. 진입 차단 날짜(`blocked_date`)는 슬롯이
    바뀌어도 '오늘은 더 진입하지 않는다' 는 판단이 유지되어야 하므로 명시적으로 이월한다.

    자금은 슬롯이 아니라 별도 자금 풀(`settings.json::short_term_pool`)이 들고 있으므로
    종목이 바뀌어도 예산은 영향을 받지 않는다.
    """
    base = {
        **EMPTY_TARGET,
        "auto_enabled": auto_enabled,
        "blocked_date": blocked_date,
    }
    if target is None:
        return base
    return {
        **base,
        "code": target.get("종목코드"),
        "name": target.get("종목명"),
        "selected_at": datetime.now().isoformat(),
        "selection_reason": target.get("선정사유"),
        "direction": target.get("방향"),
    }


# ── 원장 조작 헬퍼 ────────────────────────────────────────────────────────────


def position_qty(slot: dict[str, Any] | None) -> int:
    """단기 매매가 보유 중인 수량 (원장 기준). 없으면 0."""
    if not isinstance(slot, dict):
        return 0
    try:
        return max(0, int(slot.get("qty") or 0))
    except (TypeError, ValueError):
        return 0


def has_position(slot: dict[str, Any] | None) -> bool:
    return position_qty(slot) > 0 and bool(slot.get("code"))


def entry_price(slot: dict[str, Any] | None) -> float | None:
    if not isinstance(slot, dict):
        return None
    try:
        value = float(slot.get("entry_price") or 0)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def entry_date(slot: dict[str, Any] | None) -> date | None:
    """진입 시각의 날짜 부분. 기록이 없거나 파싱 실패면 None."""
    if not isinstance(slot, dict):
        return None
    raw = slot.get("entry_at")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw)).date()
    except ValueError:
        return None


def mark_entry(
    slot: dict[str, Any],
    price: float,
    qty: int,
    invested: float | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """매수 체결 직후 원장에 포지션 기록 (진입가·수량·투입액·진입시각·최고가 초기화).

    Args:
        price: 체결 평균가 (체결 조회로 확인한 실제 가격).
        qty: 체결 수량.
        invested: 실제로 나간 현금 (체결금액 + 매수 제비용). None 이면 `price × qty` 로 둔다.
    """
    now = now or datetime.now()
    return {
        **slot,
        "entry_price": float(price),
        "qty": int(qty),
        "invested": float(invested) if invested is not None else float(price) * int(qty),
        "entry_at": now.isoformat(),
        "peak": float(price),
    }


def clear_position(
    slot: dict[str, Any],
    blocked_date: str | None = None,
) -> dict[str, Any]:
    """청산 후 원장 비우기. 진입 차단일은 선택적으로 갱신한다.

    실현손익 반영은 자금 풀(`trader.apply_short_term_pnl`)이 따로 담당한다 — 슬롯은
    '무엇을 얼마나 들고 있나' 만, 풀은 '얼마를 굴리고 있나' 만 책임진다.
    """
    return {
        **slot,
        "entry_price": None,
        "qty": 0,
        "invested": None,
        "entry_at": None,
        "peak": None,
        "blocked_date": blocked_date if blocked_date is not None else slot.get("blocked_date"),
    }


def invested_amount(slot: dict[str, Any] | None) -> float:
    """현재 포지션에 투입된 실제 현금. 포지션이 없으면 0.

    청산 시 `회수액 - 투입액 = 실현손익` 으로 자금 풀을 갱신하는 데 쓴다. 매수 체결 조회로
    확인한 `invested`(체결금액 + 제비용)를 우선 쓰고, 그 기록이 없으면 `진입가 × 수량` 으로
    근사한다 — 체결 조회가 실패했거나 외부 매수로 잡힌 포지션의 fallback 경로다.
    """
    if isinstance(slot, dict):
        try:
            value = float(slot.get("invested") or 0)
        except (TypeError, ValueError):
            value = 0.0
        if value > 0:
            return value
    entry = entry_price(slot)
    qty = position_qty(slot)
    return float(entry) * qty if (entry and qty > 0) else 0.0


def update_peak(slot: dict[str, Any] | None, current_price: float) -> dict[str, Any] | None:
    """보유 중 현재가로 진입 이후 최고가를 상향 갱신.

    갱신된 새 슬롯을 반환하고, 갱신할 게 없으면 None 을 반환한다 (None 이면 트레이더가
    settings 쓰기를 생략 → 불필요한 디스크 I/O 회피).
    """
    if not isinstance(slot, dict) or not current_price or current_price <= 0:
        return None
    peak = float(slot.get("peak") or 0)
    if current_price > peak:
        return {**slot, "peak": float(current_price)}
    return None


def set_position_qty(slot: dict[str, Any], qty: int) -> dict[str, Any]:
    """원장 수량을 실제 잔고에 맞춰 보정한 새 슬롯 반환 (부분 체결·외부 매도 대응).

    투입액도 같은 비율로 줄인다 — 절반이 외부에서 팔렸다면 남은 포지션의 투입액도
    절반이어야 청산 시 실현손익이 맞는다.
    """
    new_qty = max(0, int(qty))
    old_qty = position_qty(slot)
    updated = {**slot, "qty": new_qty}
    if old_qty > 0 and new_qty != old_qty:
        invested = invested_amount(slot)
        if invested > 0:
            updated["invested"] = invested * new_qty / old_qty
    return updated


# ── 진입 차단 (같은 날 재진입 금지) ───────────────────────────────────────────


def block_today(slot: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    """오늘은 더 이상 진입하지 않도록 표시 (손절·최고가 청산 후)."""
    now = now or datetime.now()
    return {**slot, "blocked_date": now.date().isoformat()}


def clear_block(slot: dict[str, Any]) -> dict[str, Any]:
    return {**slot, "blocked_date": None}


def is_blocked(slot: dict[str, Any] | None, now: datetime | None = None) -> bool:
    """오늘 진입이 차단된 상태인지 (손절·최고가 청산이 오늘 발생했는지)."""
    if not isinstance(slot, dict):
        return False
    raw = slot.get("blocked_date")
    if not raw:
        return False
    now = now or datetime.now()
    return str(raw) == now.date().isoformat()


# ── 일반 슬롯과의 보유 분리 ───────────────────────────────────────────────────


def split_holdings(
    holdings: dict[str, dict],
    slot: dict[str, Any] | None,
) -> tuple[dict[str, dict], dict[str, dict]]:
    """증권사 잔고를 (일반 보유, 단기 매매 보유) 로 분리.

    단기 매매 원장 수량만큼을 잔고에서 차감해 일반 슬롯의 몫을 계산한다. 차감 결과가
    0 이하이면 그 종목은 일반 보유에서 제외된다 — 일반 매도 전략이 단기 매매 물량을
    팔아버리는 것을 막는 핵심 장치다.

    수량이 원장보다 적으면(외부 매도 등) 잔고 수량까지만 단기 매매 몫으로 인정한다.

    Returns:
        (일반 보유 dict, 단기 매매 보유 dict) — 둘 다 `get_holdings()` 와 같은 형태.
    """
    general = {code: dict(info) for code, info in holdings.items()}
    short_term: dict[str, dict] = {}

    code = slot.get("code") if isinstance(slot, dict) else None
    reserved = position_qty(slot)
    if not code or reserved <= 0 or code not in general:
        return general, short_term

    info = general[code]
    held_qty = int(info.get("qty") or 0)
    st_qty = min(reserved, held_qty)
    if st_qty <= 0:
        return general, short_term

    short_term[code] = {**info, "qty": st_qty}
    remain = held_qty - st_qty
    if remain > 0:
        general[code] = {**info, "qty": remain}
    else:
        del general[code]
    return general, short_term


# ── 종목 교체(switch) 예약 ────────────────────────────────────────────────────


def has_pending(slot: dict[str, Any] | None) -> bool:
    """교체 예약(pending_target) 이 등록되어 있는지."""
    return (
        isinstance(slot, dict)
        and isinstance(slot.get("pending_target"), dict)
        and bool(slot["pending_target"].get("종목코드"))
    )


def request_switch(slot: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    """보유 중 종목을 `target` 으로 교체 예약 (이전 보유 전량 매도는 트레이더가 처리)."""
    return {**slot, "pending_target": target, "pending_action": "switch"}


def clear_pending(slot: dict[str, Any]) -> dict[str, Any]:
    """교체 예약을 취소하고 현재 활성 종목을 그대로 유지."""
    return {**slot, "pending_target": None, "pending_action": None}


# ── 후보 목록(container) ──────────────────────────────────────────────────────
#
# 오늘 방향에 맞는 ETF 후보(1순위 + 대체)를 `selected_at` + `items` + `direction` 컨테이너로
# 관리한다. selected_at 의 날짜가 오늘과 다르면 트레이더가 일단위로 재선정한다.


def candidates_to_settings(
    items: list[dict[str, Any]],
    direction: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """`find_targets()` 결과를 후보 컨테이너 저장 포맷으로 변환.

    방향 판정 결과(`direction`)를 함께 저장해, 대시보드가 어떤 근거로 오늘 방향이
    정해졌는지 트레이더 재조회 없이 보여줄 수 있게 한다.
    """
    return {
        "selected_at": datetime.now().isoformat(),
        "items": list(items or []),
        "direction": direction,
    }


def candidates_need_refresh(
    container: dict[str, Any] | None,
    today: datetime | None = None,
) -> bool:
    """후보 목록이 비어 있거나 다른 날짜에 선정됐으면 재선정 필요 (일단위 초기화).

    후보가 0개여도 `selected_at` 이 오늘이면 재선정하지 않는다 — 중립 판정으로 후보가
    비는 것은 정상 상태이고, 매 주기 방향 판정 API 를 다시 때릴 이유가 없기 때문이다.
    (같은 날 강제 재판정이 필요하면 대시보드의 '방향 재판정' 버튼을 쓴다.)
    """
    if not isinstance(container, dict):
        return True
    selected_at = container.get("selected_at")
    if not selected_at:
        return True
    try:
        selected_date = datetime.fromisoformat(str(selected_at)).date()
    except ValueError:
        return True
    now = today or datetime.now()
    return selected_date != now.date()
