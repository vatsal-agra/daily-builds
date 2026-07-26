"""Command-line interface: index, search, serve, stats, demo."""
import argparse
import json
import os
import sys

from .crawler import crawl, DEFAULT_EXTENSIONS
from .index import Index, IndexWriter, INDEX_DIRNAME
from .query import search as run_search
from .snippet import make_snippet, to_ansi

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _parse_extensions(raw):
    if not raw:
        return DEFAULT_EXTENSIONS
    return tuple(e if e.startswith(".") else f".{e}" for e in raw.split(","))


def cmd_index(args):
    root = os.path.abspath(args.dir)
    if not os.path.isdir(root):
        print(f"error: {root!r} is not a directory", file=sys.stderr)
        return 2
    index_dir = args.index_dir or os.path.join(root, INDEX_DIRNAME)
    extensions = _parse_extensions(args.ext)
    writer = IndexWriter(root, index_dir=index_dir, extensions=extensions)
    stats = writer.build(crawl(root, extensions))
    print(
        f"Indexed {stats['total']} document(s) from {root} "
        f"({stats['reanalyzed']} analyzed, {stats['reused']} unchanged/reused, "
        f"{stats['removed']} removed) -> {index_dir}"
    )
    return 0


def _load_index(args):
    root = os.path.abspath(args.dir)
    index_dir = args.index_dir or os.path.join(root, INDEX_DIRNAME)
    return Index(index_dir)


def cmd_search(args):
    try:
        index = _load_index(args)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    results, suggestions, matched_terms = run_search(
        index, args.query, limit=args.limit, fuzzy=not args.no_fuzzy
    )

    if args.json:
        print(json.dumps({"results": results, "suggestions": suggestions}, indent=2))
        return 0

    if not results:
        print(f"No results for: {args.query}")
        if suggestions:
            print(f"Did you mean: {', '.join(suggestions)}?")
        return 0

    for i, r in enumerate(results, start=1):
        full_path = os.path.join(index.root, r["path"])
        snippet = ""
        try:
            with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                snippet = to_ansi(make_snippet(f.read(), matched_terms))
        except OSError:
            snippet = "(source file unavailable)"
        print(f"{i}. [{r['score']:.3f}] {r['title']}  ({r['path']})")
        print(f"   {snippet}")
    if suggestions:
        print(f"\n(also matched via fuzzy correction: {', '.join(suggestions)})")
    return 0


def cmd_stats(args):
    try:
        index = _load_index(args)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(f"root:          {index.root}")
    print(f"documents:     {index.doc_count}")
    print(f"vocabulary:    {len(index.terms)} unique terms")
    print(f"avg doc length:{index.avg_doc_length:.1f} tokens")
    return 0


def cmd_serve(args):
    from .server import serve

    root = os.path.abspath(args.dir)
    index_dir = args.index_dir or os.path.join(root, INDEX_DIRNAME)
    try:
        index = Index(index_dir)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    serve(index, port=args.port)
    return 0


def cmd_demo(args):
    demo_root = os.path.abspath(os.path.join(PROJECT_ROOT, os.pardir))
    demo_index_dir = os.path.join(PROJECT_ROOT, ".demo_index")

    print(f"Glean self-indexing demo")
    print(f"  corpus root : {demo_root}")
    print(f"  index dir   : {demo_index_dir}  (kept inside this project's folder)\n")

    writer = IndexWriter(demo_root, index_dir=demo_index_dir, extensions=(".md",))
    stats = writer.build(crawl(demo_root, (".md",)))
    print(
        f"Indexed {stats['total']} markdown file(s) across the daily-builds history "
        f"({stats['reanalyzed']} analyzed, {stats['reused']} reused, {stats['removed']} removed).\n"
    )

    index = Index(demo_index_dir)
    sample_queries = [
        "raft consensus",
        "bloom filter",
        '"ray tracing"',
        "chess engine AND transposition",
        "NOT chess bytecode virtual machine",
        "consesus",  # deliberate typo -> exercises fuzzy matching
    ]
    for q in sample_queries:
        results, suggestions, matched_terms = run_search(index, q, limit=3)
        print(f'> glean search "{q}"')
        if not results:
            print("  (no results)", end="")
            if suggestions:
                print(f"  -- did you mean: {', '.join(suggestions)}?")
            else:
                print()
            continue
        if suggestions:
            print(f"  (typo-corrected via: {', '.join(suggestions)})")
        for r in results:
            print(f"  [{r['score']:.3f}] {r['title']}  ({r['path']})")
        print()
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog="glean", description="A from-scratch full-text search engine.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_index = sub.add_parser("index", help="crawl and (re)build the index for a directory")
    p_index.add_argument("dir", nargs="?", default=".", help="directory to index (default: .)")
    p_index.add_argument("--index-dir", help="where to store the index (default: <dir>/.glean)")
    p_index.add_argument("--ext", help="comma-separated extensions to index (default: .md,.txt)")
    p_index.set_defaults(func=cmd_index)

    p_search = sub.add_parser("search", help="search a previously built index")
    p_search.add_argument("query")
    p_search.add_argument("--dir", default=".", help="directory whose index to search (default: .)")
    p_search.add_argument("--index-dir", help="explicit index location")
    p_search.add_argument("--limit", type=int, default=10)
    p_search.add_argument("--no-fuzzy", action="store_true", help="disable typo-tolerant fuzzy matching")
    p_search.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    p_search.set_defaults(func=cmd_search)

    p_stats = sub.add_parser("stats", help="print index statistics")
    p_stats.add_argument("--dir", default=".")
    p_stats.add_argument("--index-dir")
    p_stats.set_defaults(func=cmd_stats)

    p_serve = sub.add_parser("serve", help="serve the web search UI")
    p_serve.add_argument("--dir", default=".")
    p_serve.add_argument("--index-dir")
    p_serve.add_argument("--port", type=int, default=8899)
    p_serve.set_defaults(func=cmd_serve)

    p_demo = sub.add_parser("demo", help="index this repo's own history and run sample queries")
    p_demo.set_defaults(func=cmd_demo)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
