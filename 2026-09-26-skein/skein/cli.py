"""`skein` command-line interface."""
import argparse
import csv
import json
import sys

from .storage import Graph, SkeinError, TransactionError
from .query.lexer import LexError
from .query.parser import ParseError, parse
from .query.executor import execute
from . import algorithms
from . import viz as viz_module


def _open(path: str) -> Graph:
    return Graph(path)


def _parse_value(s: str):
    if s == "":
        return None
    low = s.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


def _format_cell(value) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True)


def print_rows(rows) -> None:
    if not rows:
        print("(0 rows)")
        return
    cols = list(rows[0].keys())
    cells = [[_format_cell(row.get(c)) for c in cols] for row in rows]
    widths = [max(len(c), *(len(row[i]) for row in cells)) if cells else len(c) for i, c in enumerate(cols)]
    print(" | ".join(c.ljust(w) for c, w in zip(cols, widths)))
    print("-+-".join("-" * w for w in widths))
    for row in cells:
        print(" | ".join(v.ljust(w) for v, w in zip(row, widths)))
    n = len(rows)
    print(f"({n} row{'s' if n != 1 else ''})")


def _run_query(graph: Graph, text: str, explain: bool = False):
    stmt = parse(text)
    return execute(graph, stmt, explain=explain)


# ------------------------------------------------------------- commands --

def cmd_init(args) -> int:
    graph = _open(args.path)
    graph.close()
    print(f"initialized empty graph at {args.path}.snapshot.json / {args.path}.wal")
    return 0


def cmd_query(args) -> int:
    graph = _open(args.path)
    try:
        if args.explain:
            rows, plan = _run_query(graph, args.text, explain=True)
            print(f"plan: {plan}" if plan is not None else "plan: (no MATCH clause -- nothing to plan)")
        else:
            rows = _run_query(graph, args.text)
        if rows is not None:
            print_rows(rows)
        else:
            print("OK")
    finally:
        graph.close()
    return 0


def cmd_shell(args) -> int:
    graph = _open(args.path)
    print(f"Skein shell -- {args.path} ({len(graph.nodes)} nodes, {len(graph.edges)} edges)")
    print("Enter a SkeinQL statement, blank line to run it, 'quit' to exit.")
    try:
        buf = []
        while True:
            try:
                line = input("skein> " if not buf else "   ...> ")
            except EOFError:
                break
            if not buf and line.strip().lower() in ("quit", "exit"):
                break
            if line.strip() == "":
                text = " ".join(buf).strip()
                buf = []
                if not text:
                    continue
                try:
                    rows = _run_query(graph, text)
                    if rows is not None:
                        print_rows(rows)
                    else:
                        print("OK")
                except (SkeinError, TransactionError, ParseError, LexError) as e:
                    print(f"error: {e}")
                continue
            buf.append(line)
    finally:
        graph.close()
    return 0


def cmd_import(args) -> int:
    graph = _open(args.path)
    id_map = {}
    try:
        with graph.transaction():
            with open(args.nodes, newline="") as f:
                reader = csv.DictReader(f)
                if reader.fieldnames is None or "id" not in reader.fieldnames:
                    raise SkeinError(f"{args.nodes}: header must include an 'id' column")
                prop_cols = [c for c in reader.fieldnames if c not in ("id", "labels")]
                for row in reader:
                    labels = [l for l in row.get("labels", "").split(";") if l]
                    props = {c: _parse_value(row[c]) for c in prop_cols if row.get(c, "") != ""}
                    nid = graph.create_node(labels, props)
                    id_map[row["id"]] = nid
            n_edges = 0
            if args.edges:
                with open(args.edges, newline="") as f:
                    reader = csv.DictReader(f)
                    required = {"src", "dst", "type"}
                    if reader.fieldnames is None or not required.issubset(reader.fieldnames):
                        raise SkeinError(f"{args.edges}: header must include src, dst, type columns")
                    prop_cols = [c for c in reader.fieldnames if c not in ("src", "dst", "type")]
                    for row in reader:
                        if row["src"] not in id_map or row["dst"] not in id_map:
                            raise SkeinError(f"{args.edges}: edge references unknown node id {row['src']!r} or {row['dst']!r}")
                        props = {c: _parse_value(row[c]) for c in prop_cols if row.get(c, "") != ""}
                        graph.create_edge(id_map[row["src"]], id_map[row["dst"]], row["type"], props)
                        n_edges += 1
    finally:
        graph.close()
    print(f"imported {len(id_map)} nodes and {n_edges} edges into {args.path}")
    return 0


def cmd_algo_pagerank(args) -> int:
    if args.top is not None and args.top <= 0:
        raise SkeinError("--top must be a positive integer")
    graph = _open(args.path)
    try:
        scores = algorithms.pagerank(graph)
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        if args.top:
            ranked = ranked[: args.top]
        rows = []
        for nid, score in ranked:
            node = graph.nodes[nid]
            rows.append({"id": nid, "labels": ",".join(sorted(node.labels)), "score": round(score, 6)})
        print_rows(rows)
    finally:
        graph.close()
    return 0


def cmd_algo_shortest_path(args) -> int:
    graph = _open(args.path)
    try:
        if args.weighted:
            path, weight = algorithms.dijkstra_shortest_path(graph, args.src, args.dst, weight_prop=args.weight_prop)
            if path is None:
                print(f"no path from {args.src} to {args.dst}")
                return 1
            print(f"path: {path}  total weight: {weight}")
        else:
            path = algorithms.bfs_shortest_path(graph, args.src, args.dst)
            if path is None:
                print(f"no path from {args.src} to {args.dst}")
                return 1
            print(f"path: {path}  hops: {len(path) - 1}")
    finally:
        graph.close()
    return 0


