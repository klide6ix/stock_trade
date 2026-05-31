import json
import os
import time
import requests
from datetime import datetime, timedelta
from config import APP_KEY, APP_SECRET, ACCOUNT_NO, BASE_URL, IS_MOCK
from core.logger import log

# 계좌번호 파싱 (앞 8자리, 뒤 2자리)
_acct_parts = ACCOUNT_NO.replace("-", "")
ACCT_PREFIX = _acct_parts[:8]
ACCT_SUFFIX = _acct_parts[8:]

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA_DIR = os.path.join(_BASE_DIR, "data")
os.makedirs(_DATA_DIR, exist_ok=True)
# 모의/실전 환경별 토큰 분리 저장
TOKEN_CACHE_FILE = os.path.join(_DATA_DIR, f".kis_token_{'mock' if IS_MOCK else 'real'}.json")

_token = None
_token_expired_at = None


def _load_token_from_disk():
    """디스크 캐시에서 토큰 로드. 만료되었으면 None 반환."""
    if not os.path.exists(TOKEN_CACHE_FILE):
        return None, None
    try:
        with open(TOKEN_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        expired_at = datetime.fromisoformat(data["expired_at"])
        if datetime.now() >= expired_at:
            return None, None
        return data["token"], expired_at
    except Exception:
        return None, None


def _save_token_to_disk(token: str, expired_at: datetime) -> None:
    try:
        with open(TOKEN_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({"token": token, "expired_at": expired_at.isoformat()}, f)
        os.chmod(TOKEN_CACHE_FILE, 0o600)
    except Exception as e:
        log(f"[인증] 토큰 캐시 저장 실패: {e}")


def get_token():
    """액세스 토큰 발급 (24시간 유효, 메모리 + 디스크 캐싱).

    KIS 는 토큰 발급을 1분에 1회로 제한하므로, 재시작 시 rate limit 회피를 위해
    디스크 캐시를 우선 사용한다.
    """
    global _token, _token_expired_at

    now = datetime.now()
    if _token and _token_expired_at and now < _token_expired_at:
        return _token

    # 디스크 캐시 확인
    disk_token, disk_expired_at = _load_token_from_disk()
    if disk_token:
        _token = disk_token
        _token_expired_at = disk_expired_at
        log("[인증] 디스크 캐시에서 토큰 로드")
        return _token

    url = f"{BASE_URL}/oauth2/tokenP"
    body = {
        "grant_type": "client_credentials",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET,
    }
    res = requests.post(url, json=body)
    res.raise_for_status()
    data = res.json()

    _token = data["access_token"]
    _token_expired_at = now + timedelta(hours=23)  # 만료 시간 23시간으로 보수적 설정
    _save_token_to_disk(_token, _token_expired_at)

    log("[인증] 토큰 발급 완료")
    return _token


def _headers(tr_id):
    token = get_token()
    return {
        "content-type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET,
        "tr_id": tr_id,
    }


# KIS REST 호출 공용 설정.
_MAX_ATTEMPTS = 3       # 최초 1회 + 재시도 2회
_RETRY_BACKOFF = 1.0    # 재시도 간 대기 기준(초). attempt 회차에 비례해 증가.
_REQUEST_TIMEOUT = 10   # 응답 대기 한도(초). 무한 대기 방지.


class KisApiError(RuntimeError):
    """KIS API 호출 실패. 서버가 반환한 status·msg_cd·msg1 본문을 메시지에 포함한다."""


def _request(method: str, url: str, tr_id: str, *, params=None, json_body=None) -> dict:
    """KIS REST 호출 공용 헬퍼. 파싱된 JSON(dict)을 반환한다.

    설계 의도:
      - 일시적 5xx / 네트워크 오류는 지수 backoff 로 최대 _MAX_ATTEMPTS 회 재시도한다.
        KIS 모의투자 서버는 실전보다 불안정해 잔고·주문 API 에서 간헐적으로
        500 Internal Server Error 를 반환하므로, 재시도가 사실상 필수다.
      - 4xx 등 비일시적 오류나 재시도 소진 시에는, KIS 가 응답 본문에 담아 보내는
        msg_cd/msg1 을 폐기하지 않고 로그·예외 메시지에 그대로 노출한다.
        (requests 의 raise_for_status() 는 URL 만 보여주고 본문을 버려 원인 파악이 어렵다.)
      - **HTTP 200 이어도 본문 rt_cd != "0" 이면 논리적 실패**다 (예: 주문 거부
        "모의투자 영업일이 아닙니다", 초당 거래건수 초과 등). HTTP 상태만 보면 거부된
        주문이 '성공' 으로 처리돼 거래 이력에 유령 체결이 기록되므로, rt_cd 도 검증한다.
        초당 거래건수 초과(EGW00201)는 일시적 제한이라 backoff 후 재시도한다.
    """
    last_exc: Exception | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            res = requests.request(
                method, url,
                headers=_headers(tr_id),
                params=params,
                json=json_body,
                timeout=_REQUEST_TIMEOUT,
            )
        except requests.RequestException as e:
            # 연결 끊김·타임아웃 등 네트워크 계층 오류 — 일시적일 수 있어 재시도.
            last_exc = e
            if attempt < _MAX_ATTEMPTS:
                wait = _RETRY_BACKOFF * attempt
                log(f"[API] 네트워크 오류 ({tr_id}), {wait:.0f}s 후 재시도 {attempt}/{_MAX_ATTEMPTS - 1}: {e}")
                time.sleep(wait)
                continue
            raise KisApiError(f"[API] 네트워크 오류 ({tr_id}) {url}: {e}") from e

        # 5xx 는 서버 측 일시 장애로 보고 재시도. (마지막 회차면 아래 오류 처리로 진행)
        if res.status_code >= 500 and attempt < _MAX_ATTEMPTS:
            wait = _RETRY_BACKOFF * attempt
            log(f"[API] {res.status_code} 서버 오류 ({tr_id}), {wait:.0f}s 후 재시도 {attempt}/{_MAX_ATTEMPTS - 1}")
            time.sleep(wait)
            continue

        if not res.ok:
            body = res.text[:500]
            msg = f"[API] {res.status_code} 응답 ({tr_id}) {url}\n응답본문: {body}"
            log(msg)
            raise KisApiError(msg)

        data = res.json()

        # HTTP 200 이어도 rt_cd != "0" 이면 논리적 실패 — KIS 는 거부도 200 으로 보낸다.
        rt_cd = data.get("rt_cd")
        if rt_cd is not None and rt_cd != "0":
            msg_cd = data.get("msg_cd", "")
            msg1 = (data.get("msg1") or "").strip()
            # 초당 거래건수 초과(EGW00201)는 일시적 제한 — backoff 후 재시도.
            if msg_cd == "EGW00201" and attempt < _MAX_ATTEMPTS:
                wait = _RETRY_BACKOFF * attempt
                log(f"[API] 호출 한도 초과 ({tr_id}) {msg1} — {wait:.0f}s 후 재시도 {attempt}/{_MAX_ATTEMPTS - 1}")
                time.sleep(wait)
                continue
            msg = f"[API] 거래 실패 ({tr_id}) rt_cd={rt_cd} msg_cd={msg_cd}: {msg1}"
            log(msg)
            raise KisApiError(msg)

        return data

    # 루프는 위에서 모두 return/raise 로 빠져나가므로 정상적으로는 도달하지 않는다(방어용).
    raise KisApiError(f"[API] 재시도 모두 실패 ({tr_id}) {url}") from last_exc


def _inquire_balance():
    """잔고조회 API 호출. (output1, output2) 원본 반환"""
    url = f"{BASE_URL}/uapi/domestic-stock/v1/trading/inquire-balance"
    tr_id = "VTTC8434R" if IS_MOCK else "TTTC8434R"

    params = {
        "CANO": ACCT_PREFIX,
        "ACNT_PRDT_CD": ACCT_SUFFIX,
        "AFHR_FLPR_YN": "N",
        "OFL_YN": "",
        "INQR_DVSN": "02",
        "UNPR_DVSN": "01",
        "FUND_STTL_ICLD_YN": "N",
        "FNCG_AMT_AUTO_RDPT_YN": "N",
        "PRCS_DVSN": "01",
        "CTX_AREA_FK100": "",
        "CTX_AREA_NK100": "",
    }

    data = _request("GET", url, tr_id, params=params)
    return data.get("output1", []), data.get("output2", [{}])


def get_holdings():
    """보유 주식 목록 조회. {종목코드: {name, qty, avg_price}} 반환"""
    output1, _ = _inquire_balance()

    holdings = {}
    for item in output1:
        qty = int(item.get("hldg_qty", "0"))
        if qty <= 0:
            continue
        code = item["pdno"]
        holdings[code] = {
            "name": item["prdt_name"],
            "qty": qty,
            "avg_price": float(item.get("pchs_avg_pric", "0")),
        }
    return holdings


def get_cash_balance() -> dict:
    """계좌 잔액 요약 조회. {예수금, 총평가금액, 순자산} 반환"""
    _, output2 = _inquire_balance()
    summary = output2[0] if output2 else {}
    return {
        "예수금": float(summary.get("dnca_tot_amt", "0")),
        "주문가능금액": float(summary.get("nxdy_excc_amt", "0")),
        "총평가금액": float(summary.get("tot_evlu_amt", "0")),
        "순자산": float(summary.get("nass_amt", "0")),
    }


def get_current_price(stock_code):
    """현재가 조회"""
    url = f"{BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-price"
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": stock_code,
    }
    data = _request("GET", url, "FHKST01010100", params=params)
    return float(data["output"]["stck_prpr"])


def get_per_eps(stock_code: str) -> dict:
    """PER, EPS 조회. {per, eps} 반환. inquire-price 응답에서 추출."""
    url = f"{BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-price"
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": stock_code,
    }
    output = _request("GET", url, "FHKST01010100", params=params).get("output", {})
    return {
        "per": float(output.get("per", 0)),
        "eps": float(output.get("eps", 0)),
    }


