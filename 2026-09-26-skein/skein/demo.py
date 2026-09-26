"""`skein demo` -- an end-to-end narrated showcase of every required
feature, run against a scratch database that's cleaned up afterward.
"""
import os
import shutil
import tempfile
import time

from .storage import Graph
from .engine import run as q
from . import algorithms


def _describe(graph, nid):
    node = graph.nodes[nid]
    return node.props.get("name", nid)


def run() -> int:
    tmpdir = tempfile.mkdtemp(prefix="skein_demo_")
    path = os.path.join(tmpdir, "demo")
    try:
        print("=== Skein demo ===")
        print(f"(scratch database: {path})")

        print("\n-- 1. Durable storage: build a small social graph --")
        g = Graph(path)
        with g.transaction():
            people = {}
            for name, age, city in [
                ("Alice", 30, "NYC"), ("Bob", 25, "NYC"), ("Carol", 35, "SF"),
                ("Dave", 28, "SF"), ("Eve", 40, "Boston"), ("Frank", 22, "NYC"),
            ]:
                people[name] = g.create_node(["Person"], {"name": name, "age": age, "city": city})
            acme = g.create_node(["Company"], {"name": "Acme"})
            for name in ("Alice", "Carol", "Eve"):
                g.create_edge(people[name], acme, "WORKS_AT", {"since": 2020})
            for a, b in [("Alice", "Bob"), ("Bob", "Carol"), ("Carol", "Dave"), ("Dave", "Eve"), ("Eve", "Frank"), ("Alice", "Carol")]:
                g.create_edge(people[a], people[b], "KNOWS", {})
        n_nodes, n_edges = len(g.nodes), len(g.edges)
        print(f"created {n_nodes} nodes, {n_edges} edges; closing and reopening to prove durability...")
        g.close()

        g = Graph(path)
        assert len(g.nodes) == n_nodes and len(g.edges) == n_edges, "reopen did not reproduce the committed state"
        print(f"reopened: {len(g.nodes)} nodes, {len(g.edges)} edges -- durable across a process restart.")

        print("\n-- 2. SkeinQL: pattern matching + WHERE + RETURN + ORDER BY --")
        for row in q(g, "MATCH (a:Person)-[:KNOWS]->(b:Person) WHERE a.age > 25 RETURN a.name, b.name ORDER BY a.name"):
            print(" ", row)

        print("\n-- 3. SkeinQL: a two-hop chain pattern --")
        for row in q(g, "MATCH (a:Person)-[:KNOWS]->(b:Person)-[:KNOWS]->(c:Person) RETURN a.name, c.name"):
            print(" ", row)

        print("\n-- 4. SkeinQL: CREATE, SET, DELETE --")
        q(g, "CREATE (x:Person {name: 'Grace', age: 33, city: 'NYC'})")
        q(g, "MATCH (x:Person {name: 'Grace'}) SET x.age = 34")
        rows = q(g, "MATCH (x:Person {name: 'Grace'}) RETURN x.name, x.age")
        print(" after CREATE + SET:", rows)
        assert rows == [{"x.name": "Grace", "x.age": 34}]
        q(g, "MATCH (x:Person {name: 'Grace'}) DELETE x")
        rows = q(g, "MATCH (x:Person {name: 'Grace'}) RETURN x.name")
        print(" after DELETE:", rows, "(gone, as expected)")
        assert rows == []

        print("\n-- 5. Query planner: an index-backed lookup returns the same rows as a scan --")
        with g.transaction():
            g.create_index("Person", "name")
        rows, plan = q(g, "MATCH (p:Person {name: 'Carol'}) RETURN p.name, p.city", explain=True)
        print(" plan:", plan)
        print(" result:", rows)
        assert plan["method"] == "prop_index"

        print("\n-- 6. Graph algorithms with independent oracles (see tests/test_algorithms.py) --")
        a, f = people["Alice"], people["Frank"]
        path = algorithms.bfs_shortest_path(g, a, f)
        print(" BFS Alice -> Frank:", [_describe(g, n) for n in path])
        wpath, weight = algorithms.dijkstra_shortest_path(g, a, f)
        print(" Dijkstra Alice -> Frank (unit weights):", [_describe(g, n) for n in wpath], "total weight", weight)
        comps = algorithms.connected_components(g)
        print(f" connected components: {len(comps)}")
        pr = algorithms.pagerank(g)
        top = sorted(((nid, s) for nid, s in pr.items() if "Person" in g.nodes[nid].labels), key=lambda kv: -kv[1])[:3]
        print(" top-3 PageRank among people:", [(g.nodes[nid].props["name"], round(s, 4)) for nid, s in top])

        print("\n-- 7. Query planner: a measurable index speedup at scale --")
        with g.transaction():
            for i in range(20000):
                g.create_node(["Item"], {"sku": f"SKU-{i:06d}"})
        target = "SKU-019999"
        t0 = time.perf_counter()
        scan_hits = sorted(
            n.props["sku"] for n in g.nodes.values() if "Item" in n.labels and n.props.get("sku") == target
        )
        t_scan = time.perf_counter() - t0
        with g.transaction():
            g.create_index("Item", "sku")
        t0 = time.perf_counter()
        idx_rows, plan2 = q(g, f"MATCH (i:Item {{sku: '{target}'}}) RETURN i.sku", explain=True)
        t_idx = time.perf_counter() - t0
        idx_hits = sorted(r["i.sku"] for r in idx_rows)
        assert idx_hits == scan_hits, "indexed and scanned lookups disagree"
        print(f" full scan:      {t_scan * 1000:.3f} ms")
        print(f" indexed lookup: {t_idx * 1000:.3f} ms  (plan: {plan2})")
        print(f" speedup: {t_scan / max(t_idx, 1e-9):.1f}x, identical results either way")

        g.close()
        print("\n=== demo complete: every required feature exercised end-to-end ===")
        return 0
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
