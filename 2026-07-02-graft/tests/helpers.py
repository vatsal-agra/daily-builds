import os
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GRAFT_BIN = os.path.join(REPO_ROOT, "bin", "graft")

sys.path.insert(0, REPO_ROOT)


def run_graft(cwd, *args, check=True, input=None):
    result = subprocess.run(
        [sys.executable, GRAFT_BIN, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        input=input,
    )
    if check and result.returncode != 0:
        raise AssertionError(
            f"graft {' '.join(args)} failed (exit {result.returncode})\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return result


def run_git(cwd, *args, check=True):
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t.com",
             "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t.com"},
    )
    if check and result.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {result.stderr}")
    return result


def write(path, content):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    mode = "wb" if isinstance(content, bytes) else "w"
    with open(path, mode) as f:
        f.write(content)


def read(path):
    with open(path, "rb") as f:
        return f.read()
