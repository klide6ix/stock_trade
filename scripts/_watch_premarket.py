"""장전(08:30~09:00) 예상체결가 실장 관측 — 갭 신호가 실제로 쓰이는지 확인.

방향 판정의 갭 가중치는 0.50 으로 가장 크지만, 그 근거인 `inquire-asking-price-exp-ccn`
응답이 **장전 창에서 오늘 세션 값으로 롤오버되는 시점**은 아직 검증되지 않았다
(README '다음 작업 후보'). 롤오버가 09:00 이후라면 `_gap_signal()` 의 stale 판정에 항상
걸려 갭 신호가 영구 미사용되고, 판정은 나머지 3신호(실측 누적손익 -2.8%)로 떨어진다.

이 스크립트는 08:25~09:02 를 1분 간격으로 관측해 아래를 기록한다.
  - 예상체결가 / 기준가 / 예상거래량 / 장운영구분코드
  - `judge_direction()` 이 갭을 실제로 썼는지 (gap_source) 와 그때의 방향·점수
  - 09:00 이후 실제 시가와의 비교 — 08:30 판정이 시가 기준 방향과 일치했는지

조회 전용(주문 없음). 기록은 `data/premarket_watch_YYYY-MM-DD.jsonl` 에 남는다.
"""
import json
import sys
import time
from datetime import datetime, timedelta

from core.etf_universe import INDEX_PROXY
from core.kis_api import BASE_URL, _request, get_daily_ohlcv, get_expected_open_quote
from core.market_direction import judge_direction

START_AT = "08:25"
END_AT = "09:02"
INTERVAL = 60


def now_hm() -> str:
    return datetime.now().strftime("%H:%M:%S")


def sample() -> dict:
    """한 번의 관측 — 예상체결가 원본 + 방향 판정 결과."""
    row: dict = {"ts": datetime.now().isoformat()}
    try:
        exp = get_expected_open_quote(INDEX_PROXY.code)
        row["exp"] = exp
    except Exception as e:
        row["exp_error"] = str(e)

    try:
        bars = get_daily_ohlcv(INDEX_PROXY.code, days=3)
        row["latest_bar_date"] = bars[0]["date"] if bars else None
        row["prev_close"] = bars[0]["close"] if bars else None
    except Exception as e:
        row["bar_error"] = str(e)

    try:
        v = judge_direction(INDEX_PROXY)
        row["judge"] = {
            "direction": v["direction"],
            "score": v["score"],
            "gap_source": v["gap_source"],
            "gap_detail": v["gap_detail"],
            "summary": v["summary"],
        }
    except Exception as e:
        row["judge_error"] = str(e)
    return row


def describe(row: dict) -> str:
    exp = row.get("exp") or {}
    j = row.get("judge") or {}
    base, prev = exp.get("기준가", 0), row.get("prev_close") or 0
    stale = "?" if not (base and prev) else ("일치" if abs(base - prev) / prev * 100 <= 0.05 else "불일치")
    return (
        f"{row['ts'][11:19]} 예상 {exp.get('예상체결가', 0):>9,.0f} "
        f"기준가 {base:>9,.0f}(전일종가 {prev:>9,.0f} {stale}) "
        f"예상량 {exp.get('예상거래량', 0):>9,} "
        f"운영코드 {exp.get('장운영구분코드', '') or '-':>6} | "
        f"{j.get('direction', '?'):>7} {j.get('score', 0):+.3f} 갭출처={j.get('gap_source') or '미사용'}"
    )


def actual_open() -> tuple[float | None, float | None]:
    """개장 후 09:00 분봉의 시가와 종가."""
    url = f"{BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice"
    rows = _request("GET", url, "FHKST03010230", params={
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": INDEX_PROXY.code,
        "FID_INPUT_DATE_1": datetime.now().strftime("%Y%m%d"),
        "FID_INPUT_HOUR_1": "090500",
        "FID_PW_DATA_INCU_YN": "N",
        "FID_FAKE_TICK_INCU_YN": "N",
    }).get("output2", [])
    first = [r for r in rows if (r.get("stck_cntg_hour") or "")[:4] == "0900"]
    if not first:
        return None, None
    return float(first[0].get("stck_oprc") or 0), float(first[0].get("stck_prpr") or 0)


def main() -> None:
    today = datetime.now().strftime("%Y-%m-%d")
    out_path = f"data/premarket_watch_{today}.jsonl"
    start = datetime.strptime(f"{today} {START_AT}", "%Y-%m-%d %H:%M")
    end = datetime.strptime(f"{today} {END_AT}", "%Y-%m-%d %H:%M")

    wait = (start - datetime.now()).total_seconds()
    if wait > 0:
        print(f"[{now_hm()}] {START_AT} 까지 {wait / 60:.1f}분 대기 — 관측 종료 {END_AT}", flush=True)
        time.sleep(wait)

    rows: list[dict] = []
    with open(out_path, "a", encoding="utf-8") as f:
        while datetime.now() < end:
            row = sample()
            rows.append(row)
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            print(describe(row), flush=True)
            time.sleep(max(0, INTERVAL - (datetime.now().second % INTERVAL)))

    # ── 결과 정리 ──
    print("\n" + "=" * 78, flush=True)
    print("장전 관측 결과", flush=True)
    print("=" * 78, flush=True)

    used = [r for r in rows if (r.get("judge") or {}).get("gap_source")]
    first_used = used[0] if used else None
    print(f"관측 {len(rows)}회 · 갭 신호 사용 {len(used)}회")
    if first_used:
        print(f"갭 최초 사용 시각: {first_used['ts'][11:19]} (출처 {first_used['judge']['gap_source']})")
    else:
        print("갭 신호가 한 번도 사용되지 않음 — stale 판정이 장전 내내 유지됨 "
              "→ 가중치 0.50 이 영구 미사용 상태")

    op, close0900 = actual_open()
    if op:
        prev = next((r.get("prev_close") for r in reversed(rows) if r.get("prev_close")), None)
        print(f"\n실제 09:00 시가 {op:,.0f}원 (09:00봉 종가 {close0900:,.0f}원)")
        if prev:
            print(f"실제 갭 {(op - prev) / prev * 100:+.2f}% (전일종가 {prev:,.0f}원 기준)")
        for label, r in (("08:30 근처", rows[0]), ("09:00 직전", rows[-1])):
            exp = (r.get("exp") or {}).get("예상체결가") or 0
            j = r.get("judge") or {}
            err = ((exp - op) / op * 100) if (exp and op) else None
            print(f"  {label} ({r['ts'][11:19]}): 예상 {exp:,.0f}원"
                  + (f" · 실제 시가 대비 {err:+.2f}%" if err is not None else "")
                  + f" · 판정 {j.get('direction')} {j.get('score', 0):+.3f}")

    print(f"\n기록: {out_path}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
