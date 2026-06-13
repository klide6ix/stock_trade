import json
import os
import pandas as pd
import streamlit as st
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

from config import CHECK_INTERVAL
from core.kis_api import get_holdings, get_current_price, get_cash_balance
from core.logger import current_log_file, latest_log_file
from core.short_term import (
    SHORT_TERM_CANDIDATE_COUNT,
    ShortTermStrategy,
    candidates_to_settings,
    clear_pending,
    has_pending,
    request_switch,
    target_to_settings,
)
from core.trader import is_market_open, is_trading_time, plan_initial_buy, BUY_CANDIDATES_FILE, TRADE_HISTORY_FILE
from core.strategy._activate import (
    primary_buy_strategy,
    view_buy_strategies,
    primary_sell_strategy,
    buy_strategy_options,
    view_buy_strategy_options,
    sell_strategy_options,
    DEFAULT_PRIMARY_BUY_KEY,
    DEFAULT_VIEW_BUY_KEYS,
    DEFAULT_SELL_KEY,
)
from core.trader import _tag_candidates
from core.strategy.sell import PEAK_PRICES_FILE
from core.settings import load_settings, set_value as set_setting

st.set_page_config(
    page_title="트레이더",
    page_icon="📈",
    layout="wide",
)

# ── 세션 상태 초기화 ───────────────────────────────────────────────────────────
if "last_prices" not in st.session_state:
    st.session_state.last_prices = {}
if "buy_candidates" not in st.session_state:
    st.session_state.buy_candidates = None
if "last_cash_balance" not in st.session_state:
    st.session_state.last_cash_balance = None


# ── 데이터 레이어 ──────────────────────────────────────────────────────────────

def fetch_price(code: str, market_open: bool) -> tuple[float | None, bool]:
    """현재가 조회. 실패 시 캐시된 마지막 가격 반환. (가격, 캐시여부) 반환"""
    try:
        price = get_current_price(code)
        st.session_state.last_prices[code] = price
        return price, False
    except Exception:
        cached = st.session_state.last_prices.get(code)
        return cached, cached is not None


def _load_peak_prices() -> dict[str, float]:
    """트레이더가 소유·갱신하는 peak_prices.json 을 읽어 반환 (대시보드는 읽기 전용).

    최고가 갱신·매도 시 정리는 모두 트레이더의 TrailingStopSellStrategy 가 담당한다.
    대시보드가 별도로 기록하면 dual-writer 로 인해 매도 후에도 stale 한 최고가가
    다시 파일에 새어 들어가므로, 여기서는 표시(참고용)를 위해 읽기만 한다.
    """
    if not os.path.exists(PEAK_PRICES_FILE):
        return {}
    try:
        with open(PEAK_PRICES_FILE, "r", encoding="utf-8") as f:
            return {k: float(v) for k, v in json.load(f).get("prices", {}).items()}
    except Exception:
        return {}


def build_holdings_rows(market_open: bool) -> tuple[list[dict], bool]:
    """보유 종목 데이터 생성. (rows, 캐시가격 사용여부) 반환"""
    holdings = get_holdings()
    peak_prices = _load_peak_prices()
    rows = []
    any_stale = False

    for code, info in holdings.items():
        price, stale = fetch_price(code, market_open)
        if stale:
            any_stale = True

        peak = peak_prices.get(code, price)
        avg_price = info["avg_price"]
        drop_pct = (peak - price) / peak * 100 if (price and peak) else None
        profit_pct = (price - avg_price) / avg_price * 100 if (price and avg_price) else None

        rows.append({
            "종목명": info["name"],
            "종목코드": code,
            "수량": info["qty"],
            "평균단가": avg_price,
            "현재가": price or 0,
            "최고가": peak or 0,
            "수익률(%)": round(profit_pct, 2) if profit_pct is not None else None,
            "최고가 대비 하락(%)": round(drop_pct, 2) if drop_pct is not None else None,
        })

    return rows, any_stale


def get_row_status(drop_pct: float | None, stop_loss_pct: float) -> str:
    if drop_pct is None:
        return "❓"
    if drop_pct >= stop_loss_pct:
        return "🔴 손절 실행"
    if drop_pct >= stop_loss_pct * 0.8:
        return "🟠 손절 임박"
    if drop_pct >= stop_loss_pct * 0.5:
        return "🟡 주의"
    return "🟢 정상"


# ── 렌더 레이어 ────────────────────────────────────────────────────────────────

def render_cash_balance() -> None:
    """계좌 잔액을 대시보드 최상단에 표시"""
    try:
        balance = get_cash_balance()
        st.session_state.last_cash_balance = balance
    except Exception:
        balance = st.session_state.last_cash_balance

    if balance is None:
        st.warning("계좌 잔액 조회 실패")
        return

    stale = balance is st.session_state.last_cash_balance and st.session_state.last_cash_balance is not None

    b1, b2, b3, b4 = st.columns(4)
    b1.metric("💰 예수금", f"{balance['예수금']:,.0f}원")
    b2.metric("🛒 주문가능금액", f"{balance['주문가능금액']:,.0f}원")
    b3.metric("📊 총 평가금액", f"{balance['총평가금액']:,.0f}원")
    b4.metric("🏦 순자산", f"{balance['순자산']:,.0f}원")

    if stale:
        st.caption("⚠️ 잔액은 마지막 조회 기준입니다.")


