"""Durable property-graph storage: nodes/edges in memory, backed by a
CRC32-checked, fsynced write-ahead log plus periodic snapshotting.

Every mutation happens inside a transaction. In-memory effects apply
immediately (so a transaction can read its own writes); the WAL only
receives the transaction's operations, framed by begin/commit markers,
at commit time. Recovery replays committed transaction groups from the
last snapshot forward and silently drops any group that never reached a
commit marker -- exactly the state a real crash mid-transaction leaves.
"""
from __future__ import annotations

import json
import os
import struct
import threading
import zlib
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Tuple

from .index import LabelIndex, PropertyIndex

_MISSING = object()


class SkeinError(Exception):
    """A user-facing error: bad query, missing element, invalid mutation."""


class TransactionError(SkeinError):
    pass


@dataclass
class Node:
    id: int
    labels: FrozenSet[str]
    props: Dict[str, Any]


@dataclass
class Edge:
    id: int
    type: str
    src: int
    dst: int
    props: Dict[str, Any]


# ---------------------------------------------------------------- WAL I/O --

def _write_record(fh, payload: bytes) -> None:
    crc = zlib.crc32(payload)
    fh.write(struct.pack(">II", len(payload), crc))
    fh.write(payload)


def _read_records(fh):
    while True:
        header = fh.read(8)
        if len(header) < 8:
            return  # clean EOF or a torn header from a crash mid-write
        length, crc = struct.unpack(">II", header)
        payload = fh.read(length)
        if len(payload) < length:
            return  # torn payload: the last write never completed
        if zlib.crc32(payload) != crc:
            return  # corrupt tail: stop trusting anything from here on
        yield json.loads(payload.decode("utf-8"))


class _Txn:
    __slots__ = ("graph",)

    def __init__(self, graph: "Graph"):
        self.graph = graph

    def __enter__(self):
        self.graph.begin()
        return self.graph

    def __exit__(self, exc_type, exc, tb):
        if exc_type is not None:
            self.graph.rollback()
            return False
        self.graph.commit()
        return False


