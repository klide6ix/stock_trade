import json
import os
import random
import time
import requests
from datetime import datetime, timedelta

try:
    import fcntl  # Unix 전용. cross-process throttle 의 flock 에 사용.
except ImportError:  # pragma: no cover - 비 Unix 플랫폼 방어
    fcntl = None
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

# ── Cross-process 호출 throttle ────────────────────────────────────────────────
# trader 프로세스와 Streamlit 대시보드 subprocess 가 같은 app key 의 초당 한도를
# 공유한다. in-process 캐시/재시도만으로는 두 프로세스의 호출이 합쳐져 burst 로
# 한도(EGW00201/EGW00215)를 넘기므로, data/ 의 lock 파일에 '다음 호출 허용 시각'을
# 기록하고 flock 으로 직렬화해 전체 시스템의 호출 간격을 강제한다.
#
# 초당 허용 호출 수: KIS 공식 상한은 실전 20/s · 모의 2/s 지만,
#   (1) 원장(EGW00215) 한도는 잔고·주문 API 에 더 빡빡하게 걸리고,
#   (2) 두 프로세스가 같은 키를 나눠 쓰므로
# 보수적으로 잡는다. 스캔(후보 탐색)이 다소 느려지는 대신 한도 초과를 사전 차단한다.
THROTTLE_FILE = os.path.join(_DATA_DIR, f".kis_throttle_{'mock' if IS_MOCK else 'real'}.lock")
_MAX_CALLS_PER_SEC = 2 if IS_MOCK else 10
_MIN_INTERVAL = 1.0 / _MAX_CALLS_PER_SEC

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

# 초당 거래건수 초과 코드. KIS 는 두 계층에서 별도로 한도를 건다.
#   EGW00201 = API 게이트웨이(EGW) 레벨 초당 호출 초과.
#   EGW00215 = 원장(브로커리지 백엔드) 레벨 초당 '거래'건수 초과 — 잔고·주문 등
#              계좌 API 에만 걸리는 더 빡빡한 제한. HTTP 200 뿐 아니라 500 본문으로도 온다.
# 둘 다 일시적 제한이라 backoff 후 재시도 대상이다.
_RATE_LIMIT_CODES = {"EGW00201", "EGW00215"}
_RATE_LIMIT_BACKOFF = 1.0   # 한도 초과는 '초당' 제한이라 1초 이상 + jitter 로 대기해 다음 창으로 넘긴다.


class KisApiError(RuntimeError):
    """KIS API 호출 실패. 서버가 반환한 status·msg_cd·msg1 본문을 메시지에 포함한다."""


