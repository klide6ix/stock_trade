import json
import os
import time
import pandas as pd
import streamlit as st
from datetime import datetime

from config import STOP_LOSS_PCT, CHECK_INTERVAL
from core.kis_api import get_holdings, get_current_price, get_volume_rank, get_cash_balance
from core.logger import LOG_FILE
from core.trader import is_market_open, plan_initial_buy, BUY_CANDIDATES_FILE, TRADE_HISTORY_FILE
from core.strategy.buy.volume_momentum import VolumeMomentumBuyStrategy
from core.strategy.sell import PEAK_PRICES_FILE
from core.settings import load_settings, set_value as set_setting

st.set_page_config(page_title="트레이더", page_icon="📈", layout="wide")

# ── 세션 상태 초기화 ───────────────────────────────────────────────────────────
if "peak_prices" not in st.session_state:
    # peak_prices.json 에서 복원 시도
    _pp = {}
    if os.path.exists(PEAK_PRICES_FILE):
        try:
            with open(PEAK_PRICES_FILE, "r", encoding="utf-8") as _f:
                _pp = {k: float(v) for k, v in json.load(_f).get("prices", {}).items()}
        except Exception:
            pass
    st.session_state.peak_prices = _pp
if "last_prices" not in st.session_state:
    st.session_state.last_prices = {}
if "last_volume_rank" not in st.session_state:
    st.session_state.last_volume_rank = []
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


def build_holdings_rows(market_open: bool) -> tuple[list[dict], bool]:
    """보유 종목 데이터 생성. (rows, 캐시가격 사용여부) 반환"""
    holdings = get_holdings()
    rows = []
    any_stale = False

    for code, info in holdings.items():
        price, stale = fetch_price(code, market_open)
        if stale:
            any_stale = True

        if price and market_open:
            if code not in st.session_state.peak_prices or price > st.session_state.peak_prices[code]:
                st.session_state.peak_prices[code] = price
                try:
                    with open(PEAK_PRICES_FILE, "w", encoding="utf-8") as _pf:
                        json.dump(
                            {"updated_at": datetime.now().isoformat(), "prices": st.session_state.peak_prices},
                            _pf, ensure_ascii=False, indent=2,
                        )
                except Exception:
                    pass

        peak = st.session_state.peak_prices.get(code, price)
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


def get_row_status(drop_pct: float | None) -> str:
    if drop_pct is None:
        return "❓"
    if drop_pct >= STOP_LOSS_PCT:
        return "🔴 손절 실행"
    if drop_pct >= STOP_LOSS_PCT * 0.8:
        return "🟠 손절 임박"
    if drop_pct >= STOP_LOSS_PCT * 0.5:
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


def render_header(market_open: bool) -> None:
    st.title("📈 트레이더 대시보드")
    render_cash_balance()
    st.divider()
    if not market_open:
        st.info("⏸ 장 운영 시간 외입니다. 보유 종목과 마지막 가격 기준으로 표시합니다.")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("장 상태", "🟢 운영 중" if market_open else "🔴 마감")
    c2.metric("손절 기준", f"{STOP_LOSS_PCT}%")
    c3.metric("확인 주기", f"{CHECK_INTERVAL // 60}분")
    c4.metric("마지막 갱신", datetime.now().strftime("%H:%M:%S"))


def render_holdings(market_open: bool) -> None:
    st.subheader("보유 종목")
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

    df = pd.DataFrame(rows)
    df["상태"] = df["최고가 대비 하락(%)"].apply(get_row_status)

    def color_row(row):
        drop = row["최고가 대비 하락(%)"]
        if drop is None:
            return [""] * len(row)
        if drop >= STOP_LOSS_PCT:
            return ["background-color: #ffcccc"] * len(row)
        if drop >= STOP_LOSS_PCT * 0.8:
            return ["background-color: #ffe4b2"] * len(row)
        if drop >= STOP_LOSS_PCT * 0.5:
            return ["background-color: #fffacd"] * len(row)
        return [""] * len(row)

    styled = (
        df.style
        .apply(color_row, axis=1)
        .format({
            "평균단가": "{:,.0f}원",
            "현재가": "{:,.0f}원",
            "최고가": "{:,.0f}원",
            "수익률(%)": lambda x: f"{x:+.2f}%" if x is not None else "-",
            "최고가 대비 하락(%)": lambda x: f"{x:.2f}%" if x is not None else "-",
        })
    )
    st.dataframe(styled, use_container_width=True, hide_index=True)


def refresh_buy_candidates() -> list[dict]:
    """매수 후보를 다시 탐색하고 파일에 저장"""
    strategy = VolumeMomentumBuyStrategy()
    candidates = strategy.find_candidates()
    with open(BUY_CANDIDATES_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {"updated_at": datetime.now().isoformat(), "candidates": candidates},
            f, ensure_ascii=False, indent=2,
        )
    return candidates


