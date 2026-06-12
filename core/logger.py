import glob
import os
import re
from datetime import datetime

_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
os.makedirs(_LOG_DIR, exist_ok=True)

# 일별 로그 파일명 패턴(`trader-YYYY-MM-DD.log`).
# log() 가 매 호출 시점의 날짜로 경로를 산출하므로, 트레이더 프로세스가 자정을 넘겨
# 계속 실행돼도 재시작 없이 자동으로 다음 날 파일로 분리된다.
# 하이픈 없는 레거시 단일 파일(`trader.log`)은 이 패턴에 매칭되지 않아 깔끔히 분리된다.
_LOG_PATTERN = "trader-{date}.log"
# 파일명에서 날짜를 뽑아내는 정규식 (보존 정리 시 사용). mtime 이 아니라 파일명 날짜를
# 기준으로 삼아, 파일이 touch 돼도 '로그가 기록된 날' 기준으로 일관되게 판정한다.
_LOG_DATE_RE = re.compile(r"^trader-(\d{4}-\d{2}-\d{2})\.log$")

# 로그 보존 기간(일). 오늘 기준 이 일수 이상 지난 일별 로그는 정리한다.
# 예) RETENTION_DAYS=5, 오늘 6/12 → 6/7(5일 전) 이전 파일 삭제, 6/8~6/12(5일치) 보존.
RETENTION_DAYS = 5


def log_path_for(dt: datetime | None = None) -> str:
    """주어진 시각(없으면 현재)의 일별 로그 파일 경로를 반환."""
    d = dt or datetime.now()
    return os.path.join(_LOG_DIR, _LOG_PATTERN.format(date=d.strftime("%Y-%m-%d")))


def current_log_file() -> str:
    """오늘 날짜의 로그 파일 경로."""
    return log_path_for()


def latest_log_file() -> str | None:
    """존재하는 가장 최근(수정 시각 기준) 일별 로그 파일 경로. 없으면 None.

    대시보드가 자정 직후·기동 직후처럼 '오늘' 파일이 아직 생성되기 전일 때
    직전 일자 로그를 대신 보여주기 위한 폴백용.
    """
    files = glob.glob(os.path.join(_LOG_DIR, _LOG_PATTERN.format(date="*")))
    if not files:
        return None
    return max(files, key=os.path.getmtime)


def cleanup_old_logs(retention_days: int = RETENTION_DAYS) -> list[str]:
    """파일명 날짜 기준으로 `retention_days` 일 이상 지난 일별 로그를 삭제. 삭제한 경로 리스트 반환.

    트리거: (1) 새 일별 파일이 처음 생성될 때(log() 내부 — 자정 경과·당일 첫 기록),
            (2) 프로세스 기동 시(main.py).
    삭제 실패(권한·동시 삭제 등)는 무시한다 — 로그 정리가 본 로직을 막으면 안 된다.
    레거시 `trader.log`(하이픈 없음)는 패턴에 안 잡혀 보존된다.
    """
    today = datetime.now().date()
    removed: list[str] = []
    for path in glob.glob(os.path.join(_LOG_DIR, _LOG_PATTERN.format(date="*"))):
        m = _LOG_DATE_RE.match(os.path.basename(path))
        if not m:
            continue
        try:
            file_date = datetime.strptime(m.group(1), "%Y-%m-%d").date()
        except ValueError:
            continue
        if (today - file_date).days >= retention_days:
            try:
                os.remove(path)
                removed.append(path)
            except OSError:
                pass  # 다른 프로세스가 이미 지웠거나 권한 문제 — 무시
    return removed


def log(msg: str) -> None:
    now = datetime.now()
    path = log_path_for(now)
    is_new_file = not os.path.exists(path)  # 당일 첫 기록(=날짜 전환) 여부
    line = f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    if is_new_file:
        # 새 일별 파일이 만들어진 직후 — 오래된 로그 정리.
        cleanup_old_logs()
