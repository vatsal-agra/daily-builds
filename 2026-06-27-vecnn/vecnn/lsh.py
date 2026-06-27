"""
LSH — Locality-Sensitive Hashing index for approximate nearest neighbours.

Uses random hyperplane projections for cosine similarity (SimHash).
For each of T hash tables we generate L random unit hyperplanes; a vector
maps to a bit-string of length L by signing each dot product.  Candidates
are the union of all vectors sharing the same bit-string in at least one table.

Parameters
----------
dim : int
    Dimensionality of vectors.
n_tables : int
    Number of independent hash tables (T).  More tables → higher recall,
    more memory.
n_bits : int
    Number of hyperplanes per table (L). Longer hash → fewer collisions per
    table, so raise n_tables to compensate.
seed : int | None
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .distance import cosine_distance


@dataclass
class _LSHNode:
    id: int
    vector: np.ndarray
    metadata: Dict[str, Any] = field(default_factory=dict)
    deleted: bool = False


class LSHIndex:
    def __init__(
        self,
        dim: int,
        n_tables: int = 10,
        n_bits: int = 16,
        seed: Optional[int] = None,
    ):
        if dim < 1:
            raise ValueError("dim must be >= 1")
        self.dim = dim
        self.n_tables = n_tables
        self.n_bits = n_bits
        self.metric = "cosine"   # LSH as implemented here is cosine-only

        rng = np.random.default_rng(seed)
        # hyperplanes[t] is shape (n_bits, dim) — each row is a unit normal
        self._hyperplanes: List[np.ndarray] = []
        for _ in range(n_tables):
            planes = rng.standard_normal((n_bits, dim))
            planes /= np.linalg.norm(planes, axis=1, keepdims=True)
            self._hyperplanes.append(planes)

        # tables[t][bucket_key] = list of node ids
        self._tables: List[Dict[tuple, List[int]]] = [{} for _ in range(n_tables)]
        self._nodes: Dict[int, _LSHNode] = {}
        self._next_id: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def size(self) -> int:
        return sum(1 for n in self._nodes.values() if not n.deleted)

    def insert(
        self,
        vector: np.ndarray,
        metadata: Optional[Dict[str, Any]] = None,
        node_id: Optional[int] = None,
    ) -> int:
        vector = self._coerce(vector)
        nid = node_id if node_id is not None else self._next_id
        self._next_id = max(self._next_id, nid + 1)

        node = _LSHNode(id=nid, vector=vector, metadata=metadata or {})
        self._nodes[nid] = node

        for t, planes in enumerate(self._hyperplanes):
            bucket = self._hash(vector, planes)
            self._tables[t].setdefault(bucket, []).append(nid)

        return nid

    def search(
        self,
        query: np.ndarray,
        k: int = 10,
        filter_fn=None,
    ) -> List[Tuple[int, float, Dict[str, Any]]]:
        if not self._nodes:
            return []
        query = self._coerce(query)

        # Collect candidate set from all tables
        candidate_ids: set = set()
        for t, planes in enumerate(self._hyperplanes):
            bucket = self._hash(query, planes)
            for nid in self._tables[t].get(bucket, []):
                candidate_ids.add(nid)

        # Score candidates by exact cosine distance
        results = []
        for nid in candidate_ids:
            node = self._nodes[nid]
            if node.deleted:
                continue
            if filter_fn is not None and not filter_fn(node.metadata):
                continue
            dist = cosine_distance(query, node.vector)
            results.append((dist, nid, node.metadata))

        results.sort()
        return [(nid, dist, meta) for dist, nid, meta in results[:k]]

    def delete(self, node_id: int) -> bool:
        if node_id not in self._nodes:
            return False
        self._nodes[node_id].deleted = True
        return True

    def all_ids(self) -> List[int]:
        return [n.id for n in self._nodes.values() if not n.deleted]

    def stats(self) -> Dict[str, Any]:
        live = sum(1 for n in self._nodes.values() if not n.deleted)
        return {
            "size": live,
            "n_tables": self.n_tables,
            "n_bits": self.n_bits,
            "dim": self.dim,
            "metric": self.metric,
        }

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    @staticmethod
    def _key_to_str(key: tuple) -> str:
        return "".join("1" if b else "0" for b in key)

    @staticmethod
    def _str_to_key(s: str) -> tuple:
        return tuple(c == "1" for c in s)

    def to_dict(self) -> Dict[str, Any]:
        tables_data = []
        for t_dict in self._tables:
            tables_data.append({self._key_to_str(k): v for k, v in t_dict.items()})
        nodes_data = {}
        for nid, node in self._nodes.items():
            nodes_data[nid] = {
                "v": node.vector.tolist(),
                "m": node.metadata,
                "d": node.deleted,
            }
        return {
            "version": 1,
            "dim": self.dim,
            "n_tables": self.n_tables,
            "n_bits": self.n_bits,
            "hyperplanes": [h.tolist() for h in self._hyperplanes],
            "tables": tables_data,
            "nodes": nodes_data,
            "next_id": self._next_id,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "LSHIndex":
        idx = cls.__new__(cls)
        idx.dim = d["dim"]
        idx.n_tables = d["n_tables"]
        idx.n_bits = d["n_bits"]
        idx.metric = "cosine"
        idx._next_id = d["next_id"]
        idx._hyperplanes = [np.array(h, dtype=np.float64) for h in d["hyperplanes"]]
        idx._tables = []
        for t_dict in d["tables"]:
            idx._tables.append({
                cls._str_to_key(k): v
                for k, v in t_dict.items()
            })
        idx._nodes = {}
        for nid_str, nd in d["nodes"].items():
            nid = int(nid_str)
            idx._nodes[nid] = _LSHNode(
                id=nid,
                vector=np.array(nd["v"], dtype=np.float64),
                metadata=nd.get("m", {}),
                deleted=nd.get("d", False),
            )
        return idx

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _hash(self, vector: np.ndarray, planes: np.ndarray) -> tuple:
        signs = (planes @ vector) >= 0
        return tuple(signs.tolist())

    def _coerce(self, v) -> np.ndarray:
        arr = np.asarray(v, dtype=np.float64)
        if arr.shape != (self.dim,):
            raise ValueError(f"Vector dim mismatch: expected {self.dim}, got {arr.shape}")
        return arr
