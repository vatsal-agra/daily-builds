"""Merge-base (lowest common ancestor) search and three-way line merge."""

from __future__ import annotations

import os
from collections import deque
from dataclasses import dataclass, field

from .diffalgo import opcodes
from .objects import MODE_FILE
from .repository import IndexEntry, RepoError, Repository

CONFLICT_START = "<<<<<<< "
CONFLICT_MID = "======="
CONFLICT_END = ">>>>>>> "


def find_merge_base(repo: Repository, sha_a: str, sha_b: str) -> str | None:
    """Nearest common ancestor of two commits (BFS out from b, first hit
    that is also an ancestor of a — correct whenever there is a single
    best merge base, which covers linear history and simple branch/merge
    graphs; more exotic criss-cross histories may pick *a* valid common
    ancestor rather than the unique best one, same simplification most
    from-scratch implementations make)."""
    if sha_a == sha_b:
        return sha_a
    ancestors_a = repo.all_ancestors(sha_a)
    visited = set()
    queue = deque([sha_b])
    while queue:
        cur = queue.popleft()
        if cur in visited:
            continue
        visited.add(cur)
        if cur in ancestors_a:
            return cur
        c = repo.objects.read_commit(cur)
        queue.extend(c.parents)
    return None


def _hunks(base: list[str], other: list[str]) -> list[tuple[int, int]]:
    """Non-equal (base_start, base_end) ranges from diffing base -> other."""
    return [
        (bs, be)
        for tag, bs, be, _os, _oe in opcodes(base, other)
        if tag != "equal"
    ]


def _touches_window(bs: int, be: int, ws: int, we: int) -> bool:
    if bs == be:  # zero-width insertion point
        return ws <= bs <= we
    return bs < we and be > ws


def _reconstruct(
    base: list[str], other: list[str], window: tuple[int, int]
) -> list[str]:
    """Rebuild `other`'s view of the base window [ws, we) using base<->other
    opcodes: equal ranges come from base, changed ranges (guaranteed to lie
    fully inside the window by construction) come from `other`."""
    ws, we = window
    out: list[str] = []
    for tag, bs, be, os_, oe in opcodes(base, other):
        if not _touches_window(bs, be, ws, we):
            continue
        if tag == "equal":
            lo, hi = max(bs, ws), min(be, we)
            out.extend(base[lo:hi])
        else:
            out.extend(other[os_:oe])
    return out


def three_way_merge_lines(
    base: list[str], ours: list[str], theirs: list[str]
) -> tuple[list[str], bool]:
    """Line-based 3-way merge, diff3-style. Returns (merged_lines, has_conflict)."""
    tagged = [(bs, be, "ours") for bs, be in _hunks(base, ours)] + [
        (bs, be, "theirs") for bs, be in _hunks(base, theirs)
    ]
    if not tagged:
        return list(base), False

    tagged.sort(key=lambda t: (t[0], t[1]))
    windows: list[list] = []  # [start, end, {sides}]
    for bs, be, side in tagged:
        if windows and bs <= windows[-1][1]:
            windows[-1][1] = max(windows[-1][1], be)
            windows[-1][2].add(side)
        else:
            windows.append([bs, be, {side}])

    merged: list[str] = []
    conflict = False
    cursor = 0
    for ws, we, sides in windows:
        merged.extend(base[cursor:ws])
        ours_view = _reconstruct(base, ours, (ws, we))
        theirs_view = _reconstruct(base, theirs, (ws, we))
        if "ours" in sides and "theirs" not in sides:
            merged.extend(ours_view)
        elif "theirs" in sides and "ours" not in sides:
            merged.extend(theirs_view)
        elif ours_view == theirs_view:
            merged.extend(ours_view)
        else:
            conflict = True
            merged.append(CONFLICT_START + "ours")
            merged.extend(ours_view)
            merged.append(CONFLICT_MID)
            merged.extend(theirs_view)
            merged.append(CONFLICT_END + "theirs")
        cursor = we
    merged.extend(base[cursor:])
    return merged, conflict


@dataclass
class MergeResult:
    fast_forward: bool
    commit_sha: str | None
    conflicts: list[str] = field(default_factory=list)