def render_buy_candidates() -> None:
    """거래량 상위 20종목 중 주간 상승률 상위 5종목 표시 (trader 저장 파일 또는 세션 캐시 사용)"""
    col_title, col_btn = st.columns([6, 1])
    col_title.subheader("매수 후보 (시가총액 상위 100 → 거래량 상위 20 → 주간 상승률 상위 5)")
    if col_btn.button("🔄 새로고침", key="refresh_candidates"):
        with st.spinner("매수 후보 탐색 중..."):
            candidates = refresh_buy_candidates()
        st.session_state.buy_candidates = candidates
        st.rerun()

    data = None
    updated_at = None

    if os.path.exists(BUY_CANDIDATES_FILE):
        try:
            with open(BUY_CANDIDATES_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            data = raw.get("candidates", [])
            updated_at = raw.get("updated_at")
            st.session_state.buy_candidates = data
        except Exception:
            data = st.session_state.buy_candidates
    else:
        data = st.session_state.buy_candidates

    if not data:
        st.info("매수 후보 데이터가 없습니다. 트레이더 시작 후 자동으로 탐색됩니다.")
        return

    if updated_at:
        try:
            ts = datetime.fromisoformat(updated_at).strftime("%Y-%m-%d %H:%M:%S")
            st.caption(f"📅 탐색 시각: {ts}")
        except Exception:
            pass

    df = pd.DataFrame(data)
    df.insert(0, "순위", range(1, len(df) + 1))

    styled = (
        df.style
        .format({
            "현재가": "{:,.0f}원",
            "거래량": "{:,.0f}",
            "주간등락률(%)": lambda x: f"{x:+.2f}%",
        })
        .map(
            lambda x: "color: #d9534f; font-weight: bold" if isinstance(x, str) and x.startswith("+") else (
                      "color: #0275d8" if isinstance(x, str) and x.startswith("-") else ""),
            subset=["주간등락률(%)"],
        )
    )
    st.dataframe(styled, use_container_width=True, hide_index=True)


def render_buy_plan_preview() -> None:
    """장 마감 시, 현재 예수금으로 매수 후보를 어떻게 분배해 구매할지 미리보기."""
    st.subheader("🛒 매수 예정 미리보기 (장 마감 상태)")
    st.caption("장이 열리면 아래 계획대로 시장가 매수 주문이 실행됩니다. 슬롯 금액이 주가보다 작아도 최소 1주는 배정.")

    # 후보 로드
    candidates = None
    if os.path.exists(BUY_CANDIDATES_FILE):
        try:
            with open(BUY_CANDIDATES_FILE, "r", encoding="utf-8") as f:
                candidates = json.load(f).get("candidates", [])
        except Exception:
            candidates = None
    if not candidates:
        candidates = st.session_state.buy_candidates

    if not candidates:
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

    plan = plan_initial_buy(candidates, cash, owned)

    if not plan:
        st.info("매수 가능한 후보가 없습니다 (주문가능금액 부족 또는 모두 보유 중).")
        return

    total = sum(p["예상금액"] for p in plan)
    slot = cash / max(1, len([c for c in candidates if c["종목코드"] not in owned]))

    c1, c2, c3 = st.columns(3)
    c1.metric("주문가능금액", f"{cash:,.0f}원")
    c2.metric("슬롯(종목당 배정)", f"{slot:,.0f}원")
    c3.metric("예상 총 주문액", f"{total:,.0f}원")

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


def render_volume_rank() -> None:
    st.subheader("거래량 상위 5종목")
    stale = False
    try:
        rows = get_volume_rank(top_n=5)
        if rows:
            st.session_state.last_volume_rank = rows
    except Exception:
        rows = st.session_state.last_volume_rank
        stale = bool(rows)

    if not rows:
        st.info("데이터를 불러올 수 없습니다.")
        return

    if stale:
        st.caption("⚠️ 장 마감 기준 마지막 데이터입니다.")

    df = pd.DataFrame(rows)
    styled = (
        df.style
        .format({
            "현재가": "{:,.0f}원",
            "등락률(%)": lambda x: f"{x:+.2f}%",
            "거래량": "{:,.0f}",
        })
        .map(
            lambda x: "color: #d9534f" if isinstance(x, str) and x.startswith("+") else (
                      "color: #0275d8" if isinstance(x, str) and x.startswith("-") else ""),
            subset=["등락률(%)"],
        )
    )
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
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
        st.code("".join(lines[-50:]), language=None)
    except FileNotFoundError:
        st.info("로그 파일이 없습니다. `python main.py`를 실행하면 로그가 표시됩니다.")


def render_sidebar() -> tuple[bool, int]:
    with st.sidebar:
        st.header("설정")

        settings = load_settings()
        buy_enabled = st.toggle(
            "🛒 매수 활성화",
            value=settings.get("buy_enabled", False),
            help="끄면 트레이더가 초기 매수 및 매도 후 재매수를 실행하지 않습니다. 매도는 계속 동작.",
        )
        if buy_enabled != settings.get("buy_enabled", False):
            set_setting("buy_enabled", buy_enabled)
        if buy_enabled:
            st.success("매수 ON")
        else:
            st.warning("매수 OFF")

        st.divider()
        auto_refresh = st.toggle(
            "자동 새로고침",
            value=settings.get("auto_refresh", True),
        )
        interval = st.slider(
            "새로고침 주기 (초)",
            min_value=10, max_value=600,
            value=int(settings.get("refresh_interval", 60)),
            step=10,
        )
        if auto_refresh != settings.get("auto_refresh", True):
            set_setting("auto_refresh", auto_refresh)
        if interval != settings.get("refresh_interval", 60):
            set_setting("refresh_interval", interval)
        if st.button("지금 새로고침", use_container_width=True):
            st.rerun()
    return auto_refresh, interval


# ── 메인 ──────────────────────────────────────────────────────────────────────

market_open = is_market_open()
auto_refresh, refresh_interval = render_sidebar()

render_header(market_open)
st.divider()
render_holdings(market_open)
st.divider()
render_buy_candidates()
if not market_open:
    st.divider()
    render_buy_plan_preview()
st.divider()
render_volume_rank()
st.divider()
render_trade_history()
st.divider()
render_log()

if auto_refresh:
    time.sleep(refresh_interval)
    st.rerun()
