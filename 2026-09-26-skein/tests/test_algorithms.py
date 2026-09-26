"""Each algorithm test cross-checks skein.algorithms against an oracle
written with a *different* algorithm and no shared code: BFS is checked
against an all-pairs Floyd-Warshall hop-count DP, Dijkstra against a
Bellman-Ford relaxation, PageRank's fixed point against a direct linear
solve (Gaussian elimination on the balance equations, not power
iteration), and connected components against a from-scratch DFS flood
fill instead of union-find.
"""
import random
import unittest

from skein.storage import Graph
from skein import algorithms


def build_random_graph(n_nodes, n_edges, seed, weighted=False):
    random.seed(seed)
    g = Graph()
    with g.transaction():
        ids = [g.create_node(["N"], {"i": i}) for i in range(n_nodes)]
        for _ in range(n_edges):
            a, b = random.choice(ids), random.choice(ids)
            props = {"weight": random.randint(1, 20)} if weighted else {}
            g.create_edge(a, b, "E", props)
    return g, ids


# ------------------------------------------------------------- oracles --

def floyd_warshall_hops(graph, node_ids):
    """All-pairs fewest-hops distance via the Floyd-Warshall DP -- an
    independent algorithm family from BFS's queue-based frontier expansion.
    """
    INF = float("inf")
    idx = {nid: i for i, nid in enumerate(node_ids)}
    n = len(node_ids)
    dist = [[INF] * n for _ in range(n)]
    for i in range(n):
        dist[i][i] = 0
    for edge in graph.edges.values():
        i, j = idx[edge.src], idx[edge.dst]
        dist[i][j] = min(dist[i][j], 1)
    for k in range(n):
        for i in range(n):
            if dist[i][k] == INF:
                continue
            for j in range(n):
                if dist[i][k] + dist[k][j] < dist[i][j]:
                    dist[i][j] = dist[i][k] + dist[k][j]
    return dist, idx


def bellman_ford(graph, node_ids, src, weight_prop="weight"):
    INF = float("inf")
    dist = {nid: INF for nid in node_ids}
    dist[src] = 0
    edges = [(e.src, e.dst, e.props.get(weight_prop, 1.0)) for e in graph.edges.values()]
    for _ in range(len(node_ids) - 1):
        changed = False
        for u, v, w in edges:
            if dist[u] + w < dist[v]:
                dist[v] = dist[u] + w
                changed = True
        if not changed:
            break
    return dist


def dfs_components(graph):
    """Weakly-connected components via an explicit-stack DFS flood fill --
    a different algorithm from union-find, sharing no code with it.
    """
    undirected = {nid: set() for nid in graph.nodes}
    for e in graph.edges.values():
        undirected[e.src].add(e.dst)
        undirected[e.dst].add(e.src)
    seen = set()
    comps = []
    for start in graph.nodes:
        if start in seen:
            continue
        stack = [start]
        comp = set()
        while stack:
            cur = stack.pop()
            if cur in comp:
                continue
            comp.add(cur)
            stack.extend(undirected[cur] - comp)
        seen |= comp
        comps.append(comp)
    return comps


def solve_pagerank_linear(graph, damping=0.85):
    """Solve PageRank's fixed point directly: r = (1-d)/N * 1 + d * M r,
    i.e. (I - d*M) r = (1-d)/N * 1, via hand-rolled Gaussian elimination.
    An entirely different computational path from power iteration.
    """
    nodes = list(graph.nodes.keys())
    n = len(nodes)
    idx = {nid: i for i, nid in enumerate(nodes)}
    out_deg = {nid: len(graph.out_edges[nid]) for nid in nodes}

    # Build M (column j has 1/out_deg(j) at each row i it links to; a
    # dangling column j spreads 1/n to every row, matching algorithms.py).
    M = [[0.0] * n for _ in range(n)]
    for nid in nodes:
        j = idx[nid]
        if out_deg[nid] == 0:
            for i in range(n):
                M[i][j] = 1.0 / n
        else:
            for eid in graph.out_edges[nid]:
                i = idx[graph.edges[eid].dst]
                M[i][j] += 1.0 / out_deg[nid]

    A = [[(1.0 if i == k else 0.0) - damping * M[i][k] for k in range(n)] for i in range(n)]
    b = [(1.0 - damping) / n] * n

    # Gaussian elimination with partial pivoting.
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(A[r][col]))
        A[col], A[pivot] = A[pivot], A[col]
        b[col], b[pivot] = b[pivot], b[col]
        pv = A[col][col]
        for k in range(col, n):
            A[col][k] /= pv
        b[col] /= pv
        for r in range(n):
            if r != col and A[r][col] != 0:
                factor = A[r][col]
                for k in range(col, n):
                    A[r][k] -= factor * A[col][k]
                b[r] -= factor * b[col]
    return {nodes[i]: b[i] for i in range(n)}


# ---------------------------------------------------------------- tests --