def render_header(market_open: bool, buy_strategy_label: str, sell_strategy_label: str) -> None:
    st.title("📈 트레이더 대시보드")
    render_cash_balance()
    st.divider()

    real_open = is_market_open()

    if not market_open:
        st.info("⏸ 장 운영 시간 외입니다. 보유 종목과 마지막 가격 기준으로 표시합니다.")

    c1, c2, c3, c4, c5 = st.columns(5)
    market_status = "🟢 운영 중" if real_open else "🔴 마감"
    c1.metric("장 상태", market_status)
    c2.metric("매수 전략", buy_strategy_label)
    c3.metric("매도 전략", sell_strategy_label)
    c4.metric("확인 주기", f"{CHECK_INTERVAL // 60}분")
    c5.metric("마지막 갱신", datetime.now().strftime("%H:%M:%S"))


def _on_holdings_editor_change() -> None:
    """사용자가 자동매도 체크박스를 토글했을 때 즉시 settings 에 반영.

    data_editor 의 returned df 가 아닌 `session_state.holdings_editor.edited_rows` 를
    콜백 안에서 직접 읽어 settings 에 저장한다. 콜백은 data_editor 의 merge 로직보다
    앞서 실행되므로, input df 와 충돌하는 편집이 폐기되는 버그의 영향을 받지 않는다.
    """
    state = st.session_state.get("holdings_editor") or {}
    edits = state.get("edited_rows") or {}
    if not edits:
        return
    codes_by_idx = st.session_state.get("_holdings_codes_by_idx") or []
    enabled = set(load_settings().get("auto_sell_enabled_codes", []) or [])
    changed = False
    for idx, edit in edits.items():
        try:
            i = int(idx)
        except (TypeError, ValueError):
            continue
        if "자동매도" not in edit or not (0 <= i < len(codes_by_idx)):
            continue
        code = codes_by_idx[i]
        if edit["자동매도"]:
            if code not in enabled:
                enabled.add(code)
                changed = True
        else:
            if code in enabled:
                enabled.discard(code)
                changed = True
    if changed:
        set_setting("auto_sell_enabled_codes", sorted(enabled))


def render_holdings(market_open: bool, stop_loss_pct: float) -> None:
    st.subheader("보유 종목")
    st.caption(
        "✅ **자동매도** 컬럼을 체크한 종목만 매도 조건 충족 시 실제 매도가 실행됩니다. "
        "미체크 종목은 조건이 충족되어도 보류됩니다."
    )
    try:
        rows, any_stale = build_holdings_rows(market_open)
    except Exception as e:
        st.error(f"데이터 조회 실패: {e}")
        return

    if not rows:
        st.info("보유 종목이 없습니다.")
        return

    if any_stale:
        st.caption("⚠️ 일부 가격은 마지막 조회 시점 기준입니다.")

    enabled_codes = set(load_settings().get("auto_sell_enabled_codes", []) or [])

    # data_editor 의 returned df 에 의존하면, `edited_rows` 가 input df 와 충돌할 때
    # Streamlit 이 일부 편집을 잘못 폐기하면서 사용자의 체크가 무시되는 버그가 있다.
    # on_change 콜백 안에서 `session_state.edited_rows` 를 직접 읽어 settings 에 즉시 반영하면,
    # data_editor 의 merge 로직과 무관하게 사용자의 클릭이 손실 없이 처리된다.
    # 콜백에서 row index → 종목코드 매핑이 필요하므로 widget 렌더 전에 session_state 에 저장.
    st.session_state["_holdings_codes_by_idx"] = [r["종목코드"] for r in rows]

    df = pd.DataFrame(rows)
    df["상태"] = df["최고가 대비 하락(%)"].apply(lambda d: get_row_status(d, stop_loss_pct))
    df.insert(0, "자동매도", df["종목코드"].apply(lambda c: c in enabled_codes))

    locked_cols = [c for c in df.columns if c != "자동매도"]
    st.data_editor(
        df,
        use_container_width=True,
        hide_index=True,
        key="holdings_editor",
        on_change=_on_holdings_editor_change,
        disabled=locked_cols,
        column_config={
            "자동매도": st.column_config.CheckboxColumn(
                "자동매도",
                help="체크된 종목만 매도 조건 충족 시 실제 시장가 매도가 실행됩니다.",
                default=False,
            ),
            "평균단가": st.column_config.NumberColumn("평균단가", format="%,d원"),
            "현재가": st.column_config.NumberColumn("현재가", format="%,d원"),
            "최고가": st.column_config.NumberColumn("최고가", format="%,d원"),
            "수익률(%)": st.column_config.NumberColumn("수익률(%)", format="%+.2f%%"),
            "최고가 대비 하락(%)": st.column_config.NumberColumn("최고가 대비 하락(%)", format="%.2f%%"),
        },
    )


def _on_short_term_auto_change() -> None:
    """단타 자동매매 토글 → settings 즉시 반영."""
    slot = load_settings().get("short_term_trade") or {}
    if not isinstance(slot, dict):
        slot = {}
    set_setting(
        "short_term_trade",
        {**slot, "auto_enabled": bool(st.session_state.short_term_auto_toggle)},
    )


def _on_short_term_select_change() -> None:
    """단타 매매 종목 라디오 선택 변경 → 활성 슬롯 갱신.

    - 선택이 현재 활성 종목과 같으면: 예약된 교체가 있으면 취소.
    - 활성 종목을 보유(매수 상태) 중이면: 즉시 갈아타지 않고 교체 예약(`request_switch`) —
      트레이더가 이전 보유 전량 매도 후 전환.
    - 미보유면: 활성 슬롯을 즉시 새 후보로 갱신 (예산 풀 이월).
    """
    chosen = st.session_state.get("short_term_select")
    settings = load_settings()
    slot = settings.get("short_term_trade") or {}
    if not isinstance(slot, dict):
        slot = {}
    items = (settings.get("short_term_candidates") or {}).get("items") or []
    active_code = slot.get("code")

    if not chosen:
        return
    if chosen == active_code:
        if has_pending(slot):
            set_setting("short_term_trade", clear_pending(slot))
        return

    item = next((c for c in items if c.get("종목코드") == chosen), None)
    if item is None:
        return

    try:
        held = bool(active_code) and active_code in get_holdings()
    except Exception:
        held = False

    if held:
        set_setting("short_term_trade", request_switch(slot, item))
    else:
        set_setting(
            "short_term_trade",
            target_to_settings(
                item,
                auto_enabled=bool(slot.get("auto_enabled", False)),
                last_realized_amount=slot.get("last_realized_amount"),
            ),
        )


