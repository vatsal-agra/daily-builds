"""Three-way merge: BFS merge-base + recursive tree merge + line-level
3-way content merge with git-style conflict markers.
"""
import os
from collections import namedtuple

from . import diffalgo, objecthash, treeops

MergeResult = namedtuple("MergeResult", ["message", "conflicts", "commit_sha"])


class MergeError(Exception):
    pass


def _ancestor_distances(repo, start):
    dist = {start: 0}
    queue = [start]
    while queue:
        cur = queue.pop(0)
        _, content = repo.read_object_any(cur)
        info = objecthash.decode_commit(content)
        for p in info["parents"]:
            if p not in dist:
                dist[p] = dist[cur] + 1
                queue.append(p)
    return dist


def find_merge_base(repo, a_sha, b_sha):
    da = _ancestor_distances(repo, a_sha)
    db = _ancestor_distances(repo, b_sha)
    common = set(da) & set(db)
    if not common:
        return None
    return min(common, key=lambda c: da[c] + db[c])


def _reconstruct_side(base, lo, hi, items, seq):
    """Rebuild one side's content over base range [lo, hi): apply each
    change item's slice of `seq` at its own base position, and fall back to
    `base` (unchanged) everywhere else in the range.
    """
    out = []
    pos = lo
    for i1, i2, j1, j2 in items:
        if i1 > pos:
            out.extend(base[pos:i1])
        out.extend(seq[j1:j2])
        pos = i2
    if pos < hi:
        out.extend(base[pos:hi])
    return out


def merge3_lines(base, ours, theirs, ours_label="ours", theirs_label="theirs"):
    """Line-level 3-way merge. Returns (merged_lines, had_conflict).

    Changed regions (in base coordinates) that *overlap or touch* are
    grouped and conflict if the two sides disagree; changes separated by at
    least one unchanged base line merge independently. This matches real
    git's behavior (verified empirically): editing two lines with a blank
    or unchanged line between them merges cleanly, but editing two
    immediately-adjacent lines (no separating context) conflicts even
    though the edited ranges don't literally overlap.
    """
    from . import diffalgo

    ops_o = [(i1, i2, j1, j2) for tag, i1, i2, j1, j2 in diffalgo.opcodes(base, ours) if tag != "equal"]
    ops_t = [(i1, i2, j1, j2) for tag, i1, i2, j1, j2 in diffalgo.opcodes(base, theirs) if tag != "equal"]

    changes = [("o",) + c for c in ops_o] + [("t",) + c for c in ops_t]
    changes.sort(key=lambda c: c[1])

    groups = []
    cur, cur_end = [], None
    for c in changes:
        s, e = c[1], c[2]
        if cur and s <= cur_end:
            cur.append(c)
            cur_end = max(cur_end, e)
        else:
            if cur:
                groups.append(cur)
            cur, cur_end = [c], e
    if cur:
        groups.append(cur)

    result = []
    conflict = False
    prev_end = 0
    for group in groups:
        lo = min(c[1] for c in group)
        hi = max(c[2] for c in group)
        result.extend(base[prev_end:lo])

        o_items = [c[1:] for c in group if c[0] == "o"]
        t_items = [c[1:] for c in group if c[0] == "t"]
        ours_seg = _reconstruct_side(base, lo, hi, o_items, ours)
        theirs_seg = _reconstruct_side(base, lo, hi, t_items, theirs)

        if not t_items:
            # only ours touched this region -> take it, no comparison needed
            result.extend(ours_seg)
        elif not o_items:
            result.extend(theirs_seg)
        elif ours_seg == theirs_seg:
            result.extend(ours_seg)
        else:
            conflict = True
            result.append(f"<<<<<<< {ours_label}")
            result.extend(ours_seg)
            result.append("=======")
            result.extend(theirs_seg)
            result.append(f">>>>>>> {theirs_label}")
        prev_end = hi
    result.extend(base[prev_end:len(base)])
    return result, conflict


def _decode_lines(repo, sha1):
    if sha1 is None:
        return []
    _, content = repo.read_object_any(sha1)
    text = content.decode("utf-8", errors="replace")
    return text.split("\n")[:-1] if text.endswith("\n") else text.split("\n")


