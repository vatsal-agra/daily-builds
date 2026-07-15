"""The `glean` command-line interface."""

import argparse
import json
import sys
from pathlib import Path

from . import rank
from .engine import SearchEngine
from .index import InvertedIndex
from .query import QuerySyntaxError

DEFAULT_INDEX_PATH = "glean.idx"


def _load_corpus_dir(directory):
    """Yield (title, text, path) for every .txt/.md file under `directory`."""
    root = Path(directory)
    if not root.exists():
        raise SystemExit(f"error: no such directory: {directory}")
    for path in sorted(root.rglob("*")):
        if path.suffix.lower() not in (".txt", ".md"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        yield path.stem, text, str(path)


def cmd_index(args):
    engine = SearchEngine()
    count = 0
    for title, text, path in _load_corpus_dir(args.directory):
        engine.add_document(title, text, path=path)
        count += 1
    if count == 0:
        print(f"no .txt/.md files found under {args.directory}", file=sys.stderr)
        sys.exit(1)
    engine.save(args.output)
    print(f"indexed {count} documents -> {args.output}")


def cmd_demo_index(args):
    from corpus.demo_corpus import load_corpus

    engine = SearchEngine()
    for article in load_corpus():
        engine.add_document(article["title"], article["text"], path=article["topic"])
    engine.save(args.output)
    print(f"indexed {engine.index.doc_count} demo articles -> {args.output}")


def _open_engine(index_path):
    if not Path(index_path).exists():
        print(f"error: index file not found: {index_path!r} (run `glean index` first)", file=sys.stderr)
        sys.exit(1)
    try:
        return SearchEngine.load(index_path)
    except Exception as exc:  # corrupt/foreign file
        print(f"error: could not load index {index_path!r}: {exc}", file=sys.stderr)
        sys.exit(1)


def cmd_search(args):
    if args.top_k < 0:
        print(f"error: --top-k must be >= 0, got {args.top_k}", file=sys.stderr)
        sys.exit(1)
    engine = _open_engine(args.index)
    try:
        results = engine.search(args.query, top_k=args.top_k)
    except QuerySyntaxError as exc:
        print(f"query error: {exc}", file=sys.stderr)
        sys.exit(1)
    if not results:
        print("no results")
        suggestions = engine.did_you_mean(args.query)
        for term, candidates in suggestions.items():
            words = ", ".join(word for word, _distance in candidates[:3])
            print(f"did you mean: {words}?")
        return
    for i, r in enumerate(results, start=1):
        snippet = rank.snippet_to_text(r.snippet_pieces)
        print(f"{i}. [{r.score:.3f}] {r.title}  ({r.path})")
        print(f"   {snippet}")


def cmd_stats(args):
    engine = _open_engine(args.index)
    print(json.dumps(engine.stats(), indent=2))


def cmd_serve(args):
    from .server import run_server

    run_server(args.index, args.port, demo=args.demo)


def build_parser():
    p = argparse.ArgumentParser(prog="glean", description="A from-scratch full-text search engine.")
    sub = p.add_subparsers(dest="command", required=True)

    p_index = sub.add_parser("index", help="build an index from a directory of .txt/.md files")
    p_index.add_argument("directory")
    p_index.add_argument("-o", "--output", default=DEFAULT_INDEX_PATH)
    p_index.set_defaults(func=cmd_index)

    p_demo_index = sub.add_parser("demo-index", help="build an index from the bundled demo corpus")
    p_demo_index.add_argument("-o", "--output", default=DEFAULT_INDEX_PATH)
    p_demo_index.set_defaults(func=cmd_demo_index)

    p_search = sub.add_parser("search", help="run a query against an index")
    p_search.add_argument("query")
    p_search.add_argument("-i", "--index", default=DEFAULT_INDEX_PATH)
    p_search.add_argument("-k", "--top-k", type=int, default=10)
    p_search.set_defaults(func=cmd_search)

    p_stats = sub.add_parser("stats", help="print index statistics")
    p_stats.add_argument("-i", "--index", default=DEFAULT_INDEX_PATH)
    p_stats.set_defaults(func=cmd_stats)

    p_serve = sub.add_parser("serve", help="serve the interactive search UI")
    p_serve.add_argument("-i", "--index", default=DEFAULT_INDEX_PATH)
    p_serve.add_argument("-p", "--port", type=int, default=8752)
    p_serve.add_argument("--demo", action="store_true", help="build the demo index first")
    p_serve.set_defaults(func=cmd_serve)

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
