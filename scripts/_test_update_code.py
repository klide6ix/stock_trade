"""부팅 시 코드 갱신 검증 — 임시 디렉터리의 실제 git 저장소로 돈다 (네트워크 · 운영 저장소 미사용).

구성: bare `origin` ← `dev`(개발 PC 역할)가 push, `server`(운영 역할)가 `update()` 로 받는다.
가짜 저장소의 회귀 테스트는 `scripts/_test_*.py` 한 줄짜리 스크립트다.

검증 대상
  1. 최신이면 아무것도 안 한다 / 새 커밋 + 테스트 통과면 fast-forward 반영
  2. 테스트 실패 · 시간 초과 · 테스트 없음이면 거부하고 HEAD 를 그대로 둔다 (worktree 도 정리)
  3. 서버의 커밋 안 된 수정 · origin 에 없는 서버 커밋이면 건너뛴다 — untracked 파일은 막지 않는다
  4. fetch 실패면 error, requirements 가 바뀌면 pip 먼저 · pip 실패면 거부
  5. 검증은 새 커밋의 테스트로 한다 (서버에 있던 옛 테스트가 아니라)
  6. 유닛 파일 변경 감지 · 상태 파일 기록 · main 은 예외에도 0
"""
import json
import os
import subprocess
import sys
import tempfile
from unittest.mock import patch

from scripts import update_code as uc

fails = []


def check(name, cond, detail=""):
    print(f"  {'✅' if cond else '❌'} {name}" + (f" — {detail}" if detail else ""))
    if not cond:
        fails.append(name)


def sh(cwd, *args):
    res = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                         cwd=cwd, capture_output=True, text=True)
    assert res.returncode == 0, (args, res.stderr)
    return res.stdout.strip()


def write(repo, rel, text):
    path = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


PASS = "print('✅ 전부 통과')\n"
FAIL = "import sys; print('❌ 실패 1건'); sys.exit(1)\n"
HANG = "import time; time.sleep(30)\n"


def setup():
    root = tempfile.mkdtemp(prefix="uc-test-")
    origin, dev, server = (os.path.join(root, n) for n in ("origin.git", "dev", "server"))
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", origin], check=True)
    subprocess.run(["git", "clone", "-q", origin, dev], check=True, capture_output=True)
    sh(dev, "checkout", "-q", "-b", "main")
    write(dev, "scripts/_test_a.py", PASS)
    write(dev, "requirements.txt", "requests\n")
    write(dev, "app.py", "v = 1\n")
    sh(dev, "add", "-A"); sh(dev, "commit", "-q", "-m", "init"); sh(dev, "push", "-q", "origin", "main")
    subprocess.run(["git", "clone", "-q", origin, server], check=True, capture_output=True)
    return dev, server


def commit(dev, files, msg="change"):
    for rel, text in files.items():
        write(dev, rel, text)
    sh(dev, "add", "-A"); sh(dev, "commit", "-q", "-m", msg); sh(dev, "push", "-q", "origin", "main")
    return sh(dev, "rev-parse", "--short", "HEAD")


def head(repo):
    return sh(repo, "rev-parse", "--short", "HEAD")


def worktrees(repo):
    return len([l for l in sh(repo, "worktree", "list").splitlines() if l.strip()])


def no_pip(*a, **k):
    raise AssertionError("pip 이 불리면 안 됨")


print("── 1. 최신 · 반영 ──")
dev, server = setup()
with patch.object(uc, "pip_install", no_pip):
    st = uc.update(server)
check("새 커밋 없음 → uptodate", st["result"] == "uptodate" and st["old"] == st["new"] == head(server), str(st))

new = commit(dev, {"app.py": "v = 2\n"})
before = head(server)
with patch.object(uc, "pip_install", no_pip):
    st = uc.update(server)
check("새 커밋 + 테스트 통과 → updated · HEAD 이동", st["result"] == "updated" and head(server) == new, str(st))
check("이전·이후 커밋과 개수 기록", st["old"] == before and st["new"] == new and st["commits"] == 1)
check("작업 트리에 새 코드가 반영됨", open(os.path.join(server, "app.py")).read() == "v = 2\n")
check("검증용 worktree 정리", worktrees(server) == 1)
check("상세에 통과한 테스트 수", "1종 통과" in st["detail"], st["detail"])

print("── 2. 거부 ──")
dev, server = setup()
before = head(server)
commit(dev, {"app.py": "v = 2\n", "scripts/_test_a.py": FAIL})
st = uc.update(server)
check("테스트 실패 → rejected · HEAD 그대로", st["result"] == "rejected" and head(server) == before, str(st))
check("실패한 테스트 이름과 마지막 줄", "_test_a.py 실패" in st["detail"] and "실패 1건" in st["detail"], st["detail"])
check("작업 트리도 그대로", open(os.path.join(server, "app.py")).read() == "v = 1\n")
check("거부돼도 worktree 정리", worktrees(server) == 1)

dev, server = setup()
before = head(server)
commit(dev, {"scripts/_test_b.py": HANG})
with patch.object(uc, "TEST_TIMEOUT_SEC", 1):
    st = uc.update(server)
