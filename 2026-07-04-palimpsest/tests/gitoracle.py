"""Helpers for running the real `git` binary as a verification oracle.

Palimpsest never calls `git` at runtime — these helpers are test-only, used
to prove our object encoding is byte-identical to real Git's.
"""

from __future__ import annotations

import os
import shutil
import subprocess

GIT_AVAILABLE = shutil.which("git") is not None

FIXED_ENV = {
    "GIT_AUTHOR_NAME": "Palimpsest",
    "GIT_AUTHOR_EMAIL": "palimpsest@local",
    "GIT_COMMITTER_NAME": "Palimpsest",
    "GIT_COMMITTER_EMAIL": "palimpsest@local",
}


def run_git(args: list[str], cwd: str, env_extra: dict | None = None) -> str:
    env = dict(os.environ)
    env.update(FIXED_ENV)
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["HOME"] = cwd  # isolate from any user gitconfig with signing enabled
    if env_extra:
        env.update(env_extra)
    result = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false"] + args,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed: {result.stdout}\n{result.stderr}"
        )
    return result.stdout


def git_init(cwd: str) -> None:
    run_git(["init", "-q"], cwd)


def git_hash_object(cwd: str, path: str) -> str:
    return run_git(["hash-object", path], cwd).strip()


EMPTY_TREE_SHA = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


def git_mktree(cwd: str, entries: list[tuple[str, str, str, str]]) -> str:
    """entries: list of (mode, name, sha, kind)."""
    if not entries:
        return EMPTY_TREE_SHA
    lines = []
    for mode, name, sha, kind in entries:
        lines.append(f"{mode} {kind} {sha}\t{name}")
    payload = "\n".join(lines) + "\n"
    result = subprocess.run(
        ["git", "mktree"],
        cwd=cwd,
        input=payload,
        text=True,
        capture_output=True,
        env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "HOME": cwd},
    )
    if result.returncode != 0:
        raise RuntimeError(f"git mktree failed: {result.stderr}")
    return result.stdout.strip()


def git_commit_tree(
    cwd: str, tree: str, parents: list[str], message: str, timestamp: int
) -> str:
    args = ["commit-tree", tree, "-m", message]
    for p in parents:
        args += ["-p", p]
    env_extra = {
        "GIT_AUTHOR_DATE": f"{timestamp} +0000",
        "GIT_COMMITTER_DATE": f"{timestamp} +0000",
    }
    return run_git(args, cwd, env_extra).strip()