def get_quote_snapshot(stock_code: str) -> dict:
    """현재가 + 52주 고/저 + PER/EPS/PBR 일괄 조회. inquire-price 단일 호출."""
    url = f"{BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-price"
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": stock_code,
    }
    output = _request("GET", url, "FHKST01010100", params=params).get("output", {})
    return {
        "현재가": float(output.get("stck_prpr", 0)),
        "52주최고": float(output.get("w52_hgpr", 0)),
        "52주최저": float(output.get("w52_lwpr", 0)),
        "per": float(output.get("per", 0)),
        "eps": float(output.get("eps", 0)),
        "pbr": float(output.get("pbr", 0)),
        "전일대비등락률(%)": float(output.get("prdy_ctrt", 0)),
    }


def get_daily_ohlcv(stock_code: str, days: int = 60) -> list[dict]:
    """최근 N영업일 일봉 OHLCV 시계열. 최신순 정렬 (index 0 = 가장 최근).

    한 종목당 1회 호출로 이평선·RSI·거래량 폭증 등 기술 지표 산출에 사용.
    """
    today = datetime.now()
    start = today - timedelta(days=int(days * 1.6) + 10)  # 영업일 보정 (주말·공휴일)

    url = f"{BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": stock_code,
        "FID_INPUT_DATE_1": start.strftime("%Y%m%d"),
        "FID_INPUT_DATE_2": today.strftime("%Y%m%d"),
        "FID_PERIOD_DIV_CODE": "D",
        "FID_ORG_ADJ_PRC": "0",
    }
    output = _request("GET", url, "FHKST03010100", params=params).get("output2", [])

    bars: list[dict] = []
    for bar in output:
        try:
            close = float(bar.get("stck_clpr", 0))
        except (TypeError, ValueError):
            continue
        if close == 0:
            continue
        bars.append({
            "date": bar.get("stck_bsop_date"),
            "open": float(bar.get("stck_oprc", 0) or 0),
            "high": float(bar.get("stck_hgpr", 0) or 0),
            "low": float(bar.get("stck_lwpr", 0) or 0),
            "close": close,
            "volume": int(bar.get("acml_vol", 0) or 0),
        })
    return bars[:days]


