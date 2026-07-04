"""The `strata` command-line interface."""

import argparse
import os
import sys
import time

from .repository import (
    DirtyWorktree, MergeConflict, NotARepository, Repository, RepositoryError,
)
from .objects import InvalidObject
from .store import CorruptObject, ObjectNotFound


def _short(commit_id):
    return commit_id[:10]


def _format_date(timestamp):
    return time.strftime("%a %b %d %H:%M:%S %Y %z", time.localtime(timestamp))


def cmd_init(args):
    path = args.path or "."
    try:
        Repository.init(path)
    except RepositoryError as exc:
        print(f"strata: {exc}", file=sys.stderr)
        return 1
    print(f"Initialized empty Strata repository in {path}/.strata")
    return 0


def cmd_add(args):
    repo = Repository.discover()
    try:
        result = repo.add(args.paths)
    except RepositoryError as exc:
        print(f"strata: {exc}", file=sys.stderr)
        return 1
    for path in result["staged"]:
        print(f"add '{path}'")
    for path in result["removed"]:
        print(f"remove '{path}'")
    return 0


def cmd_status(args):
    repo = Repository.discover()
    st = repo.status()
    branch = repo.current_branch() or "(detached HEAD)"
    print(f"On branch {branch}")
    if repo.head_commit() is None:
        print("\nNo commits yet")
    if repo.merge_in_progress():
        print("\nYou have unmerged paths; fix conflicts and run `strata commit`")

    any_output = False
    if st["staged_added"] or st["staged_modified"] or st["staged_deleted"]:
        any_output = True
        print("\nChanges to be committed:")
        for p in st["staged_added"]:
            print(f"\tnew file:   {p}")
        for p in st["staged_modified"]:
            print(f"\tmodified:   {p}")
        for p in st["staged_deleted"]:
            print(f"\tdeleted:    {p}")

    if st["unstaged_modified"] or st["unstaged_deleted"]:
        any_output = True
        print("\nChanges not staged for commit:")
        for p in st["unstaged_modified"]:
            print(f"\tmodified:   {p}")
        for p in st["unstaged_deleted"]:
            print(f"\tdeleted:    {p}")

    if st["untracked"]:
        any_output = True
        print("\nUntracked files:")
        for p in st["untracked"]:
            print(f"\t{p}")

    if not any_output:
        print("\nnothing to commit, working tree clean")
    return 0


def cmd_commit(args):
    repo = Repository.discover()
    if not args.message:
        print("strata: aborting commit due to empty commit message", file=sys.stderr)
        return 1
    try:
        commit_id = repo.commit(args.message)
    except RepositoryError as exc:
        print(f"strata: {exc}", file=sys.stderr)
        return 1
    branch = repo.current_branch() or "HEAD"
    print(f"[{branch} {_short(commit_id)}] {args.message.splitlines()[0]}")
    return 0


def cmd_log(args):
    repo = Repository.discover()
    try:
        commits = repo.log(args.ref or "HEAD")
    except RepositoryError as exc:
        print(f"strata: {exc}", file=sys.stderr)
        return 1
    if not commits:
        print("strata: no commits yet")
        return 0
    for cid, commit in commits:
        print(f"commit {cid}")
        if len(commit.parents) > 1:
            print(f"Merge: {' '.join(_short(p) for p in commit.parents)}")
        print(f"Author: {commit.author}")
        print(f"Date:   {_format_date(commit.timestamp)}")
        print()
        for line in commit.message.rstrip("\n").splitlines():
            print(f"    {line}")
        print()
    return 0


def cmd_branch(args):
    repo = Repository.discover()
    if args.name:
        try:
            repo.create_branch(args.name, args.start)
        except RepositoryError as exc:
            print(f"strata: {exc}", file=sys.stderr)
            return 1
        print(f"Created branch '{args.name}'")
        return 0
    current = repo.current_branch()
    for name in repo.list_branches():
        marker = "*" if name == current else " "
        print(f"{marker} {name}")
    if current is None:
        print("* (detached HEAD)")
    return 0


def cmd_checkout(args):
    repo = Repository.discover()
    try:
        repo.checkout(args.target, force=args.force)
    except DirtyWorktree as exc:
        print(f"strata: error: {exc}", file=sys.stderr)
        return 1
    except RepositoryError as exc:
        print(f"strata: {exc}", file=sys.stderr)
        return 1
    if args.target in repo.list_branches():
        print(f"Switched to branch '{args.target}'")
    else:
        print(f"Note: checking out '{args.target}' (detached HEAD)")
    return 0