def render_short_term(market_open: bool) -> None:
    """단기 매매 (단타) — 상위 N종 후보 목록에서 라디오로 1종을 골라 자동매매.

    후보 목록은 코스피200 근사 풀에서 등락률+거래량 ranking 결합 상위 N종을 일단위로 선정.
    트레이더는 후보의 selected_at 날짜가 오늘이 아니면 자동 재선정하며, 수동 버튼은 강제 재선정용.
    """
    strategy = ShortTermStrategy()

    col_title, col_btn = st.columns([6, 1])
    col_title.subheader(f"🎯 단기 매매 — {strategy.display_name}")
    if col_btn.button("🔄 후보 선정", key="refresh_short_term"):
        with st.spinner("등락률·거래량 ranking 조회 중... (API 3회, 즉시 완료)"):
            items = strategy.find_targets(n=SHORT_TERM_CANDIDATE_COUNT)
        set_setting("short_term_candidates", candidates_to_settings(items))
        # 활성 슬롯이 미보유면 #1 종목으로 갱신 (보유 중이면 유지 — 보호)
        slot = load_settings().get("short_term_trade") or {}
        if not isinstance(slot, dict):
            slot = {}
        active_code = slot.get("code")
        try:
            held = bool(active_code) and active_code in get_holdings()
        except Exception:
            held = False
        if items and not held:
            set_setting(
                "short_term_trade",
                target_to_settings(
                    items[0],
                    auto_enabled=bool(slot.get("auto_enabled", False)),
                    last_realized_amount=slot.get("last_realized_amount"),
                ),
            )
        if items:
            st.success(f"후보 {len(items)}종 선정 완료.")
        else:
            st.warning("두 ranking 모두 등장한 종목이 시총 풀 안에 없습니다.")
        st.rerun()

    from core.trader import (
        Trader as _Trader,
        short_term_buy_delay_min,
        short_term_buy_start_label,
    )
    budget_max = _Trader.SHORT_TERM_BUDGET_MAX
    buy_delay = short_term_buy_delay_min()
    buy_start = short_term_buy_start_label()
    with st.expander("ℹ️ 동작 안내", expanded=False):
        st.markdown(
            f"**등락률 순위 + 거래량 순위가 모두 상위**인 종목 최대 {SHORT_TERM_CANDIDATE_COUNT}종을 후보로 선정합니다 (rank 합산이 작을수록 우선).\n\n"
            f"- 풀: KOSPI200 시총 상위 {strategy.pool_top_n} 우선, 풀 안에 후보가 없으면 KOSPI200 전체에서 fallback.\n"
            f"- **후보 목록에서 라디오로 1종을 선택**하고 '자동매매'를 켜면 그 종목을 매수합니다. 단 **진입 게이트**(전일대비등락률 ≤ +{strategy.entry_max_chg_pct:.0f}% 과열 컷 · 현재가 ≥ 당일 저가 +{strategy.entry_min_rebound_pct:.0f}% 반등)를 통과한 자리에서만 매수하고, 미충족 시 다음 주기 재평가.\n"
            f"- **청산(3중)**: ① 손절 매수가 대비 **-{strategy.stop_loss_pct:.0f}%** · ② 트레일링 수익 **+{strategy.trail_arm_pct:.0f}%** 도달 후 최고가 대비 **-{strategy.trail_drop_pct:.0f}%** 하락 시 청산"
            + (f" · ③ 익절 **+{strategy.take_profit_pct:.0f}%**" if strategy.take_profit_pct > 0 else " (익절은 트레일링에 위임)")
            + ".\n"
            f"- **개장 직후 변동성 회피**: 후보 선정은 9시부터 하되, 실제 매수는 "
            f"**{buy_start} 이후**(개장 후 {buy_delay}분) 시작. 지연 시간은 사이드바에서 조절 가능.\n"
            f"- 매도 즉시 다음 후보로 활성 종목을 자동 지정 (직전 매도 종목 제외).\n"
            f"- 후보는 매일 자동 재선정되며, **보유 중인 종목은 유지**하고 미보유(빈) 슬롯만 새 후보 #1로 갱신.\n"
            f"- 보유 중 라디오로 다른 종목을 고르면 **이전 보유를 전량 매도 후 전환**합니다.\n"
            f"- 매수 예산: **min(직전 매도 회수 금액, 상한 {budget_max:,.0f}원, 주문가능금액)** "
            f"— 이익은 상한으로 캡, 손실은 이 매매 자금 풀에서 흡수 (일반 자금 보충 X)."
        )

    settings = load_settings()
    slot = settings.get("short_term_trade") or {}
    if not isinstance(slot, dict):
        slot = {}
    container = settings.get("short_term_candidates") or {}
    items = container.get("items") or []

    if not items:
        st.info("후보가 없습니다. 위의 '🔄 후보 선정' 버튼을 누르거나, 트레이더가 다음 주기에 자동 선정합니다.")
        return

    # ── 후보 테이블 (읽기 전용, 상위 N종) ──
    cand_df = pd.DataFrame([
        {
            "순위": i,
            "종목명": c.get("종목명", ""),
            "종목코드": c.get("종목코드", ""),
            "현재가": c.get("현재가", 0) or 0,
            "등락률(%)": c.get("등락률(%)"),
            "거래량": c.get("거래량", 0) or 0,
            "선정사유": c.get("선정사유", ""),
        }
        for i, c in enumerate(items, start=1)
    ])
    st.dataframe(
        cand_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "현재가": st.column_config.NumberColumn("현재가", format="%,d원"),
            "등락률(%)": st.column_config.NumberColumn("등락률(%)", format="%+.2f%%"),
            "거래량": st.column_config.NumberColumn("거래량", format="%,d"),
        },
    )

    # ── 라디오(후보 목록에서 매매 종목 1종 선택) + 자동매매 토글 ──
    active_code = slot.get("code")
    options = [c.get("종목코드") for c in items if c.get("종목코드")]
    # 라디오 라벨에 위 표와 동일한 순위·종목명·등락률을 담아 목록 자체가 선택지가 되게 한다.
    label_map: dict[str, str] = {}
    for i, c in enumerate(items, start=1):
        code = c.get("종목코드")
        if not code:
            continue
        name = c.get("종목명") or code
        chg = c.get("등락률(%)")
        chg_str = f"  ({chg:+.2f}%)" if isinstance(chg, (int, float)) else ""
        label_map[code] = f"{i}. {name} [{code}]{chg_str}"
    # 보유/활성 종목이 후보 목록 밖이어도 선택지에 포함 (보유 포지션 추적 유지)
    if active_code and active_code not in options:
        options = [active_code] + options
        label_map.setdefault(active_code, f"(보유) {slot.get('name') or active_code} [{active_code}]")

    # session_state 선택값이 현재 옵션에 없으면 활성 종목(없으면 #1)으로 보정 (stale 값 에러 방지)
    if st.session_state.get("short_term_select") not in options:
        st.session_state.short_term_select = (
            active_code if active_code in options else (options[0] if options else None)
        )
    # 자동매매 토글 1회 시드 — 이후엔 widget 이 상태 유지, on_change 가 영속화
    if "short_term_auto_toggle" not in st.session_state:
        st.session_state.short_term_auto_toggle = bool(slot.get("auto_enabled", False))

    col_sel, col_auto = st.columns([3, 1])
    with col_sel:
        st.radio(
            "매매 종목 선택 (목록에서 1종)",
            options=options,
            format_func=lambda c: label_map.get(c, c),
            key="short_term_select",
            on_change=_on_short_term_select_change,
            help="후보 목록에서 실제 자동매매할 1종을 선택합니다. 보유 중 다른 종목을 고르면 이전 보유를 전량 매도 후 전환합니다.",
        )
    with col_auto:
        st.toggle(
            "자동매매",
            key="short_term_auto_toggle",
            on_change=_on_short_term_auto_change,
            help="켜면 선택 종목을 매수/매도 조건 충족 시 시장가로 자동 실행합니다.",
        )

    # 교체 예약 안내 (보유 중 라디오로 다른 종목을 골랐을 때)
    _render_short_term_pending(slot)

    # ── 활성 종목 상태 ──
    if not active_code:
        st.caption("선택된 매매 종목이 없습니다. 후보 목록에서 라디오로 종목을 선택하세요.")
        return

    name = slot.get("name") or active_code
    price, stale = fetch_price(active_code, market_open)
    holding_qty = 0
    avg_price = None
    profit_pct: float | None = None
    try:
        held = get_holdings().get(active_code)
        if held:
            holding_qty = held.get("qty", 0)
            avg_price = held.get("avg_price")
            if price and avg_price:
                profit_pct = (price - avg_price) / avg_price * 100
    except Exception:
        pass

    if stale:
        st.caption("⚠️ 가격은 마지막 조회 시점 기준입니다.")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("매매 종목", name)
    m2.metric("현재가", f"{(price or 0):,.0f}원")
    m3.metric("보유수량", f"{holding_qty:,}주")
    m4.metric("수익률", f"{profit_pct:+.2f}%" if profit_pct is not None else "—")

    # 다음 진입 예산 상한 — 직전 매도 회수 금액이 있으면 그것이 상한, 없으면 BUDGET_MAX.
    last_realized = slot.get("last_realized_amount")
    if isinstance(last_realized, (int, float)) and last_realized > 0:
        next_budget_cap = min(float(last_realized), float(budget_max))
        st.caption(
            f"💰 다음 진입 예산 상한: **{next_budget_cap:,.0f}원** "
            f"(직전 매도 회수 {last_realized:,.0f}원 vs 상한 {budget_max:,.0f}원 중 작은 쪽)"
        )
    else:
        st.caption(f"💰 다음 진입 예산 상한: **{budget_max:,.0f}원** (첫 진입 또는 매도 이력 없음)")


