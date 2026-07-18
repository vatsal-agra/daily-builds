"""`trove build|search|serve|eval` command-line interface."""

import argparse
import os
import sys

from .engine import Engine
from .index import build_index, DEFAULT_EXTENSIONS


def _cmd_build(args):
    if args.repo_history:
        from .corpora import build_repo_history_index
        index = build_repo_history_index(args.directory)
    else:
        extensions = tuple(e if e.startswith(".") else f".{e}" for e in args.ext.split(","))
        index = build_index(args.directory, extensions=extensions, split_headers=not args.no_split)
    if index.N == 0:
        print(f"error: no {extensions} files found under {args.directory!r}", file=sys.stderr)
        return 1
    index.save(args.out)
    print(f"indexed {index.N} documents, {len(index.postings)} unique terms -> {args.out}")
    return 0


def _cmd_search(args):
    if not os.path.exists(args.index):
        print(f"error: index not found at {args.index!r} — run `trove build` first", file=sys.stderr)
        return 1
    engine = Engine.load(args.index)
    outcome = engine.search(args.query, top=args.top, k1=args.k1, b=args.b)
    if outcome["error"]:
        print(f"query error: {outcome['error']}", file=sys.stderr)
        return 1
    if outcome["corrections"]:
        for typed, corrected in outcome["corrections"]:
            print(f"(no match for '{typed}' — using '{corrected}')")
    if not outcome["results"]:
        print("no results")
        return 0
    print(f"{outcome['total_matches']} matches, top {len(outcome['results'])} shown, {outcome['took_ms']}ms")
    for i, r in enumerate(outcome["results"], start=1):
        print(f"{i:2}. [{r.score:6.3f}] {r.title}  ({r.path})")
    return 0


def _cmd_serve(args):
    from .server import serve
    if not os.path.exists(args.index):
        print(f"error: index not found at {args.index!r} — run `trove build` first", file=sys.stderr)
        return 1
    serve(args.index, port=args.port)
    return 0


def _cmd_eval(args):
    from .evaluation import run_eval
    if not os.path.exists(args.index):
        print(f"error: index not found at {args.index!r} — run `trove build` first", file=sys.stderr)
        return 1
    engine = Engine.load(args.index)
    return run_eval(engine, args.judgments)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="trove", description="A from-scratch full-text search engine.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build", help="build an index over a directory of text/markdown files")
    p_build.add_argument("directory")
    p_build.add_argument("--out", default="trove.index.json")
    p_build.add_argument("--ext", default=",".join(DEFAULT_EXTENSIONS))
    p_build.add_argument("--no-split", action="store_true", help="don't split markdown '## ' sections into separate documents")
    p_build.add_argument("--repo-history", action="store_true", help="index this daily-builds repo's past project READMEs + LEDGER.md entries specifically (directory = repo root)")
    p_build.set_defaults(func=_cmd_build)

    p_search = sub.add_parser("search", help="run a query against a built index")
    p_search.add_argument("query")
    p_search.add_argument("--index", default="trove.index.json")
    p_search.add_argument("--top", type=int, default=10)
    p_search.add_argument("--k1", type=float, default=1.5)
    p_search.add_argument("--b", type=float, default=0.75)
    p_search.set_defaults(func=_cmd_search)

    p_serve = sub.add_parser("serve", help="serve the interactive web UI")
    p_serve.add_argument("--index", default="trove.index.json")
    p_serve.add_argument("--port", type=int, default=8765)
    p_serve.set_defaults(func=_cmd_serve)

    p_eval = sub.add_parser("eval", help="score ranking quality against hand-labeled relevance judgments")
    p_eval.add_argument("--index", default="trove.index.json")
    p_eval.add_argument("--judgments", default=None)
    p_eval.set_defaults(func=_cmd_eval)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