def cmd_diff(args):
    repo = Repository.discover()
    try:
        if args.ref_a and args.ref_b:
            lines = repo.diff_refs(args.ref_a, args.ref_b)
        elif args.ref_a:
            lines = repo.diff_ref_worktree(args.ref_a)
        else:
            lines = repo.diff_worktree()
    except RepositoryError as exc:
        print(f"strata: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write("".join(lines))
    return 0


def cmd_merge(args):
    repo = Repository.discover()
    try:
        result = repo.merge(args.branch)
    except MergeConflict as exc:
        print("Auto-merging: conflicts in the following files:")
        for p in exc.paths:
            print(f"\tCONFLICT: {p}")
        print("Fix conflicts and then commit the result.")
        return 1
    except RepositoryError as exc:
        print(f"strata: {exc}", file=sys.stderr)
        return 1
    if result["status"] == "up-to-date":
        print("Already up to date.")
    elif result["status"] == "fast-forward":
        print(f"Fast-forward merge to {_short(result['commit'])}")
    else:
        print(f"Merge made: {_short(result['commit'])}")
    return 0


def cmd_viz(args):
    from .visualizer import render_html
    repo = Repository.discover()
    html = render_html(repo)
    out_path = args.output or "strata-graph.html"
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"Wrote {out_path}")
    return 0


def cmd_config(args):
    repo = Repository.discover()
    if args.value is not None:
        repo.set_config(args.key, args.value)
        return 0
    value = repo.get_config(args.key)
    if value is None:
        print(f"strata: no such config key: {args.key}", file=sys.stderr)
        return 1
    print(value)
    return 0


def cmd_show(args):
    repo = Repository.discover()
    try:
        commit_id = repo.resolve(args.ref)
        commit = repo.get_commit(commit_id)
    except RepositoryError as exc:
        print(f"strata: {exc}", file=sys.stderr)
        return 1
    print(f"commit {commit_id}")
    print(f"Author: {commit.author}")
    print(f"Date:   {_format_date(commit.timestamp)}")
    print()
    for line in commit.message.rstrip("\n").splitlines():
        print(f"    {line}")
    print()
    if commit.parents:
        lines = repo.diff_refs(commit.parents[0], commit_id)
        sys.stdout.write("".join(lines))
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog="strata", description="A version control system built from scratch.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="create a new repository")
    p.add_argument("path", nargs="?")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("add", help="stage files")
    p.add_argument("paths", nargs="+")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("status", help="show the working tree status")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("commit", help="record staged changes")
    p.add_argument("-m", "--message", required=True)
    p.set_defaults(func=cmd_commit)

    p = sub.add_parser("log", help="show commit history")
    p.add_argument("ref", nargs="?")
    p.set_defaults(func=cmd_log)

    p = sub.add_parser("branch", help="list or create branches")
    p.add_argument("name", nargs="?")
    p.add_argument("start", nargs="?")
    p.set_defaults(func=cmd_branch)

    p = sub.add_parser("checkout", help="switch branches or restore working tree")
    p.add_argument("target")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_checkout)

    p = sub.add_parser("diff", help="show changes")
    p.add_argument("ref_a", nargs="?")
    p.add_argument("ref_b", nargs="?")
    p.set_defaults(func=cmd_diff)

    p = sub.add_parser("merge", help="merge a branch into the current branch")
    p.add_argument("branch")
    p.set_defaults(func=cmd_merge)

    p = sub.add_parser("viz", help="render an interactive HTML commit-graph visualizer")
    p.add_argument("-o", "--output")
    p.set_defaults(func=cmd_viz)

    p = sub.add_parser("config", help="get or set a repo config value (e.g. user.name)")
    p.add_argument("key")
    p.add_argument("value", nargs="?")
    p.set_defaults(func=cmd_config)

    p = sub.add_parser("show", help="show a commit and its diff")
    p.add_argument("ref", nargs="?", default="HEAD")
    p.set_defaults(func=cmd_show)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except NotARepository as exc:
        print(f"strata: {exc}", file=sys.stderr)
        return 1
    except (ObjectNotFound, CorruptObject, InvalidObject) as exc:
        print(f"strata: fatal: object store error: {exc}", file=sys.stderr)
        return 1


def run():
    """Entry point used by both `python -m strata` and direct script execution;
    swallows BrokenPipeError so piping output into `head`/`less` doesn't print
    a Python traceback for what is normal, expected pipe-closing behavior."""
    try:
        sys.exit(main())
    except BrokenPipeError:
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        sys.exit(1)


if __name__ == "__main__":
    run()
