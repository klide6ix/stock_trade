"""운영 로그 점검 — 하루치 단기 매매가 정상으로 돌았는지 한 화면에 요약한다.

조회 전용이다. 로그 파일과 git·프로세스 정보만 읽고 KIS API 는 부르지 않는다. 트레이더가
떠 있는 AWS 에서 그대로 돌리면 된다(실행 중인 트레이더에 영향 없음).

    .venv/bin/python -m scripts.check_logs              # 가장 최근 개장일
    .venv/bin/python -m scripts.check_logs 2026-10-16   # 특정 날짜
    .venv/bin/python -m scripts.check_logs --days 10    # 최근 개장일 10일 요약표

점검 항목
  - 실행 버전: 트레이더 프로세스가 디스크의 최신 코드보다 나중에 떴는가 (pull 후 재시작 누락 탐지)
  - 개장 판정: 실측 갭이 몇 번째 시도에 반영됐는가, 09:05 까지 실패했는가
  - 진입: 마감(09:30) 전에 들어갔는가, 목표 수량을 다 채웠는가, 재주문 · 체결 미확정 · 목표 미달
  - 원장: 원장 밖 체결분 편입 · 외부 청산 · 수량 보정 · 취소 실패(수동 확인 필요)
  - 청산 사유 · 수익률, EGW00215(초당 한도) 건수, 오류
"""
import argparse
import glob
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date, datetime

from core.market_calendar import is_open_day

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(BASE, "logs")
LINE_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})\] (.*)$")
WEEKDAY = "월화수목금토일"

ENTRY_UNTIL = "09:30:00"         # trader.SHORT_TERM_ENTRY_UNTIL (지연이 길면 뒤로 밀린다)
REJUDGE_UNTIL = "09:05:00"       # trader.OPEN_REJUDGE_UNTIL

# 타임라인에서 빼는 반복 로그 (매 주기 찍힌다).
ROUTINE = ("보유 중 ", "분 대기 —", "자동매매 OFF", "정산 대기 중", "재진입 차단 상태")


@dataclass
class Entry:
    time: str
    name: str
    target: int
    fills: list[int] = field(default_factory=list)
    reorders: int = 0
    unconfirmed: bool = False
    shortfall: str = ""
    no_fill: bool = False
    adopted: int = 0             # 체결 미확정 뒤 다음 주기 잔고 정산으로 편입된 수량

    @property
    def filled(self) -> int:
        return sum(self.fills) + self.adopted


@dataclass
class Day:
    day: date
    path: str
    lines: list[tuple[str, str]]                 # (HH:MM:SS, 메시지)
    entries: list[Entry] = field(default_factory=list)
    exits: list[tuple[str, str, str, str]] = field(default_factory=list)   # (시각, 종목, 사유, 수익률)
    verdicts: list[tuple[str, str]] = field(default_factory=list)
    rejudge_tries: int = 0
    rejudge_done: str = ""
    egw: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)
    ledger: list[tuple[str, str]] = field(default_factory=list)
    entry_closed_logs: int = 0
    starts: list[str] = field(default_factory=list)


def log_files() -> dict[date, str]:
    out = {}
    for path in glob.glob(os.path.join(LOG_DIR, "trader-*.log")):
        m = re.search(r"trader-(\d{4}-\d{2}-\d{2})\.log$", path)
        if m:
            out[datetime.strptime(m.group(1), "%Y-%m-%d").date()] = path
    return out


def parse(day: date, path: str) -> Day:
    lines = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for raw in f:
            m = LINE_RE.match(raw.rstrip("\n"))
            if m:
                lines.append((m.group(2), m.group(3)))
            elif lines and raw.strip():          # 여러 줄짜리 메시지(예외 트레이스)는 앞 줄에 붙인다
                t, msg = lines[-1]
                lines[-1] = (t, msg + " ⏎ " + raw.strip())
    d = Day(day, path, lines)

    current: Entry | None = None
    for t, msg in lines:
        name = (re.search(r"\[단기매매\]\[([^\]]+)\]", msg) or [None, ""])[1]
        if "트레이더 시작" in msg:
            d.starts.append(t)
        if msg.startswith("[방향판정]") and re.search(r"📈|📉|➖|판정 불가", msg):
            d.verdicts.append((t, re.sub(r" — .*", "", msg.replace("[방향판정] ", ""))))
        if msg.startswith("[개장판정] 실측 갭(실시간 등락률)"):
            d.rejudge_tries += 1
        if msg.startswith("[개장판정] 실측 갭 반영 완료") and not d.rejudge_done:
            d.rejudge_done = t
        if "초당 한도 초과" in msg and "재시도 1/" in msg:
            d.egw += 1
        if ("오류" in msg and "[API]" not in msg) or "Traceback" in msg or "수동 확인 필요" in msg:
            d.errors.append((t, msg))
        if "진입 마감" in msg and "경과" in msg:
            d.entry_closed_logs += 1
        adopted = re.search(r"원장 밖 체결분 편입 — (\d+)주", msg)
        if adopted and current is not None and current.unconfirmed and not current.adopted:
            current.adopted = int(adopted.group(1))      # 설계된 회수 경로 — 진입에 합친다
        elif re.search(r"원장 밖 체결분 편입|외부 청산으로 보고|원장 수량 보정", msg):
            d.ledger.append((t, msg))

        m = re.search(r"★ 진입 .*→ (?:지정가|시장가) (\d+)주", msg)
        if m:
            current = Entry(t, name, int(m.group(1)))
            d.entries.append(current)
            continue
        if current is None:
            pass
        elif "↻ 재주문" in msg:
            current.reorders += 1
        elif (m := re.search(r"\] 체결 (\d+)주 @ .* · 지출", msg)):
            current.fills.append(int(m.group(1)))
        elif "체결 미확정" in msg:
            current.unconfirmed = True
        elif (m := re.search(r"⚠️ 목표 (\d+)주 중 (\d+)주만", msg)):
            current.shortfall = f"{m.group(2)}/{m.group(1)}주"
        elif "체결 없음 — 주문 전부 취소 확인" in msg:
            current.no_fill = True
        if (m := re.search(r"★ 청산 조건 충족 \((.*?)\) → (\d+)주 .*\(수익률 ([+-][\d.]+)%\)", msg)):
            d.exits.append((t[:5], name, re.sub(r":.*", "", m.group(1)), f"{m.group(3)}%"))
            current = None
    return d