class Graph:
    def __init__(self, path: Optional[str] = None):
        self.path = path
        self.nodes: Dict[int, Node] = {}
        self.edges: Dict[int, Edge] = {}
        self.out_edges: Dict[int, List[int]] = {}
        self.in_edges: Dict[int, List[int]] = {}
        self._next_node_id = 1
        self._next_edge_id = 1

        self.label_index = LabelIndex()
        self.prop_indexes: Dict[Tuple[str, str], PropertyIndex] = {}

        self._lock = threading.RLock()
        self._txn_depth = 0
        self._txn_id = 0
        self._txn_id_counter = 0
        self._txn_ops: List[Tuple[dict, dict]] = []
        self._wal_fh = None
        self._snapshot_path = None
        self._wal_path = None

        if path:
            self._snapshot_path = path + ".snapshot.json"
            self._wal_path = path + ".wal"
            self._load()
            self._wal_fh = open(self._wal_path, "ab")

    # ------------------------------------------------------------ loading --

    def _load(self) -> None:
        if os.path.exists(self._snapshot_path):
            with open(self._snapshot_path, "r") as f:
                snap = json.load(f)
            # Trust the persisted counters over recomputing from surviving
            # ids: a node/edge created then deleted must not have its id
            # reused, and `_apply` below can only ever raise these further.
            self._next_node_id = snap["next_node_id"]
            self._next_edge_id = snap["next_edge_id"]
            for n in snap["nodes"]:
                self._apply({"op": "create_node", "id": n["id"], "labels": n["labels"], "props": n["props"]})
            for e in snap["edges"]:
                self._apply({"op": "create_edge", "id": e["id"], "type": e["type"], "src": e["src"], "dst": e["dst"], "props": e["props"]})
            for label, prop in snap.get("indexes", []):
                self._apply({"op": "create_index", "label": label, "prop": prop})
        if os.path.exists(self._wal_path):
            with open(self._wal_path, "rb") as f:
                self._replay_wal(f)

    def _replay_wal(self, fh) -> None:
        pending: Dict[int, List[dict]] = {}
        for rec in _read_records(fh):
            op = rec["op"]
            txn = rec.get("txn")
            if op == "begin":
                pending[txn] = []
            elif op == "commit":
                for queued in pending.pop(txn, []):
                    self._apply(queued)
            elif op == "rollback":
                pending.pop(txn, None)
            else:
                pending.setdefault(txn, []).append(rec)
        # Any transaction still pending here never reached a commit marker
        # (the process crashed mid-transaction) -- it is correctly discarded.

    # ------------------------------------------------------- transactions --

    def begin(self) -> int:
        with self._lock:
            if self._txn_depth == 0:
                self._txn_id_counter += 1
                self._txn_id = self._txn_id_counter
                self._txn_ops = []
            self._txn_depth += 1
            return self._txn_id

    def commit(self) -> None:
        with self._lock:
            if self._txn_depth == 0:
                raise TransactionError("commit() with no active transaction")
            self._txn_depth -= 1
            if self._txn_depth > 0:
                return
            if self._wal_fh is not None:
                txn = self._txn_id
                _write_record(self._wal_fh, json.dumps({"op": "begin", "txn": txn}).encode("utf-8"))
                for op, _undo in self._txn_ops:
                    rec = dict(op)
                    rec["txn"] = txn
                    _write_record(self._wal_fh, json.dumps(rec).encode("utf-8"))
                _write_record(self._wal_fh, json.dumps({"op": "commit", "txn": txn}).encode("utf-8"))
                self._wal_fh.flush()
                os.fsync(self._wal_fh.fileno())
            self._txn_ops = []

    def rollback(self) -> None:
        with self._lock:
            if self._txn_depth == 0:
                raise TransactionError("rollback() with no active transaction")
            for _op, undo in reversed(self._txn_ops):
                self._apply(undo)
            self._txn_ops = []
            self._txn_depth = 0

    def transaction(self) -> _Txn:
        return _Txn(self)

    def in_transaction(self) -> bool:
        return self._txn_depth > 0

    def _require_txn(self) -> None:
        if self._txn_depth == 0:
            raise TransactionError("mutation attempted outside of a transaction")

    def _log(self, op: dict, undo: dict) -> None:
        self._txn_ops.append((op, undo))

    # -------------------------------------------------------------- apply --
    # `_apply` is the single choke point that mutates in-memory state (and
    # keeps indexes in sync) for both live mutation calls, WAL replay, and
    # transaction rollback (whose "undo" records are themselves ordinary
    # forward ops) -- one code path, so replay can never drift from live
    # behavior.

    def _apply(self, op: dict) -> None:
        kind = op["op"]
        if kind == "create_node":
            nid = op["id"]
            labels = frozenset(op["labels"])
            props = dict(op["props"])
            self.nodes[nid] = Node(nid, labels, props)
            self.out_edges[nid] = []
            self.in_edges[nid] = []
            self.label_index.add(nid, labels)
            for label, prop, idx in self._indexes_for_labels(labels):
                if prop in props:
                    idx.add(props[prop], nid)
            if nid >= self._next_node_id:
                self._next_node_id = nid + 1
        elif kind == "delete_node":
            nid = op["id"]
            node = self.nodes.pop(nid)
            self.label_index.remove(nid, node.labels)
            for label, prop, idx in self._indexes_for_labels(node.labels):
                if prop in node.props:
                    idx.remove(node.props[prop], nid)
            del self.out_edges[nid]
            del self.in_edges[nid]
        elif kind == "create_edge":
            eid = op["id"]
            edge = Edge(eid, op["type"], op["src"], op["dst"], dict(op["props"]))
            self.edges[eid] = edge
            self.out_edges[edge.src].append(eid)
            self.in_edges[edge.dst].append(eid)
            if eid >= self._next_edge_id:
                self._next_edge_id = eid + 1
        elif kind == "delete_edge":
            eid = op["id"]
            edge = self.edges.pop(eid)
            self.out_edges[edge.src].remove(eid)
            self.in_edges[edge.dst].remove(eid)
        elif kind == "set_node_prop":
            nid, key, value = op["id"], op["key"], op["value"]
            node = self.nodes[nid]
            old = node.props.get(key, _MISSING)
            if old is not _MISSING:
                for label in node.labels:
                    idx = self.prop_indexes.get((label, key))
                    if idx is not None:
                        idx.remove(old, nid)
            node.props[key] = value
            for label in node.labels:
                idx = self.prop_indexes.get((label, key))
                if idx is not None:
                    idx.add(value, nid)
        elif kind == "unset_node_prop":
            nid, key = op["id"], op["key"]
            node = self.nodes[nid]
            old = node.props.pop(key, _MISSING)
            if old is not _MISSING:
                for label in node.labels:
                    idx = self.prop_indexes.get((label, key))
                    if idx is not None:
                        idx.remove(old, nid)
        elif kind == "set_edge_prop":
            eid, key, value = op["id"], op["key"], op["value"]
            self.edges[eid].props[key] = value
        elif kind == "unset_edge_prop":
            eid, key = op["id"], op["key"]
            self.edges[eid].props.pop(key, None)
        elif kind == "create_index":
            key = (op["label"], op["prop"])
            if key not in self.prop_indexes:
                idx = PropertyIndex()
                for n in self.nodes.values():
                    if op["label"] in n.labels and op["prop"] in n.props:
                        idx.add(n.props[op["prop"]], n.id)
                self.prop_indexes[key] = idx
        elif kind == "drop_index":
            self.prop_indexes.pop((op["label"], op["prop"]), None)
        else:
            raise SkeinError(f"unknown WAL/undo operation {kind!r}")

    def _indexes_for_labels(self, labels: Iterable[str]):
        for (label, prop), idx in self.prop_indexes.items():
            if label in labels:
                yield label, prop, idx

    # ------------------------------------------------------------ lookups --

    def get_node(self, nid: int) -> Node:
        node = self.nodes.get(nid)
        if node is None:
            raise SkeinError(f"no such node {nid}")
        return node

    def get_edge(self, eid: int) -> Edge:
        edge = self.edges.get(eid)
        if edge is None:
            raise SkeinError(f"no such edge {eid}")
        return edge

    # ---------------------------------------------------------- mutations --

    def create_node(self, labels: Iterable[str] = (), props: Optional[dict] = None) -> int:
        self._require_txn()
        nid = self._next_node_id
        self._next_node_id += 1
        op = {"op": "create_node", "id": nid, "labels": sorted(set(labels)), "props": dict(props or {})}
        self._apply(op)
        self._log(op, {"op": "delete_node", "id": nid})
        return nid

    def delete_node(self, nid: int, detach: bool = False) -> None:
        self._require_txn()
        node = self.get_node(nid)
        touching = list(self.out_edges[nid]) + list(self.in_edges[nid])
        if touching and not detach:
            raise SkeinError(f"node {nid} still has {len(touching)} edge(s); use DETACH DELETE")
        for eid in touching:
            if eid in self.edges:
                self.delete_edge(eid)
        undo = {"op": "create_node", "id": nid, "labels": sorted(node.labels), "props": dict(node.props)}
        op = {"op": "delete_node", "id": nid}
        self._apply(op)
        self._log(op, undo)

    def create_edge(self, src: int, dst: int, type_: str, props: Optional[dict] = None) -> int:
        self._require_txn()
        self.get_node(src)
        self.get_node(dst)
        eid = self._next_edge_id
        self._next_edge_id += 1
        op = {"op": "create_edge", "id": eid, "type": type_, "src": src, "dst": dst, "props": dict(props or {})}
        self._apply(op)
        self._log(op, {"op": "delete_edge", "id": eid})
        return eid

    def delete_edge(self, eid: int) -> None:
        self._require_txn()
        edge = self.get_edge(eid)
        undo = {"op": "create_edge", "id": eid, "type": edge.type, "src": edge.src, "dst": edge.dst, "props": dict(edge.props)}
        op = {"op": "delete_edge", "id": eid}
        self._apply(op)
        self._log(op, undo)

    def set_node_prop(self, nid: int, key: str, value) -> None:
        self._require_txn()
        node = self.get_node(nid)
        old = node.props.get(key, _MISSING)
        op = {"op": "set_node_prop", "id": nid, "key": key, "value": value}
        self._apply(op)
        undo = {"op": "unset_node_prop", "id": nid, "key": key} if old is _MISSING else {"op": "set_node_prop", "id": nid, "key": key, "value": old}
        self._log(op, undo)

    def set_edge_prop(self, eid: int, key: str, value) -> None:
        self._require_txn()
        edge = self.get_edge(eid)
        old = edge.props.get(key, _MISSING)
        op = {"op": "set_edge_prop", "id": eid, "key": key, "value": value}
        self._apply(op)
        undo = {"op": "unset_edge_prop", "id": eid, "key": key} if old is _MISSING else {"op": "set_edge_prop", "id": eid, "key": key, "value": old}
        self._log(op, undo)

    def create_index(self, label: str, prop: str) -> None:
        self._require_txn()
        if (label, prop) in self.prop_indexes:
            return
        op = {"op": "create_index", "label": label, "prop": prop}
        self._apply(op)
        self._log(op, {"op": "drop_index", "label": label, "prop": prop})

    def drop_index(self, label: str, prop: str) -> None:
        self._require_txn()
        if (label, prop) not in self.prop_indexes:
            return
        op = {"op": "drop_index", "label": label, "prop": prop}
        self._apply(op)
        self._log(op, {"op": "create_index", "label": label, "prop": prop})

    # --------------------------------------------------------- durability --

    def checkpoint(self) -> None:
        with self._lock:
            if self._txn_depth != 0:
                raise TransactionError("cannot checkpoint mid-transaction")
            if not self.path:
                return
            tmp = self._snapshot_path + ".tmp"
            data = {
                "next_node_id": self._next_node_id,
                "next_edge_id": self._next_edge_id,
                "nodes": [{"id": n.id, "labels": sorted(n.labels), "props": n.props} for n in self.nodes.values()],
                "edges": [{"id": e.id, "type": e.type, "src": e.src, "dst": e.dst, "props": e.props} for e in self.edges.values()],
                "indexes": [[label, prop] for (label, prop) in self.prop_indexes.keys()],
            }
            with open(tmp, "w") as f:
                json.dump(data, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self._snapshot_path)
            self._wal_fh.close()
            open(self._wal_path, "wb").close()
            self._wal_fh = open(self._wal_path, "ab")

    def close(self) -> None:
        with self._lock:
            if self.path:
                self.checkpoint()
                if self._wal_fh:
                    self._wal_fh.close()
                    self._wal_fh = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    # ------------------------------------------------------------- stats --

    def stats(self) -> dict:
        return {
            "nodes": len(self.nodes),
            "edges": len(self.edges),
            "labels": self.label_index.labels(),
            "indexes": sorted(self.prop_indexes.keys()),
        }
