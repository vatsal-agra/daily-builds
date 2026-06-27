"""
Collection — high-level wrapper around an index that adds:
  - Named collection management
  - JSON persistence (save / load)
  - Metadata-aware search with filter expressions
  - Bulk insert from JSONL
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

from .hnsw import HNSWIndex
from .lsh import LSHIndex


class Collection:
    """
    A named, persistent collection of vectors backed by an HNSW index.

    Parameters
    ----------
    name : str
        Collection name (used as the file stem for persistence).
    dim : int
        Vector dimensionality.
    metric : str
        Distance metric: "cosine", "euclidean", or "inner".
    index_type : str
        "hnsw" or "lsh"
    index_params : dict
        Forwarded verbatim to HNSWIndex or LSHIndex constructor.
    """

    def __init__(
        self,
        name: str,
        dim: int,
        metric: str = "cosine",
        index_type: str = "hnsw",
        index_params: Optional[Dict[str, Any]] = None,
    ):
        self.name = name
        self.dim = dim
        self.metric = metric
        self.index_type = index_type
        params = index_params or {}

        if index_type == "hnsw":
            self._index = HNSWIndex(dim=dim, metric=metric, **params)
        elif index_type == "lsh":
            self._index = LSHIndex(dim=dim, **params)
        else:
            raise ValueError(f"Unknown index_type '{index_type}'. Use 'hnsw' or 'lsh'.")

    # ------------------------------------------------------------------
    # Insert
    # ------------------------------------------------------------------

    def add(
        self,
        vector: np.ndarray,
        metadata: Optional[Dict[str, Any]] = None,
        node_id: Optional[int] = None,
    ) -> int:
        return self._index.insert(vector, metadata=metadata, node_id=node_id)

    def add_batch(self, vectors, metadatas=None) -> List[int]:
        ids = []
        for i, v in enumerate(vectors):
            meta = metadatas[i] if metadatas else None
            ids.append(self.add(v, meta))
        return ids

    def add_from_jsonl(self, path: str) -> int:
        """
        Insert vectors from a JSONL file.
        Each line must be a JSON object with at least a "vector" key.
        Optional keys: "id" (int), "metadata" (dict).
        Returns count of inserted vectors.
        """
        count = 0
        with open(path, "r", encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as e:
                    raise ValueError(f"Line {lineno}: invalid JSON — {e}") from e
                if "vector" not in obj:
                    raise ValueError(f"Line {lineno}: missing 'vector' key")
                self.add(
                    np.array(obj["vector"], dtype=np.float64),
                    metadata=obj.get("metadata"),
                    node_id=obj.get("id"),
                )
                count += 1
        return count

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self,
        query: np.ndarray,
        k: int = 10,
        ef: Optional[int] = None,
        filter_expr: Optional[Dict[str, Any]] = None,
    ) -> List[Tuple[int, float, Dict[str, Any]]]:
        """
        Search for k nearest neighbours.

        filter_expr, if provided, is a dict of {key: value} that must
        match the vector's metadata exactly (AND logic).
        """
        filter_fn = _make_filter(filter_expr) if filter_expr else None

        if isinstance(self._index, HNSWIndex):
            return self._index.search(query, k=k, ef=ef, filter_fn=filter_fn)
        else:
            return self._index.search(query, k=k, filter_fn=filter_fn)

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete(self, node_id: int) -> bool:
        return self._index.delete(node_id)

    # ------------------------------------------------------------------
    # Info
    # ------------------------------------------------------------------

    @property
    def size(self) -> int:
        return self._index.size

    def stats(self) -> Dict[str, Any]:
        return {"name": self.name, **self._index.stats()}

    def all_ids(self) -> List[int]:
        return self._index.all_ids()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: str) -> None:
        """Save collection to a JSON file."""
        data = {
            "version": 1,
            "name": self.name,
            "dim": self.dim,
            "metric": self.metric,
            "index_type": self.index_type,
            "index": self._index.to_dict(),
        }
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)

    @classmethod
    def load(cls, path: str) -> "Collection":
        """Load collection from a JSON file."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("version") != 1:
            raise ValueError(f"Unsupported collection version: {data.get('version')}")
        coll = cls.__new__(cls)
        coll.name = data["name"]
        coll.dim = data["dim"]
        coll.metric = data["metric"]
        coll.index_type = data["index_type"]
        if data["index_type"] == "hnsw":
            coll._index = HNSWIndex.from_dict(data["index"])
        elif data["index_type"] == "lsh":
            coll._index = LSHIndex.from_dict(data["index"])
        else:
            raise ValueError(f"Unknown index_type: {data['index_type']}")
        return coll

    # ------------------------------------------------------------------
    # Raw index access (for visualisation)
    # ------------------------------------------------------------------

    @property
    def index(self):
        return self._index


# ---------------------------------------------------------------------------
# Filter helper
# ---------------------------------------------------------------------------

def _make_filter(expr: Dict[str, Any]) -> Callable[[Dict], bool]:
    def fn(meta: Dict) -> bool:
        for k, v in expr.items():
            if meta.get(k) != v:
                return False
        return True
    return fn
