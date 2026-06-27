"""
HNSW — Hierarchical Navigable Small World index.

Reference: Malkov & Yashunin, "Efficient and Robust Approximate Nearest
Neighbor Search Using Hierarchical Navigable Small World Graphs", 2018.
https://arxiv.org/abs/1603.09320

Algorithms implemented (numbered as in the paper):
  1. INSERT
  2. SEARCH-LAYER  (beam search within one layer)
  3. SELECT-NEIGHBORS-HEURISTIC  (diversity-aware pruning)
  4. K-NN-SEARCH  (top-level query)

Additional:
  - DELETE via tombstoning + opportunistic re-link
  - Serialisation / deserialisation to plain dict (JSON-safe)
"""
from __future__ import annotations

import heapq
import json
import math
import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

from .distance import get_metric, get_batch_metric, VALID_METRICS


# ---------------------------------------------------------------------------
# Internal node
# ---------------------------------------------------------------------------

@dataclass
class _Node:
    id: int
    vector: np.ndarray
    level: int                              # max layer this node lives in
    neighbors: List[List[int]]             # neighbors[layer] = list of neighbor ids
    metadata: Dict[str, Any] = field(default_factory=dict)
    deleted: bool = False

    def __post_init__(self):
        # ensure neighbors list is exactly level+1 entries
        while len(self.neighbors) <= self.level:
            self.neighbors.append([])


# ---------------------------------------------------------------------------
# Priority queue helpers  (we use a min-heap on (distance, id) pairs)
# ---------------------------------------------------------------------------

def _heap_push(heap, dist, nid):
    heapq.heappush(heap, (dist, nid))


def _heap_pop(heap):
    return heapq.heappop(heap)


def _heap_largest(heap):
    # O(n) — only used for the "candidates" max-heap trick in beam search
    return max(heap)


# ---------------------------------------------------------------------------
# HNSW Index
# ---------------------------------------------------------------------------

