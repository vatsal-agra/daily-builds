"""Phylogenetic tree reconstruction: pairwise-alignment-derived distance
matrices, UPGMA (average-linkage clustering) and Neighbor-Joining tree
construction, and Newick serialization.

Pure Python 3 stdlib only.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from helix.align import global_align


class PhyloError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Distance matrices
# ---------------------------------------------------------------------------

def p_distance(aligned_a: str, aligned_b: str) -> float:
    """Proportion of aligned, non-gap columns that differ (the simplest
    sequence distance measure)."""
    if len(aligned_a) != len(aligned_b):
        raise PhyloError("aligned sequences must be the same length")
    compared = 0
    diffs = 0
    for x, y in zip(aligned_a, aligned_b):
        if x == "-" or y == "-":
            continue
        compared += 1
        if x != y:
            diffs += 1
    if compared == 0:
        raise PhyloError("no ungapped columns to compare")
    return diffs / compared


def jukes_cantor_distance(p: float) -> float:
    """Jukes-Cantor-corrected distance from a raw p-distance, accounting for
    unseen multiple substitutions at the same site. Undefined (saturated)
    for p >= 0.75; returns math.inf in that case rather than raising, since
    that is itself a meaningful (if uninformative) result."""
    if p < 0:
        raise PhyloError("p-distance must be non-negative")
    if p >= 0.75:
        return math.inf
    return -0.75 * math.log(1 - (4.0 / 3.0) * p)


def distance_matrix(
    sequences: dict[str, str], *, correction: str = "jc", **align_kwargs,
) -> tuple[list[str], list[list[float]]]:
    """Build a symmetric distance matrix over named DNA sequences by
    globally aligning every pair (Gotoh affine-gap) and converting the
    resulting alignment's p-distance to a final distance.

    correction: 'raw' (p-distance) or 'jc' (Jukes-Cantor corrected).
    Returns (names, matrix) where matrix[i][j] is the distance between
    names[i] and names[j] (matrix[i][i] == 0.0).
    """
    if correction not in ("raw", "jc"):
        raise PhyloError("correction must be 'raw' or 'jc'")
    if len(sequences) < 2:
        raise PhyloError("need at least 2 sequences to build a distance matrix")
    names = list(sequences.keys())
    n = len(names)
    mat = [[0.0] * n for _ in range(n)]
    default_kwargs = dict(match=1, mismatch=-1, gap_open=4, gap_extend=1)
    default_kwargs.update(align_kwargs)
    for i in range(n):
        for j in range(i + 1, n):
            aln = global_align(sequences[names[i]], sequences[names[j]], **default_kwargs)
            p = p_distance(aln.aligned_a, aln.aligned_b)
            d = jukes_cantor_distance(p) if correction == "jc" else p
            mat[i][j] = mat[j][i] = d
    return names, mat


def distance_matrix_is_ultrametric(names: list[str], mat: list[list[float]], tol: float = 1e-9) -> bool:
    """Check the three-point/ultrametric condition: for every triple i,j,k
    the two largest of {d(i,j), d(i,k), d(j,k)} are equal."""
    n = len(names)
    for i in range(n):
        for j in range(i + 1, n):
            for k in range(j + 1, n):
                d = sorted([mat[i][j], mat[i][k], mat[j][k]])
                if abs(d[1] - d[2]) > tol:
                    return False
    return True


# ---------------------------------------------------------------------------
# Tree representation + Newick
# ---------------------------------------------------------------------------

@dataclass
class TreeNode:
    name: str | None = None          # set only on leaves
    children: list["TreeNode"] = field(default_factory=list)
    branch_length: float = 0.0        # length of the edge to this node's parent

    def is_leaf(self) -> bool:
        return not self.children

    def leaves(self) -> list["TreeNode"]:
        if self.is_leaf():
            return [self]
        out = []
        for c in self.children:
            out.extend(c.leaves())
        return out

    def total_branch_length(self) -> float:
        total = self.branch_length
        for c in self.children:
            total += c.total_branch_length()
        return total

    def to_newick(self) -> str:
        return _newick(self) + ";"


def _fmt(x: float) -> str:
    return f"{x:.6f}".rstrip("0").rstrip(".") or "0"


def _newick(node: TreeNode) -> str:
    if node.is_leaf():
        return f"{node.name}:{_fmt(node.branch_length)}"
    inner = ",".join(_newick(c) for c in node.children)
    if node.branch_length:
        return f"({inner}):{_fmt(node.branch_length)}"
    return f"({inner})"


# ---------------------------------------------------------------------------
# UPGMA
# ---------------------------------------------------------------------------

def upgma(names: list[str], mat: list[list[float]]) -> TreeNode:
    """Average-linkage hierarchical clustering (UPGMA). Produces an
    ultrametric, rooted binary tree (or a multifurcation only in the
    degenerate case of exact distance ties)."""
    n = len(names)
    if n < 2:
        raise PhyloError("UPGMA needs at least 2 taxa")
    # Each active cluster: id -> (TreeNode, size, height)
    next_id = n
    clusters: dict[int, tuple[TreeNode, int, float]] = {
        i: (TreeNode(name=names[i]), 1, 0.0) for i in range(n)
    }
    # distances between active cluster ids
    dist: dict[tuple[int, int], float] = {}
    for i in range(n):
        for j in range(i + 1, n):
            dist[(i, j)] = mat[i][j]

    def d(a, b):
        return dist[(a, b)] if a < b else dist[(b, a)]

    active = list(range(n))
    while len(active) > 1:
        # find closest pair
        best = None
        for ii in range(len(active)):
            for jj in range(ii + 1, len(active)):
                a, b = active[ii], active[jj]
                dd = d(a, b)
                if best is None or dd < best[0]:
                    best = (dd, a, b)
        dd, a, b = best
        node_a, size_a, height_a = clusters[a]
        node_b, size_b, height_b = clusters[b]
        new_height = dd / 2.0
        node_a.branch_length = max(new_height - height_a, 0.0)
        node_b.branch_length = max(new_height - height_b, 0.0)
        new_node = TreeNode(children=[node_a, node_b])
        new_size = size_a + size_b
        # update distances to the merged cluster (average linkage)
        for c in active:
            if c in (a, b):
                continue
            new_d = (size_a * d(a, c) + size_b * d(b, c)) / new_size
            dist[(min(c, next_id), max(c, next_id))] = new_d
        clusters[next_id] = (new_node, new_size, new_height)
        active = [c for c in active if c not in (a, b)] + [next_id]
        next_id += 1

    root = clusters[active[0]][0]
    root.branch_length = 0.0
    return root


# ---------------------------------------------------------------------------
# Neighbor-Joining (Saitou & Nei, 1987)
# ---------------------------------------------------------------------------

def neighbor_joining(names: list[str], mat: list[list[float]]) -> TreeNode:
    """Saitou-Nei neighbor joining. Produces an unrooted tree represented
    here as a rooted TreeNode at the final internal join (the standard way
    to display an NJ tree; branch lengths are unaffected by this choice)."""
    n = len(names)
    if n < 2:
        raise PhyloError("Neighbor-Joining needs at least 2 taxa")
    if n == 2:
        a, b = TreeNode(name=names[0]), TreeNode(name=names[1])
        d = mat[0][1]
        a.branch_length = d / 2.0
        b.branch_length = d / 2.0
        return TreeNode(children=[a, b])

    next_id = n
    nodes: dict[int, TreeNode] = {i: TreeNode(name=names[i]) for i in range(n)}
    dist: dict[int, dict[int, float]] = {i: {} for i in range(n)}
    for i in range(n):
        for j in range(n):
            if i != j:
                dist[i][j] = mat[i][j]

    active = list(range(n))

    while len(active) > 2:
        m = len(active)
        row_sum = {i: sum(dist[i][j] for j in active if j != i) for i in active}
        # Q-matrix minimization
        best = None
        for ii in range(m):
            for jj in range(ii + 1, m):
                i, j = active[ii], active[jj]
                q = (m - 2) * dist[i][j] - row_sum[i] - row_sum[j]
                if best is None or q < best[0]:
                    best = (q, i, j)
        _, i, j = best
        dij = dist[i][j]
        delta = (row_sum[i] - row_sum[j]) / (m - 2)
        limb_i = max(0.5 * (dij + delta), 0.0)
        limb_j = max(0.5 * (dij - delta), 0.0)
        nodes[i].branch_length = limb_i
        nodes[j].branch_length = limb_j
        new_node = TreeNode(children=[nodes[i], nodes[j]])
        new_dist = {}
        for k in active:
            if k in (i, j):
                continue
            new_dist[k] = 0.5 * (dist[i][k] + dist[j][k] - dij)
        nodes[next_id] = new_node
        dist[next_id] = new_dist
        for k in new_dist:
            dist[k][next_id] = new_dist[k]
        for k in active:
            dist[k].pop(i, None)
            dist[k].pop(j, None)
        del dist[i]
        del dist[j]
        active = [k for k in active if k not in (i, j)] + [next_id]
        next_id += 1

    # exactly two active nodes remain: join them with the final edge,
    # split proportionally (the standard NJ convention).
    i, j = active
    dij = dist[i][j]
    nodes[i].branch_length = dij / 2.0
    nodes[j].branch_length = dij / 2.0
    return TreeNode(children=[nodes[i], nodes[j]])
