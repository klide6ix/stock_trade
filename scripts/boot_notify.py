"""부팅 알림 — EC2 가 켜질 때마다 바뀌는 공인 IP 로 대시보드 주소를 이메일(SNS)·텔레그램으로 보낸다.

운영 서버는 평일 08:20 에 켜지고 15:40 에 꺼진다(EventBridge Scheduler, `deploy/README.md`).
Elastic IP 는 꺼져 있는 동안에도 과금되므로 쓰지 않는다 — 그래서 부팅마다 공인 IP 가 바뀌고,
대시보드가 실제로 응답하는 것을 확인한 뒤 새 주소를 보낸다. 08:25 까지 알림이 없으면 기동
실패라는 뜻이므로 heartbeat 역할도 겸한다.

휴장일에 켜졌으면 같은 알림에 종료 예고를 붙이고 `SHUTDOWN_DELAY_MIN` 분 뒤 스스로 끈다.
스케줄러는 평일 cron 뿐이라 KRX 휴장일을 모른다. 판별은 트레이더와 같은 `market_calendar`
를 쓰고, 조회에 실패하면 '평일 = 개장' 이므로 이 경로로 거래일을 놓치는 일은 없다. EC2 의
기본 설정(instance-initiated shutdown = stop)에서 OS 종료는 Stop 이지 Terminate 가 아니다.

자동 종료를 하지 않는 경우
  - 부팅 직후(가동 `FRESH_BOOT_SEC` 이내)가 아니다 — `systemctl restart` 같은 수동 재시작
  - 저장소 루트에 `.stay_up` 파일이 있다 — 휴일 점검·배포용 (`touch .stay_up`, 끝나면 삭제)
  - 예고 시간 안에 `sudo shutdown -c` 로 취소했다

    .venv/bin/python -m scripts.boot_notify             # systemd ExecStartPost 가 실행
    .venv/bin/python -m scripts.boot_notify --dry-run   # 보내지도 끄지도 않고 메시지만 출력

알림 채널 (`.env` 에 설정된 것만, 둘 다 있으면 둘 다 보낸다)
  - `NOTIFY_SNS_TOPIC_ARN` — Amazon SNS topic 으로 publish, 구독한 이메일로 온다. 인스턴스 역할
    자격 증명(IMDS)을 쓰므로 서버에 비밀값이 없다. AL2023 기본 탑재 AWS CLI 로 보내 boto3 의존성을
    늘리지 않는다. 메일 제목에 주소를 넣어 알림 미리보기만으로 IP 가 보이게 한다.
  - `TELEGRAM_BOT_TOKEN` · `TELEGRAM_CHAT_ID` — 텔레그램 봇.

이 스크립트는 어떤 경우에도 0 으로 끝난다 — 알림 실패가 systemd 서비스 실패로 번져 트레이더까지
내려가면 안 된다.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import time
from datetime import datetime

import requests

import config  # noqa: F401 — .env 로딩(load_dotenv)
from core.logger import log
from core.market_calendar import is_open_day

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STAY_UP_FILE = os.path.join(BASE, ".stay_up")

DASHBOARD_PORT = 8501
HEALTH_URL = f"http://localhost:{DASHBOARD_PORT}/_stcore/health"
HEALTH_WAIT_SEC = 120
# 휴장일 종료 예고 — 주말에 점검하려고 직접 켰을 때 취소할 여유.
SHUTDOWN_DELAY_MIN = 5
# 이보다 오래 떠 있었으면 부팅이 아니라 서비스 재시작으로 본다.
FRESH_BOOT_SEC = 600

IMDS = "http://169.254.169.254/latest"
TELEGRAM_API = "https://api.telegram.org"
SEND_RETRIES = 3
SNS_TOPIC_ENV = "NOTIFY_SNS_TOPIC_ARN"
# SNS 제목 제약 — ASCII · 줄바꿈 없음 · 100자 미만. 어기면 publish 자체가 거부된다.
SNS_SUBJECT_MAX = 99


def public_ip() -> str | None:
    """IMDSv2 로 이 인스턴스의 공인 IPv4 를 읽는다. EC2 밖이거나 공인 IP 가 없으면 None."""
    try:
        token = requests.put(
            f"{IMDS}/api/token",
            headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"},
            timeout=3,
        ).text
        res = requests.get(
            f"{IMDS}/meta-data/public-ipv4",
            headers={"X-aws-ec2-metadata-token": token},
            timeout=3,
        )
    except requests.RequestException:
        return None
    return res.text.strip() if res.ok and res.text.strip() else None


def wait_dashboard(timeout_sec: int = HEALTH_WAIT_SEC) -> bool:
    """Streamlit health 가 'ok' 를 줄 때까지 기다린다. 프로세스가 떴다고 화면이 열리는 건 아니다."""
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        try:
            if requests.get(HEALTH_URL, timeout=2).text.strip() == "ok":
                return True
        except requests.RequestException:
            pass
        time.sleep(2)
    return False


def read_uptime_sec() -> float | None:
    """OS 가동 시간(초). /proc 가 없는 환경(macOS 등)이면 None."""
    try:
        with open("/proc/uptime", "r", encoding="utf-8") as f:
            return float(f.read().split()[0])
    except (OSError, ValueError, IndexError):
        return None


def shutdown_blocker(uptime_sec: float | None, stay_up: bool) -> str | None:
    """휴장일 자동 종료를 막는 사유. None 이면 종료한다.

    모르면 끄지 않는다 — 잘못 꺼지는 쪽(점검 중 서버가 내려감)이 잘못 켜져 있는 쪽
    (몇백 원)보다 비싸다.
    """
    if stay_up:
        return ".stay_up 파일 있음"
    if uptime_sec is None:
        return "가동 시간 확인 불가"
    if uptime_sec > FRESH_BOOT_SEC:
        return f"부팅 직후 아님 — 가동 {uptime_sec / 60:.0f}분"
    return None


def build_message(now: datetime, started: bool, ip: str | None,
                  open_day: bool, blocker: str | None) -> tuple[str, bool]:
    """(알림 본문, 종료 여부). 휴장일이 아니면 blocker 는 보지 않는다."""
    url = f"http://{ip}:{DASHBOARD_PORT}" if ip else "공인 IP 조회 실패"
    if started:
        lines = [f"🟢 트레이더 기동 {now:%m-%d %H:%M}", url]
    else:
        lines = [
            f"🔴 트레이더 기동 실패 {now:%m-%d %H:%M} — {HEALTH_WAIT_SEC}초 동안 대시보드 응답 없음",
            url,
            "logs/startup.log 확인 필요",
        ]
    if open_day:
        return "\n".join(lines), False
    if blocker:
        lines.append(f"휴장일 — 자동 종료 안 함 ({blocker})")
        return "\n".join(lines), False
    lines.append(f"휴장일 — {SHUTDOWN_DELAY_MIN}분 뒤 자동 종료 (취소: sudo shutdown -c)")
    return "\n".join(lines), True


def build_subject(now: datetime, started: bool, ip: str | None, shutdown: bool) -> str:
    """메일 제목 — 알림 미리보기만 보고도 주소와 상태를 알 수 있게. SNS 제약상 ASCII 만 쓴다."""
    state = "up" if started else "FAILED"
    where = f"http://{ip}:{DASHBOARD_PORT}" if ip else "IP unknown"
    subject = f"StockTrader {state} {now:%m-%d %H:%M} {where}"
    if shutdown:
        subject += f" (holiday, off in {SHUTDOWN_DELAY_MIN}m)"
    return subject[:SNS_SUBJECT_MAX]


def send_sns(subject: str, text: str) -> bool:
    """SNS topic 으로 publish. 리전은 topic ARN 에서 읽는다(arn:aws:sns:<region>:<account>:<name>)."""
    topic = os.getenv(SNS_TOPIC_ENV)
    if not topic:
        return False
    parts = topic.split(":")
    if len(parts) != 6 or parts[2] != "sns":
        log(f"[부팅알림] {SNS_TOPIC_ENV} 형식이 SNS topic ARN 이 아닙니다: {topic}")
        return False
    try:
        res = subprocess.run(
            ["aws", "sns", "publish", "--region", parts[3], "--topic-arn", topic,
             "--subject", subject, "--message", text, "--query", "MessageId", "--output", "text"],
            capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        log(f"[부팅알림] SNS 전송 실패: {type(e).__name__}")
        return False
    if res.returncode != 0:
        err = res.stderr.strip().splitlines()
        log(f"[부팅알림] SNS 전송 실패 (exit {res.returncode}): {err[-1] if err else ''}")
        return False
    return True


def configured_channels() -> list[str]:
    channels = []
    if os.getenv(SNS_TOPIC_ENV):
        channels.append("sns")
    if os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"):
        channels.append("telegram")
    return channels


def notify(subject: str, text: str) -> bool:
    """설정된 모든 채널로 보낸다(한 채널이 실패해도 나머지는 시도). 하나라도 성공하면 True."""
    channels = configured_channels()
    if not channels:
        log(f"[부팅알림] 알림 채널이 없습니다 — .env 에 {SNS_TOPIC_ENV} 또는 "
            "TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID 를 넣어 주세요")
        return False
    results = []
    for ch in channels:
        results.append(send_sns(subject, text) if ch == "sns" else send_telegram(text))
    return any(results)


def send_telegram(text: str) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        log("[부팅알림] .env 에 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 가 없어 알림을 보내지 않았습니다")
        return False
    for attempt in range(1, SEND_RETRIES + 1):
        try:
            res = requests.post(
                f"{TELEGRAM_API}/bot{token}/sendMessage",
                data={"chat_id": chat_id, "text": text},
                timeout=10,
            )
            if res.ok and res.json().get("ok"):
                return True
            # 토큰이 URL 에 들어가므로 예외 문자열 대신 상태 코드·설명만 남긴다.
            detail = f"HTTP {res.status_code} {res.json().get('description', '') if res.content else ''}"
        except (requests.RequestException, ValueError) as e:
            detail = type(e).__name__
        log(f"[부팅알림] 텔레그램 전송 실패 {attempt}/{SEND_RETRIES}: {detail}")
        time.sleep(3)
    return False


def schedule_shutdown() -> bool:
    """`SHUTDOWN_DELAY_MIN` 분 뒤 종료를 예약한다. ec2-user 는 기본으로 NOPASSWD sudo 다.

    `-n` 이라 비밀번호가 필요한 환경이면 기다리지 않고 바로 실패한다.
    """
    res = subprocess.run(
        ["sudo", "-n", "shutdown", "-h", f"+{SHUTDOWN_DELAY_MIN}"],
        capture_output=True, text=True,
    )
    if res.returncode != 0:
        log(f"[부팅알림] 자동 종료 예약 실패 (exit {res.returncode}): {res.stderr.strip()}")
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="보내지도 끄지도 않고 메시지만 출력")
    args = parser.parse_args()

    # health 를 먼저 기다린다 — 그 사이 트레이더가 휴장일 달력을 받아 파일에 남기므로,
    # 아래 is_open_day 는 대개 KIS 를 다시 부르지 않고 파일을 읽는다(1일 1회 권장).
    started = wait_dashboard()
    ip = public_ip()
    now = datetime.now()
    open_day = is_open_day(now)
    blocker = None if open_day else shutdown_blocker(read_uptime_sec(), os.path.exists(STAY_UP_FILE))
    text, shutdown = build_message(now, started, ip, open_day, blocker)
    subject = build_subject(now, started, ip, shutdown)

    log(f"[부팅알림] {text.replace(chr(10), ' | ')}")
    if args.dry_run:
        print(f"\n--- dry-run: 전송·종료 생략 (종료 대상={shutdown}) ---\n제목: {subject}\n{text}")
        return 0

    notify(subject, text)
    if shutdown and not schedule_shutdown():
        notify("StockTrader holiday shutdown FAILED - server still running",
               "⚠️ 휴장일 자동 종료 예약 실패 — 서버가 계속 켜져 있습니다 (로그 확인)")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:  # 알림 실패로 서비스가 실패 처리되지 않게
        log(f"[부팅알림] 예외로 중단: {type(e).__name__}: {e}")
        raise SystemExit(0)
