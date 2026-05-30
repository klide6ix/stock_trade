"""단기간 매매 (단타) 전략 — 코스피200 근사 풀에서 등락률+거래량 ranking 결합 상위 N종 후보.

선정 흐름 (KIS API 3회 호출, 일봉 조회 없음 — 즉시 완료):
  1. 시가총액 상위 N (default 100) → 코스피200 근사 풀. KIS API 에 코스피200 직접 조회가 없어
     시총으로 근사한다 (한국시장 시총 상위 100 ≒ 코스피 대형주 핵심).
  2. KIS 등락률 ranking (`ranking/fluctuation`) → 시총 풀 ∩ 등락률 양수 종목.
  3. KIS 거래량 ranking (`quotations/volume-rank`) → 시총 풀 ∩ 거래량 상위 종목.
  4. 두 ranking 모두에 등장하는 종목 → ranking 합산이 작을수록(=양쪽에서 상위) 상위. 상위 N종 후보.

매매 모델: 후보 최대 N종(`SHORT_TERM_CANDIDATE_COUNT`)을 선정해 대시보드 콤보 박스로 1종을 골라
자동매매(매수/매도)한다. 실제 거래는 한 번에 1종(활성 슬롯)만 진행.
매도 기준: 매수 평균가 대비 stop_loss_pct (default 5%) 이상 하락.
초기화 단위: 일단위. 후보 목록의 selected_at 날짜가 오늘과 다르면 트레이더가 후보를 재선정.

설계 의도: 이전 "N일 연속 상승" 조건은 시총 상위에서 통과 종목이 0개로 떨어지는 경우가 잦아 폐기.
ranking 결합 방식은 한국 시장에서 안정적으로 후보를 산출하면서도 모멘텀(등락률) + 유동성(거래량)
양쪽을 동시에 반영해 단타 적합 종목을 골라낸다.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from core.kis_api import (
    get_fluctuation_rank,
    get_market_cap_rank,
    get_volume_rank,
)
from core.logger import log

# 단타 후보 최대 종목 수 — 대시보드 콤보 박스에 노출할 후보 개수.
SHORT_TERM_CANDIDATE_COUNT = 5


def select_kospi200_universe(top_n: int = 200, market: str = "kospi200") -> list[dict]:
    """코스피200 시총 상위 풀.

    KIS ranking API 의 `FID_INPUT_ISCD=2001` (KOSPI200 지수 구성종목) 으로 직접 조회.
    실 응답 검증 완료 — KIS 가 KOSPI200 구성종목만 정확히 반환한다.
    """
    return get_market_cap_rank(top_n=top_n, market=market)


class ShortTermStrategy:
    """단기 매매 (단타) — 코스피200 근사 풀에서 등락률+거래량 ranking 결합으로 1종목 선정.

    Args:
        stop_loss_pct: 매수 평균가 대비 매도 발동 하락률 % (default 5.0).
        pool_top_n: 시총 상위 종목 수 = 코스피200 근사 풀 크기 (default 100).
        ranking_fetch_n: 각 ranking API 의 응답 종목 수 상한 (default 100). KIS 응답 한도가
            실제 적용되므로 큰 값을 주어도 KIS 가 주는 만큼만 받음.
    """

    def __init__(
        self,
        stop_loss_pct: float = 5.0,
        pool_top_n: int = 100,
        ranking_fetch_n: int = 100,
    ) -> None:
        self.stop_loss_pct = stop_loss_pct
        self.pool_top_n = pool_top_n
        self.ranking_fetch_n = ranking_fetch_n

    @property
    def display_name(self) -> str:
        return f"단타 (코스피200·등락률+거래량 ranking·{self.stop_loss_pct}%손절)"

    # ── 종목 선정 ──────────────────────────────────────────────────────────────

    def find_targets(
        self,
        n: int = SHORT_TERM_CANDIDATE_COUNT,
        exclude_codes: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        """등락률 ranking + 거래량 ranking 결합으로 상위 n종 후보 선정.

        호출 수: 3회 (시총 / 등락률 / 거래량). 일봉 조회 없음 → 즉시 완료.

        Args:
            n: 반환할 최대 후보 수 (rank 합산 오름차순 상위 n종).
            exclude_codes: 후보에서 제외할 종목코드 집합. 매도 직후 같은 종목이 다시 선정되는
                것을 방지하기 위해 트레이더가 직전 매도 종목을 전달한다. None 이면 제외 없음.

        Returns:
            각 후보 dict — `종목코드`/`종목명`/`현재가`/`등락률(%)`/`거래량`/`등락률순위`/
            `거래량순위`/`선정사유`. 후보가 없으면 빈 리스트.

        시총 풀 fallback: 시총 풀 ∩ ranking 교집합이 비면 두 ranking 의 KOSPI200 전체
        교집합으로 fallback 한다. 사용자에게는 선정 사유에 풀 종류를 명시.
        """
        exclude = set(exclude_codes) if exclude_codes else set()
        # 세 ranking 모두 KOSPI200 구성종목만 조회 (`FID_INPUT_ISCD=2001`).
        # KIS 가 KOSPI200 지수 구성종목 한정으로 정확히 응답하는 것을 실 호출 검증 완료.
        # 거래량 ranking 도 KOSDAQ 저가 소형주가 사라지고 KOSPI200 대형주만 들어와
        # 시총 풀과의 교집합이 자연스럽게 확보된다.
        pool = select_kospi200_universe(top_n=self.pool_top_n, market="kospi200")
        cap_codes: set[str] = {item["종목코드"] for item in pool}

        try:
            fluct = get_fluctuation_rank(top_n=self.ranking_fetch_n, market="kospi200")
        except Exception as e:
            log(f"[단타] 등락률 ranking 조회 실패: {e}")
            return None
        try:
            volume = get_volume_rank(top_n=self.ranking_fetch_n, market="kospi200")
        except Exception as e:
            log(f"[단타] 거래량 ranking 조회 실패: {e}")
            return None

        # 등락률 ranking — 양봉만 인덱싱 (시총 풀과 무관하게 모든 응답).
        fluct_rank: dict[str, dict] = {}
        for i, item in enumerate(fluct, start=1):
            code = item["종목코드"]
            chg_pct = float(item.get("등락률(%)", 0) or 0)
            if not code or chg_pct <= 0:
                continue
            fluct_rank[code] = {
                "rank": i,
                "chg_pct": chg_pct,
                "name": item.get("종목명", ""),
                "price": float(item.get("현재가", 0) or 0),
            }

        # 거래량 ranking — 모든 응답 인덱싱 (시총 풀과 무관).
        volume_rank: dict[str, dict] = {}
        for i, item in enumerate(volume, start=1):
            code = item["종목코드"]
            if not code:
                continue
            volume_rank[code] = {
                "rank": i,
                "volume": int(item.get("거래량", 0) or 0),
                "name": item.get("종목명", ""),
                "price": float(item.get("현재가", 0) or 0),
            }

        # 1단계: 두 ranking 의 시장 전체 교집합 — 제외 종목 컷
        market_intersect = (set(fluct_rank) & set(volume_rank)) - exclude
        # 2단계: 시총 풀 ∩ ranking 교집합 (primary 후보)
        cap_intersect = market_intersect & cap_codes

        if cap_intersect:
            selected = cap_intersect
            scope = "KOSPI200 시총상위"
        elif market_intersect:
            selected = market_intersect
            scope = "KOSPI200 전체(시총 풀 fallback)"
        else:
            selected = set()
            scope = "(없음)"

        log(
            f"[단타] 시총 {len(cap_codes)} / 양봉등락률 {len(fluct_rank)} / "
            f"거래량 {len(volume_rank)} / 시장교집합 {len(market_intersect)} / "
            f"시총교집합 {len(cap_intersect)} → '{scope}' {len(selected)}종목 평가"
        )

        if not selected:
            log("[단타] 두 ranking 모두 등장한 종목 자체가 없음")
            return []

        ranked: list[dict] = []
        for code in selected:
            fr = fluct_rank[code]
            vr = volume_rank[code]
            # 종목명/현재가는 두 ranking 응답 중 채워진 쪽 우선
            name = fr["name"] or vr["name"]
            price = fr["price"] or vr["price"]
            ranked.append({
                "종목코드": code,
                "종목명": name,
                "현재가": price,
                "등락률(%)": round(fr["chg_pct"], 2),
                "거래량": vr["volume"],
                "등락률순위": fr["rank"],
                "거래량순위": vr["rank"],
                "rank_sum": fr["rank"] + vr["rank"],
                "in_kospi": code in cap_codes,
            })
        ranked.sort(key=lambda c: c["rank_sum"])
        top = ranked[: max(1, n)]

        candidates: list[dict[str, Any]] = []
        for c in top:
            in_kospi_label = "KOSPI200 시총상위" if c["in_kospi"] else "KOSPI200"
            candidates.append({
                "종목코드": c["종목코드"],
                "종목명": c["종목명"],
                "현재가": c["현재가"],
                "등락률(%)": c["등락률(%)"],
                "거래량": c["거래량"],
                "등락률순위": c["등락률순위"],
                "거래량순위": c["거래량순위"],
                "선정사유": (
                    f"등락률 {c['등락률순위']}위 · 거래량 {c['거래량순위']}위 · "
                    f"+{c['등락률(%)']:.2f}% · {in_kospi_label}"
                ),
            })

        names = ", ".join(f"{c['종목명']}({c['종목코드']})" for c in candidates)
        log(f"[단타] ranking 결합 후보 {len(ranked)}개 평가 → 상위 {len(candidates)}종 선정: {names}")
        return candidates

    def find_target(
        self,
        exclude_codes: set[str] | None = None,
    ) -> dict[str, Any] | None:
        """상위 1종만 선정 (find_targets 의 단일 종목 wrapper). 후보 없으면 None.

        매도 직후 다음 활성 종목을 자동 지정할 때처럼 단일 결과만 필요한 경우 사용.
        """
        items = self.find_targets(n=1, exclude_codes=exclude_codes)
        return items[0] if items else None

    # ── 매수 트리거 ────────────────────────────────────────────────────────────

    def should_buy(self, target: dict[str, Any], current_price: float) -> tuple[bool, str]:
        """선정 자체가 매수 신호이므로, 종목이 지정된 동안에는 항상 매수 가능.

        실제 미보유/미매도 판단 (오늘 이미 매도했는지) 은 트레이더가 holdings + sold 플래그로 수행.
        """
        return True, "등락률+거래량 ranking 상위 종목 진입"

    # ── 매도 트리거 ────────────────────────────────────────────────────────────

    def should_sell(
        self,
        target: dict[str, Any],
        current_price: float,
        avg_price: float | None,
    ) -> tuple[bool, str]:
        """매수 평균가 대비 stop_loss_pct 이상 하락 시 매도."""
        if not avg_price or avg_price <= 0:
            return False, ""
        drop_pct = (avg_price - current_price) / avg_price * 100
        if drop_pct >= self.stop_loss_pct:
            return True, f"매수가 대비 {drop_pct:.2f}% 하락 (기준 {self.stop_loss_pct}%)"
        return False, ""


# ── settings 직렬화 / 검증 헬퍼 ────────────────────────────────────────────────

EMPTY_TARGET: dict[str, Any] = {
    "code": None,
    "name": None,
    "selected_at": None,
    "selection_reason": None,
    "auto_enabled": False,
    "last_realized_amount": None,
    # 보유 중 활성 종목을 콤보 박스로 다른 후보로 바꾸면, 즉시 덮어쓰지 않고 여기 대기.
    # 트레이더가 이전 보유를 전량 매도한 뒤 이 후보(`find_targets()` 원형, 한글 키)로 전환한다.
    "pending_target": None,
    # 사용자가 보유 중 종목 교체를 요청하면 "switch" — 트레이더가 매도 후 pending 으로 전환.
    "pending_action": None,
}


def target_to_settings(
    target: dict[str, Any] | None,
    auto_enabled: bool,
    last_realized_amount: float | None = None,
) -> dict[str, Any]:
    """후보(`find_targets()` 항목) 를 활성 슬롯 저장 포맷으로 변환.

    항상 pending 관련 필드를 초기화한 새 슬롯을 반환하므로, 활성 종목이 교체되면
    이전 대기 후보/예약 액션이 자동으로 정리된다.

    Args:
        last_realized_amount: 직전 매도 시 회수된 금액(체결가×수량). 다음 매수 예산 상한으로 사용.
            None 이면 첫 진입 또는 매도 이력 없음 → 매수 시 `SHORT_TERM_BUDGET_MAX` 로 fallback.
    """
    if target is None:
        return {
            **EMPTY_TARGET,
            "auto_enabled": auto_enabled,
            "last_realized_amount": last_realized_amount,
        }
    return {
        **EMPTY_TARGET,
        "code": target.get("종목코드"),
        "name": target.get("종목명"),
        "selected_at": datetime.now().isoformat(),
        "selection_reason": target.get("선정사유"),
        "auto_enabled": auto_enabled,
        "last_realized_amount": last_realized_amount,
    }


def is_target_set(slot: dict[str, Any] | None) -> bool:
    """단타 활성 슬롯에 종목이 지정되어 있는지."""
    return bool(slot) and bool(slot.get("code"))


# ── 종목 교체(switch) 슬롯 헬퍼 ───────────────────────────────────────────────
#
# 활성 종목을 보유(매수 상태) 중일 때 콤보 박스로 다른 후보를 고르면, 즉시 갈아타지 않고
# 'pending_target' 으로 예약한다. 트레이더가 이전 보유를 전량 매도한 뒤 새 종목으로 전환한다.


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


# ── 후보 목록(container) 헬퍼 ─────────────────────────────────────────────────
#
# 콤보 박스에 노출할 상위 N종 후보를 `selected_at` + `items` 컨테이너로 관리한다.
# selected_at 의 날짜가 오늘과 다르면(또는 비어 있으면) 트레이더가 일단위로 재선정한다.


def empty_candidates() -> dict[str, Any]:
    return {"selected_at": None, "items": []}


def candidates_to_settings(items: list[dict[str, Any]]) -> dict[str, Any]:
    """`find_targets()` 결과 리스트를 후보 컨테이너 저장 포맷으로 변환."""
    return {"selected_at": datetime.now().isoformat(), "items": list(items or [])}


def candidates_need_refresh(
    container: dict[str, Any] | None,
    today: datetime | None = None,
) -> bool:
    """후보 목록이 비어 있거나 다른 날짜에 선정됐으면 재선정 필요 (일단위 초기화)."""
    if not isinstance(container, dict) or not container.get("items"):
        return True
    selected_at = container.get("selected_at")
    if not selected_at:
        return True
    try:
        selected_date = datetime.fromisoformat(selected_at).date()
    except Exception:
        return True
    now = today or datetime.now()
    return selected_date != now.date()