def merge_branch(repo: Repository, branch: str, timestamp: int | None = None) -> MergeResult:
    current_branch = repo.head_ref()
    if current_branch is None:
        raise RepoError("cannot merge while HEAD is detached")

    head_sha = repo.head_commit()
    other_sha = repo.resolve_ref(branch)
    if other_sha is None:
        raise RepoError(f"unknown branch: {branch!r}")
    if head_sha is None:
        raise RepoError("cannot merge: no commits on the current branch yet")

    dirty = repo._dirty_paths()
    if dirty:
        raise RepoError(
            f"your local changes would be overwritten by merge; commit or "
            f"stash first. Dirty paths: {sorted(dirty)}"
        )

    if other_sha == head_sha:
        return MergeResult(fast_forward=True, commit_sha=head_sha)

    base_sha = find_merge_base(repo, head_sha, other_sha)
    if base_sha == head_sha:
        # HEAD is an ancestor of `other` -> fast-forward: move the working
        # tree/index to other_sha's tree, then repoint the current branch.
        repo.checkout(other_sha, force=True)
        repo.update_branch(current_branch, other_sha)
        repo.set_head_to_branch(current_branch)
        return MergeResult(fast_forward=True, commit_sha=other_sha)
    if base_sha == other_sha:
        # Already contains the other branch's work.
        return MergeResult(fast_forward=True, commit_sha=head_sha)

    base_files = repo.flatten_tree(repo.objects.read_commit(base_sha).tree) if base_sha else {}
    ours_files = repo.flatten_tree(repo.objects.read_commit(head_sha).tree)
    theirs_files = repo.flatten_tree(repo.objects.read_commit(other_sha).tree)

    all_paths = sorted(set(base_files) | set(ours_files) | set(theirs_files))
    conflicts: list[str] = []
    new_index: list[IndexEntry] = []

    for path in all_paths:
        base_entry = base_files.get(path)
        ours_entry = ours_files.get(path)
        theirs_entry = theirs_files.get(path)

        if ours_entry == theirs_entry:
            result_entry = ours_entry
        elif base_entry == ours_entry:
            result_entry = theirs_entry
        elif base_entry == theirs_entry:
            result_entry = ours_entry
        else:
            # All three differ (or added/deleted on both sides differently):
            # do a line-level 3-way merge, treating a missing side as empty.
            base_lines = _blob_lines(repo, base_entry)
            ours_lines = _blob_lines(repo, ours_entry)
            theirs_lines = _blob_lines(repo, theirs_entry)
            merged_lines, has_conflict = three_way_merge_lines(
                base_lines, ours_lines, theirs_lines
            )
            content = ("\n".join(merged_lines) + "\n") if merged_lines else ""
            sha = repo.objects.write_blob(content.encode("utf-8"))
            mode = (ours_entry or theirs_entry or (MODE_FILE, None))[0]
            result_entry = (mode, sha)
            if has_conflict:
                conflicts.append(path)

        full = os.path.join(repo.root, path)
        if result_entry is None:
            if os.path.exists(full):
                os.remove(full)
            continue
        mode, sha = result_entry
        os.makedirs(os.path.dirname(full), exist_ok=True)
        data = repo.objects.read_blob(sha)
        with open(full, "wb") as f:
            f.write(data)
        new_index.append(IndexEntry(path=path, mode=mode, sha=sha))

    repo.write_index(new_index)
    repo._prune_empty_dirs()

    if conflicts:
        return MergeResult(fast_forward=False, commit_sha=None, conflicts=conflicts)

    sha = repo.commit(
        f"Merge branch '{branch}' into {current_branch}",
        timestamp=timestamp,
        extra_parents=[other_sha],
    )
    return MergeResult(fast_forward=False, commit_sha=sha)


def _blob_lines(repo: Repository, entry) -> list[str]:
    if entry is None:
        return []
    _mode, sha = entry
    data = repo.objects.read_blob(sha)
    text = data.decode("utf-8", errors="replace")
    if text == "":
        return []
    body = text[:-1] if text.endswith("\n") else text
    return body.split("\n")
