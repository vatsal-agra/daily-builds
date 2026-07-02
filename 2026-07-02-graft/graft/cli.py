import argparse
import os
import sys
import time

from . import diffalgo, objecthash, treeops, worktree
from .index import IndexEntry, read_index, write_index
from .repository import RepoError, Repository

DEFAULT_AUTHOR_NAME = os.environ.get("GRAFT_AUTHOR_NAME", "Graft User")
DEFAULT_AUTHOR_EMAIL = os.environ.get("GRAFT_AUTHOR_EMAIL", "graft@example.com")


def _err(msg):
    print(f"graft: {msg}", file=sys.stderr)
    return 1


def _repo():
    return Repository.discover()


# ------------------------------------------------------------------ init --

def cmd_init(args):
    try:
        repo = Repository.init(args.path)
    except RepoError as e:
        return _err(str(e))
    print(f"Initialized empty Graft repository in {repo.gitdir}")
    return 0


# ------------------------------------------------------------ hash-object --

def cmd_hash_object(args):
    repo = _repo() if args.write else None
    with open(args.file, "rb") as f:
        content = f.read()
    if args.write:
        sha1 = repo.write_object(args.type, content)
    else:
        sha1, _ = objecthash.hash_bytes(args.type, content)
    print(sha1)
    return 0


def cmd_cat_file(args):
    repo = _repo()
    try:
        sha1 = repo.resolve_ref_or_sha(args.object)
        obj_type, content = repo.read_object_any(sha1)
    except (RepoError, objecthash.ObjectError) as e:
        return _err(str(e))
    if args.show_type:
        print(obj_type)
        return 0
    if args.size:
        print(len(content))
        return 0
    if obj_type == "tree":
        for entry in objecthash.decode_tree(content):
            kind = "tree" if entry.is_dir() else "blob"
            print(f"{entry.mode} {kind} {entry.sha1}\t{entry.name}")
    elif obj_type == "commit":
        sys.stdout.write(content.decode("utf-8"))
    else:
        sys.stdout.buffer.write(content)
    return 0


# ----------------------------------------------------------- add / rm ----

def cmd_add(args):
    repo = _repo()
    entries = read_index(repo.index_path)
    all_files = worktree.list_worktree_files(repo.worktree)
    targets = set()
    for p in args.paths:
        p = p.rstrip("/")
        abspath = os.path.join(repo.worktree, p)
        if os.path.isdir(abspath) or p == ".":
            prefix = "" if p == "." else p + "/"
            targets |= {f for f in all_files if f.startswith(prefix)}
        else:
            rel = os.path.relpath(abspath, repo.worktree).replace(os.sep, "/")
            if rel not in all_files:
                return _err(f"pathspec '{p}' did not match any tracked files")
            targets.add(rel)
    if not targets:
        return _err("nothing specified, nothing added")
    for rel in sorted(targets):
        abspath = os.path.join(repo.worktree, rel)
        mode, sha1 = worktree.hash_working_file(abspath)
        content = worktree.read_blob_bytes(abspath)
        repo.write_object("blob", content)
        st = os.lstat(abspath)
        entries[rel] = IndexEntry(rel, mode, sha1, st.st_size, st.st_mtime)
    write_index(repo.index_path, entries)
    return 0


def cmd_rm(args):
    repo = _repo()
    entries = read_index(repo.index_path)
    missing = [p for p in args.paths if p not in entries]
    if missing:
        return _err(f"pathspec '{missing[0]}' did not match any staged files")
    for p in args.paths:
        del entries[p]
        if not args.cached:
            abspath = os.path.join(repo.worktree, p)
            if os.path.exists(abspath):
                os.remove(abspath)
    write_index(repo.index_path, entries)
    return 0


# --------------------------------------------------------------- status --

def _head_paths(repo):
    head_sha = repo.resolve_head()
    tree_sha = treeops.tree_of_commit(repo, head_sha)
    return treeops.flatten_tree(repo, tree_sha)


