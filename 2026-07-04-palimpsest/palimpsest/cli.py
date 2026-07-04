"""Command-line interface, argparse subcommands mirroring git's UX."""

from __future__ import annotations

import argparse
import os
import sys

from . import objects as objmod
from .diffalgo import unified_diff
from .repository import NotARepository, RepoError, Repository, find_repo_root


def _repo_from_cwd() -> Repository:
    root = find_repo_root(".")
    return Repository(root)


def _lines(data: bytes) -> tuple[list[str], bool]:
    """Decode bytes to a list of lines (no trailing newlines) plus whether
    the content ended with a trailing newline."""
    text = data.decode("utf-8", errors="replace")
    if text == "":
        return [], True
    ends_with_nl = text.endswith("\n")
    body = text[:-1] if ends_with_nl else text
    return body.split("\n"), ends_with_nl


def cmd_init(args: argparse.Namespace) -> int:
    path = args.path or "."
    try:
        repo = Repository.init(path)
    except RepoError as e:
        print(f"plm: error: {e}", file=sys.stderr)
        return 1
    print(f"Initialized empty Palimpsest repository in {repo.plm_dir}")
    return 0


def cmd_hash_object(args: argparse.Namespace) -> int:
    if args.stdin:
        data = sys.stdin.buffer.read()
    else:
        with open(args.file, "rb") as f:
            data = f.read()
    sha, store = objmod.hash_object_bytes(args.type, data)
    if args.write:
        repo = _repo_from_cwd()
        repo.objects.write_raw(args.type, data)
    print(sha)
    return 0


def cmd_cat_file(args: argparse.Namespace) -> int:
    repo = _repo_from_cwd()
    try:
        obj_type, payload = repo.objects.read_raw(args.sha)
    except KeyError as e:
        print(f"plm: error: {e}", file=sys.stderr)
        return 1
    if args.type_only:
        print(obj_type)
    elif args.size_only:
        print(len(payload))
    elif obj_type == "tree":
        for entry in objmod.decode_tree(payload):
            kind = "tree" if entry.mode == objmod.MODE_DIR else "blob"
            print(f"{entry.mode} {kind} {entry.sha}\t{entry.name}")
    elif hasattr(sys.stdout, "buffer"):
        sys.stdout.buffer.write(payload)
    else:
        sys.stdout.write(payload.decode("utf-8", errors="replace"))
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    repo = _repo_from_cwd()
    try:
        staged = repo.add(args.paths)
    except RepoError as e:
        print(f"plm: error: {e}", file=sys.stderr)
        return 1
    for p in staged:
        print(f"add '{p}'")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    repo = _repo_from_cwd()
    st = repo.status()
    branch = repo.head_ref()
    if branch:
        print(f"On branch {branch}")
    else:
        print(f"HEAD detached at {repo.head_commit()[:8]}")
    if repo.head_commit() is None:
        print("\nNo commits yet")
    if st["staged_added"] or st["staged_modified"] or st["staged_deleted"]:
        print("\nChanges to be committed:")
        for p in st["staged_added"]:
            print(f"\tnew file:   {p}")
        for p in st["staged_modified"]:
            print(f"\tmodified:   {p}")
        for p in st["staged_deleted"]:
            print(f"\tdeleted:    {p}")
    if st["not_staged_modified"] or st["not_staged_deleted"]:
        print("\nChanges not staged for commit:")
        for p in st["not_staged_modified"]:
            print(f"\tmodified:   {p}")
        for p in st["not_staged_deleted"]:
            print(f"\tdeleted:    {p}")
    if st["untracked"]:
        print("\nUntracked files:")
        for p in st["untracked"]:
            print(f"\t{p}")
    if st["clean"]:
        print("\nnothing to commit, working tree clean")
    return 0


def cmd_commit(args: argparse.Namespace) -> int:
    repo = _repo_from_cwd()
    try:
        sha = repo.commit(args.message, allow_empty=args.allow_empty)
    except RepoError as e:
        print(f"plm: error: {e}", file=sys.stderr)
        return 1
    branch = repo.head_ref() or "detached HEAD"
    print(f"[{branch} {sha[:8]}] {args.message.splitlines()[0]}")
    return 0


