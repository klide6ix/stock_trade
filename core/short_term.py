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

    진입(매수)·청산(매도) 철학:
      단타에서 진입 타이밍을 완벽히 맞추려 필터를 빡빡하게 걸면 후보가 0개로 떨어진다.
      따라서 진입은 '명백히 나쁜 자리'만 가볍게 거르고(추가 API 호출 0 — 매 주기 조회하는
      현재가 snapshot 의 당일 OHLC·등락률만 사용), 리스크는 청산(트레일링+손절)으로 관리한다.

      청산은 트레일링 스탑 중심의 3중 구조:
        1. 하드 손절 — 매수가 대비 -stop_loss_pct
        2. 트레일링 스탑 — 수익이 trail_arm_pct 도달해 '무장'된 뒤, 진입 후 최고가(peak) 대비
           -trail_drop_pct 하락 시 청산. "올라도 못 파는" 문제(손절 일변도)의 핵심 해결책.
        3. (옵션) 하드 익절 — 매수가 대비 +take_profit_pct (default 0 = 비활성, 트레일링에 위임)

    Args:
        stop_loss_pct: 매수 평균가 대비 손절 발동 하락률 % (default 3.0).
        trail_arm_pct: 트레일링 무장(arm) 수익률 % — 최고 수익이 이 값에 도달해야 트레일링
            청산이 활성화된다 (default 3.0). 진입 직후 잔파동에 트레일링이 즉시 발동하는 것 방지.
        trail_drop_pct: 무장 후 진입 후 최고가(peak) 대비 이만큼 하락 시 청산 % (default 2.0).
        take_profit_pct: 하드 익절 목표 % (default 0.0 = 비활성, 트레일링에 위임).
        entry_max_chg_pct: 진입 허용 전일대비등락률 상한 % (default 15.0). 이미 폭등한 종목
            추격 금지. 0 이면 비활성.
        entry_min_rebound_pct: 당일 저가 대비 최소 반등 % (default 1.0). 현재가가 당일 최저점에서
            이만큼 올라온 종목만 진입 — 저점에서 못 벗어나고 흘러내리는 종목('떨어지는 칼날') 회피.
            "현재가 ≥ 시가" 기준 대신 "저점 대비 반등" 으로 보아, 갭하락으로 시작했어도 저점에서
            반등 중인 종목을 놓치지 않는다. 0 이면 비활성.
        entry_min_pullback_pct: 진입 시 당일 고가 대비 최소 눌림 % (default 0.0 = 비활성). >0 이면
            현재가가 고가에서 이만큼 빠진 자리에서만 진입(꼭지 추격 회피). 단 떨어지는 칼날 위험.
        pool_top_n: 시총 상위 종목 수 = 코스피200 근사 풀 크기 (default 100).
        ranking_fetch_n: 각 ranking API 의 응답 종목 수 상한 (default 100). KIS 응답 한도가
            실제 적용되므로 큰 값을 주어도 KIS 가 주는 만큼만 받음.
    """

    def __init__(
        self,
        stop_loss_pct: float = 3.0,
        trail_arm_pct: float = 3.0,
        trail_drop_pct: float = 2.0,
        take_profit_pct: float = 0.0,
        entry_max_chg_pct: float = 15.0,
        entry_min_rebound_pct: float = 1.0,
        entry_min_pullback_pct: float = 0.0,
        pool_top_n: int = 100,
        ranking_fetch_n: int = 100,
    ) -> None:
        self.stop_loss_pct = stop_loss_pct
        self.trail_arm_pct = trail_arm_pct
        self.trail_drop_pct = trail_drop_pct
        self.take_profit_pct = take_profit_pct
        self.entry_max_chg_pct = entry_max_chg_pct
        self.entry_min_rebound_pct = entry_min_rebound_pct
        self.entry_min_pullback_pct = entry_min_pullback_pct
        self.pool_top_n = pool_top_n
        self.ranking_fetch_n = ranking_fetch_n

    @property
    def display_name(self) -> str:
        return (
            f"코스피200·등락률+거래량 ranking·트레일링({self.trail_arm_pct}%↑/"
            f"peak−{self.trail_drop_pct}%)·{self.stop_loss_pct}%손절"
        )

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

    def should_buy(
        self,
        target: dict[str, Any],
        snapshot: dict[str, Any],
    ) -> tuple[bool, str]:
        """진입 게이트 — '명백히 나쁜 자리'만 거른다 (추가 API 호출 0).

        선정(등락률+거래량 ranking 상위)은 종목 후보일 뿐, 진입 시점에 당일 시세로
        다음을 검사한다 (모두 통과해야 매수):
          1. 과열 컷: 전일대비등락률 ≤ entry_max_chg_pct — 이미 폭등한 종목 추격 금지.
          2. 반등 확인 컷: 현재가 ≥ 당일 저가 × (1 + entry_min_rebound_pct/100) — 저점에서
             못 벗어나고 흘러내리는 종목('떨어지는 칼날') 회피. 갭하락 시작 종목도 저점에서
             반등 중이면 통과.
          3. (옵션) 고점 추격 컷: 현재가 ≤ 당일 고가 × (1 - entry_min_pullback_pct/100).

        조건 미충족 시 매수하지 않고 다음 주기 재평가한다(슬롯·후보는 유지).

        Args:
            target: 활성 단타 슬롯 (현재 미사용 — 시그니처 일관성용).
            snapshot: get_quote_snapshot() 결과 (현재가/시가/고가/저가/전일대비등락률(%)).

        실제 미보유/미매도 판단은 트레이더가 holdings 로 수행한다.
        """
        price = float(snapshot.get("현재가", 0) or 0)
        if price <= 0:
            return False, "현재가 조회 실패"

        chg = float(snapshot.get("전일대비등락률(%)", 0) or 0)
        if self.entry_max_chg_pct > 0 and chg > self.entry_max_chg_pct:
            return False, f"과열 컷 (등락률 +{chg:.2f}% > 상한 +{self.entry_max_chg_pct}%)"

        low = float(snapshot.get("저가", 0) or 0)
        if self.entry_min_rebound_pct > 0 and low > 0:
            rebound_floor = low * (1 + self.entry_min_rebound_pct / 100)
            if price < rebound_floor:
                return False, (
                    f"반등 미달 컷 (현재가 {price:,.0f} < 당일저가 {low:,.0f} "
                    f"+{self.entry_min_rebound_pct}% = {rebound_floor:,.0f})"
                )

        high = float(snapshot.get("고가", 0) or 0)
        if self.entry_min_pullback_pct > 0 and high > 0:
            threshold = high * (1 - self.entry_min_pullback_pct / 100)
            if price > threshold:
                return False, (
                    f"고점 추격 컷 (현재가 {price:,.0f} > 고가 {high:,.0f} "
                    f"−{self.entry_min_pullback_pct}% = {threshold:,.0f})"
                )

        rebound = ((price - low) / low * 100) if low > 0 else 0
        return True, f"진입 조건 충족 (등락률 {chg:+.2f}% · 저가 대비 +{rebound:.2f}% 반등)"

    # ── 매도 트리거 ────────────────────────────────────────────────────────────

    def should_sell(
        self,
        target: dict[str, Any],
        current_price: float,
        avg_price: float | None,
    ) -> tuple[bool, str]:
        """3중 청산 — 하드 손절 / 트레일링 스탑 / (옵션) 하드 익절.

        우선순위대로 검사하며, 트레일링은 진입 후 최고가(`target["peak"]`)를 기준으로 한다.
        peak 는 트레이더가 매 주기 현재가로 갱신해 슬롯에 저장한다.

        Args:
            target: 활성 단타 슬롯. `peak`(진입 후 최고가) 필드를 참조한다.
            current_price: 현재가.
            avg_price: 매수 평균가.
        """
        if not avg_price or avg_price <= 0:
            return False, ""

        # 1. 하드 손절 — 최악 손실 한정
        drop_from_buy = (avg_price - current_price) / avg_price * 100
        if drop_from_buy >= self.stop_loss_pct:
            return True, f"손절: 매수가 대비 -{drop_from_buy:.2f}% (기준 -{self.stop_loss_pct}%)"

        # 2. 트레일링 스탑 — 최고 수익이 무장 기준 도달 후, peak 대비 하락 시 청산
        peak = float(target.get("peak") or 0) if isinstance(target, dict) else 0
        if peak > 0:
            peak_gain = (peak - avg_price) / avg_price * 100
            if peak_gain >= self.trail_arm_pct:  # 무장됨
                drop_from_peak = (peak - current_price) / peak * 100
                if drop_from_peak >= self.trail_drop_pct:
                    return True, (
                        f"트레일링: 최고가 {peak:,.0f} 대비 -{drop_from_peak:.2f}% "
                        f"(기준 -{self.trail_drop_pct}%, 최고수익 +{peak_gain:.2f}%)"
                    )

        # 3. (옵션) 하드 익절 — 트레일링에 위임 시 비활성(0)
        if self.take_profit_pct > 0:
            gain_from_buy = (current_price - avg_price) / avg_price * 100
            if gain_from_buy >= self.take_profit_pct:
                return True, f"익절: 매수가 대비 +{gain_from_buy:.2f}% (목표 +{self.take_profit_pct}%)"

        return False, ""


# ── settings 직렬화 / 검증 헬퍼 ────────────────────────────────────────────────

EMPTY_TARGET: dict[str, Any] = {
    "code": None,
    "name": None,
    "selected_at": None,
    "selection_reason": None,
    "auto_enabled": False,
    "last_realized_amount": None,
    # 진입 후 최고가 — 트레일링 스탑 기준. 트레이더가 매 주기 현재가로 상향 갱신하고
    # 매수 직후 체결가로 초기화한다. 매도/교체/재선정 시 새 슬롯에서 None 으로 리셋됨
    # (일반 보유의 peak_prices.json 과 독립 — 서로 간섭 없음).
    "peak": None,
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


def update_peak(slot: dict[str, Any] | None, current_price: float) -> dict[str, Any] | None:
    """보유 중 현재가로 진입 후 최고가(peak)를 상향 갱신.

    현재가가 기존 peak 보다 높으면 갱신된 새 슬롯을 반환하고, 그렇지 않으면 None 을 반환한다
    (None 이면 트레이더가 settings 쓰기를 생략 → 불필요한 디스크 I/O 회피).
    """
    if not isinstance(slot, dict) or not current_price or current_price <= 0:
        return None
    peak = float(slot.get("peak") or 0)
    if current_price > peak:
        return {**slot, "peak": float(current_price)}
    return None


def set_peak(slot: dict[str, Any], peak: float) -> dict[str, Any]:
    """매수 직후 peak 를 체결가로 초기화한 새 슬롯 반환."""
    return {**slot, "peak": float(peak)}


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