check("테스트 시간 초과 → rejected", st["result"] == "rejected" and "시간 초과" in st["detail"] and head(server) == before, str(st))

dev, server = setup()
before = head(server)
sh(dev, "rm", "-q", "scripts/_test_a.py"); sh(dev, "commit", "-q", "-m", "drop tests"); sh(dev, "push", "-q", "origin", "main")
st = uc.update(server)
check("테스트 파일이 사라진 커밋 → rejected", st["result"] == "rejected" and head(server) == before, str(st))

print("── 3. 건너뜀 ──")
dev, server = setup()
before = head(server)
commit(dev, {"app.py": "v = 2\n"})
write(server, "app.py", "v = 99  # 서버에서 손으로 고침\n")
st = uc.update(server)
check("서버에 커밋 안 된 수정 → skipped · 수정 보존", st["result"] == "skipped" and head(server) == before
      and "v = 99" in open(os.path.join(server, "app.py")).read(), str(st))

dev, server = setup()
commit(dev, {"app.py": "v = 2\n"})
write(server, "local.py", "x = 1\n"); sh(server, "add", "local.py"); sh(server, "commit", "-q", "-m", "server-only")
before = head(server)
st = uc.update(server)
check("서버에만 있는 커밋(갈라짐) → skipped · HEAD 그대로", st["result"] == "skipped" and head(server) == before
      and "fast-forward 불가" in st["detail"], str(st))

dev, server = setup()
new = commit(dev, {"app.py": "v = 2\n"})
write(server, "venv.sh", "echo hi\n"); write(server, "logs/trader.log", "x\n")
st = uc.update(server)
check("untracked 파일(venv.sh · logs)은 막지 않는다", st["result"] == "updated" and head(server) == new, str(st))

print("── 4. fetch · 의존성 ──")
dev, server = setup()
before = head(server)
sh(server, "remote", "set-url", "origin", "/nonexistent/repo.git")
st = uc.update(server)
check("fetch 실패 → error · HEAD 그대로", st["result"] == "error" and "fetch 실패" in st["detail"] and head(server) == before, str(st))

dev, server = setup()
new = commit(dev, {"requirements.txt": "requests\nboto3\n"})
seen = []
with patch.object(uc, "pip_install", lambda req, py=None: seen.append(open(req).read()) or (True, "")):
    st = uc.update(server)
check("requirements 변경 → 새 커밋의 requirements 로 pip 먼저", seen == ["requests\nboto3\n"], str(seen))
check("pip 성공 + 테스트 통과 → updated", st["result"] == "updated" and head(server) == new)

dev, server = setup()
before = head(server)
commit(dev, {"requirements.txt": "requests\nnot-a-real-package\n"})
with patch.object(uc, "pip_install", lambda req, py=None: (False, "의존성 설치 실패: No matching distribution")):
    st = uc.update(server)
check("pip 실패 → rejected · HEAD 그대로", st["result"] == "rejected" and "의존성" in st["detail"] and head(server) == before, str(st))

print("── 5. 새 커밋의 테스트로 검증 ──")
dev, server = setup()
before = head(server)
# 서버의 옛 테스트는 통과하지만 새 커밋이 추가한 테스트가 실패 → 거부돼야 한다.
commit(dev, {"scripts/_test_new.py": FAIL})
st = uc.update(server)
check("새 커밋에 추가된 실패 테스트도 잡는다", st["result"] == "rejected" and "_test_new.py" in st["detail"] and head(server) == before, str(st))

print("── 6. 유닛 · 상태 파일 · main ──")
dev, server = setup()
write(server, "deploy/stock-trade.service", "[Unit]\nA\n")
inst = os.path.join(tempfile.mkdtemp(), "installed.service")
write(os.path.dirname(inst), "installed.service", "[Unit]\nA\n")
check("유닛 같음 → False", uc.unit_changed(server, inst) is False)
write(os.path.dirname(inst), "installed.service", "[Unit]\nB\n")
check("유닛 다름 → True", uc.unit_changed(server, inst) is True)
check("설치본 없음(로컬) → False", uc.unit_changed(server, "/nonexistent/x.service") is False)

path = os.path.join(tempfile.mkdtemp(), "logs", ".update_status.json")
uc.write_status({"result": "updated", "detail": "회귀 1종 통과"}, path)
check("상태 파일 기록 (한글 그대로)", json.load(open(path, encoding="utf-8"))["detail"] == "회귀 1종 통과")

written = []
with patch.object(uc, "update", side_effect=RuntimeError("boom")), \
        patch.object(uc, "write_status", lambda s, p=None: written.append(s)), \
        patch.object(uc, "unit_changed", lambda repo: False), patch("core.logger.log", lambda m: None):
    code = uc.main()
check("update 예외에도 main 은 0 · error 상태 기록", code == 0 and written and written[0]["result"] == "error"
      and "boom" in written[0]["detail"], str(written))

print()
if fails:
    print(f"❌ 실패 {len(fails)}건: {fails}")
    sys.exit(1)
print("✅ 전부 통과")