class HNSWIndex:
    """
    Approximate nearest-neighbour index using Hierarchical Navigable Small
    World graphs.

    Parameters
    ----------
    dim : int
        Dimensionality of vectors.
    metric : str
        One of "cosine", "euclidean", "inner".
    M : int
        Maximum number of bi-directional connections per node per layer.
        M_max0 (layer 0) = 2*M.
    ef_construction : int
        Beam width during index construction.
    ef_search : int
        Default beam width during search (overridable per query).
    seed : int | None
        Random seed for reproducibility.
    """

    def __init__(
        self,
        dim: int,
        metric: str = "cosine",
        M: int = 16,
        ef_construction: int = 200,
        ef_search: int = 50,
        seed: Optional[int] = None,
    ):
        if metric not in VALID_METRICS:
            raise ValueError(f"metric must be one of {sorted(VALID_METRICS)}")
        if dim < 1:
            raise ValueError("dim must be >= 1")
        if M < 2:
            raise ValueError("M must be >= 2")
        if ef_construction < M:
            raise ValueError("ef_construction must be >= M")

        self.dim = dim
        self.metric = metric
        self.M = M
        self.M0 = 2 * M          # max connections at layer 0
        self.ef_construction = ef_construction
        self.ef_search = ef_search
        self.mL = 1.0 / math.log(M)  # normalisation for level generation

        self._dist = get_metric(metric)
        self._dist_batch = get_batch_metric(metric)
        self._rng = random.Random(seed)

        self._nodes: Dict[int, _Node] = {}
        self._entry_point: Optional[int] = None
        self._max_layer: int = -1
        self._next_id: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def size(self) -> int:
        return sum(1 for n in self._nodes.values() if not n.deleted)

    @property
    def total_nodes(self) -> int:
        return len(self._nodes)

    def insert(
        self,
        vector: np.ndarray,
        metadata: Optional[Dict[str, Any]] = None,
        node_id: Optional[int] = None,
    ) -> int:
        """
        Insert a vector into the index.  Returns the assigned node id.
        """
        vector = self._coerce(vector)
        nid = node_id if node_id is not None else self._next_id
        self._next_id = max(self._next_id, nid + 1)
        level = self._random_level()
        node = _Node(
            id=nid,
            vector=vector,
            level=level,
            neighbors=[[] for _ in range(level + 1)],
            metadata=metadata or {},
        )
        self._nodes[nid] = node

        # Algorithm 1 — INSERT
        ep_id = self._entry_point

        if ep_id is None:
            # first node becomes the global entry point
            self._entry_point = nid
            self._max_layer = level
            return nid

        ep_dist = self._dist(vector, self._nodes[ep_id].vector)

        # Phase 1: descend from max_layer down to level+1 (greedy, ef=1)
        for lc in range(self._max_layer, level, -1):
            ep_id, ep_dist = self._greedy_descend(vector, ep_id, ep_dist, lc)

        # Phase 2: for each layer from min(level, max_layer) down to 0,
        # beam-search and link bidirectionally.
        for lc in range(min(level, self._max_layer), -1, -1):
            candidates = self._search_layer(
                vector, ep_id, ep_dist, self.ef_construction, lc
            )
            # select M neighbours (M0 at layer 0)
            M_max = self.M0 if lc == 0 else self.M
            neighbours = self._select_neighbours(vector, candidates, M_max)

            node.neighbors[lc] = [nb_id for nb_id in neighbours]

            # bidirectional link
            for nb_id in neighbours:
                nb = self._nodes[nb_id]
                nb_neighbours = nb.neighbors[lc]
                if len(nb_neighbours) < M_max:
                    nb_neighbours.append(nid)
                else:
                    # shrink: keep the best M_max connections
                    nb_neighbours.append(nid)
                    pruned = self._select_neighbours(
                        nb.vector,
                        [(self._dist(nb.vector, self._nodes[x].vector), x)
                         for x in nb_neighbours if not self._nodes[x].deleted],
                        M_max,
                    )
                    nb.neighbors[lc] = list(pruned)

            # update entry point for next layer
            ep_id, ep_dist = candidates[0][1], candidates[0][0]

        # update global entry point if node has a higher level
        if level > self._max_layer:
            self._entry_point = nid
            self._max_layer = level

        return nid

    def search(
        self,
        query: np.ndarray,
        k: int = 10,
        ef: Optional[int] = None,
        filter_fn=None,
    ) -> List[Tuple[int, float, Dict[str, Any]]]:
        """
        Return the k approximate nearest neighbours.

        Returns a list of (id, distance, metadata) sorted ascending by distance.
        filter_fn(metadata) -> bool may be supplied for post-filter.
        """
        if not self._nodes or self._entry_point is None:
            return []
        query = self._coerce(query)
        ef = ef or self.ef_search

        # Algorithm 4 — K-NN-SEARCH
        ep_id = self._entry_point
        ep_dist = self._dist(query, self._nodes[ep_id].vector)

        # descend to layer 1 with greedy search
        for lc in range(self._max_layer, 0, -1):
            ep_id, ep_dist = self._greedy_descend(query, ep_id, ep_dist, lc)

        # beam search on layer 0 with ef candidates
        candidates = self._search_layer(query, ep_id, ep_dist, max(ef, k), 0)

        results = []
        for dist, nid in candidates:
            if self._nodes[nid].deleted:
                continue
            meta = self._nodes[nid].metadata
            if filter_fn is not None and not filter_fn(meta):
                continue
            results.append((nid, dist, meta))
            if len(results) == k:
                break

        return results

    def delete(self, node_id: int) -> bool:
        """Lazy-delete: mark the node as deleted.  Returns True if found."""
        if node_id not in self._nodes:
            return False
        self._nodes[node_id].deleted = True
        # If the entry point was deleted, find a new one.
        if self._entry_point == node_id:
            self._entry_point = next(
                (n.id for n in self._nodes.values() if not n.deleted), None
            )
            if self._entry_point is not None:
                self._max_layer = self._nodes[self._entry_point].level
        return True

    def get_node(self, node_id: int) -> Optional[_Node]:
        return self._nodes.get(node_id)

    def all_ids(self) -> List[int]:
        return [n.id for n in self._nodes.values() if not n.deleted]

    # ------------------------------------------------------------------
    # HNSW Algorithms
    # ------------------------------------------------------------------

    def _random_level(self) -> int:
        # Algorithm 1, eq. (1): level = floor(-ln(uniform(0,1]) * mL)
        return int(math.floor(-math.log(self._rng.random() or 1e-10) * self.mL))

    def _greedy_descend(
        self, query: np.ndarray, ep_id: int, ep_dist: float, layer: int
    ) -> Tuple[int, float]:
        """One-step greedy walk: always move to the closest neighbour."""
        improved = True
        while improved:
            improved = False
            for nb_id in self._nodes[ep_id].neighbors[layer]:
                if nb_id not in self._nodes or self._nodes[nb_id].deleted:
                    continue
                d = self._dist(query, self._nodes[nb_id].vector)
                if d < ep_dist:
                    ep_id, ep_dist = nb_id, d
                    improved = True
        return ep_id, ep_dist

    def _search_layer(
        self,
        query: np.ndarray,
        ep_id: int,
        ep_dist: float,
        ef: int,
        layer: int,
    ) -> List[Tuple[float, int]]:
        """
        Algorithm 2 — SEARCH-LAYER.
        Returns a sorted list of (distance, node_id) of at most ef candidates.
        Batches distance computations per node expansion for speed.
        """
        visited: Set[int] = {ep_id}
        # candidates: min-heap (closest first)
        candidates: List[Tuple[float, int]] = [(ep_dist, ep_id)]
        # W (working set): max-heap — negated distances so heappop removes furthest
        W: List[Tuple[float, int]] = [(-ep_dist, ep_id)]

        while candidates:
            c_dist, c_id = heapq.heappop(candidates)
            f_dist = -W[0][0]
            if c_dist > f_dist:
                break   # all remaining candidates are further than the furthest in W

            # Collect unvisited, non-deleted neighbours and batch their distances
            nb_ids = []
            nb_vecs = []
            for nb_id in self._nodes[c_id].neighbors[layer]:
                if nb_id in visited or nb_id not in self._nodes:
                    continue
                nb_node = self._nodes[nb_id]
                visited.add(nb_id)
                if not nb_node.deleted:
                    nb_ids.append(nb_id)
                    nb_vecs.append(nb_node.vector)

            if not nb_ids:
                continue

            # One vectorized distance call for all neighbours at once
            if len(nb_ids) == 1:
                dists = [self._dist(query, nb_vecs[0])]
            else:
                mat = np.stack(nb_vecs)
                dists = self._dist_batch(query, mat).tolist()

            f_dist2 = -W[0][0]
            for nb_id, nb_dist in zip(nb_ids, dists):
                if nb_dist < f_dist2 or len(W) < ef:
                    heapq.heappush(candidates, (nb_dist, nb_id))
                    heapq.heappush(W, (-nb_dist, nb_id))
                    if len(W) > ef:
                        heapq.heappop(W)
                        f_dist2 = -W[0][0]

        # Return sorted (closest first)
        return sorted((-nd, nid) for nd, nid in W)

    def _select_neighbours(
        self,
        query: np.ndarray,
        candidates: List[Tuple[float, int]],
        M: int,
    ) -> List[int]:
        """
        Algorithm 3 — SELECT-NEIGHBORS-HEURISTIC.
        Prefer closer neighbours but keep them diverse (avoid all clustering
        behind one hub by checking whether a candidate is closer to the
        query than to any already-selected neighbour).
        """
        if not candidates:
            return []

        # Sort by distance (ascending)
        sorted_cands = sorted(candidates)
        result: List[int] = []
        discarded: List[Tuple[float, int]] = []

        for dist, nid in sorted_cands:
            if len(result) >= M:
                break
            node = self._nodes.get(nid)
            if node is None or node.deleted:
                continue
            # Keep if it is closer to query than to any already-accepted neighbour
            is_diverse = True
            for nb_id in result:
                nb_node = self._nodes[nb_id]
                if self._dist(node.vector, nb_node.vector) < dist:
                    is_diverse = False
                    break
            if is_diverse:
                result.append(nid)
            else:
                discarded.append((dist, nid))

        # If we still need more neighbours, fill from discarded
        for dist, nid in discarded:
            if len(result) >= M:
                break
            result.append(nid)

        return result

    # ------------------------------------------------------------------
    # Layer graph access (for visualisation)
    # ------------------------------------------------------------------

    def get_layer_graph(self, layer: int) -> Dict[int, List[int]]:
        """Return adjacency dict for the given layer (non-deleted nodes only)."""
        graph = {}
        for nid, node in self._nodes.items():
            if node.deleted or node.level < layer:
                continue
            nbs = [n for n in node.neighbors[layer]
                   if n in self._nodes and not self._nodes[n].deleted]
            graph[nid] = nbs
        return graph

    def stats(self) -> Dict[str, Any]:
        live = [n for n in self._nodes.values() if not n.deleted]
        if not live:
            return {"size": 0, "max_layer": -1}
        layer_counts = {}
        total_edges = 0
        for n in live:
            for lc in range(n.level + 1):
                layer_counts[lc] = layer_counts.get(lc, 0) + 1
                total_edges += len(n.neighbors[lc])
        return {
            "size": len(live),
            "deleted": len(self._nodes) - len(live),
            "max_layer": self._max_layer,
            "M": self.M,
            "M0": self.M0,
            "ef_construction": self.ef_construction,
            "ef_search": self.ef_search,
            "metric": self.metric,
            "dim": self.dim,
            "layer_node_counts": layer_counts,
            "total_edges": total_edges,
            "avg_degree_l0": total_edges / max(len(live), 1),
        }

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        nodes_data = {}
        for nid, node in self._nodes.items():
            nodes_data[nid] = {
                "v": node.vector.tolist(),
                "l": node.level,
                "n": node.neighbors,
                "m": node.metadata,
                "d": node.deleted,
            }
        return {
            "version": 1,
            "dim": self.dim,
            "metric": self.metric,
            "M": self.M,
            "ef_construction": self.ef_construction,
            "ef_search": self.ef_search,
            "entry_point": self._entry_point,
            "max_layer": self._max_layer,
            "next_id": self._next_id,
            "nodes": nodes_data,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "HNSWIndex":
        idx = cls(
            dim=d["dim"],
            metric=d["metric"],
            M=d["M"],
            ef_construction=d["ef_construction"],
            ef_search=d["ef_search"],
        )
        idx._entry_point = d["entry_point"]
        idx._max_layer = d["max_layer"]
        idx._next_id = d["next_id"]
        for nid_str, nd in d["nodes"].items():
            nid = int(nid_str)
            node = _Node(
                id=nid,
                vector=np.array(nd["v"], dtype=np.float64),
                level=nd["l"],
                neighbors=[list(x) for x in nd["n"]],
                metadata=nd.get("m", {}),
                deleted=nd.get("d", False),
            )
            idx._nodes[nid] = node
        return idx

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _coerce(self, v) -> np.ndarray:
        arr = np.asarray(v, dtype=np.float64)
        if arr.shape != (self.dim,):
            raise ValueError(
                f"Vector dim mismatch: expected {self.dim}, got {arr.shape}"
            )
        return arr
