"""원장 밖으로 빠진 단기 매매 물량을 원장에 편입한다 (운영 호스트에서 1회 실행).

    python -m scripts.adopt_short_term_position --code 102110            # 미리보기
    python -m scripts.adopt_short_term_position --code 102110 --apply    # 실제 기록

배경: 2026-09-30 TIGER 200 28주가 체결됐지만 원장에 기록되지 않아 청산 대상에서 빠졌다
(README 참조). 근본 수정(진입 의도 write-ahead)은 같은 일이 다시 생기는 것을 막지만,
이미 빠진 물량은 이 스크립트로 되돌린다.

동작
  - 잔고의 해당 종목 **전량**을 단기 매매 포지션으로 기록한다(진입가 = 증권사 평단).
  - 슬롯이 다른 종목을 들고 있으면 그 물량은 원장 밖(일반 보유)으로 나간다. 그래서
    `--drop-current` 를 명시해야만 진행한다.
  - 진입 시각을 과거로 두면 다음 거래일 개장 첫 주기에 보유기간 만료로 정상 청산된다.
  - 주문은 내지 않는다. `data/settings.json` 의 `short_term_trade` 만 바꾼다.

트레이더가 실행 중이면 원장을 동시에 쓸 수 있으므로 거부한다(`--force` 로 무시 가능).
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime

from core.kis_api import get_holdings
from core.settings import get as get_setting, set_value as set_setting
from core.short_term import drop_entry_intent, position_qty


def trader_running() -> bool:
    try:
        out = subprocess.run(["pgrep", "-f", "main.py"], capture_output=True, text=True)
        return bool(out.stdout.strip())
    except FileNotFoundError:
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--code", required=True, help="편입할 종목코드 (예: 102110)")
    ap.add_argument("--entry-at", help="진입 시각 ISO (기본: 지금). 과거면 다음 개장에 청산")
    ap.add_argument("--drop-current", action="store_true",
                    help="슬롯이 다른 종목을 들고 있어도 교체 (그 물량은 일반 보유로 나감)")
    ap.add_argument("--apply", action="store_true", help="실제로 기록 (없으면 미리보기)")
    ap.add_argument("--force", action="store_true", help="트레이더 실행 중이어도 진행")
    args = ap.parse_args()

    if trader_running() and not args.force:
        print("❌ 트레이더(main.py)가 실행 중입니다. ./stop.sh 후 다시 실행하세요.")
        return 1

    slot = get_setting("short_term_trade") or {}
    holdings = get_holdings()
    held = holdings.get(args.code)
    if not held or int(held.get("qty") or 0) <= 0:
        print(f"❌ 잔고에 {args.code} 가 없습니다.")
        return 1

    held_qty = int(held["qty"])
    avg = float(held.get("avg_price") or 0)
    cur_code, cur_qty = slot.get("code"), position_qty(slot)

    if cur_code and cur_code != args.code and cur_qty > 0 and not args.drop_current:
        print(f"❌ 슬롯이 {slot.get('name')}({cur_code}) {cur_qty}주를 들고 있습니다. "
              f"교체하면 그 물량은 일반 보유로 나갑니다 — 의도한 것이면 --drop-current 를 붙이세요.")
        return 1

    entry_at = args.entry_at or datetime.now().isoformat()
    new_slot = drop_entry_intent({
        **slot,
        "code": args.code,
        "name": held.get("name") or args.code,
        "entry_price": avg,
        "qty": held_qty,
        "invested": avg * held_qty,
        "entry_at": entry_at,
        "peak": avg,
        "pending_action": None,
        "pending_target": None,
        "selection_reason": f"원장 편입 (수동, {datetime.now():%Y-%m-%d})",
    })

    keys = ("code", "name", "qty", "entry_price", "invested", "entry_at", "peak", "auto_enabled")
    print("── 현재 원장 ──")
    print(json.dumps({k: slot.get(k) for k in keys}, ensure_ascii=False, indent=2))
    print("── 편입 후 ──")
    print(json.dumps({k: new_slot.get(k) for k in keys}, ensure_ascii=False, indent=2))
    if cur_code and cur_code != args.code and cur_qty > 0:
        print(f"⚠ {slot.get('name')}({cur_code}) {cur_qty}주는 원장에서 빠져 일반 보유가 됩니다.")

    if not args.apply:
        print("\n(미리보기 — 기록하려면 --apply)")
        return 0
    set_setting("short_term_trade", new_slot)
    print("\n✅ 기록했습니다. ./start.sh 로 트레이더를 다시 켜세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
