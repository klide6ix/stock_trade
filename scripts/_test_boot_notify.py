"""부팅 알림 검증 (네트워크 · 종료 명령은 가짜로 주입 — 실제 전송·종료 없음).

검증 대상
  1. `shutdown_blocker` — .stay_up · 가동 시간 미상 · 수동 재시작이면 끄지 않는다
  2. `build_message` — 개장일엔 종료 문구가 없고, 휴장일엔 종료 예고 또는 막힌 사유가 붙는다
  3. `main` 배선 — 휴장일 + 부팅 직후에만 종료 예약, dry-run 은 전송·종료 모두 생략,
     예약 실패 시 경고 알림, 텔레그램 설정 누락·전송 오류에도 0 으로 끝난다
"""
import sys
from datetime import datetime
from unittest.mock import MagicMock, patch

import requests

from scripts import boot_notify as bn

fails = []


def check(name, cond, detail=""):
    print(f"  {'✅' if cond else '❌'} {name}" + (f" — {detail}" if detail else ""))
    if not cond:
        fails.append(name)


NOW = datetime(2026, 10, 9, 8, 21)

print("── 1. shutdown_blocker ──")
check("부팅 직후 + 플래그 없음 → 종료", bn.shutdown_blocker(90.0, False) is None)
check("경계값(FRESH_BOOT_SEC 정각)은 부팅 직후로 본다", bn.shutdown_blocker(float(bn.FRESH_BOOT_SEC), False) is None)
check(".stay_up 이 있으면 끄지 않는다", bn.shutdown_blocker(90.0, True) == ".stay_up 파일 있음")
check("가동 시간을 모르면 끄지 않는다", bn.shutdown_blocker(None, False) == "가동 시간 확인 불가")
r = bn.shutdown_blocker(bn.FRESH_BOOT_SEC + 1.0, False)
check("부팅 직후가 아니면(수동 재시작) 끄지 않는다", r is not None and "부팅 직후 아님" in r, str(r))

print("── 2. build_message ──")
text, off = bn.build_message(NOW, True, "1.2.3.4", True, None)
check("개장일: 주소 포함 · 종료 안 함", "http://1.2.3.4:8501" in text and "🟢" in text and not off, text)
check("개장일: 휴장 문구 없음", "휴장일" not in text)
text, off = bn.build_message(NOW, True, "1.2.3.4", True, "무엇이든")
check("개장일엔 blocker 를 보지 않는다", not off and "휴장일" not in text)
text, off = bn.build_message(NOW, True, "1.2.3.4", False, None)
check("휴장일 + 막힘 없음 → 종료 예고", off and f"{bn.SHUTDOWN_DELAY_MIN}분 뒤 자동 종료" in text, text)
check("종료 예고에 취소 방법 안내", "sudo shutdown -c" in text)
text, off = bn.build_message(NOW, True, "1.2.3.4", False, ".stay_up 파일 있음")
check("휴장일 + 막힘 → 종료 안 함 · 사유 표시", not off and ".stay_up 파일 있음" in text, text)
text, off = bn.build_message(NOW, False, None, True, None)
check("기동 실패 + IP 미상 → 🔴 · 로그 안내 · IP 실패 표시",
      "🔴" in text and "startup.log" in text and "공인 IP 조회 실패" in text, text)
text, off = bn.build_message(NOW, False, "1.2.3.4", False, None)
check("기동 실패여도 휴장일이면 끈다 (트레이더 없이 켜 둘 이유 없음)", off)


print("── 3. main 배선 ──")


def run_main(*, open_day, uptime, stay_up=False, dry_run=False, shutdown_ok=True,
             env=None, post=None):
    sent, shut = [], []

    def fake_send(text):
        sent.append(text)
        return True

    def fake_shutdown():
        shut.append(True)
        return shutdown_ok

    argv = ["boot_notify"] + (["--dry-run"] if dry_run else [])
    patches = [
        patch.object(sys, "argv", argv),
        patch.object(bn, "wait_dashboard", return_value=True),
        patch.object(bn, "public_ip", return_value="1.2.3.4"),
        patch.object(bn, "is_open_day", return_value=open_day),
        patch.object(bn, "read_uptime_sec", return_value=uptime),
        patch.object(bn.os.path, "exists", side_effect=lambda p: stay_up if p == bn.STAY_UP_FILE else False),
        patch.object(bn, "log", lambda msg: None),
        patch.object(bn, "schedule_shutdown", fake_shutdown),
        patch("builtins.print", lambda *a, **k: None),
    ]
    if post is None:
        patches.append(patch.object(bn, "send_telegram", fake_send))
    else:
        patches += [patch.object(bn.requests, "post", post), patch.object(bn.time, "sleep", lambda s: None),
                    patch.dict(bn.os.environ, env or {}, clear=False)]
    for p in patches:
        p.start()
    try:
        code = bn.main()
    finally:
        for p in reversed(patches):
            p.stop()
    return code, sent, shut