def get_weekly_price_change(stock_code: str) -> float | None:
    """최근 1주일 종가 기준 가격 변화율(%) 반환. 실패 시 None"""
    today = datetime.now()
    week_ago = today - timedelta(days=7)

    url = f"{BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-daily-price"
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": stock_code,
        "FID_INPUT_DATE_1": week_ago.strftime("%Y%m%d"),
        "FID_INPUT_DATE_2": today.strftime("%Y%m%d"),
        "FID_PERIOD_DIV_CODE": "D",
        "FID_ORG_ADJ_PRC": "0",
    }
    output = _request("GET", url, "FHKST03010100", params=params).get("output2", [])

    if len(output) < 2:
        return None

    # output2: 최신순 정렬 (index 0 = 오늘, index -1 = 1주일 전)
    latest = float(output[0].get("stck_clpr", 0))
    oldest = float(output[-1].get("stck_clpr", 0))

    if oldest == 0:
        return None

    return (latest - oldest) / oldest * 100


# KIS ranking API 의 시장 구분 코드 (`FID_INPUT_ISCD`).
# "0000": KRX 전체, "0001": KOSPI 만, "1001": KOSDAQ 만, "2001": KOSPI200 (지수 구성종목)
_MARKET_ISCD = {
    "all": "0000",
    "kospi": "0001",
    "kosdaq": "1001",
    "kospi200": "2001",
}