def cmd_log(args: argparse.Namespace) -> int:
    repo = _repo_from_cwd()
    entries = repo.log()
    if not entries:
        print("No commits yet")
        return 0
    for sha, commit in entries:
        print(f"commit {sha}")
        for p in commit.parents[1:]:
            print(f"merge:  {p[:8]}")
        print(f"Author: {commit.author_name} <{commit.author_email}>")
        print(f"Date:   {commit.author_time} {commit.author_tz}")
        print()
        for line in commit.message.rstrip("\n").split("\n"):
            print(f"    {line}")
        print()
    return 0


def cmd_branch(args: argparse.Namespace) -> int:
    repo = _repo_from_cwd()
    if args.name is None:
        current = repo.head_ref()
        for b in repo.list_branches():
            marker = "*" if b == current else " "
            print(f"{marker} {b}")
        return 0
    try:
        repo.create_branch(args.name)
    except RepoError as e:
        print(f"plm: error: {e}", file=sys.stderr)
        return 1
    print(f"Created branch '{args.name}'")
    return 0


def cmd_checkout(args: argparse.Namespace) -> int:
    repo = _repo_from_cwd()
    try:
        sha = repo.checkout(args.ref, force=args.force)
    except RepoError as e:
        print(f"plm: error: {e}", file=sys.stderr)
        return 1
    print(f"Switched to {args.ref!r} ({sha[:8]})")
    return 0


def _read_side(repo: Repository, spec: str, path: str) -> tuple[list[str], bool, bool]:
    """Return (lines, had_trailing_newline, exists) for `spec` on `path`.

    spec is one of "worktree", "index", or a resolved commit sha.
    """
    if spec == "worktree":
        full = os.path.join(repo.root, path)
        if not os.path.exists(full):
            return [], True, False
        with open(full, "rb") as f:
            data = f.read()
        lines, nl = _lines(data)
        return lines, nl, True
    if spec == "index":
        for e in repo.read_index():
            if e.path == path:
                data = repo.objects.read_blob(e.sha)
                lines, nl = _lines(data)
                return lines, nl, True
        return [], True, False
    # commit sha
    commit = repo.objects.read_commit(spec)
    files = repo.flatten_tree(commit.tree)
    if path not in files:
        return [], True, False
    _mode, sha = files[path]
    data = repo.objects.read_blob(sha)
    lines, nl = _lines(data)
    return lines, nl, True


def cmd_diff(args: argparse.Namespace) -> int:
    repo = _repo_from_cwd()
    revs = args.revisions
    if len(revs) == 0:
        left, right = "index", "worktree"
        left_label, right_label = "index", "working tree"
    elif len(revs) == 1:
        sha = repo.resolve_ref(revs[0])
        if sha is None:
            print(f"plm: error: unknown revision: {revs[0]!r}", file=sys.stderr)
            return 1
        left, right = sha, "worktree"
        left_label, right_label = revs[0], "working tree"
    elif len(revs) == 2:
        sha_a = repo.resolve_ref(revs[0])
        sha_b = repo.resolve_ref(revs[1])
        if sha_a is None or sha_b is None:
            print("plm: error: unknown revision", file=sys.stderr)
            return 1
        left, right = sha_a, sha_b
        left_label, right_label = revs[0], revs[1]
    else:
        print("plm: error: diff takes at most 2 revisions", file=sys.stderr)
        return 1

    if args.staged:
        left, right = repo.head_commit() or "index", "index"
        left_label, right_label = "HEAD", "index"
        if left == "index":  # unborn HEAD: diff against empty tree
            left = None

    def all_paths_for(spec):
        if spec is None:
            return set()
        if spec == "worktree":
            return set(repo._walk_working_files())
        if spec == "index":
            return {e.path for e in repo.read_index()}
        commit = repo.objects.read_commit(spec)
        return set(repo.flatten_tree(commit.tree).keys())

    paths = sorted(all_paths_for(left) | all_paths_for(right))
    out_chunks = []
    for path in paths:
        if left is None:
            a_lines, a_nl, a_exists = [], True, False
        else:
            a_lines, a_nl, a_exists = _read_side(repo, left, path)
        b_lines, b_nl, b_exists = _read_side(repo, right, path)
        if a_lines == b_lines and a_exists == b_exists:
            continue
        label_a = f"{left_label}:{path}" if a_exists else "/dev/null"
        label_b = f"{right_label}:{path}" if b_exists else "/dev/null"
        diff_text = unified_diff(a_lines, b_lines, label_a, label_b)
        if diff_text:
            out_chunks.append(diff_text)
    sys.stdout.write("".join(out_chunks))
    return 0