def compute_status(repo):
    """Return dict with staged/unstaged/untracked change lists."""
    head_paths = _head_paths(repo)
    index_entries = read_index(repo.index_path)
    wt_files = set(worktree.list_worktree_files(repo.worktree))

    staged_new, staged_modified, staged_deleted = [], [], []
    for path, entry in index_entries.items():
        if path not in head_paths:
            staged_new.append(path)
        elif head_paths[path][1] != entry.sha1:
            staged_modified.append(path)
    for path in head_paths:
        if path not in index_entries:
            staged_deleted.append(path)

    unstaged_modified, unstaged_deleted = [], []
    for path, entry in index_entries.items():
        abspath = os.path.join(repo.worktree, path)
        if not os.path.exists(abspath):
            unstaged_deleted.append(path)
            continue
        _, sha1 = worktree.hash_working_file(abspath)
        if sha1 != entry.sha1:
            unstaged_modified.append(path)

    untracked = sorted(wt_files - set(index_entries))

    return {
        "staged_new": sorted(staged_new),
        "staged_modified": sorted(staged_modified),
        "staged_deleted": sorted(staged_deleted),
        "unstaged_modified": sorted(unstaged_modified),
        "unstaged_deleted": sorted(unstaged_deleted),
        "untracked": untracked,
    }


def cmd_status(args):
    repo = _repo()
    st = compute_status(repo)
    branch = repo.current_branch()
    if branch:
        print(f"On branch {branch}")
    else:
        print(f"HEAD detached at {repo.resolve_head()[:10]}")

    any_changes = False
    if st["staged_new"] or st["staged_modified"] or st["staged_deleted"]:
        any_changes = True
        print("\nChanges to be committed:")
        for p in st["staged_new"]:
            print(f"\tnew file:   {p}")
        for p in st["staged_modified"]:
            print(f"\tmodified:   {p}")
        for p in st["staged_deleted"]:
            print(f"\tdeleted:    {p}")

    if st["unstaged_modified"] or st["unstaged_deleted"]:
        any_changes = True
        print("\nChanges not staged for commit:")
        for p in st["unstaged_modified"]:
            print(f"\tmodified:   {p}")
        for p in st["unstaged_deleted"]:
            print(f"\tdeleted:    {p}")

    if st["untracked"]:
        any_changes = True
        print("\nUntracked files:")
        for p in st["untracked"]:
            print(f"\t{p}")

    if not any_changes:
        print("\nnothing to commit, working tree clean")
    return 0


# --------------------------------------------------------------- commit --

def cmd_commit(args):
    repo = _repo()
    entries = read_index(repo.index_path)
    head_sha = repo.resolve_head()
    head_tree = treeops.tree_of_commit(repo, head_sha)
    head_paths = treeops.flatten_tree(repo, head_tree)

    paths = {path: (e.mode, e.sha1) for path, e in entries.items()}
    if paths == head_paths and head_sha is not None:
        return _err("nothing to commit, working tree clean")
    if not args.message:
        return _err("commit message required (-m)")

    tree_sha = treeops.build_tree_from_paths(repo, paths)
    parents = [head_sha] if head_sha else []
    ts = int(args.date) if args.date else int(time.time())
    author = (DEFAULT_AUTHOR_NAME, DEFAULT_AUTHOR_EMAIL, ts, "+0000")
    content = objecthash.encode_commit(tree_sha, parents, author, author, args.message)
    commit_sha = repo.write_object("commit", content)

    branch = repo.current_branch()
    if branch:
        repo.write_ref(f"refs/heads/{branch}", commit_sha)
    else:
        repo.write_head_detached(commit_sha)
    print(f"[{branch or 'HEAD detached'} {commit_sha[:10]}] {args.message.splitlines()[0]}")
    return 0


# ------------------------------------------------------------------ log --

def _iter_ancestors(repo, start_sha):
    seen = set()
    stack = [start_sha] if start_sha else []
    order = []
    while stack:
        sha = stack.pop(0)
        if sha in seen or sha is None:
            continue
        seen.add(sha)
        _, content = repo.read_object_any(sha)
        info = objecthash.decode_commit(content)
        order.append((sha, info))
        stack.extend(info["parents"])
    return order


def cmd_log(args):
    repo = _repo()
    start = repo.resolve_ref_or_sha(args.rev) if args.rev else repo.resolve_head()
    if start is None:
        print("fatal: your current branch does not have any commits yet", file=sys.stderr)
        return 1
    for sha, info in _iter_ancestors(repo, start):
        print(f"commit {sha}")
        if len(info["parents"]) > 1:
            print(f"Merge: {' '.join(p[:10] for p in info['parents'])}")
        print(f"Author: {info['author']}")
        print()
        for line in info["message"].rstrip("\n").split("\n"):
            print(f"    {line}")
        print()
    return 0


# --------------------------------------------------------------- branch --