def checks(d: Day) -> list[tuple[bool, str]]:
    """(정상 여부, 설명) 목록."""
    out: list[tuple[bool, str]] = []
    if not is_open_day(d.day, fetch=False):
        trades = d.entries + d.exits
        out.append((not trades, "휴장일 — 매매 없음" if not trades else f"휴장일인데 매매 로그 {len(trades)}건"))
        return out

    if d.rejudge_done:
        out.append((d.rejudge_done <= REJUDGE_UNTIL,
                    f"개장 판정 실측 갭 반영 {d.rejudge_done} ({d.rejudge_tries}회 시도)"))
    else:
        out.append((False, f"개장 판정 실측 갭 미반영 ({d.rejudge_tries}회 시도) — 장전 판정으로 매매"))

    if not d.entries:
        out.append((False, "진입 없음 — 자동매매 OFF · 중립 판정 · 전일 포지션 보유 중인지 확인"))
    for e in d.entries:
        filled = e.filled
        late = e.time > ENTRY_UNTIL
        out.append((not late, f"진입 {e.time} {e.name}" + (" — 마감(09:30) 이후 ⚠️" if late else "")))
        if e.unconfirmed:
            ok = e.adopted >= e.target
            out.append((ok, f"  목표 {e.target}주 · 체결 미확정 → 다음 주기 잔고 정산으로 {e.adopted}주 편입"
                        + (" (설계된 회수 경로)" if ok else " — 목표 미달, 원장·잔고 대조 필요")))
        elif e.no_fill:
            out.append((False, f"  주문 {e.reorders + 1}건 모두 무체결 — 다음 주기 재시도"))
        else:
            how = f"주문 {e.reorders + 1}건" + (f" (재주문 {e.reorders}회)" if e.reorders else "")
            out.append((filled >= e.target, f"  목표 {e.target}주 · 체결 {filled}주 · {how}"
                        + (f" · 목표 미달 {e.shortfall}" if e.shortfall else "")))
    for t, msg in d.ledger:
        out.append((False, f"원장 보정 {t} — {msg.split('] ', 2)[-1][:90]}"))
    if d.entry_closed_logs > 1:
        out.append((False, f"'진입 마감' 로그 {d.entry_closed_logs}줄 (하루 1줄이어야 함)"))
    out.append((True, f"EGW00215 초당 한도 초과 {d.egw}건 (재시도로 성공했으면 기능 피해 없음)"))
    out.append((not d.errors, f"오류 {len(d.errors)}건" if d.errors else "오류 없음"))
    return out


def running_version() -> list[tuple[bool, str]]:
    """트레이더 프로세스가 디스크의 최신 코드보다 나중에 떴는지 — pull 후 재시작 누락 탐지."""
    code_files = glob.glob(os.path.join(BASE, "core", "**", "*.py"), recursive=True)
    code_files += [os.path.join(BASE, p) for p in ("main.py", "config.py")]
    newest = max(code_files, key=os.path.getmtime)
    code_mtime = datetime.fromtimestamp(os.path.getmtime(newest))
    head = subprocess.run(["git", "log", "-1", "--format=%h %s"], cwd=BASE,
                          capture_output=True, text=True).stdout.strip()
    out = [(True, f"HEAD {head[:70]}")]
    try:
        pids = subprocess.run(["pgrep", "-f", "python.*main.py"], capture_output=True,
                              text=True).stdout.split()
        starts = []
        for pid in pids:
            raw = subprocess.run(["ps", "-o", "lstart=", "-p", pid], capture_output=True,
                                 text=True).stdout.strip()
            if raw:
                starts.append(datetime.strptime(" ".join(raw.split()), "%a %b %d %H:%M:%S %Y"))
    except (OSError, ValueError) as e:
        return out + [(False, f"프로세스 확인 실패: {e}")]
    if not starts:
        return out + [(False, "트레이더 프로세스(main.py)가 떠 있지 않다")]
    started = min(starts)
    ok = started >= code_mtime
    return out + [(ok, f"트레이더 기동 {started:%m-%d %H:%M} · 코드 갱신 {code_mtime:%m-%d %H:%M} "
                       f"({os.path.relpath(newest, BASE)})"
                       + ("" if ok else " — 재시작 전 코드로 동작 중, ./stop.sh && ./start.sh 필요"))]


