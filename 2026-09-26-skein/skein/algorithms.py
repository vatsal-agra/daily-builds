"""Classic graph algorithms over a Graph: BFS shortest path, Dijkstra
weighted shortest path, PageRank, and connected components. Each has an
independent brute-force/closed-form oracle in tests/test_algorithms.py
written with no shared code, so a bug here can't hide behind a bug in its
own test.
"""
import heapq
from collections import deque

from .storage import SkeinError


def _require_node(graph, nid, label):
    if nid not in graph.nodes:
        raise SkeinError(f"{label} node {nid} does not exist")


def bfs_shortest_path(graph, src, dst, directed=True):
    """Unweighted shortest path (fewest hops) from src to dst, or None."""
    _require_node(graph, src, "source")
    _require_node(graph, dst, "destination")
    if src == dst:
        return [src]
    visited = {src}
    parent = {}
    queue = deque([src])
    while queue:
        cur = queue.popleft()
        neighbors = [graph.edges[eid].dst for eid in graph.out_edges[cur]]
        if not directed:
            neighbors += [graph.edges[eid].src for eid in graph.in_edges[cur]]
        for nxt in neighbors:
            if nxt in visited:
                continue
            visited.add(nxt)
            parent[nxt] = cur
            if nxt == dst:
                path = [dst]
                while path[-1] != src:
                    path.append(parent[path[-1]])
                path.reverse()
                return path
            queue.append(nxt)
    return None


def dijkstra_shortest_path(graph, src, dst, weight_prop="weight", directed=True, default_weight=1.0):
    """Weighted shortest path from src to dst. Returns (path, total_weight)
    or (None, inf) if unreachable. Edge weights come from `weight_prop`
    (default 1.0 if absent, so an unweighted graph degenerates to BFS
    distance); negative weights raise, since Dijkstra is unsound there.
    """
    _require_node(graph, src, "source")
    _require_node(graph, dst, "destination")
    dist = {src: 0.0}
    parent = {}
    visited = set()
    pq = [(0.0, src)]
    while pq:
        d, cur = heapq.heappop(pq)
        if cur in visited:
            continue
        visited.add(cur)
        if cur == dst:
            break
        edges = [(eid, graph.edges[eid].dst) for eid in graph.out_edges[cur]]
        if not directed:
            edges += [(eid, graph.edges[eid].src) for eid in graph.in_edges[cur]]
        for eid, nxt in edges:
            w = graph.edges[eid].props.get(weight_prop, default_weight)
            if w < 0:
                raise SkeinError(f"edge {eid} has negative weight {w}; Dijkstra requires non-negative weights")
            nd = d + w
            if nxt not in dist or nd < dist[nxt] - 1e-15:
                dist[nxt] = nd
                parent[nxt] = cur
                heapq.heappush(pq, (nd, nxt))
    if dst not in dist:
        return None, float("inf")
    path = [dst]
    while path[-1] != src:
        path.append(parent[path[-1]])
    path.reverse()
    return path, dist[dst]


def pagerank(graph, damping=0.85, max_iter=200, tol=1e-12):
    """Power-iteration PageRank over directed edges, with the standard
    dangling-node fix (a node with no out-edges leaks its rank uniformly
    to every node instead of vanishing). Returns {node_id: score}, summing
    to ~1.0 for a non-empty graph.
    """
    nodes = list(graph.nodes.keys())
    n = len(nodes)
    if n == 0:
        return {}
    rank = {nid: 1.0 / n for nid in nodes}
    out_degree = {nid: len(graph.out_edges[nid]) for nid in nodes}
    for _ in range(max_iter):
        dangling_sum = sum(rank[nid] for nid in nodes if out_degree[nid] == 0)
        base = (1.0 - damping) / n + damping * dangling_sum / n
        new_rank = dict.fromkeys(nodes, base)
        for nid in nodes:
            if out_degree[nid] == 0:
                continue
            share = damping * rank[nid] / out_degree[nid]
            for eid in graph.out_edges[nid]:
                dst = graph.edges[eid].dst
                new_rank[dst] += share
        diff = sum(abs(new_rank[nid] - rank[nid]) for nid in nodes)
        rank = new_rank
        if diff < tol:
            break
    return rank


def connected_components(graph):
    """Weakly-connected components (edge direction ignored), via
    union-find. Returns a list of sets of node ids.
    """
    parent = {nid: nid for nid in graph.nodes}

    def find(x):
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    for edge in graph.edges.values():
        union(edge.src, edge.dst)

    groups = {}
    for nid in graph.nodes:
        groups.setdefault(find(nid), set()).add(nid)
    return list(groups.values())