def _throttle() -> None:
    """모든 KIS REST 호출 직전에 호출. 프로세스 경계를 넘어 최소 호출 간격을 보장한다.

    동작('슬롯 예약' 패턴):
      1. lock 파일에 flock(LOCK_EX) — 동시에 한 호출자만 진입.
      2. 파일에 저장된 '다음 허용 시각'(prev)을 읽는다.
      3. 내 슬롯 = max(now, prev). 다음 호출자를 위해 (슬롯 + _MIN_INTERVAL)을 기록.
      4. flock 해제 후, 슬롯 시각까지 sleep (lock 을 쥔 채 자지 않아 다른 호출자를
         불필요하게 막지 않는다 — 예약은 이미 파일에 반영됨).

    두 프로세스(trader·대시보드)가 같은 머신의 wall clock(time.time())을 공유하므로
    프로세스 간에도 슬롯이 단조 증가하며 간격이 유지된다. 가용성 우선 — 파일/flock 에
    문제가 생기면 throttle 없이 호출을 진행한다(거래를 막지 않음)."""
    if fcntl is None:
        return
    try:
        fd = os.open(THROTTLE_FILE, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError:
        return
    f = os.fdopen(fd, "r+")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            content = f.read().strip()
            prev = float(content) if content else 0.0
        except (ValueError, OSError):
            prev = 0.0
        now = time.time()
        slot = max(now, prev)
        f.seek(0)
        f.truncate()
        f.write(f"{slot + _MIN_INTERVAL:.6f}")
        f.flush()
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        f.close()

    wait = slot - now
    if wait > 0:
        time.sleep(wait)


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
      - 초당 거래건수 초과(_RATE_LIMIT_CODES)는 HTTP 200·4xx·5xx 어느 상태로 오든
        일시적 제한으로 보고, 다음 1초 창으로 넘기기 위해 길게(+jitter) backoff 후 재시도한다.
    """
    last_exc: Exception | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            _throttle()  # 프로세스 경계 넘어 초당 한도 준수 (재시도 호출도 포함).
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

        # 본문(JSON)을 먼저 파싱한다. KIS 는 한도 초과를 HTTP 500 본문으로도 보내므로,
        # 상태 코드만 보지 말고 msg_cd 를 추출해 '한도 초과'인지부터 가린다.
        # (5xx 가 HTML 등 비 JSON 이면 ValueError → body_json=None 으로 두고 아래 5xx 분기로 넘긴다.)
        try:
            body_json = res.json()
        except ValueError:
            body_json = None
        msg_cd = body_json.get("msg_cd") if body_json else None

        # 초당 거래건수 초과 — 상태 코드와 무관하게 backoff 후 재시도해 다음 창으로 넘긴다.
        if msg_cd in _RATE_LIMIT_CODES and attempt < _MAX_ATTEMPTS:
            wait = _RATE_LIMIT_BACKOFF * attempt + random.uniform(0, 0.5)
            msg1 = (body_json.get("msg1") or "").strip()
            log(f"[API] 초당 한도 초과 ({tr_id}/{msg_cd}) {msg1} — {wait:.1f}s 후 재시도 {attempt}/{_MAX_ATTEMPTS - 1}")
            time.sleep(wait)
            continue

        # 5xx (한도 외) 는 서버 측 일시 장애로 보고 재시도. (마지막 회차면 아래 오류 처리로 진행)
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

        data = body_json if body_json is not None else res.json()

        # HTTP 200 이어도 rt_cd != "0" 이면 논리적 실패 — KIS 는 거부도 200 으로 보낸다.
        # (한도 코드는 위에서 이미 재시도 처리됨 — 여기 도달하면 재시도 소진 또는 비한도 실패다.)
        rt_cd = data.get("rt_cd")
        if rt_cd is not None and rt_cd != "0":
            msg_cd = data.get("msg_cd", "")
            msg1 = (data.get("msg1") or "").strip()
            msg = f"[API] 거래 실패 ({tr_id}) rt_cd={rt_cd} msg_cd={msg_cd}: {msg1}"
            log(msg)
            raise KisApiError(msg)

        return data

    # 루프는 위에서 모두 return/raise 로 빠져나가므로 정상적으로는 도달하지 않는다(방어용).
    raise KisApiError(f"[API] 재시도 모두 실패 ({tr_id}) {url}") from last_exc


# 잔고조회(inquire-balance) 단기 캐시.
# 한 사이클에서 get_holdings()(매도 점검·단타) 와 get_cash_balance() 가 같은 원장 API 를
# 여러 번 호출하는데, 이게 EGW00215(원장 초당 한도)의 직접적 원인이다. 짧은 TTL 로
# 사이클 내 중복 호출을 1회로 합쳐 원장 부하를 줄인다. TTL(3초) << CHECK_INTERVAL(60초)
# 이라 의사결정 granularity 에는 영향이 없고, 자기 주문 직후엔 아래에서 캐시를 무효화한다.
_BALANCE_CACHE_TTL = 3.0
_balance_cache: tuple[list, list] | None = None
_balance_cache_at = 0.0


def _invalidate_balance_cache() -> None:
    """잔고 캐시 무효화. 자기 매수·매도 주문 직후 호출해 다음 조회가 최신 원장을 읽게 한다."""
    global _balance_cache
    _balance_cache = None


def _inquire_balance(*, use_cache: bool = True):
    """잔고조회 API 호출. (output1, output2) 원본 반환. 기본적으로 단기 캐시를 사용한다."""
    global _balance_cache, _balance_cache_at
    now = time.monotonic()
    if use_cache and _balance_cache is not None and (now - _balance_cache_at) < _BALANCE_CACHE_TTL:
        return _balance_cache

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
    result = (data.get("output1", []), data.get("output2", [{}]))
    _balance_cache = result
    _balance_cache_at = now
    return result


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


def get_orderbook(stock_code: str, depth: int = 5) -> dict:
    """호가창 조회 — 매도/매수 호가와 잔량 (`inquire-asking-price-exp-ccn`).

    지정가 주문의 단가를 여기서 그대로 가져오면 **호가 단위를 추측할 필요가 없다**.
    한국 시장은 종목·가격대마다 호가 단위가 달라(실측: 인버스 ETF 1원, KODEX 200 5원)
    현재가에 임의 버퍼를 더하면 유효하지 않은 단가가 나올 수 있는데, 거래소가 준 호가는
    정의상 항상 유효하다.

    Returns:
        {"매도호가": [(가격, 잔량), ...], "매수호가": [(가격, 잔량), ...]} — 1호가부터 순서대로.
    """
    url = f"{BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn"
    data = _request("GET", url, "FHKST01010200", params={
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": stock_code,
    })
    out = data.get("output1") or {}

    def _levels(price_key: str, qty_key: str) -> list[tuple[float, int]]:
        levels = []
        for i in range(1, min(depth, 10) + 1):
            try:
                price = float(out.get(f"{price_key}{i}", 0) or 0)
                qty = int(float(out.get(f"{qty_key}{i}", 0) or 0))
            except (TypeError, ValueError):
                continue
            if price > 0:
                levels.append((price, qty))
        return levels

    return {
        "매도호가": _levels("askp", "askp_rsqn"),
        "매수호가": _levels("bidp", "bidp_rsqn"),
    }


def get_orderable_cash(
    stock_code: str = "005930",
    price: float = 0,
    market_order: bool = True,
) -> dict:
    """**실제** 주문 가능 현금과 최대 매수 수량 (매수가능조회, `inquire-psbl-order`).

    잔고 API 의 `nxdy_excc_amt`(익일정산금액)를 주문가능금액으로 쓰면 두 군데가 어긋난다.

    1. **미결제 매수 미반영** — 매수 대금은 D+2 결제라 오늘 체결분이 D+1 필드에서 아직
       빠지지 않는다. 이미 쓴 돈을 또 쓸 수 있다고 오판한다(실측: 잔고 API 3,387,580원
       vs 실제 주문가능현금 478,180원 — 차액이 정확히 당일 매수 체결액).
    2. **시장가 증거금** — 시장가 매수는 체결가가 미확정이라 KIS 가 **상한가(현재가 +30%)**
       기준으로 주문금액을 계산한다. 현재가로 나눈 수량은 주문금액이 가용 현금의 약 77%
       를 넘는 순간 `APBK0952 주문가능금액을 초과 했습니다` 로 거부된다.

    이 API 는 둘 다 반영한 계좌의 실제 여력을 돌려주므로, 매수 수량은 반드시
    `최대매수수량` 으로 상한을 씌워야 한다.

    Args:
        stock_code: 조회 기준 종목코드. `주문가능현금` 은 계좌 단위 값이라 종목과 무관하지만,
            `최대매수수량` 은 이 종목의 계산단가 기준이므로 실제 매수할 종목을 넘겨야 한다.
        price: 지정가 주문 시 주문 단가. 시장가면 무시된다.
        market_order: True 면 시장가(ORD_DVSN=01) 기준으로 계산 — 계산단가에 상한가가 잡힌다.

    Returns:
        {주문가능현금, 최대매수금액, 최대매수수량, 계산단가}
    """
    url = f"{BASE_URL}/uapi/domestic-stock/v1/trading/inquire-psbl-order"
    tr_id = "VTTC8908R" if IS_MOCK else "TTTC8908R"
    params = {
        "CANO": ACCT_PREFIX,
        "ACNT_PRDT_CD": ACCT_SUFFIX,
        "PDNO": stock_code,
        "ORD_UNPR": "0" if market_order else str(int(price or 0)),
        "ORD_DVSN": "01" if market_order else "00",
        "CMA_EVLU_AMT_ICLD_YN": "N",
        "OVRS_ICLD_YN": "N",
    }
    data = _request("GET", url, tr_id, params=params)
    out = data.get("output") or {}

    def _f(key: str) -> float:
        try:
            return float(out.get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0.0

    return {
        "주문가능현금": _f("ord_psbl_cash"),
        # 미수 없이 살 수 있는 금액·수량 (신용/미수 미사용 계좌 기준 실질 한도)
        "최대매수금액": _f("nrcvb_buy_amt"),
        "최대매수수량": int(_f("nrcvb_buy_qty")),
        "계산단가": _f("psbl_qty_calc_unpr"),
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


def get_roe(stock_code: str) -> float | None:
    """최근 결산 ROE(자기자본이익률, %) 반환. 실패/데이터 없음 시 None.

    KIS 국내주식 재무비율 API(`finance/financial-ratio`, tr_id `FHKST66430300`)의
    `roe_val` 을 사용한다. `FID_DIV_CLS_CODE="0"`(연간) 으로 조회해 응답 리스트의
    첫 항목(가장 최근 결산)을 취한다.

    ROE 를 쓰는 이유: PER=주가/EPS 라 PER 와 EPS 를 함께 비교하면 사실상 같은
    축(주가 대비 이익)을 중복 평가하게 된다. ROE 는 '자본을 얼마나 효율적으로
    이익으로 전환했나' 라는 독립적 수익성 지표라, PER(밸류에이션)·주간등락률(모멘텀)과
    직교하는 신호를 더한다.
    """
    url = f"{BASE_URL}/uapi/domestic-stock/v1/finance/financial-ratio"
    params = {
        "FID_DIV_CLS_CODE": "0",            # 0=연간, 1=분기
        "fid_cond_mrkt_div_code": "J",
        "fid_input_iscd": stock_code,
    }
    try:
        output = _request("GET", url, "FHKST66430300", params=params).get("output", [])
    except Exception as e:
        log(f"[재무비율] ROE 조회 실패 ({stock_code}): {e}")
        return None
    if not output:
        return None
    raw = output[0].get("roe_val")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


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
        "시가": float(output.get("stck_oprc", 0) or 0),
        "고가": float(output.get("stck_hgpr", 0) or 0),
        "저가": float(output.get("stck_lwpr", 0) or 0),
        "52주최고": float(output.get("w52_hgpr", 0)),
        "52주최저": float(output.get("w52_lwpr", 0)),
        "per": float(output.get("per", 0)),
        "eps": float(output.get("eps", 0)),
        "pbr": float(output.get("pbr", 0)),
        "전일대비등락률(%)": float(output.get("prdy_ctrt", 0)),
    }


def get_expected_open_quote(stock_code: str) -> dict:
    """장 시작 전(08:30~09:00) 예상체결 정보 조회. `inquire-asking-price-exp-ccn` 단일 호출.

    개장 전에는 실시간 체결가가 없고 `inquire-price` 는 전일 종가를 그대로 주므로,
    '오늘 시장이 위로 열릴지 아래로 열릴지' 를 판단하려면 동시호가 예상체결가를 봐야 한다.

    **주의 — stale 응답**: 이 API 는 장 시간 외에도 직전 세션의 잔존값을 그대로 반환한다
    (실측: 일요일 호출 시 금요일 장 데이터가 그대로 나오고, `기준가` 는 목요일 종가였다).
    따라서 호출부는 반드시 `기준가` 가 '오늘 세션 기준의 전일 종가' 와 일치하는지 대조해
    stale 여부를 판정해야 한다. → `core/market_direction.py::_gap_signal` 참고.

    Returns:
        {예상체결가, 예상등락률(%), 예상거래량, 기준가, 현재가, 장운영구분코드}
    """
    url = f"{BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn"
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": stock_code,
    }
    output = _request("GET", url, "FHKST01010200", params=params).get("output2", {})

    def _f(key: str) -> float:
        try:
            return float(output.get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0.0

    return {
        "예상체결가": _f("antc_cnpr"),
        "예상등락률(%)": _f("antc_cntg_prdy_ctrt"),
        "예상거래량": int(_f("antc_vol")),
        "기준가": _f("stck_sdpr"),          # 오늘 세션의 전일 종가 — stale 판정용
        "현재가": _f("stck_prpr"),
        "장운영구분코드": output.get("antc_mkop_cls_code", ""),
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


def get_order_execution(
    order_no: str,
    stock_code: str,
    side: str,
    date: datetime | None = None,
) -> dict | None:
    """주문번호로 **실제 체결 결과**를 조회. 체결 내역이 없으면 None.

    시장가 주문은 주문 시점 현재가와 체결가가 호가 스프레드만큼 어긋난다(ETF 1,125원짜리
    2,600주면 1틱 5원 차이가 1만원 이상). 손익을 현재가 기준으로 계산하면 이 오차가 계속
    누적되므로, 체결 후 원장에는 이 함수가 돌려주는 실제 체결가·체결금액을 기록한다.

    `inquire-daily-ccld`(주식일별주문체결조회) 를 오늘·해당 종목·해당 매매구분으로 좁혀
    조회한 뒤 `odno`(주문번호) 가 일치하는 행을 찾는다.

    제비용(수수료·세금) 주의: 응답의 `output2.prsm_tlex_smtl`(추정 제비용 합계)은
    **ODNO 필터를 무시하고 조회 구간 전체를 합산**한다(실측 확인). 따라서 조회 결과가
    우리 주문 1건뿐일 때만 그 값을 이 주문의 비용으로 인정하고(`제비용신뢰=True`),
    같은 종목을 그날 여러 번 거래했다면 귀속이 불가능하므로 0·False 로 돌려준다.

    Args:
        order_no: 주문 응답의 `ODNO`.
        stock_code: 종목코드 (조회 범위 축소용).
        side: "buy" | "sell".
        date: 주문일 (기본 오늘).

    Returns:
        {주문번호, 체결수량, 체결평균가, 총체결금액, 미체결수량, 추정제비용, 제비용신뢰}
        또는 None (아직 체결 미반영·조회 실패).
    """
    day = (date or datetime.now()).strftime("%Y%m%d")
    url = f"{BASE_URL}/uapi/domestic-stock/v1/trading/inquire-daily-ccld"
    tr_id = "VTTC8001R" if IS_MOCK else "TTTC8001R"
    params = {
        "CANO": ACCT_PREFIX,
        "ACNT_PRDT_CD": ACCT_SUFFIX,
        "INQR_STRT_DT": day,
        "INQR_END_DT": day,
        "SLL_BUY_DVSN_CD": "01" if side == "sell" else "02",
        "INQR_DVSN": "00",          # 역순 (최근 주문부터)
        "PDNO": stock_code,
        "CCLD_DVSN": "01",          # 체결된 건만
        "ORD_GNO_BRNO": "",
        "ODNO": str(order_no or ""),
        "INQR_DVSN_3": "00",
        "INQR_DVSN_1": "",
        "CTX_AREA_FK100": "",
        "CTX_AREA_NK100": "",
    }
    try:
        data = _request("GET", url, tr_id, params=params)
    except Exception as e:
        log(f"[체결조회] 실패 ({stock_code} {side} {order_no}): {e}")
        return None

    rows = data.get("output1", []) or []
    row = next((r for r in rows if str(r.get("odno", "")).lstrip("0") == str(order_no).lstrip("0")), None)
    if row is None:
        return None

    def _f(src: dict, key: str) -> float:
        try:
            return float(src.get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0.0

    filled_qty = int(_f(row, "tot_ccld_qty"))
    if filled_qty <= 0:
        return None

    summary = data.get("output2") or {}
    # 조회 결과가 우리 주문 1건뿐일 때만 제비용을 이 주문에 귀속시킨다.
    fee_trusted = len(rows) == 1
    fee = _f(summary, "prsm_tlex_smtl") if fee_trusted else 0.0

    return {
        "주문번호": str(row.get("odno", "")),
        "체결수량": filled_qty,
        "체결평균가": _f(row, "avg_prvs"),
        "총체결금액": _f(row, "tot_ccld_amt"),
        "미체결수량": int(_f(row, "rmn_qty")),
        "추정제비용": fee,
        "제비용신뢰": fee_trusted,
    }


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

    result = _request("POST", url, tr_id, json_body=body)
    _invalidate_balance_cache()  # 보유·예수금이 바뀌므로 다음 조회는 캐시 우회.
    return result


def buy_limit_order(stock_code: str, qty: int, price: float) -> dict:
    """지정가 매수 주문.

    시장가 대비 두 가지 이점이 있다.
      1. **증거금** — 시장가는 체결가 미확정이라 KIS 가 상한가(+30%) 기준으로 주문금액을
         검증하지만, 지정가는 주문 단가 그대로 계산한다. 같은 현금으로 약 30% 더 살 수 있다.
      2. **체결가 확정** — 슬리피지가 없어 진입가가 예측 가능하다.

    대신 미체결 위험이 있으므로, 단가는 호가창의 매도호가(즉시 체결 가능한 가격)에서 고르고
    체결 확인 후 잔량은 취소하는 흐름과 함께 써야 한다.
    """
    url = f"{BASE_URL}/uapi/domestic-stock/v1/trading/order-cash"
    tr_id = "VTTC0802U" if IS_MOCK else "TTTC0802U"

    body = {
        "CANO": ACCT_PREFIX,
        "ACNT_PRDT_CD": ACCT_SUFFIX,
        "PDNO": stock_code,
        "ORD_DVSN": "00",   # 00 = 지정가
        "ORD_QTY": str(int(qty)),
        "ORD_UNPR": str(int(price)),
    }

    result = _request("POST", url, tr_id, json_body=body)
    _invalidate_balance_cache()
    return result


def cancel_order(order_no: str, org_no: str, qty: int = 0, all_remaining: bool = True) -> dict:
    """미체결 주문 취소 (`order-rvsecncl`, 정정취소주문).

    지정가 주문이 부분 체결로 남으면 잔량이 계속 살아 있어 (1) 현금이 묶이고 (2) 나중에
    체결되면 원장에 없는 유령 포지션이 생긴다. 진입 확인 후 잔량은 반드시 취소한다.

    Args:
        order_no: 원주문번호 (`ODNO`).
        org_no: 주문 응답의 `KRX_FWDG_ORD_ORGNO` (한국거래소전송주문조직번호).
        qty: 취소 수량. `all_remaining=True` 면 무시되고 잔량 전부 취소된다.
        all_remaining: 잔량 전부 취소 여부.
    """
    url = f"{BASE_URL}/uapi/domestic-stock/v1/trading/order-rvsecncl"
    tr_id = "VTTC0803U" if IS_MOCK else "TTTC0803U"

    body = {
        "CANO": ACCT_PREFIX,
        "ACNT_PRDT_CD": ACCT_SUFFIX,
        "KRX_FWDG_ORD_ORGNO": str(org_no or ""),
        "ORGN_ODNO": str(order_no),
        "ORD_DVSN": "00",
        "RVSE_CNCL_DVSN_CD": "02",              # 02 = 취소
        "ORD_QTY": "0" if all_remaining else str(int(qty)),
        "ORD_UNPR": "0",
        "QTY_ALL_ORD_YN": "Y" if all_remaining else "N",
    }

    result = _request("POST", url, tr_id, json_body=body)
    _invalidate_balance_cache()
    return result


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

    result = _request("POST", url, tr_id, json_body=body)
    _invalidate_balance_cache()  # 보유·예수금이 바뀌므로 다음 조회는 캐시 우회.
    return result
