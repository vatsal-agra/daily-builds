"""
VecNN CLI — command-line interface for the vector search engine.

Subcommands:
  demo     — generate random vectors, benchmark recall vs speed
  insert   — bulk-insert from a JSONL file
  search   — query nearest neighbours
  bench    — sweep ef values and print recall/QPS table
  compare  — HNSW vs LSH vs exact on the same dataset
  viz      — generate HTML visualizer
  info     — show index statistics
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import List, Optional

import numpy as np


def _import_vecnn():
    # Make sure parent package is importable regardless of how the CLI is invoked
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from vecnn.collection import Collection
    from vecnn.hnsw import HNSWIndex
    from vecnn.lsh import LSHIndex
    from vecnn import bench as benchmod
    from vecnn import viz as vizmod
    return Collection, HNSWIndex, LSHIndex, benchmod, vizmod


def _random_vectors(n: int, dim: int, seed: int = 42) -> np.ndarray:
    rng = np.random.default_rng(seed)
    vecs = rng.standard_normal((n, dim))
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vecs / norms


def _print_table(headers: List[str], rows: List[List], col_sep: str = "  "):
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))
    fmt = col_sep.join(f"{{:<{w}}}" for w in widths)
    sep = col_sep.join("-" * w for w in widths)
    print(fmt.format(*headers))
    print(sep)
    for row in rows:
        print(fmt.format(*[str(c) for c in row]))


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_demo(args):
    Collection, HNSWIndex, LSHIndex, benchmod, vizmod = _import_vecnn()

    n = args.n
    dim = args.dim
    k = args.k
    metric = args.metric
    print(f"VecNN demo: {n} random unit vectors, dim={dim}, metric={metric}, k={k}\n")

    # Generate data
    print("Generating vectors …")
    t0 = time.perf_counter()
    vectors = _random_vectors(n, dim, seed=args.seed)
    print(f"  Generated {n} vectors in {(time.perf_counter()-t0)*1000:.1f} ms")

    # Build HNSW
    print(f"\nBuilding HNSW (M={args.M}, ef_construction={args.ef_c}) …")
    t0 = time.perf_counter()
    hnsw = HNSWIndex(dim=dim, metric=metric, M=args.M, ef_construction=args.ef_c, seed=42)
    categories = ["A", "B", "C", "D"]
    ids = []
    for i, v in enumerate(vectors):
        meta = {"idx": i, "category": categories[i % len(categories)]}
        ids.append(hnsw.insert(v, metadata=meta))
    build_ms = (time.perf_counter() - t0) * 1000
    print(f"  Built in {build_ms:.1f} ms  ({build_ms/n:.2f} ms/insert)")
    st = hnsw.stats()
    print(f"  Max layer: {st['max_layer']}  |  Total edges: {st['total_edges']}")

    # Benchmark recall vs ef
    print(f"\nRecall@{k} sweep (100 random queries) …")
    query_vecs = _random_vectors(100, dim, seed=99)
    ef_vals = sorted({k, k*2, k*4, 50, 100, 200, 400})
    ef_vals = [e for e in ef_vals if e >= k]
    results = benchmod.benchmark(hnsw, query_vecs, vectors, ids, k=k, ef_values=ef_vals)

    rows = [[r["ef"], f"{r['recall_at_k']:.3f}", r["qps"], f"{r['avg_query_ms']} ms"]
            for r in results]
    _print_table(["ef", f"recall@{k}", "QPS", "avg_query"], rows)

    # Build LSH for comparison
    print(f"\nBuilding LSH (T={args.lsh_tables}, L={args.lsh_bits}) …")
    t0 = time.perf_counter()
    lsh = LSHIndex(dim=dim, n_tables=args.lsh_tables, n_bits=args.lsh_bits, seed=42)
    for i, v in enumerate(vectors):
        meta = {"idx": i, "category": categories[i % len(categories)]}
        lsh.insert(v, metadata=meta)
    lsh_ms = (time.perf_counter() - t0) * 1000
    print(f"  Built in {lsh_ms:.1f} ms")

    print(f"\nHead-to-head comparison (HNSW vs LSH vs exact, {len(query_vecs)} queries, k={k}) …")
    comp = benchmod.compare_indices(hnsw, lsh, query_vecs, vectors, ids, k=k)
    rows = []
    for name, m in [("exact", comp["exact"]), ("hnsw", comp["hnsw"]), ("lsh", comp.get("lsh", {}))]:
        if m:
            rows.append([name, f"{m['recall_at_k']:.3f}", m["qps"], f"{m['avg_ms']} ms"])
    _print_table(["method", f"recall@{k}", "QPS", "avg_query"], rows)

    # Metadata filter demo
    print(f"\nMetadata filter demo — search with filter={{category: 'A'}} …")
    q = query_vecs[0]
    raw = hnsw.search(q, k=k)
    filtered = hnsw.search(q, k=k, filter_fn=lambda m: m.get("category") == "A")
    print(f"  Unfiltered: {[r[0] for r in raw]}")
    print(f"  Filtered (cat=A): {[r[0] for r in filtered]}")
    assert all(hnsw.get_node(r[0]).metadata.get("category") == "A" for r in filtered), \
        "Filter did not restrict to category A!"
    print("  ✓ Filter correct")

    # Optionally save viz
    if args.out_viz:
        print(f"\nGenerating HTML visualizer → {args.out_viz} …")
        html = vizmod.generate_html(
            hnsw,
            query=query_vecs[0],
            query_k=k,
            title=f"VecNN demo — {n} vectors, dim={dim}",
        )
        Path(args.out_viz).write_text(html, encoding="utf-8")
        print(f"  Saved {len(html)//1024} KB")

    print("\nDemo complete.")


def cmd_insert(args):
    Collection, *_ = _import_vecnn()
    path = args.collection
    if os.path.exists(path):
        coll = Collection.load(path)
        print(f"Loaded collection '{coll.name}' ({coll.size} vectors)")
    else:
        if args.dim is None:
            sys.exit("--dim required when creating a new collection")
        coll = Collection(
            name=Path(path).stem,
            dim=args.dim,
            metric=args.metric,
            index_type=args.index_type,
        )
        print(f"Created new collection '{coll.name}' dim={args.dim}")

    count = coll.add_from_jsonl(args.file)
    print(f"Inserted {count} vectors  (total: {coll.size})")
    coll.save(path)
    print(f"Saved → {path}")


def cmd_search(args):
    Collection, *_ = _import_vecnn()
    if not os.path.exists(args.collection):
        sys.exit(f"Collection not found: {args.collection}")
    coll = Collection.load(args.collection)

    with open(args.query, "r") as f:
        q_data = json.load(f)
    q_vec = np.array(q_data["vector"], dtype=np.float64)
    filter_expr = q_data.get("filter")

    results = coll.search(q_vec, k=args.k, filter_expr=filter_expr)
    print(f"Top-{args.k} nearest neighbours from '{coll.name}':")
    for rank, (nid, dist, meta) in enumerate(results, 1):
        meta_str = json.dumps(meta) if meta else "{}"
        print(f"  {rank:2d}.  id={nid:<6}  dist={dist:.6f}  {meta_str}")


def cmd_bench(args):
    Collection, HNSWIndex, LSHIndex, benchmod, vizmod = _import_vecnn()
    if not os.path.exists(args.collection):
        sys.exit(f"Collection not found: {args.collection}")
    coll = Collection.load(args.collection)
    if coll.index_type != "hnsw":
        sys.exit("bench requires an HNSW collection")

    hnsw = coll.index
    ids = hnsw.all_ids()
    if not ids:
        sys.exit("Collection is empty")

    vectors = np.stack([hnsw.get_node(nid).vector for nid in ids])
    n_q = min(args.n_queries, len(ids))
    rng = np.random.default_rng(42)
    q_idx = rng.choice(len(ids), n_q, replace=False)
    query_vecs = vectors[q_idx]

    print(f"Benchmarking '{coll.name}' ({len(ids)} vectors, k={args.k}, {n_q} queries) …\n")
    ef_vals = [int(x) for x in args.ef.split(",")] if args.ef else None
    results = benchmod.benchmark(hnsw, query_vecs, vectors, ids, k=args.k, ef_values=ef_vals)
    rows = [[r["ef"], f"{r['recall_at_k']:.3f}", r["qps"], f"{r['avg_query_ms']} ms"]
            for r in results]
    _print_table(["ef", f"recall@{args.k}", "QPS", "avg_query"], rows)


def cmd_compare(args):
    Collection, HNSWIndex, LSHIndex, benchmod, vizmod = _import_vecnn()
    if not os.path.exists(args.collection):
        sys.exit(f"Collection not found: {args.collection}")
    coll = Collection.load(args.collection)
    if coll.index_type != "hnsw":
        sys.exit("compare requires an HNSW collection (LSH is built on-the-fly)")

    hnsw = coll.index
    ids = hnsw.all_ids()
    if not ids:
        sys.exit("Collection is empty")
    vectors = np.stack([hnsw.get_node(nid).vector for nid in ids])

    print(f"Building LSH on-the-fly (T={args.lsh_tables}, L={args.lsh_bits}) …")
    lsh = LSHIndex(dim=coll.dim, n_tables=args.lsh_tables, n_bits=args.lsh_bits, seed=42)
    for nid in ids:
        n = hnsw.get_node(nid)
        lsh.insert(n.vector, metadata=n.metadata, node_id=nid)

    n_q = min(args.n_queries, len(ids))
    rng = np.random.default_rng(42)
    q_idx = rng.choice(len(ids), n_q, replace=False)
    query_vecs = vectors[q_idx]

    print(f"Comparing on {n_q} queries, k={args.k} …\n")
    comp = benchmod.compare_indices(hnsw, lsh, query_vecs, vectors, ids, k=args.k)
    rows = []
    for name in ["exact", "hnsw", "lsh"]:
        m = comp.get(name, {})
        if m:
            rows.append([name, f"{m['recall_at_k']:.3f}", m["qps"], f"{m['avg_ms']} ms"])
    _print_table(["method", f"recall@{args.k}", "QPS", "avg_query"], rows)


def cmd_viz(args):
    Collection, HNSWIndex, LSHIndex, benchmod, vizmod = _import_vecnn()
    if not os.path.exists(args.collection):
        sys.exit(f"Collection not found: {args.collection}")
    coll = Collection.load(args.collection)
    if coll.index_type != "hnsw":
        sys.exit("viz requires an HNSW collection")

    query = None
    if args.query:
        with open(args.query) as f:
            query = np.array(json.load(f)["vector"], dtype=np.float64)

    print(f"Generating HTML visualizer for '{coll.name}' …")
    html = vizmod.generate_html(
        coll.index,
        query=query,
        query_k=args.k,
        title=f"VecNN — {coll.name}",
        max_nodes=args.max_nodes,
    )
    out = args.out or (coll.name + "_viz.html")
    Path(out).write_text(html, encoding="utf-8")
    print(f"Saved {len(html)//1024} KB → {out}")


def cmd_info(args):
    Collection, *_ = _import_vecnn()
    if not os.path.exists(args.collection):
        sys.exit(f"Collection not found: {args.collection}")
    coll = Collection.load(args.collection)
    st = coll.stats()
    for k, v in st.items():
        print(f"  {k:<26} {v}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        prog="vecnn",
        description="VecNN — from-scratch HNSW + LSH vector search engine",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # demo
    p = sub.add_parser("demo", help="generate random vectors, benchmark recall vs speed")
    p.add_argument("-n", type=int, default=2000, help="number of vectors (default 2000)")
    p.add_argument("--dim", type=int, default=64, help="dimensionality (default 64)")
    p.add_argument("-k", type=int, default=10, help="k for recall@k (default 10)")
    p.add_argument("--metric", default="cosine", choices=["cosine", "euclidean", "inner"])
    p.add_argument("--M", type=int, default=16)
    p.add_argument("--ef-c", type=int, default=200, metavar="EF_CONSTRUCTION")
    p.add_argument("--lsh-tables", type=int, default=10)
    p.add_argument("--lsh-bits", type=int, default=16)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out-viz", metavar="FILE", help="also write HTML visualizer")

    # insert
    p = sub.add_parser("insert", help="bulk-insert vectors from a JSONL file")
    p.add_argument("collection", help="path to collection JSON file")
    p.add_argument("file", help="JSONL file with {vector, [id], [metadata]}")
    p.add_argument("--dim", type=int)
    p.add_argument("--metric", default="cosine")
    p.add_argument("--index-type", default="hnsw", choices=["hnsw", "lsh"])

    # search
    p = sub.add_parser("search", help="search nearest neighbours")
    p.add_argument("collection", help="path to collection JSON file")
    p.add_argument("query", help="JSON file with {vector, [filter]}")
    p.add_argument("-k", type=int, default=10)

    # bench
    p = sub.add_parser("bench", help="sweep ef values and print recall/QPS table")
    p.add_argument("collection")
    p.add_argument("-k", type=int, default=10)
    p.add_argument("--n-queries", type=int, default=100)
    p.add_argument("--ef", help="comma-separated ef values, e.g. '10,50,100,200'")

    # compare
    p = sub.add_parser("compare", help="HNSW vs LSH vs exact comparison")
    p.add_argument("collection")
    p.add_argument("-k", type=int, default=10)
    p.add_argument("--n-queries", type=int, default=100)
    p.add_argument("--lsh-tables", type=int, default=10)
    p.add_argument("--lsh-bits", type=int, default=16)

    # viz
    p = sub.add_parser("viz", help="generate interactive HTML visualizer")
    p.add_argument("collection")
    p.add_argument("--query", help="JSON file with query vector to animate")
    p.add_argument("-k", type=int, default=5)
    p.add_argument("--out", help="output HTML file (default: <name>_viz.html)")
    p.add_argument("--max-nodes", type=int, default=500)

    # info
    p = sub.add_parser("info", help="show index statistics")
    p.add_argument("collection")

    args = parser.parse_args()
    dispatch = {
        "demo": cmd_demo,
        "insert": cmd_insert,
        "search": cmd_search,
        "bench": cmd_bench,
        "compare": cmd_compare,
        "viz": cmd_viz,
        "info": cmd_info,
    }
    try:
        dispatch[args.command](args)
    except (ValueError, FileNotFoundError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