def mark(ok: bool) -> str:
    return "✅" if ok else "⚠️ "


def report(d: Day, with_version: bool) -> None:
    open_day = is_open_day(d.day, fetch=False)
    print(f"════ {d.day} ({WEEKDAY[d.day.weekday()]}) 운영 로그 점검 ════")
    print(f"파일 {os.path.relpath(d.path, BASE)} · {len(d.lines):,}줄 · {'개장일' if open_day else '휴장일'}"
          + (f" · 트레이더 시작 {', '.join(d.starts)}" if d.starts else ""))

    if with_version:
        print("\n[실행 버전]")
        for ok, text in running_version():
            print(f"  {mark(ok)} {text}")

    if d.verdicts:
        pre = [v for v in d.verdicts if v[0] < "09:00:00"]
        post = [v for v in d.verdicts if v[0] >= "09:00:00"]
        print("\n[방향 판정]")
        if pre:
            print(f"  장전 마지막 {pre[-1][0]} {pre[-1][1]}  (장전 {len(pre)}회)")
        if post:
            # 실측 갭이 반영된 시점의 판정이 그날 매매 방향이다 (그 전 시도는 갭 미사용).
            final = [v for v in post if v[0] <= d.rejudge_done] if d.rejudge_done else post[:1]
            print(f"  개장 후     {(final or post)[-1][0]} {(final or post)[-1][1]}")

    print("\n[단기 매매 타임라인]")
    shown = 0
    for t, msg in d.lines:
        key = msg.startswith(("[단기매매]", "[개장판정]", "[지정가]", "[체결조회]")) or "★" in msg
        if key and not any(r in msg for r in ROUTINE):
            print(f"  {t} {msg[:150]}")
            shown += 1
    if not shown:
        print("  (없음)")
    if d.exits:
        print("\n[청산]  " + " · ".join(f"{t} {n} {r} {p}" for t, n, r, p in d.exits))

    results = checks(d)
    print("\n[자동 점검]")
    for ok, text in results:
        print(f"  {mark(ok)} {text}")
    for t, msg in d.errors[:10]:
        print(f"      {t} {msg[:140]}")
    bad = sum(1 for ok, _ in results if not ok)
    print(f"\n결론: {'정상' if not bad else f'확인 필요 {bad}건'}")


def summary(days: list[Day]) -> None:
    print("날짜 | 개장판정(시도) | 진입 | 종목 | 목표/체결 | 재주문 | 미확정 | 청산 | EGW | 오류 | 결과")
    for d in days:
        e = d.entries[0] if d.entries else None
        gap = f"{d.rejudge_done[:5]}({d.rejudge_tries})" if d.rejudge_done else f"미반영({d.rejudge_tries})"
        exit_ = " / ".join(f"{r} {p}" for _, _, r, p in d.exits) or "-"
        bad = sum(1 for ok, _ in checks(d) if not ok)
        cells = [
            f"{d.day:%m-%d}({WEEKDAY[d.day.weekday()]})", gap,
            e.time[:5] if e else "-",
            re.sub(r"\(\d+\)$", "", e.name) if e else "-",
            f"{e.target}/{e.filled}" if e else "-",
            str(sum(x.reorders for x in d.entries)) if e else "-",
            "예" if any(x.unconfirmed for x in d.entries) else "-",
            exit_, str(d.egw), str(len(d.errors)),
            "정상" if not bad else f"⚠️ {bad}",
        ]
        print(" | ".join(cells))


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="운영 로그 점검 (조회 전용)")
    ap.add_argument("date", nargs="?", help="YYYY-MM-DD (기본: 가장 최근 개장일)")
    ap.add_argument("--days", type=int, help="최근 개장일 N일 요약표")
    args = ap.parse_args(argv)

    files = log_files()
    if not files:
        sys.exit(f"로그 파일 없음: {LOG_DIR}")

    if args.days:
        days = sorted((d for d in files if is_open_day(d, fetch=False)), reverse=True)[:args.days]
        summary([parse(d, files[d]) for d in sorted(days)])
        return

    if args.date:
        day = datetime.strptime(args.date, "%Y-%m-%d").date()
        if day not in files:
            sys.exit(f"{day} 로그 없음 (보관: 운영일 14일)")
    else:
        now = datetime.now()
        candidates = [d for d in files if is_open_day(d, fetch=False)
                      and (d < now.date() or now.strftime("%H:%M") >= "09:00")]
        if not candidates:
            sys.exit("점검할 개장일 로그가 없다")
        day = max(candidates)
    report(parse(day, files[day]), with_version=not args.date)


if __name__ == "__main__":
    main()