def _render_short_term_pending(slot: dict) -> None:
    """교체 예약(pending) 안내 — 보유 중 라디오로 다른 종목을 골랐을 때.

    트레이더가 다음 주기에 이전 보유를 전량 매도한 뒤 예약 종목으로 전환한다.
    """
    if not (has_pending(slot) and slot.get("pending_action") == "switch"):
        return
    pending = slot["pending_target"]
    p_name = pending.get("종목명") or pending.get("종목코드")
    p_code = pending.get("종목코드")
    st.warning(
        f"🔁 **교체 예약됨** → {p_name} ({p_code}). "
        "다음 트레이더 주기에 이전 보유 종목을 전량 매도하고 전환합니다 "
        "(장 시간 외라면 개장 후 진행)."
    )
    if st.button("교체 취소 (이전 종목 유지)", key="st_cancel_switch"):
        set_setting("short_term_trade", clear_pending(slot))
        st.rerun()


def refresh_buy_candidates() -> list[dict]:
    """매수 후보를 다시 탐색하고 파일에 저장 (메인 + view 전략 모두 실행).

    매수 실행에 사용되는 메인 전략 후보만 반환하며, 파일에는 모든 전략의 후보를
    `_strategy` / `_strategy_label` 식별 필드와 함께 통합 저장한다.
    """
    primary = primary_buy_strategy()
    view_strategies = view_buy_strategies()
    primary_name = type(primary).__name__

    with open(BUY_CANDIDATES_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {
                "status": "refreshing",
                "started_at": datetime.now().isoformat(),
                "strategy": primary_name,
                "candidates": [],
            },
            f, ensure_ascii=False, indent=2,
        )

    main_candidates = primary.find_candidates()
    _tag_candidates(main_candidates, primary)
    all_candidates: list[dict] = list(main_candidates)
    for vs in view_strategies:
        try:
            view_results = vs.find_candidates()
            _tag_candidates(view_results, vs)
            all_candidates.extend(view_results)
        except Exception:
            continue

    with open(BUY_CANDIDATES_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {
                "status": "ready",
                "updated_at": datetime.now().isoformat(),
                "strategy": primary_name,
                "primary_strategy": primary_name,
                "primary_strategy_label": primary.display_name,
                "candidates": all_candidates,
            },
            f, ensure_ascii=False, indent=2,
        )
    return main_candidates