def get_market_cap_rank(top_n: int = 100, market: str = "all") -> list[dict]:
    """시가총액 상위 종목 조회. [{종목코드, 종목명, 현재가, 시가총액(억), 거래량}] 반환.

    Args:
        market: 시장 구분 ("all" | "kospi" | "kosdaq"). default "all" (KRX 전체).
    """
    url = f"{BASE_URL}/uapi/domestic-stock/v1/ranking/market-cap"
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_COND_SCR_DIV_CODE": "20174",
        "FID_INPUT_ISCD": _MARKET_ISCD.get(market, "0000"),
        "FID_DIV_CLS_CODE": "0",
        "FID_BLNG_CLS_CODE": "0",
        "FID_TRGT_CLS_CODE": "111111111",
        "FID_TRGT_EXLS_CLS_CODE": "000000",
        "FID_INPUT_PRICE_1": "",
        "FID_INPUT_PRICE_2": "",
        "FID_VOL_CNT": "",
        "FID_INPUT_DATE_1": "",
    }
    data = _request("GET", url, "FHPST01740000", params=params)

    result = []
    for item in data.get("output", [])[:top_n]:
        result.append({
            "종목코드": item.get("mksc_shrn_iscd", ""),
            "종목명": item.get("hts_kor_isnm", ""),
            "현재가": float(item.get("stck_prpr", 0)),
            "시가총액(억)": int(item.get("stck_avls", 0)),
            "거래량": int(item.get("acml_vol", 0)),
        })
    return result