def cmd_algo_components(args) -> int:
    graph = _open(args.path)
    try:
        components = algorithms.connected_components(graph)
        components.sort(key=len, reverse=True)
        for i, comp in enumerate(components):
            print(f"component {i}: {sorted(comp)} ({len(comp)} node(s))")
        print(f"{len(components)} connected component(s) total")
    finally:
        graph.close()
    return 0


def cmd_demo(args) -> int:
    from . import demo
    return demo.run()


def cmd_viz(args) -> int:
    graph = _open(args.path)
    try:
        html = viz_module.render_html(graph, query_text=args.query)
    finally:
        graph.close()
    out_path = args.out or (args.path + ".html")
    with open(out_path, "w") as f:
        f.write(html)
    print(f"wrote {out_path} ({len(graph.nodes)} nodes, {len(graph.edges)} edges)")
    return 0


def cmd_crash_demo(args) -> int:
    import random
    import subprocess
    import sys as _sys
    import time

    if args.rounds <= 0:
        raise SkeinError("--rounds must be a positive integer")
    if args.batch <= 0:
        raise SkeinError("--batch must be a positive integer")

    print(f"crash-demo: {args.rounds} rounds of kill -9 mid-write against {args.path}, batch size {args.batch}")
    prior = 0
    for i in range(args.rounds):
        proc = subprocess.Popen([_sys.executable, "-m", "skein.crash_worker", args.path, str(args.batch)])
        time.sleep(random.uniform(0.02, 0.2))
        proc.kill()
        proc.wait()
        graph = Graph(args.path)
        n = len(graph.nodes)
        graph.close()
        if n < prior:
            raise SkeinError(f"round {i}: node count went backwards ({n} < {prior}) -- corruption after crash!")
        if n % args.batch != 0:
            raise SkeinError(
                f"round {i}: {n} nodes present after recovery, not a multiple of batch size {args.batch} "
                "-- a partial transaction became visible!"
            )
        print(f"  round {i}: killed worker mid-run; {n} nodes present after recovery (was {prior})")
        prior = n
    print("crash-demo: every reopen succeeded and the node count stayed an exact multiple of the "
          "per-transaction batch size -- no partial transaction was ever visible after a real kill -9.")
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="skein", description="A from-scratch property-graph database.")
    sub = p.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="create an empty graph database")
    p_init.add_argument("path")
    p_init.set_defaults(func=cmd_init)

    p_query = sub.add_parser("query", help="run a single SkeinQL statement")
    p_query.add_argument("path")
    p_query.add_argument("text")
    p_query.add_argument("--explain", action="store_true", help="print the chosen query plan")
    p_query.set_defaults(func=cmd_query)

    p_shell = sub.add_parser("shell", help="interactive SkeinQL REPL")
    p_shell.add_argument("path")
    p_shell.set_defaults(func=cmd_shell)

    p_import = sub.add_parser("import", help="bulk-load nodes/edges from CSV")
    p_import.add_argument("path")
    p_import.add_argument("--nodes", required=True, help="CSV with columns: id,labels,<props...>")
    p_import.add_argument("--edges", help="CSV with columns: src,dst,type,<props...>")
    p_import.set_defaults(func=cmd_import)

    p_algo = sub.add_parser("algo", help="graph algorithms")
    algo_sub = p_algo.add_subparsers(dest="algo_command", required=True)

    p_pr = algo_sub.add_parser("pagerank")
    p_pr.add_argument("path")
    p_pr.add_argument("--top", type=int, default=None)
    p_pr.set_defaults(func=cmd_algo_pagerank)

    p_sp = algo_sub.add_parser("shortest-path")
    p_sp.add_argument("path")
    p_sp.add_argument("--src", type=int, required=True)
    p_sp.add_argument("--dst", type=int, required=True)
    p_sp.add_argument("--weighted", action="store_true")
    p_sp.add_argument("--weight-prop", default="weight")
    p_sp.set_defaults(func=cmd_algo_shortest_path)

    p_cc = algo_sub.add_parser("components")
    p_cc.add_argument("path")
    p_cc.set_defaults(func=cmd_algo_components)

    p_demo = sub.add_parser("demo", help="run the built-in showcase")
    p_demo.set_defaults(func=cmd_demo)

    p_viz = sub.add_parser("viz", help="generate an interactive HTML graph visualizer")
    p_viz.add_argument("path")
    p_viz.add_argument("--out", help="output HTML path (default: <path>.html)")
    p_viz.add_argument("--query", help="a SkeinQL statement whose match is highlighted in the visualizer")
    p_viz.set_defaults(func=cmd_viz)

    p_crash = sub.add_parser("crash-demo", help="prove crash recovery with a real kill -9 mid-write")
    p_crash.add_argument("path")
    p_crash.add_argument("--rounds", type=int, default=5)
    p_crash.add_argument("--batch", type=int, default=500, help="nodes per transaction in the worker")
    p_crash.set_defaults(func=cmd_crash_demo)

    return p


def main(argv=None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args) or 0
    except (SkeinError, TransactionError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except (ParseError, LexError) as e:
        print(f"query error: {e}", file=sys.stderr)
        return 1
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