def _signal_score_bg(value) -> str:
    """0~100 시그널점수를 흰색→짙은 녹색 그라데이션 CSS 로 변환 (matplotlib 의존 회피).

    matplotlib `Greens` cmap 을 흉내내어 (247,252,245) → (0,68,27) 선형 보간.
    50 이상은 가독성을 위해 글자색을 흰색으로 전환.
    """
    if not isinstance(value, (int, float)):
        return ""
    t = max(0.0, min(1.0, float(value) / 100.0))
    r = round(247 + (0 - 247) * t)
    g = round(252 + (68 - 252) * t)
    b = round(245 + (27 - 245) * t)
    fg = "color: white" if t >= 0.5 else ""
    return f"background-color: rgb({r},{g},{b}); {fg}".rstrip("; ")


def _render_candidate_table(items: list[dict]) -> None:
    """후보 dict 리스트를 테이블로 표시. `_strategy*` 메타 필드는 자동 숨김."""
    df = pd.DataFrame(items)
    df = df.drop(columns=[c for c in ("_strategy", "_strategy_label") if c in df.columns])
    df.insert(0, "순위", range(1, len(df) + 1))
    if "시그널점수" in df.columns:
        cols = ["순위", "시그널점수"] + [c for c in df.columns if c not in ("순위", "시그널점수")]
        df = df[cols]

    fmt: dict = {}
    if "현재가" in df.columns:
        fmt["현재가"] = "{:,.0f}원"
    if "거래량" in df.columns:
        fmt["거래량"] = "{:,.0f}"
    if "시그널점수" in df.columns:
        fmt["시그널점수"] = "{:.1f}"
    pct_cols = [c for c in df.columns if c.endswith("(%)")]
    for col in pct_cols:
        fmt[col] = lambda x: f"{x:+.2f}%" if isinstance(x, (int, float)) else x

    styled = df.style.format(fmt)
    if pct_cols:
        styled = styled.map(
            lambda x: "color: #d9534f; font-weight: bold" if isinstance(x, str) and x.startswith("+") else (
                      "color: #0275d8" if isinstance(x, str) and x.startswith("-") else ""),
            subset=pct_cols,
        )
    if "시그널점수" in df.columns:
        styled = styled.map(_signal_score_bg, subset=["시그널점수"])
    st.dataframe(styled, use_container_width=True, hide_index=True)