def cmd_branch(args):
    repo = _repo()
    if args.delete:
        if args.delete == repo.current_branch():
            return _err(f"cannot delete branch '{args.delete}' checked out")
        if repo.read_ref(f"refs/heads/{args.delete}") is None:
            return _err(f"branch '{args.delete}' not found")
        repo.delete_ref(f"refs/heads/{args.delete}")
        print(f"Deleted branch {args.delete}")
        return 0
    if args.name:
        start_sha = repo.resolve_ref_or_sha(args.start) if args.start else repo.resolve_head()
        if start_sha is None:
            return _err("cannot create a branch with no commits yet")
        if repo.read_ref(f"refs/heads/{args.name}") is not None:
            return _err(f"branch '{args.name}' already exists")
        repo.write_ref(f"refs/heads/{args.name}", start_sha)
        return 0
    current = repo.current_branch()
    for b in repo.list_branches():
        marker = "*" if b == current else " "
        print(f"{marker} {b}")
    return 0


# ------------------------------------------------------------- checkout --

def _apply_tree_to_worktree(repo, target_paths, current_paths):
    for path in current_paths:
        if path not in target_paths:
            abspath = os.path.join(repo.worktree, path)
            if os.path.exists(abspath):
                os.remove(abspath)
    for path, (mode, sha1) in target_paths.items():
        abspath = os.path.join(repo.worktree, path)
        os.makedirs(os.path.dirname(abspath) or repo.worktree, exist_ok=True)
        _, content = repo.read_object_any(sha1)
        if mode == "120000":
            if os.path.islink(abspath) or os.path.exists(abspath):
                os.remove(abspath)
            os.symlink(content.decode("utf-8"), abspath)
        else:
            with open(abspath, "wb") as f:
                f.write(content)
            if mode == "100755":
                os.chmod(abspath, 0o755)
    entries = {
        path: IndexEntry(path, mode, sha1, len(repo.read_object_any(sha1)[1]), time.time())
        for path, (mode, sha1) in target_paths.items()
    }
    write_index(repo.index_path, entries)


def cmd_checkout(args):
    repo = _repo()
    st = compute_status(repo)
    dirty = st["unstaged_modified"] or st["unstaged_deleted"] or st["staged_new"] or st["staged_modified"] or st["staged_deleted"]
    if dirty and not args.force:
        return _err("you have uncommitted changes; commit, stash, or use --force")

    branch_ref = f"refs/heads/{args.target}"
    is_branch = repo.read_ref(branch_ref) is not None
    target_sha = repo.resolve_ref_or_sha(args.target)
    target_tree = treeops.tree_of_commit(repo, target_sha)
    target_paths = treeops.flatten_tree(repo, target_tree)
    current_paths = read_index(repo.index_path)

    _apply_tree_to_worktree(repo, target_paths, current_paths)

    if is_branch:
        repo.write_head_ref(branch_ref)
        print(f"Switched to branch '{args.target}'")
    else:
        repo.write_head_detached(target_sha)
        print(f"Note: checking out {target_sha[:10]} (detached HEAD)")
    return 0


# ------------------------------------------------------------------ diff --

def _blob_lines(repo, sha1):
    if sha1 is None:
        return []
    _, content = repo.read_object_any(sha1)
    text = content.decode("utf-8", errors="replace")
    return text.split("\n")[:-1] if text.endswith("\n") else text.split("\n")


def _working_lines(abspath):
    if not os.path.exists(abspath):
        return None
    with open(abspath, "rb") as f:
        text = f.read().decode("utf-8", errors="replace")
    return text.split("\n")[:-1] if text.endswith("\n") else text.split("\n")


def cmd_diff(args):
    repo = _repo()
    out_lines = []
    if args.cached:
        head_sha = repo.resolve_head()
        head_paths = treeops.flatten_tree(repo, treeops.tree_of_commit(repo, head_sha))
        index_entries = read_index(repo.index_path)
        all_paths = sorted(set(head_paths) | set(index_entries))
        for path in all_paths:
            old_sha = head_paths.get(path, (None, None))[1]
            new_sha = index_entries[path].sha1 if path in index_entries else None
            if old_sha == new_sha:
                continue
            out_lines += diffalgo.unified_diff(
                _blob_lines(repo, old_sha), _blob_lines(repo, new_sha),
                f"a/{path}" if old_sha else "/dev/null",
                f"b/{path}" if new_sha else "/dev/null",
            )
    else:
        index_entries = read_index(repo.index_path)
        wt_files = set(worktree.list_worktree_files(repo.worktree))
        all_paths = sorted(set(index_entries) | wt_files)
        for path in all_paths:
            old_sha = index_entries[path].sha1 if path in index_entries else None
            abspath = os.path.join(repo.worktree, path)
            new_lines = _working_lines(abspath)
            old_lines = _blob_lines(repo, old_sha)
            if new_lines is None:
                new_lines = []
            if old_sha is not None:
                _, old_content = repo.read_object_any(old_sha)
                new_content = worktree.read_blob_bytes(abspath) if os.path.exists(abspath) else b""
                if old_content == new_content:
                    continue
            out_lines += diffalgo.unified_diff(
                old_lines, new_lines,
                f"a/{path}" if old_sha else "/dev/null",
                f"b/{path}" if os.path.exists(abspath) else "/dev/null",
            )
    print("\n".join(out_lines))
    return 0