def _merge_trees(repo, base_paths, ours_paths, theirs_paths, ours_label, theirs_label):
    merged = {}
    conflicts = []
    all_paths = sorted(set(base_paths) | set(ours_paths) | set(theirs_paths))
    for path in all_paths:
        b = base_paths.get(path)
        o = ours_paths.get(path)
        t = theirs_paths.get(path)
        if o == t:
            if o is not None:
                merged[path] = o
            continue
        if o == b:
            if t is not None:
                merged[path] = t
            continue
        if t == b:
            if o is not None:
                merged[path] = o
            continue
        if o is None or t is None:
            conflicts.append(path)
            if o is not None:
                merged[path] = o
            elif t is not None:
                merged[path] = t
            continue
        if o[0] != t[0]:
            conflicts.append(path)
            merged[path] = o
            continue
        _, ours_bytes = repo.read_object_any(o[1])
        _, theirs_bytes = repo.read_object_any(t[1])
        if diffalgo.is_binary(ours_bytes) or diffalgo.is_binary(theirs_bytes):
            # can't line-merge binary content; keep ours and flag for manual resolution
            conflicts.append(path)
            merged[path] = o
            continue
        base_lines = _decode_lines(repo, b[1] if b else None)
        ours_lines = _decode_lines(repo, o[1])
        theirs_lines = _decode_lines(repo, t[1])
        merged_lines, had_conflict = merge3_lines(
            base_lines, ours_lines, theirs_lines, ours_label, theirs_label
        )
        text = "\n".join(merged_lines)
        if merged_lines:
            text += "\n"
        sha1 = repo.write_object("blob", text.encode("utf-8"))
        merged[path] = (o[0], sha1)
        if had_conflict:
            conflicts.append(path)
    return merged, sorted(set(conflicts))


def merge(repo, other_name, author_name, author_email):
    from .cli import _apply_tree_to_worktree  # local import: avoid a cli<->merge import cycle
    import time

    ours_branch = repo.current_branch()
    if ours_branch is None:
        raise MergeError("cannot merge: HEAD is detached")
    ours_sha = repo.resolve_head()
    if ours_sha is None:
        raise MergeError("cannot merge into a branch with no commits yet")
    theirs_sha = repo.resolve_ref_or_sha(other_name)

    if ours_sha == theirs_sha:
        return MergeResult("Already up to date.", [], None)

    base_sha = find_merge_base(repo, ours_sha, theirs_sha)
    if base_sha is None:
        raise MergeError(f"refusing to merge unrelated histories with {other_name!r}")

    if base_sha == theirs_sha:
        return MergeResult("Already up to date.", [], None)

    current_paths = treeops.flatten_tree(repo, treeops.tree_of_commit(repo, ours_sha))

    if base_sha == ours_sha:
        # fast-forward
        target_tree = treeops.tree_of_commit(repo, theirs_sha)
        target_paths = treeops.flatten_tree(repo, target_tree)
        _apply_tree_to_worktree(repo, target_paths, current_paths)
        repo.write_ref(f"refs/heads/{ours_branch}", theirs_sha)
        return MergeResult(f"Fast-forward to {theirs_sha[:10]}", [], theirs_sha)

    base_paths = treeops.flatten_tree(repo, treeops.tree_of_commit(repo, base_sha))
    ours_paths = current_paths
    theirs_paths = treeops.flatten_tree(repo, treeops.tree_of_commit(repo, theirs_sha))

    merged_paths, conflicts = _merge_trees(
        repo, base_paths, ours_paths, theirs_paths, ours_branch, other_name
    )

    _apply_tree_to_worktree(repo, merged_paths, current_paths)

    if conflicts:
        with open(os.path.join(repo.gitdir, "MERGE_HEAD"), "w") as f:
            f.write(theirs_sha + "\n")
        with open(os.path.join(repo.gitdir, "MERGE_MSG"), "w") as f:
            f.write(f"Merge branch '{other_name}' into {ours_branch}\n")
        return MergeResult(
            f"Auto-merging produced {len(conflicts)} conflict(s)", conflicts, None
        )

    tree_sha = treeops.build_tree_from_paths(repo, merged_paths)
    ts = int(time.time())
    author = (author_name, author_email, ts, "+0000")
    message = f"Merge branch '{other_name}' into {ours_branch}\n"
    content = objecthash.encode_commit(tree_sha, [ours_sha, theirs_sha], author, author, message)
    commit_sha = repo.write_object("commit", content)
    repo.write_ref(f"refs/heads/{ours_branch}", commit_sha)
    return MergeResult(f"Merge made ({commit_sha[:10]}).", [], commit_sha)
