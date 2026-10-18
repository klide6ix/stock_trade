"""부팅 시 코드 갱신 — origin/main 의 새 커밋을 회귀 테스트로 검증한 뒤에만 반영한다.

systemd 의 `ExecStartPre` 로 트레이더 기동 직전에 돈다. 서버는 평일 아침마다 새로 켜지므로
`git push` 만 해 두면 다음 날 08:20 에 반영된다. 장중에는 코드가 바뀌지 않는다.

실거래 서버라 '자동 배포' 의 위험을 두 겹으로 막는다.
  1. **검증 게이트** — 새 커밋을 임시 worktree 에 꺼내 **서버 venv 의 Python 으로** 그 커밋의
     `scripts/_test_*.py` 를 전부 돌린다(서버는 3.11 · 로컬은 3.14 라 로컬 통과가 서버 통과를
     보장하지 않는다). 하나라도 실패하면 반영하지 않는다. 테스트가 임시 worktree 안에서 돌기 때문에
     운영 `data/` · `logs/` 는 건드리지 않는다.
  2. **기동은 절대 막지 않는다** — fetch 실패 · 시간 초과 · fast-forward 불가 · 서버의 커밋 안 된
     수정 · 테스트 실패 · 예외, 무엇이든 기존 코드 그대로 두고 0 으로 끝난다. `reset --hard` 같은
     파괴적 명령은 쓰지 않는다(`merge --ff-only` 만).

테스트가 잡는 건 **고장**뿐이다. 테스트를 통과하는 전략 동작 변경(청산선 · 진입 조건)은 그대로
반영된다 — main 에는 실거래에 넣어도 되는 커밋만 push 한다는 전제다.

결과는 `STATUS_FILE` 에 남기고 `boot_notify` 가 메일 본문 · 제목 태그로 알린다. systemd 유닛
파일은 pull 로 바뀌어도 이번 기동에 반영되지 않으므로(유닛은 기동 전에 이미 읽힘) 설치본과 다르면
그 사실도 함께 남긴다.

    .venv/bin/python -m scripts.update_code    # systemd ExecStartPre 가 실행 (ec2-user)
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATUS_FILE = os.path.join(BASE, "logs", ".update_status.json")
UNIT_IN_REPO = os.path.join("deploy", "stock-trade.service")
UNIT_INSTALLED = "/etc/systemd/system/stock-trade.service"

REMOTE, BRANCH = "origin", "main"
FETCH_TIMEOUT_SEC = 30
PIP_TIMEOUT_SEC = 300
TEST_TIMEOUT_SEC = 120      # 테스트 파일 하나당. 현재 전체 10종이 2초 안팎이다.

# 부팅 중엔 아무도 프롬프트에 답할 수 없다 — 자격 증명 · 호스트 키 질문에 멈추지 않고 실패하게.
GIT_ENV = {
    **os.environ,
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_SSH_COMMAND": "ssh -o BatchMode=yes -o ConnectTimeout=10",
}


def git(repo: str, *args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True,
                          timeout=timeout, env=GIT_ENV)


def _last_line(res: subprocess.CompletedProcess) -> str:
    lines = (res.stderr or res.stdout or "").strip().splitlines()
    return lines[-1] if lines else f"exit {res.returncode}"


def _short(repo: str, rev: str) -> str:
    return git(repo, "rev-parse", "--short", rev).stdout.strip()


def pip_install(requirements: str, python: str = sys.executable) -> tuple[bool, str]:
    try:
        res = subprocess.run([python, "-m", "pip", "install", "-q", "-r", requirements],
                             capture_output=True, text=True, timeout=PIP_TIMEOUT_SEC)
    except subprocess.TimeoutExpired:
        return False, "의존성 설치 시간 초과"
    return (True, "") if res.returncode == 0 else (False, f"의존성 설치 실패: {_last_line(res)}")


def run_tests(tree: str, python: str = sys.executable) -> tuple[bool, str]:
    """`tree` 의 회귀 테스트 전부. 하나라도 실패 · 시간 초과면 거기서 멈춘다."""
    tests = sorted(glob.glob(os.path.join(tree, "scripts", "_test_*.py")))
    if not tests:
        return False, "회귀 테스트 파일이 없음"
    env = {**os.environ, "PYTHONPATH": tree}
    for path in tests:
        name = os.path.basename(path)
        try:
            res = subprocess.run([python, path], cwd=tree, capture_output=True, text=True,
                                 timeout=TEST_TIMEOUT_SEC, env=env)
        except subprocess.TimeoutExpired:
            return False, f"{name} 시간 초과({TEST_TIMEOUT_SEC}초)"
        if res.returncode != 0:
            return False, f"{name} 실패 — {_last_line(res)}"
    return True, f"회귀 {len(tests)}종 통과"


def unit_changed(repo: str, installed: str = UNIT_INSTALLED) -> bool:
    """저장소의 유닛 파일이 설치본과 다른가. 어느 한쪽이 없으면(로컬 등) 판단하지 않는다."""
    src = os.path.join(repo, UNIT_IN_REPO)
    try:
        with open(src, "rb") as a, open(installed, "rb") as b:
            return a.read() != b.read()
    except OSError:
        return False


def update(repo: str = BASE, python: str = sys.executable) -> dict:
    """origin/main 을 검증해 반영한다. result: updated | uptodate | rejected | skipped | error."""
    old = _short(repo, "HEAD")
    status = {"at": datetime.now().isoformat(timespec="seconds"), "old": old, "new": old,
              "commits": 0, "result": "error", "detail": ""}

    def done(result: str, detail: str = "") -> dict:
        status.update(result=result, detail=detail)
        return status

    try:
        fetched = git(repo, "fetch", "--quiet", REMOTE, BRANCH, timeout=FETCH_TIMEOUT_SEC)
    except subprocess.TimeoutExpired:
        return done("error", f"fetch 시간 초과({FETCH_TIMEOUT_SEC}초)")
    if fetched.returncode != 0:
        return done("error", f"fetch 실패 — {_last_line(fetched)}")

    target = f"{REMOTE}/{BRANCH}"
    status["new"] = new = _short(repo, target)
    if new == old:
        return done("uptodate")
    if git(repo, "merge-base", "--is-ancestor", "HEAD", target).returncode != 0:
        return done("skipped", f"fast-forward 불가 — 서버에 {target} 에 없는 커밋이 있음")
    if git(repo, "status", "--porcelain", "--untracked-files=no").stdout.strip():
        return done("skipped", "서버에 커밋 안 된 수정이 있음")
    status["commits"] = int(git(repo, "rev-list", "--count", f"HEAD..{target}").stdout.strip() or 0)

    tree = tempfile.mkdtemp(prefix="stock-trade-update-")
    try:
        added = git(repo, "worktree", "add", "--detach", tree, target, timeout=60)
        if added.returncode != 0:
            return done("error", f"검증용 worktree 생성 실패 — {_last_line(added)}")
        if git(repo, "diff", "--quiet", "HEAD", target, "--", "requirements.txt").returncode != 0:
            ok, detail = pip_install(os.path.join(tree, "requirements.txt"), python)
            if not ok:
                return done("rejected", detail)
        ok, detail = run_tests(tree, python)
        if not ok:
            return done("rejected", detail)
        merged = git(repo, "merge", "--ff-only", "--quiet", target)
        if merged.returncode != 0:
            return done("error", f"반영 실패 — {_last_line(merged)}")
        return done("updated", detail)
    finally:
        git(repo, "worktree", "remove", "--force", tree)
        shutil.rmtree(tree, ignore_errors=True)
        git(repo, "worktree", "prune")


def write_status(status: dict, path: str = STATUS_FILE) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False)
    os.replace(tmp, path)


def main() -> int:
    try:
        status = update()
    except Exception as e:  # 어떤 예외도 기동을 막지 않는다
        status = {"at": datetime.now().isoformat(timespec="seconds"), "old": "?", "new": "?",
                  "commits": 0, "result": "error", "detail": f"{type(e).__name__}: {e}"}
    status["unit_changed"] = unit_changed(BASE)
    try:
        write_status(status)
    except OSError:
        pass
    try:
        from core.logger import log
        log(f"[코드갱신] {status['result']} {status['old']} → {status['new']} "
            f"({status['commits']}커밋) {status['detail']}".rstrip())
    except Exception:
        print(status)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