code, sent, shut = run_main(open_day=True, uptime=60.0)
check("개장일: 알림 1회 · 종료 없음 · 0 종료", code == 0 and len(sent) == 1 and not shut)
code, sent, shut = run_main(open_day=False, uptime=60.0)
check("휴장일 + 부팅 직후: 알림 후 종료 예약", len(sent) == 1 and shut == [True] and "자동 종료" in sent[0])
code, sent, shut = run_main(open_day=False, uptime=3600.0)
check("휴장일 + 수동 재시작: 종료 안 함", not shut and "자동 종료 안 함" in sent[0])
code, sent, shut = run_main(open_day=False, uptime=60.0, stay_up=True)
check("휴장일 + .stay_up: 종료 안 함", not shut and ".stay_up" in sent[0])
code, sent, shut = run_main(open_day=False, uptime=60.0, dry_run=True)
check("dry-run: 전송·종료 모두 생략", code == 0 and not sent and not shut)
code, sent, shut = run_main(open_day=False, uptime=60.0, shutdown_ok=False)
check("종료 예약 실패 → 경고 알림 추가", len(sent) == 2 and "예약 실패" in sent[1], str(sent))

# 실제 send_telegram 경로 — 설정 누락 · 네트워크 오류 · API 거부
with patch.dict(bn.os.environ, {}, clear=False):
    bn.os.environ.pop("TELEGRAM_BOT_TOKEN", None)
    bn.os.environ.pop("TELEGRAM_CHAT_ID", None)
    with patch.object(bn, "log", lambda m: None), patch.object(bn.requests, "post") as p:
        check("토큰 누락 → 전송 시도 없이 False", bn.send_telegram("x") is False and not p.called)

ENV = {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "c"}
boom = MagicMock(side_effect=requests.ConnectionError("down"))
code, _, _ = run_main(open_day=True, uptime=60.0, env=ENV, post=boom)
check("네트워크 오류: 재시도 후 포기 · 0 종료", code == 0 and boom.call_count == bn.SEND_RETRIES, f"calls={boom.call_count}")

denied = MagicMock()
denied.return_value.ok = False
denied.return_value.status_code = 401
denied.return_value.content = b"{}"
denied.return_value.json.return_value = {"ok": False, "description": "Unauthorized"}
code, _, _ = run_main(open_day=True, uptime=60.0, env=ENV, post=denied)
check("API 거부(401): 재시도 후 포기 · 0 종료", code == 0 and denied.call_count == bn.SEND_RETRIES)

ok_res = MagicMock()
ok_res.return_value.ok = True
ok_res.return_value.json.return_value = {"ok": True}
with patch.dict(bn.os.environ, ENV), patch.object(bn.requests, "post", ok_res), patch.object(bn, "log", lambda m: None):
    check("정상 응답 → 1회로 성공", bn.send_telegram("x") is True and ok_res.call_count == 1)
    kwargs = ok_res.call_args.kwargs
    check("chat_id · text 를 form 으로 보낸다", kwargs["data"] == {"chat_id": "c", "text": "x"})

print("── 4. 가동 시간 · IMDS (환경 의존 없이) ──")
with patch("builtins.open", side_effect=OSError):
    check("/proc/uptime 없음 → None", bn.read_uptime_sec() is None)
with patch.object(bn.requests, "put", side_effect=requests.ConnectTimeout()):
    check("IMDS 미응답(EC2 밖) → None", bn.public_ip() is None)

print()
if fails:
    print(f"❌ 실패 {len(fails)}건: {fails}")
    sys.exit(1)
print("✅ 전부 통과")