def get_volume_rank(top_n: int = 30, market: str = "all") -> list[dict]:
    """거래량 상위 종목 조회 (당일 누적 거래량 순). 단일 호출.

    Args:
        market: 시장 구분 ("all" | "kospi" | "kosdaq"). default "all" (KRX 전체).
            KIS 거래량 ranking 은 "주식 수 거래량" 기준이라 KOSDAQ 저가 소형주가 상위를 채운다.
            KOSPI 대형주를 보고 싶으면 market="kospi" 권장.

    [{종목코드, 종목명, 현재가, 등락률(%), 거래량, 순위}] 반환 — 순위는 응답 순서(1부터).
    """
    url = f"{BASE_URL}/uapi/domestic-stock/v1/quotations/volume-rank"
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_COND_SCR_DIV_CODE": "20171",
        "FID_INPUT_ISCD": _MARKET_ISCD.get(market, "0000"),
        "FID_DIV_CLS_CODE": "0",
        "FID_BLNG_CLS_CODE": "0",
        "FID_TRGT_CLS_CODE": "111111111",
        "FID_TRGT_EXLS_CLS_CODE": "000000",
        "FID_INPUT_PRICE_1": "",
        "FID_INPUT_PRICE_2": "",
        "FID_VOL_CNT": "",
        "FID_INPUT_DATE_1": "",
    }
    data = _request("GET", url, "FHPST01710000", params=params)

    result = []
    for idx, item in enumerate(data.get("output", [])[:top_n], start=1):
        result.append({
            "순위": int(item.get("data_rank", idx) or idx),
            "종목코드": item.get("mksc_shrn_iscd", ""),
            "종목명": item.get("hts_kor_isnm", ""),
            "현재가": float(item.get("stck_prpr", 0) or 0),
            "등락률(%)": float(item.get("prdy_ctrt", 0) or 0),
            "거래량": int(item.get("acml_vol", 0) or 0),
        })
    return result


def get_fluctuation_rank(top_n: int = 30, market: str = "all") -> list[dict]:
    """일간 등락률 상위 종목 조회 (상승률 순). [{종목코드, 종목명, 현재가, 등락률(%)}] 반환.

    Args:
        market: 시장 구분 ("all" | "kospi" | "kosdaq"). default "all" (KRX 전체).
    """
    url = f"{BASE_URL}/uapi/domestic-stock/v1/ranking/fluctuation"
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_COND_SCR_DIV_CODE": "20170",
        "FID_INPUT_ISCD": _MARKET_ISCD.get(market, "0000"),
        "FID_RANK_SORT_CLS_CODE": "0",
        "FID_INPUT_CNT_1": "0",
        "FID_PRC_CLS_CODE": "1",
        "FID_INPUT_PRICE_1": "",
        "FID_INPUT_PRICE_2": "",
        "FID_VOL_CNT": "",
        "FID_TRGT_CLS_CODE": "0",
        "FID_TRGT_EXLS_CLS_CODE": "0",
        "FID_DIV_CLS_CODE": "0",
        "FID_RSFL_RATE1": "",
        "FID_RSFL_RATE2": "",
    }
    data = _request("GET", url, "FHPST01700000", params=params)

    result = []
    for item in data.get("output", [])[:top_n]:
        code = item.get("stck_shrn_iscd") or item.get("mksc_shrn_iscd", "")
        result.append({
            "종목코드": code,
            "종목명": item.get("hts_kor_isnm", ""),
            "현재가": float(item.get("stck_prpr", 0)),
            "등락률(%)": float(item.get("prdy_ctrt", 0)),
        })
    return result


def sell_market_order(stock_code, qty):
    """시장가 매도 주문"""
    url = f"{BASE_URL}/uapi/domestic-stock/v1/trading/order-cash"
    tr_id = "VTTC0801U" if IS_MOCK else "TTTC0801U"

    body = {
        "CANO": ACCT_PREFIX,
        "ACNT_PRDT_CD": ACCT_SUFFIX,
        "PDNO": stock_code,
        "ORD_DVSN": "01",   # 01 = 시장가
        "ORD_QTY": str(qty),
        "ORD_UNPR": "0",    # 시장가는 0
    }

    return _request("POST", url, tr_id, json_body=body)


def buy_market_order(stock_code, qty):
    """시장가 매수 주문"""
    url = f"{BASE_URL}/uapi/domestic-stock/v1/trading/order-cash"
    tr_id = "VTTC0802U" if IS_MOCK else "TTTC0802U"

    body = {
        "CANO": ACCT_PREFIX,
        "ACNT_PRDT_CD": ACCT_SUFFIX,
        "PDNO": stock_code,
        "ORD_DVSN": "01",   # 01 = 시장가
        "ORD_QTY": str(qty),
        "ORD_UNPR": "0",    # 시장가는 0
    }

    return _request("POST", url, tr_id, json_body=body)
