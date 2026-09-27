import glob
import os
import re
from datetime import date, datetime

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

# 로그 보존 기간 — **운영일(평일) 기준** 일수.
#
# 달력 일수로 자르면 주말·연휴가 끼는 만큼 실제로 들여다볼 수 있는 거래일이 줄어든다.
# 보관 5일이던 시절 금요일에 남는 건 화~금 4거래일뿐이었고, 연휴가 끼면 2~3일로 줄었다.
# 실제로 2026-09 에 08-12·08-26 사건을 사후 조사할 때 해당 일자 로그가 이미 지워져
# 원인 규명이 정황 증거에 머문 전례가 있다(README '시뮬 vs 실계좌 대조' 참조).
# 그래서 평일 파일을 최신순으로 세어 N번째 평일을 컷오프로 잡는다 — 달력으로는 약 3주치.
RETENTION_TRADING_DAYS = 14


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


def cleanup_old_logs(retention_days: int = RETENTION_TRADING_DAYS) -> list[str]:
    """**운영일(평일) 기준** `retention_days` 일치를 남기고 더 오래된 일별 로그를 삭제.

    판정 방식: 존재하는 로그의 **파일명 날짜** 중 평일만 최신순으로 세어
    `retention_days` 번째 평일을 컷오프로 잡고, 그보다 이전 날짜의 파일을 모두 지운다.
    컷오프 이후라면 주말 파일도 함께 남는다 — 그 구간을 **연속으로** 읽을 수 있어야
    사후 추적에 쓸 수 있기 때문이다(주말만 구멍 난 로그는 시계열로 못 읽는다).

    파일명 날짜를 쓰는 이유는 mtime 이 touch·복사로 바뀌어도 '기록된 날' 기준으로
    일관되게 판정하기 위함이다.

    한계: 공휴일 휴장일에도 프로세스가 켜져 있으면 그날 파일이 생기고, 평일이므로
    운영일로 함께 세어진다. 연휴가 긴 달에는 실제 거래일이 그만큼 줄어든다 — 파일
    내용을 읽어 거래 유무를 판별하는 대신 비용 0 의 근사를 택했다.

    트리거: (1) 새 일별 파일이 처음 생성될 때(log() 내부 — 자정 경과·당일 첫 기록),
            (2) 프로세스 기동 시(main.py).
    삭제 실패(권한·동시 삭제 등)는 무시한다 — 로그 정리가 본 로직을 막으면 안 된다.
    레거시 `trader.log`(하이픈 없음)는 패턴에 안 잡혀 보존된다.

    Returns:
        삭제한 파일 경로 리스트 (보관 한도에 못 미치면 빈 리스트).
    """
    dated: list[tuple[date, str]] = []
    for path in glob.glob(os.path.join(_LOG_DIR, _LOG_PATTERN.format(date="*"))):
        m = _LOG_DATE_RE.match(os.path.basename(path))
        if not m:
            continue
        try:
            dated.append((datetime.strptime(m.group(1), "%Y-%m-%d").date(), path))
        except ValueError:
            continue

    # 평일(운영일)만 최신순으로 세어 N 번째 평일을 컷오프로 잡는다.
    weekdays = sorted({d for d, _ in dated if d.weekday() < 5}, reverse=True)
    if len(weekdays) <= retention_days:
        return []                       # 아직 보관 한도에 못 미친다
    cutoff = weekdays[retention_days - 1]

    removed: list[str] = []
    for file_date, path in dated:
        if file_date >= cutoff:
            continue
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