def cmd_merge(args: argparse.Namespace) -> int:
    from .merge import merge_branch

    repo = _repo_from_cwd()
    try:
        result = merge_branch(repo, args.branch)
    except RepoError as e:
        print(f"plm: error: {e}", file=sys.stderr)
        return 1
    if result.fast_forward:
        print(f"Fast-forward to {result.commit_sha[:8]}")
    elif result.conflicts:
        print(f"Automatic merge failed; fix conflicts and commit:")
        for p in result.conflicts:
            print(f"\tboth modified: {p}")
        return 1
    else:
        print(f"Merge made: {result.commit_sha[:8]}")
    return 0


def cmd_viz(args: argparse.Namespace) -> int:
    from .viz import generate_html

    repo = _repo_from_cwd()
    html = generate_html(repo)
    out_path = args.output or "palimpsest-viz.html"
    with open(out_path, "w") as f:
        f.write(html)
    print(f"Wrote {out_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="plm", description="Palimpsest version control")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("init", help="create a new repository")
    sp.add_argument("path", nargs="?", default=".")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("hash-object", help="compute object hash")
    sp.add_argument("file", nargs="?")
    sp.add_argument("-t", "--type", default="blob")
    sp.add_argument("-w", "--write", action="store_true")
    sp.add_argument("--stdin", action="store_true")
    sp.set_defaults(func=cmd_hash_object)

    sp = sub.add_parser("cat-file", help="inspect an object")
    sp.add_argument("sha")
    sp.add_argument("-t", "--type-only", action="store_true")
    sp.add_argument("-s", "--size-only", action="store_true")
    sp.set_defaults(func=cmd_cat_file)

    sp = sub.add_parser("add", help="stage files")
    sp.add_argument("paths", nargs="+")
    sp.set_defaults(func=cmd_add)

    sp = sub.add_parser("status", help="show working tree status")
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("commit", help="record staged changes")
    sp.add_argument("-m", "--message", required=True)
    sp.add_argument("--allow-empty", action="store_true")
    sp.set_defaults(func=cmd_commit)

    sp = sub.add_parser("log", help="show commit history")
    sp.set_defaults(func=cmd_log)

    sp = sub.add_parser("branch", help="list or create branches")
    sp.add_argument("name", nargs="?")
    sp.set_defaults(func=cmd_branch)

    sp = sub.add_parser("checkout", help="switch branches/commits")
    sp.add_argument("ref")
    sp.add_argument("-f", "--force", action="store_true")
    sp.set_defaults(func=cmd_checkout)
    sp2 = sub.add_parser("switch", help="alias for checkout")
    sp2.add_argument("ref")
    sp2.add_argument("-f", "--force", action="store_true")
    sp2.set_defaults(func=cmd_checkout)

    sp = sub.add_parser("diff", help="show changes")
    sp.add_argument("revisions", nargs="*")
    sp.add_argument("--staged", action="store_true")
    sp.set_defaults(func=cmd_diff)

    sp = sub.add_parser("merge", help="merge a branch into HEAD")
    sp.add_argument("branch")
    sp.set_defaults(func=cmd_merge)

    sp = sub.add_parser("viz", help="render an interactive commit graph HTML")
    sp.add_argument("-o", "--output")
    sp.set_defaults(func=cmd_viz)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except NotARepository as e:
        print(f"plm: error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