def render_buy_candidates() -> None:
    """전략별 매수 후보를 그룹 단위로 표시. primary 그룹만 실제 매수에 사용된다."""
    col_title, col_btn = st.columns([6, 1])
    col_title.subheader("매수 후보 (전략별)")
    if col_btn.button("🔄 새로고침", key="refresh_candidates"):
        with st.spinner("매수 후보 탐색 중..."):
            candidates = refresh_buy_candidates()
        st.session_state.buy_candidates = candidates
        st.rerun()

    data: list[dict] = []
    updated_at = None
    status = "ready"
    started_at = None
    primary_strategy = None
    primary_strategy_label = None

    if os.path.exists(BUY_CANDIDATES_FILE):
        try:
            with open(BUY_CANDIDATES_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            status = raw.get("status", "ready")
            data = raw.get("candidates", []) or []
            updated_at = raw.get("updated_at")
            started_at = raw.get("started_at")
            primary_strategy = raw.get("primary_strategy") or raw.get("strategy")
            primary_strategy_label = raw.get("primary_strategy_label")
            if status == "ready":
                st.session_state.buy_candidates = data
        except Exception:
            data = st.session_state.buy_candidates or []
    else:
        data = st.session_state.buy_candidates or []

    if status == "refreshing":
        msg = "🔄 매수 후보 탐색 중..."
        if started_at:
            try:
                ts = datetime.fromisoformat(started_at).strftime("%H:%M:%S")
                msg += f" (시작 {ts})"
            except Exception:
                pass
        st.info(msg)
        return

    if not data:
        st.info("매수 후보 데이터가 없습니다. 트레이더 시작 후 자동으로 탐색됩니다.")
        return

    if updated_at:
        try:
            ts = datetime.fromisoformat(updated_at).strftime("%Y-%m-%d %H:%M:%S")
            st.caption(f"📅 탐색 시각: {ts}")
        except Exception:
            pass

    # _strategy 키로 그룹화. 첫 등장 순서를 유지해서 primary 가 위로 오도록.
    groups: dict[str, dict] = {}
    # primary 전략이 0개를 반환해도 빈 그룹으로 먼저 등록 — 사용자에게 활성 상태/조건 미충족을 명시.
    if primary_strategy:
        groups[primary_strategy] = {
            "label": primary_strategy_label or primary_strategy,
            "is_primary": True,
            "items": [],
        }
    for c in data:
        key = c.get("_strategy", "기타")
        if key not in groups:
            groups[key] = {
                "label": c.get("_strategy_label", key),
                "is_primary": (key == primary_strategy),
                "items": [],
            }
        groups[key]["items"].append(c)

    if not groups:
        _render_candidate_table(data)
        return

    for key, info in groups.items():
        marker = " · 매수 실행" if info["is_primary"] else " · view-only"
        st.markdown(f"**{info['label']}**{marker}")
        if info["items"]:
            _render_candidate_table(info["items"])
        else:
            st.caption("⚠️ 조건 통과 종목 없음 — 현재 시장 상황에서 이 전략의 필터를 통과한 종목이 없습니다.")


def render_buy_plan_preview() -> None:
    """장 마감 시, 현재 예수금으로 매수 후보를 어떻게 분배해 구매할지 미리보기."""
    st.subheader("🛒 매수 예정 미리보기 (장 마감 상태)")
    st.caption("장이 열리면 아래 계획대로 시장가 매수 주문이 실행됩니다. 슬롯 금액이 주가보다 작아도 최소 1주는 배정.")

    # 후보 로드 — primary 전략 후보만 매수 실행 대상.
    # JSON 을 정상 로드한 경우, primary 필터 결과가 비어 있더라도 절대 view-only 후보로
    # fallback 하지 않는다 (view-only 후보가 실제 매수 계획에 새어 들어가는 것을 차단).
    candidates: list[dict] | None = None
    json_loaded = False
    if os.path.exists(BUY_CANDIDATES_FILE):
        try:
            with open(BUY_CANDIDATES_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            all_candidates = raw.get("candidates", []) or []
            primary_strategy = raw.get("primary_strategy") or raw.get("strategy")
            if primary_strategy and any("_strategy" in c for c in all_candidates):
                candidates = [c for c in all_candidates if c.get("_strategy") == primary_strategy]
            else:
                candidates = all_candidates
            json_loaded = True
        except Exception:
            candidates = None

    # JSON 로드 자체가 실패한 경우에만 세션 캐시로 fallback
    if not json_loaded and not candidates:
        candidates = st.session_state.buy_candidates

    if not candidates:
        if json_loaded:
            st.info("primary 매수 전략의 조건 통과 종목이 없어 매수 계획을 생성할 수 없습니다.")
        else:
            st.info("매수 후보 데이터가 없습니다.")
        return

    # 예수금 (캐시 허용)
    balance = st.session_state.last_cash_balance
    try:
        balance = get_cash_balance()
        st.session_state.last_cash_balance = balance
    except Exception:
        pass
    if not balance:
        st.warning("예수금을 알 수 없어 미리보기를 생성할 수 없습니다.")
        return

    cash = balance["주문가능금액"]
    try:
        owned = set(get_holdings().keys())
    except Exception:
        owned = set()

    # 사이드바와 동일한 한도 적용 (settings.json 값을 사용)
    raw_max = load_settings().get("max_holdings", 5)
    try:
        max_holdings = int(raw_max)
    except (TypeError, ValueError):
        max_holdings = 5
    if max_holdings < 1:
        max_holdings = 1

    plan = plan_initial_buy(candidates, cash, owned, max_holdings=max_holdings)

    if not plan:
        if len(owned) >= max_holdings:
            st.info(f"보유 {len(owned)}종 ≥ 한도 {max_holdings}종 — 매수 슬롯 없음.")
        else:
            st.info("매수 가능한 후보가 없습니다 (주문가능금액 부족 또는 모두 보유 중).")
        return

    total = sum(p["예상금액"] for p in plan)
    slot = cash / len(plan)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("주문가능금액", f"{cash:,.0f}원")
    c2.metric("슬롯(종목당 배정)", f"{slot:,.0f}원")
    c3.metric("예상 총 주문액", f"{total:,.0f}원")
    c4.metric("보유/한도", f"{len(owned)} / {max_holdings}")

    rows = [{
        "순위": i + 1,
        "종목명": p["종목명"],
        "종목코드": p["종목코드"],
        "현재가": p["현재가"],
        "수량": p["수량"],
        "예상금액": p["예상금액"],
    } for i, p in enumerate(plan)]

    df = pd.DataFrame(rows)
    styled = df.style.format({
        "현재가": "{:,.0f}원",
        "예상금액": "{:,.0f}원",
        "수량": "{:,}주",
    })
    st.dataframe(styled, use_container_width=True, hide_index=True)


def render_trade_history() -> None:
    """trade_history.json 기반 매수/매도 이력 표시"""
    st.subheader("거래 이력")

    if not os.path.exists(TRADE_HISTORY_FILE):
        st.info("거래 이력이 없습니다.")
        return

    try:
        with open(TRADE_HISTORY_FILE, "r", encoding="utf-8") as f:
            trades = json.load(f).get("trades", [])
    except Exception as e:
        st.error(f"거래 이력 로드 실패: {e}")
        return

    if not trades:
        st.info("거래 이력이 없습니다.")
        return

    rows = []
    for t in reversed(trades):  # 최신순
        ts = t.get("timestamp", "")
        try:
            ts = datetime.fromisoformat(ts).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass
        trade_type = t.get("type", "")
        rows.append({
            "시각": ts,
            "구분": "🟢 매수" if trade_type == "buy" else "🔴 매도",
            "종목명": t.get("name", ""),
            "종목코드": t.get("code", ""),
            "체결가": t.get("price", 0),
            "수량": t.get("qty", 0),
            "거래금액": t.get("amount", 0),
            "메모": t.get("reason", ""),
        })

    df = pd.DataFrame(rows)
    styled = (
        df.style
        .format({
            "체결가": "{:,.0f}원",
            "거래금액": "{:,.0f}원",
        })
        .map(
            lambda x: "color: #d9534f; font-weight: bold" if isinstance(x, str) and "매도" in x else (
                      "color: #2e7d32; font-weight: bold" if isinstance(x, str) and "매수" in x else ""),
            subset=["구분"],
        )
    )
    st.dataframe(styled, use_container_width=True, hide_index=True)


def render_log() -> None:
    st.subheader("최근 로그")
    # 오늘 일별 로그를 우선 표시하고, 자정 직후·기동 직후처럼 아직 없으면 직전 일자로 폴백.
    path = current_log_file()
    if not os.path.exists(path):
        path = latest_log_file()
    if not path or not os.path.exists(path):
        st.info("로그 파일이 없습니다. `python main.py`를 실행하면 로그가 표시됩니다.")
        return
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    st.caption(f"파일: `{os.path.basename(path)}`")
    st.code("".join(lines[-50:]), language=None)


def _init_sidebar_state(settings: dict) -> None:
    """settings.json 의 값을 session_state 로 1회 시드.

    Streamlit widget 은 `key=` 가 부여되면 session_state 의 값을 우선 사용한다.
    여기서 한 번만 시드하고, 이후 widget 변경은 on_change 콜백이 settings 로 영속화한다.
    매 rerun 마다 settings 를 다시 읽지 않아 auto-refresh race condition 을 회피한다.
    """
    if st.session_state.get("_sidebar_initialized"):
        return

    all_buy_options = buy_strategy_options()
    all_buy_keys = [k for k, _ in all_buy_options]
    sell_options = sell_strategy_options()
    sell_keys = [k for k, _ in sell_options]

    primary_key = settings.get("primary_buy_strategy", DEFAULT_PRIMARY_BUY_KEY)
    if primary_key not in all_buy_keys:
        primary_key = DEFAULT_PRIMARY_BUY_KEY

    sell_key = settings.get("sell_strategy", DEFAULT_SELL_KEY)
    if sell_key not in sell_keys:
        sell_key = DEFAULT_SELL_KEY

    raw_view_keys = settings.get("view_buy_strategies", DEFAULT_VIEW_BUY_KEYS)
    if not isinstance(raw_view_keys, list):
        raw_view_keys = DEFAULT_VIEW_BUY_KEYS
    # primary 와 겹치거나 알 수 없는 키는 제외
    view_keys = [k for k in raw_view_keys if k != primary_key and k in all_buy_keys]

    raw_max = settings.get("max_holdings", 5)
    try:
        max_holdings_val = int(raw_max)
    except (TypeError, ValueError):
        max_holdings_val = 5
    if max_holdings_val < 1:
        max_holdings_val = 1

    raw_delay = settings.get("short_term_buy_delay_min", 10)
    try:
        buy_delay_val = int(raw_delay)
    except (TypeError, ValueError):
        buy_delay_val = 10
    if buy_delay_val < 0:
        buy_delay_val = 0

    st.session_state.buy_enabled_toggle = bool(settings.get("buy_enabled", False))
    st.session_state.primary_buy_select = primary_key
    st.session_state.view_buy_multiselect = view_keys
    st.session_state.sell_strategy_select = sell_key
    st.session_state.stop_loss_input = float(settings.get("stop_loss_pct", 10.0))
    st.session_state.max_holdings_input = max_holdings_val
    st.session_state.short_term_buy_delay_input = buy_delay_val
    st.session_state.auto_refresh_toggle = bool(settings.get("auto_refresh", True))
    st.session_state.refresh_interval_slider = int(settings.get("refresh_interval", 60))
    st.session_state._sidebar_initialized = True


def _on_buy_enabled_change() -> None:
    set_setting("buy_enabled", bool(st.session_state.buy_enabled_toggle))


def _on_primary_buy_change() -> None:
    new_primary = st.session_state.primary_buy_select
    set_setting("primary_buy_strategy", new_primary)
    # primary 가 view 목록에 들어있으면 view 에서도 제거 (UI · 영속화 양쪽 동기화)
    current_view = list(st.session_state.get("view_buy_multiselect", []))
    if new_primary in current_view:
        current_view = [k for k in current_view if k != new_primary]
        st.session_state.view_buy_multiselect = current_view
        set_setting("view_buy_strategies", current_view)


def _on_view_buy_change() -> None:
    set_setting("view_buy_strategies", list(st.session_state.view_buy_multiselect))


def _on_sell_strategy_change() -> None:
    set_setting("sell_strategy", st.session_state.sell_strategy_select)


def _on_stop_loss_change() -> None:
    set_setting("stop_loss_pct", float(st.session_state.stop_loss_input))


def _on_max_holdings_change() -> None:
    set_setting("max_holdings", int(st.session_state.max_holdings_input))


def _on_short_term_buy_delay_change() -> None:
    set_setting("short_term_buy_delay_min", int(st.session_state.short_term_buy_delay_input))


def _on_auto_refresh_change() -> None:
    set_setting("auto_refresh", bool(st.session_state.auto_refresh_toggle))


def _on_refresh_interval_change() -> None:
    set_setting("refresh_interval", int(st.session_state.refresh_interval_slider))


def render_sidebar() -> tuple[bool, int, str, str, float]:
    """사이드바 렌더. (auto_refresh, interval, buy_strategy_label, sell_strategy_label, stop_loss_pct) 반환.

    영속화는 widget 의 `on_change` 콜백에서만 수행 — auto-refresh rerun 시 default 가
    덮어쓰는 race 를 방지한다. 모든 widget 에 `key=` 를 부여해 session_state 가
    widget 상태를 안정적으로 유지하도록 한다.
    """
    settings = load_settings()
    _init_sidebar_state(settings)

    all_buy_options = buy_strategy_options()
    all_buy_keys = [k for k, _ in all_buy_options]
    all_buy_label_by_key = {k: l for k, l in all_buy_options}
    sell_options = sell_strategy_options()
    sell_keys_list = [k for k, _ in sell_options]
    sell_label_by_key = {k: l for k, l in sell_options}

    with st.sidebar:
        st.header("설정")

        st.toggle(
            "🛒 매수 활성화",
            key="buy_enabled_toggle",
            on_change=_on_buy_enabled_change,
            help="끄면 트레이더가 초기 매수 및 매도 후 재매수를 실행하지 않습니다. 매도는 계속 동작.",
        )
        if st.session_state.buy_enabled_toggle:
            st.success("매수 ON")
        else:
            st.warning("매수 OFF")

        st.number_input(
            "최대 보유 종목 수",
            min_value=1, max_value=20,
            step=1,
            key="max_holdings_input",
            on_change=_on_max_holdings_change,
            help="이 수를 초과하지 않도록 매수 시점에 슬롯을 제한합니다. 매도 후 재매수도 한도 미만일 때만 실행.",
        )

        st.divider()
        st.subheader("📊 매수 전략")

        # 활성 매수 전략 (primary) — 실제 매수 실행에 사용
        st.selectbox(
            "활성 매수 전략 (실제 매수 실행)",
            options=all_buy_keys,
            format_func=lambda k: all_buy_label_by_key.get(k, k),
            key="primary_buy_select",
            on_change=_on_primary_buy_change,
        )
        current_primary_key = st.session_state.primary_buy_select

        # 보조 매수 전략 (view) — primary 키는 후보에서 자동 제외
        view_option_keys = [k for k in all_buy_keys if k != current_primary_key]
        st.multiselect(
            "보조 매수 전략 (대시보드 비교용)",
            options=view_option_keys,
            format_func=lambda k: all_buy_label_by_key.get(k, k),
            key="view_buy_multiselect",
            on_change=_on_view_buy_change,
        )

        st.divider()
        st.subheader("🛡 매도 전략")
        st.selectbox(
            "활성 매도 전략",
            options=sell_keys_list,
            format_func=lambda k: sell_label_by_key.get(k, k),
            key="sell_strategy_select",
            on_change=_on_sell_strategy_change,
        )
        current_sell_key = st.session_state.sell_strategy_select

        if current_sell_key == "trailing_stop":
            st.number_input(
                "손절 기준 (%)",
                min_value=1.0, max_value=50.0,
                step=0.5,
                key="stop_loss_input",
                on_change=_on_stop_loss_change,
                help="최고가 대비 이 비율 이상 하락하면 시장가 매도. 다음 확인 주기부터 반영됩니다.",
            )
        else:
            st.caption("ℹ️ 보유 종목 테이블의 '최고가/하락률' 컬럼은 참고용으로만 표시됩니다.")

        st.divider()
        st.subheader("🎯 단기 매매")
        st.number_input(
            "개장 후 매수 지연 (분)",
            min_value=0, max_value=60,
            step=1,
            key="short_term_buy_delay_input",
            on_change=_on_short_term_buy_delay_change,
            help="개장(09:00) 후 이 시간이 지나야 실매수를 시작합니다. 종목 탐색·선정은 9시부터 진행. 0=개장 즉시 매수.",
        )

        st.divider()
        st.toggle("자동 새로고침", key="auto_refresh_toggle", on_change=_on_auto_refresh_change)
        st.slider(
            "새로고침 주기 (초)",
            min_value=10, max_value=600,
            step=10,
            key="refresh_interval_slider",
            on_change=_on_refresh_interval_change,
        )
        if st.button("지금 새로고침", use_container_width=True):
            st.rerun()

    buy_label = all_buy_label_by_key.get(current_primary_key, current_primary_key)
    sell_label = sell_label_by_key.get(current_sell_key, current_sell_key)
    return (
        bool(st.session_state.auto_refresh_toggle),
        int(st.session_state.refresh_interval_slider),
        buy_label,
        sell_label,
        float(st.session_state.stop_loss_input),
    )


# ── 메인 ──────────────────────────────────────────────────────────────────────

# market_open: 대시보드가 '매매 활성' 으로 동작할지 여부 (모의는 장 시간 외에도 활성).
# 실제 시장 상태는 render_header 가 is_market_open() 으로 따로 표시한다.
market_open = is_trading_time()
auto_refresh, refresh_interval, buy_label, sell_label, stop_loss_pct = render_sidebar()

render_header(market_open, buy_label, sell_label)
st.divider()
render_holdings(market_open, stop_loss_pct)
st.divider()
render_short_term(market_open)
st.divider()
render_buy_candidates()
if not market_open:
    st.divider()
    render_buy_plan_preview()
st.divider()
render_trade_history()
st.divider()
render_log()

if auto_refresh:
    # JS 기반 비블로킹 자동 새로고침. `time.sleep` 으로 스크립트를 잠재우면 그 사이 발생한
    # 위젯 인터랙션이 큐잉만 되고 즉시 처리되지 않아 체크박스 클릭이 반영되지 않는 문제가 있었다.
    st_autorefresh(interval=refresh_interval * 1000, key="_auto_refresh_tick")