# ---------------------------------------------------------------- merge --

def cmd_merge(args):
    from . import merge as merge_mod
    repo = _repo()
    try:
        result = merge_mod.merge(repo, args.branch, DEFAULT_AUTHOR_NAME, DEFAULT_AUTHOR_EMAIL)
    except merge_mod.MergeError as e:
        return _err(str(e))
    print(result.message)
    if result.conflicts:
        print("Automatic merge failed; fix conflicts and then commit the result.")
        for path in result.conflicts:
            print(f"CONFLICT (content): Merge conflict in {path}")
        return 1
    return 0


# ------------------------------------------------------------------- gc --

def cmd_gc(args):
    from . import packfile as packmod
    repo = _repo()
    stats = packmod.pack_repository(repo)
    print(
        f"Packed {stats['object_count']} objects "
        f"({stats['loose_bytes']} bytes loose -> {stats['pack_bytes']} bytes packed, "
        f"{stats['ratio']:.1f}x)"
    )
    return 0


# ------------------------------------------------------------------ viz --

def cmd_viz(args):
    from . import viz as viz_mod
    repo = _repo()
    out_path = viz_mod.render(repo, args.output)
    print(f"Wrote {out_path}")
    return 0


# --------------------------------------------------------------- parser --

def build_parser():
    p = argparse.ArgumentParser(prog="graft", description="A version control system from scratch.")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("init")
    sp.add_argument("path", nargs="?", default=".")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("hash-object")
    sp.add_argument("file")
    sp.add_argument("-t", "--type", default="blob", choices=objecthash.VALID_TYPES)
    sp.add_argument("-w", "--write", action="store_true")
    sp.set_defaults(func=cmd_hash_object)

    sp = sub.add_parser("cat-file")
    sp.add_argument("object")
    sp.add_argument("-t", dest="show_type", action="store_true")
    sp.add_argument("-s", dest="size", action="store_true")
    sp.set_defaults(func=cmd_cat_file)

    sp = sub.add_parser("add")
    sp.add_argument("paths", nargs="+")
    sp.set_defaults(func=cmd_add)

    sp = sub.add_parser("rm")
    sp.add_argument("paths", nargs="+")
    sp.add_argument("--cached", action="store_true")
    sp.set_defaults(func=cmd_rm)

    sp = sub.add_parser("status")
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("commit")
    sp.add_argument("-m", "--message", default=None)
    sp.add_argument("--date", default=None, help="override unix timestamp (testing)")
    sp.set_defaults(func=cmd_commit)

    sp = sub.add_parser("log")
    sp.add_argument("rev", nargs="?", default=None)
    sp.set_defaults(func=cmd_log)

    sp = sub.add_parser("branch")
    sp.add_argument("name", nargs="?", default=None)
    sp.add_argument("start", nargs="?", default=None)
    sp.add_argument("-d", "--delete", default=None)
    sp.set_defaults(func=cmd_branch)

    sp = sub.add_parser("checkout")
    sp.add_argument("target")
    sp.add_argument("-f", "--force", action="store_true")
    sp.set_defaults(func=cmd_checkout)

    sp = sub.add_parser("diff")
    sp.add_argument("--cached", action="store_true")
    sp.set_defaults(func=cmd_diff)

    sp = sub.add_parser("merge")
    sp.add_argument("branch")
    sp.set_defaults(func=cmd_merge)

    sp = sub.add_parser("gc")
    sp.set_defaults(func=cmd_gc)

    sp = sub.add_parser("viz")
    sp.add_argument("-o", "--output", default="graft-viz.html")
    sp.set_defaults(func=cmd_viz)

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args) or 0
    except RepoError as e:
        return _err(str(e))
    except objecthash.ObjectError as e:
        return _err(str(e))


if __name__ == "__main__":
    sys.exit(main())
