#!/usr/bin/env python3
"""Sift command-line interface."""

import argparse
import sys
import time

from sift.index import build_index_from_dir
from sift.storage import save_index, load_index
from sift.engine import Engine


def _load_engine(index_path):
    try:
        index = load_index(index_path)
    except FileNotFoundError:
        print(f"error: index file not found: {index_path}", file=sys.stderr)
        sys.exit(1)
    except (ValueError, IndexError):
        print(f"error: {index_path} is not a valid Sift index file", file=sys.stderr)
        sys.exit(1)
    return Engine(index)


def cmd_index(args):
    t0 = time.time()
    index = build_index_from_dir(args.corpus_dir)
    if index.doc_count == 0:
        print(f"error: no .txt/.md files found in {args.corpus_dir}", file=sys.stderr)
        sys.exit(1)
    save_index(index, args.out)
    elapsed = time.time() - t0
    print(
        f"indexed {index.doc_count} documents, {len(index.vocabulary())} unique "
        f"terms, {index.total_length} total tokens -> {args.out} ({elapsed:.2f}s)"
    )


def cmd_search(args):
    engine = _load_engine(args.index)
    try:
        results = engine.search(args.query, k1=args.k1, b=args.b, limit=args.limit)
    except Exception as exc:
        print(f"query error: {exc}", file=sys.stderr)
        sys.exit(1)

    if not results:
        print(f"no results for: {args.query}")
        suggestions = []
        for word in args.query.split():
            word = word.strip('"()*~')
            if not word or word.lower() in ("and", "or", "not"):
                continue
            from sift.analyzer import analyze_query_term

            hits = engine.suggest(analyze_query_term(word))
            suggestions.extend(w for w, _ in hits)
        if suggestions:
            print(f"did you mean: {', '.join(sorted(set(suggestions))[:5])}?")
        return

    for rank, (doc_id, score) in enumerate(results, start=1):
        doc = engine.index.documents[doc_id]
        print(f"{rank}. [{score:.3f}] {doc.title}  ({doc.path})")
        if args.snippets:
            snippet = engine.snippet_for(doc_id, args.query)
            if snippet:
                import re

                plain = re.sub(r"</?mark>", lambda m: "**" if m.group(0) == "<mark>" else "**", snippet)
                import html as _html

                print(f"   {_html.unescape(plain)}")


def cmd_serve(args):
    from sift.server import run_server

    engine = _load_engine(args.index)
    run_server(engine, port=args.port)


def cmd_demo(args):
    import os
    import tempfile

    from sift.cli import cmd_index as _idx, cmd_search as _search  # noqa: F401

    corpus_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "corpus")
    with tempfile.TemporaryDirectory() as tmp:
        index_path = os.path.join(tmp, "demo.sift")
        idx_args = argparse.Namespace(corpus_dir=corpus_dir, out=index_path)
        cmd_index(idx_args)

        demo_queries = [
            "python",
            "mars rover",
            '"black hole"',
            "space AND NOT mars",
            "jazz OR counterpoint",
            "pytho~2",
            "quan*",
            "nonexistentgibberishword",
        ]
        for q in demo_queries:
            print(f"\n=== search: {q} ===")
            search_args = argparse.Namespace(
                index=index_path, query=q, k1=1.5, b=0.75, limit=3, snippets=True
            )
            cmd_search(search_args)


def build_parser():
    parser = argparse.ArgumentParser(prog="sift", description="A from-scratch full-text search engine.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_index = sub.add_parser("index", help="build an index from a directory of .txt/.md files")
    p_index.add_argument("corpus_dir")
    p_index.add_argument("-o", "--out", default="index.sift")
    p_index.set_defaults(func=cmd_index)

    p_search = sub.add_parser("search", help="run a query against a built index")
    p_search.add_argument("query")
    p_search.add_argument("-i", "--index", default="index.sift")
    p_search.add_argument("-k", "--limit", type=int, default=10)
    p_search.add_argument("--k1", type=float, default=1.5)
    p_search.add_argument("--b", type=float, default=0.75)
    p_search.add_argument("--snippets", action="store_true", default=True)
    p_search.add_argument("--no-snippets", dest="snippets", action="store_false")
    p_search.set_defaults(func=cmd_search)

    p_serve = sub.add_parser("serve", help="serve an interactive HTML search UI")
    p_serve.add_argument("-i", "--index", default="index.sift")
    p_serve.add_argument("-p", "--port", type=int, default=8000)
    p_serve.set_defaults(func=cmd_serve)

    p_demo = sub.add_parser("demo", help="build the bundled demo corpus and run sample queries")
    p_demo.set_defaults(func=cmd_demo)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