class TestBFS(unittest.TestCase):
    def test_random_graphs_against_floyd_warshall(self):
        for seed in range(15):
            g, ids = build_random_graph(8, 14, seed)
            dist, idx = floyd_warshall_hops(g, ids)
            for src in ids:
                for dst in ids:
                    path = algorithms.bfs_shortest_path(g, src, dst)
                    expected = dist[idx[src]][idx[dst]]
                    if expected == float("inf"):
                        self.assertIsNone(path, f"seed={seed} src={src} dst={dst}")
                    else:
                        self.assertIsNotNone(path, f"seed={seed} src={src} dst={dst}")
                        self.assertEqual(len(path) - 1, expected, f"seed={seed} src={src} dst={dst}")
                        self.assertEqual(path[0], src)
                        self.assertEqual(path[-1], dst)

    def test_path_edges_actually_exist(self):
        g, ids = build_random_graph(10, 15, seed=1)
        for src in ids:
            for dst in ids:
                path = algorithms.bfs_shortest_path(g, src, dst)
                if path is None:
                    continue
                for a, b in zip(path, path[1:]):
                    self.assertTrue(
                        any(e.dst == b for eid in g.out_edges[a] for e in [g.edges[eid]]),
                        f"no edge {a}->{b} in claimed path {path}",
                    )


class TestDijkstra(unittest.TestCase):
    def test_random_weighted_graphs_against_bellman_ford(self):
        for seed in range(15):
            g, ids = build_random_graph(8, 14, seed, weighted=True)
            for src in ids:
                bf = bellman_ford(g, ids, src)
                for dst in ids:
                    path, weight = algorithms.dijkstra_shortest_path(g, src, dst)
                    expected = bf[dst]
                    if expected == float("inf"):
                        self.assertIsNone(path, f"seed={seed} src={src} dst={dst}")
                    else:
                        self.assertAlmostEqual(weight, expected, places=9, msg=f"seed={seed} src={src} dst={dst}")

    def test_negative_weight_rejected(self):
        g = Graph()
        with g.transaction():
            a = g.create_node(["N"], {})
            b = g.create_node(["N"], {})
            g.create_edge(a, b, "E", {"weight": -5})
        with self.assertRaises(Exception):
            algorithms.dijkstra_shortest_path(g, a, b)

    def test_unweighted_edges_default_to_one(self):
        g = Graph()
        with g.transaction():
            a = g.create_node(["N"], {})
            b = g.create_node(["N"], {})
            c = g.create_node(["N"], {})
            g.create_edge(a, b, "E", {})
            g.create_edge(b, c, "E", {})
        path, weight = algorithms.dijkstra_shortest_path(g, a, c)
        self.assertEqual(weight, 2.0)


class TestPageRank(unittest.TestCase):
    def test_sums_to_one(self):
        g, ids = build_random_graph(12, 20, seed=2)
        pr = algorithms.pagerank(g)
        self.assertAlmostEqual(sum(pr.values()), 1.0, places=6)

    def test_matches_direct_linear_solve(self):
        for seed in range(8):
            g, ids = build_random_graph(6, 10, seed)
            power = algorithms.pagerank(g, max_iter=500, tol=1e-14)
            linear = solve_pagerank_linear(g)
            for nid in ids:
                self.assertAlmostEqual(power[nid], linear[nid], places=6, msg=f"seed={seed} node={nid}")

    def test_dangling_node_does_not_leak_rank(self):
        g = Graph()
        with g.transaction():
            a = g.create_node(["N"], {})
            b = g.create_node(["N"], {})  # b has no outgoing edges: dangling
            g.create_edge(a, b, "E", {})
        pr = algorithms.pagerank(g)
        self.assertAlmostEqual(sum(pr.values()), 1.0, places=6)

    def test_empty_graph(self):
        g = Graph()
        self.assertEqual(algorithms.pagerank(g), {})


class TestConnectedComponents(unittest.TestCase):
    def test_random_graphs_against_dfs_flood_fill(self):
        for seed in range(15):
            g, ids = build_random_graph(10, 12, seed)
            expected = dfs_components(g)
            actual = algorithms.connected_components(g)
            self.assertEqual(
                sorted(frozenset(c) for c in expected),
                sorted(frozenset(c) for c in actual),
                f"seed={seed}",
            )

    def test_isolated_nodes_are_singleton_components(self):
        g = Graph()
        with g.transaction():
            a = g.create_node(["N"], {})
            b = g.create_node(["N"], {})
        comps = algorithms.connected_components(g)
        self.assertEqual(sorted(frozenset(c) for c in comps), sorted([frozenset([a]), frozenset([b])]))

    def test_direction_ignored(self):
        g = Graph()
        with g.transaction():
            a = g.create_node(["N"], {})
            b = g.create_node(["N"], {})
            g.create_edge(b, a, "E", {})  # edge points b -> a
        comps = algorithms.connected_components(g)
        self.assertEqual(len(comps), 1)


if __name__ == "__main__":
    unittest.main()
