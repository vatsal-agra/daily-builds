"""The Chord protocol itself: node state plus the paper's core algorithms.

This module is transport-agnostic: every algorithm that needs to talk to
another node takes an `rpc_call(node_ref, method, params) -> result` callable.
`server.py` supplies a real-socket implementation for the live cluster;
`tests/test_node_unit.py` supplies an in-process, no-socket implementation
that dispatches directly into other `ChordNode` instances in the same
process, so the Chord algorithms themselves can be unit-tested fast and
deterministically, independent of any network.
"""

from __future__ import annotations

import random
import threading
from dataclasses import dataclass
from typing import Callable, Optional

from . import hashing


class RPCError(Exception):
    """Raised by an rpc_call implementation when a remote node is unreachable."""


class KeyNotFoundError(Exception):
    pass


@dataclass(frozen=True)
class NodeRef:
    id: int
    host: str
    port: int

    def to_dict(self) -> dict:
        return {"id": self.id, "host": self.host, "port": self.port}

    @staticmethod
    def from_dict(d: dict) -> "NodeRef":
        return NodeRef(id=d["id"], host=d["host"], port=d["port"])

    def addr(self):
        return (self.host, self.port)

    def __str__(self):
        return f"{self.host}:{self.port}#{self.id}"


RpcCall = Callable[[NodeRef, str, dict], dict]


def make_node_ref(host: str, port: int, m_bits: int) -> NodeRef:
    return NodeRef(id=hashing.node_id_for_addr(host, port, m_bits), host=host, port=port)


class LookupFailed(Exception):
    pass


def iterative_find_successor(start: NodeRef, target_id: int, rpc_call: RpcCall, max_hops: int = 64):
    """Client-driven iterative Chord lookup, fault-tolerant to dead hops.

    Repeatedly asks whichever node we currently believe is closest
    ("find_successor_step") either "I am responsible, here is the answer"
    or "ask this closer node instead." If a hop is unreachable (the node
    died), falls back to asking the *previous* good hop for its successor
    list and resumes routing through the next live candidate in it --
    exactly the fault-tolerant lookup behaviour the Chord paper describes
    successor lists enabling.

    Returns (final_node_ref, hops) where hops is the ordered list of node
    refs that were actually, successfully contacted en route (used both to
    report/measure real hop counts and, by callers like get(), as a
    fallback path to the responsible node's replicas).
    """
    current = start
    hops: list[NodeRef] = []
    # ids of nodes we have *successfully* contacted so far -- used only to
    # detect a genuine routing cycle among confirmed-live hops. A candidate
    # we are merely about to *try* (picked as a dead-node fallback) is not
    # added here until it actually answers, so a fallback guess never
    # trips the loop guard before it gets its one attempt.
    contacted_ids = set()

    for _ in range(max_hops):
        try:
            resp = rpc_call(current, "find_successor_step", {"id": target_id})
        except RPCError:
            if not hops:
                raise LookupFailed(f"bootstrap node {current} is unreachable") from None
            prev = hops[-1]
            resp = rpc_call(prev, "get_successor_list", {})
            candidates = [NodeRef.from_dict(d) for d in resp["successors"]]
            candidates = [c for c in candidates if c.id != current.id and c.id not in contacted_ids]
            if not candidates:
                raise LookupFailed(f"no live successor candidates after {current} died") from None
            current = candidates[0]
            continue

        if current.id in contacted_ids:
            raise LookupFailed(f"routing loop detected while looking up {target_id}")
        contacted_ids.add(current.id)
        hops.append(current)
        if resp["final"]:
            return NodeRef.from_dict(resp["node"]), hops
        current = NodeRef.from_dict(resp["next"])

    raise LookupFailed(f"lookup for id={target_id} did not converge in {max_hops} hops")


class ChordNode:
    """One Chord ring member's local state and algorithms.

    `r` is the successor-list length (replication factor / fault-tolerance
    depth): a node's data is replicated onto its next `r` successors, so
    up to `r - 1` simultaneous node failures cannot lose data reachable
    from the ring.
    """

    def __init__(self, host: str, port: int, m_bits: int = hashing.DEFAULT_M_BITS, r: int = 4):
        self.m_bits = m_bits
        self.r = r
        self.ref = make_node_ref(host, port, m_bits)
        self.lock = threading.RLock()

        self.predecessor: Optional[NodeRef] = None
        self.successor_list: list[NodeRef] = [self.ref] * r
        self.finger: list[Optional[NodeRef]] = [None] * m_bits
        self._fix_finger_cursor = 0

        # key_id -> (original_key_string, value) that THIS node is primary for.
        self.data: dict[int, tuple[str, object]] = {}
        # owner_node_id -> {key_id -> (key_string, value)}: replicas this
        # node is holding on behalf of a node upstream of it (because this
        # node is in that owner's successor list).
        self.replica_data: dict[int, dict[int, tuple[str, object]]] = {}

        self.alive = True  # flips False only in in-process unit tests to simulate a crash

    # -- basic ring accessors -------------------------------------------------

    def get_successor(self) -> NodeRef:
        with self.lock:
            return self.successor_list[0]

    def get_successor_list(self) -> list[NodeRef]:
        with self.lock:
            return list(self.successor_list)

    def get_predecessor(self) -> Optional[NodeRef]:
        with self.lock:
            return self.predecessor

    # -- Chord core algorithms (paper Figures 4-7) -----------------------------

    def closest_preceding_finger(self, target_id: int) -> NodeRef:
        with self.lock:
            for i in range(self.m_bits - 1, -1, -1):
                f = self.finger[i]
                if f is not None and hashing.in_interval(f.id, self.ref.id, target_id, self.m_bits):
                    return f
            return self.successor_list[0]

    def local_find_successor_step(self, target_id: int) -> dict:
        """Answer one hop of a lookup: either "I am responsible" or "ask them"."""
        with self.lock:
            succ = self.successor_list[0]
            if succ.id == self.ref.id or hashing.in_interval(target_id, self.ref.id, succ.id, self.m_bits, incl_b=True):
                return {"final": True, "node": succ.to_dict()}
            nxt = self.closest_preceding_finger(target_id)
            if nxt.id == self.ref.id:
                # No finger strictly progresses us; fall back to successor to
                # guarantee forward progress rather than looping on ourselves.
                return {"final": True, "node": succ.to_dict()}
            return {"final": False, "next": nxt.to_dict()}

    def join(self, bootstrap: Optional[NodeRef], rpc_call: RpcCall) -> None:
        """Join the ring containing `bootstrap`, or start a new ring if None."""
        with self.lock:
            self.predecessor = None
            if bootstrap is None:
                self.successor_list = [self.ref] * self.r
                return

        succ, _hops = iterative_find_successor(bootstrap, self.ref.id, rpc_call)

        with self.lock:
            self.successor_list[0] = succ

        if succ.id != self.ref.id:
            try:
                resp = rpc_call(succ, "get_successor_list", {})
                their_list = [NodeRef.from_dict(d) for d in resp["successors"]]
            except RPCError:
                their_list = []
            with self.lock:
                self.successor_list = [succ] + [n for n in their_list if n.id != self.ref.id][: self.r - 1]
                while len(self.successor_list) < self.r:
                    self.successor_list.append(self.successor_list[-1])

            try:
                resp = rpc_call(succ, "transfer_keys", {"new_node_id": self.ref.id})
                with self.lock:
                    for key_id_str, (kstr, value) in resp["items"]:
                        self.data[int(key_id_str)] = (kstr, value)
            except RPCError:
                pass

    def notify(self, candidate: NodeRef) -> None:
        """Another node believes it might be our predecessor."""
        with self.lock:
            should_accept = self.predecessor is None or hashing.in_interval(
                candidate.id, self.predecessor.id, self.ref.id, self.m_bits
            )
            if not should_accept or candidate.id == self.ref.id:
                return
            old_pred = self.predecessor
            self.predecessor = candidate

        # Migrate any keys we hold that now belong to the new predecessor:
        # keys in (old_predecessor, candidate] are candidate's responsibility.
        start = old_pred.id if old_pred is not None else self.ref.id
        with self.lock:
            to_move = [
                k for k in self.data
                if hashing.in_interval(k, start, candidate.id, self.m_bits, incl_b=True)
            ]
            moved = {str(k): self.data.pop(k) for k in to_move}
        if moved:
            self._push_store_batch(candidate, moved)

    def stabilize(self, rpc_call: RpcCall) -> None:
        # NOTE: even a single-node ring (successor == self) must still be
        # asked for "its" predecessor here -- that self-call is how a lone
        # node discovers the first node that ever joins it (see the join()
        # docstring-level note in node.py's module tests). Special-casing
        # succ == self away would leave the ring permanently pointed at
        # itself.
        succ = self.get_successor()
        try:
            resp = rpc_call(succ, "get_predecessor", {})
        except RPCError:
            self._replace_dead_successor(rpc_call)
            succ = self.get_successor()
        else:
            x = NodeRef.from_dict(resp["predecessor"]) if resp.get("predecessor") else None
            if x is not None and x.id != self.ref.id and hashing.in_interval(
                x.id, self.ref.id, succ.id, self.m_bits
            ):
                with self.lock:
                    self.successor_list[0] = x
                succ = x

        try:
            rpc_call(succ, "notify", {"node": self.ref.to_dict()})
        except RPCError:
            pass

        try:
            resp = rpc_call(succ, "get_successor_list", {})
            their_list = [NodeRef.from_dict(d) for d in resp["successors"]]
            with self.lock:
                merged = [succ] + [n for n in their_list if n.id != self.ref.id]
                seen = set()
                dedup = []
                for n in merged:
                    if n.id not in seen:
                        seen.add(n.id)
                        dedup.append(n)
                dedup = dedup[: self.r] or [self.ref]
                while len(dedup) < self.r:
                    dedup.append(dedup[-1])
                self.successor_list = dedup
        except RPCError:
            pass

    def _replace_dead_successor(self, rpc_call: RpcCall) -> None:
        with self.lock:
            self.successor_list.pop(0)
            if not self.successor_list:
                self.successor_list = [self.ref]

    def check_predecessor(self, rpc_call: RpcCall) -> None:
        pred = self.get_predecessor()
        if pred is None or pred.id == self.ref.id:
            return
        try:
            rpc_call(pred, "ping", {})
        except RPCError:
            with self.lock:
                dead_id = pred.id
                self.predecessor = None
                orphaned = self.replica_data.pop(dead_id, None)
                if orphaned:
                    for k, v in orphaned.items():
                        self.data.setdefault(k, v)

    def fix_fingers(self, rpc_call: RpcCall, batch: int = 4) -> None:
        for _ in range(batch):
            with self.lock:
                i = self._fix_finger_cursor
                self._fix_finger_cursor = (self._fix_finger_cursor + 1) % self.m_bits
            start = hashing.finger_start(self.ref.id, i, self.m_bits)
            try:
                node, _hops = iterative_find_successor(self.ref, start, rpc_call)
            except LookupFailed:
                continue
            with self.lock:
                self.finger[i] = node

    # -- data-plane RPC handlers -----------------------------------------------

    def rpc_store(self, key: str, value) -> None:
        kid = hashing.key_id(key, self.m_bits)
        with self.lock:
            self.data[kid] = (key, value)

    def rpc_replicate(self, owner_id: int, key: str, value) -> None:
        kid = hashing.key_id(key, self.m_bits)
        with self.lock:
            self.replica_data.setdefault(owner_id, {})[kid] = (key, value)

    def rpc_retrieve(self, key: str):
        kid = hashing.key_id(key, self.m_bits)
        with self.lock:
            if kid in self.data:
                return self.data[kid][1]
            for store in self.replica_data.values():
                if kid in store:
                    return store[kid][1]
        raise KeyNotFoundError(f"key {key!r} not found (not held as primary or replica on this node)")

    def rpc_transfer_keys(self, new_node_id: int) -> dict:
        with self.lock:
            start = self.predecessor.id if self.predecessor is not None else self.ref.id
            to_move = [
                k for k in self.data
                if hashing.in_interval(k, start, new_node_id, self.m_bits, incl_b=True)
            ]
            items = [(str(k), self.data.pop(k)) for k in to_move]
        return {"items": items}

    def _push_store_batch(self, target: NodeRef, items: dict) -> None:
        """Best-effort direct push used by notify()'s key migration; the
        server layer supplies the real rpc_call via a bound method set at
        construction time (see server.py)."""
        pusher = getattr(self, "_rpc_pusher", None)
        if pusher is None:
            # No transport bound (e.g. bare unit test of notify()) -- keep
            # the data locally rather than silently dropping it.
            with self.lock:
                for k, v in items.items():
                    self.data[int(k)] = v
            return
        for k, (kstr, value) in items.items():
            try:
                pusher(target, "store", {"key": kstr, "value": value})
            except RPCError:
                with self.lock:
                    self.data[int(k)] = (kstr, value)

    def replicate_to_successors(self, rpc_call: RpcCall) -> None:
        """Periodic anti-entropy: push every primary key we own onto our
        current successor list, so replicas track topology changes over
        time (not just at the moment of the original put)."""
        with self.lock:
            successors = [n for n in self.successor_list if n.id != self.ref.id]
            items = list(self.data.items())
        for succ in successors:
            for kid, (kstr, value) in items:
                try:
                    rpc_call(succ, "replicate", {"owner_id": self.ref.id, "key": kstr, "value": value})
                except RPCError:
                    continue

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "id": self.ref.id,
                "host": self.ref.host,
                "port": self.ref.port,
                "predecessor": self.predecessor.to_dict() if self.predecessor else None,
                "successor_list": [n.to_dict() for n in self.successor_list],
                "finger_table": [f.to_dict() if f else None for f in self.finger],
                "num_primary_keys": len(self.data),
                "num_replica_owners": len(self.replica_data),
            }


def get(key: str, start: NodeRef, rpc_call: RpcCall, m_bits: int = hashing.DEFAULT_M_BITS):
    """External-client style get: returns (value, hops_used).

    `m_bits` MUST match the ring's actual identifier-space width (i.e. the
    `--m-bits` a cluster was started with), not just the library default --
    hashing a key into the wrong-sized space silently mis-targets storage
    the moment a ring uses a non-default width. Callers that already know
    a node's ring config (the CLI reads it out of cluster state) must pass
    it explicitly rather than relying on the default.
    """
    kid = hashing.key_id(key, m_bits)
    final_node, hops = iterative_find_successor(start, kid, rpc_call)
    candidates = [final_node]
    try:
        resp = rpc_call(final_node, "get_successor_list", {})
        candidates += [NodeRef.from_dict(d) for d in resp["successors"] if d["id"] != final_node.id]
    except RPCError:
        if hops:
            prev = hops[-1]
            try:
                resp = rpc_call(prev, "get_successor_list", {})
                candidates = [NodeRef.from_dict(d) for d in resp["successors"]]
            except RPCError as e:
                raise LookupFailed(
                    f"both the responsible node {final_node} and the previous hop {prev} "
                    f"are unreachable while looking up key={key!r}"
                ) from e

    last_err: Optional[Exception] = None
    for cand in candidates:
        try:
            value = rpc_call(cand, "retrieve", {"key": key})
            return value, hops + [cand]
        except (RPCError, KeyNotFoundError) as e:
            last_err = e
            continue
    raise last_err or LookupFailed(f"no reachable replica for key={key!r}")


def put(key: str, value, start: NodeRef, rpc_call: RpcCall, m_bits: int = hashing.DEFAULT_M_BITS):
    """External-client style put: returns (responsible_node, hops_used).

    See `get()`'s docstring: `m_bits` must match the ring's actual width.
    """
    kid = hashing.key_id(key, m_bits)
    final_node, hops = iterative_find_successor(start, kid, rpc_call)
    rpc_call(final_node, "store", {"key": key, "value": value})
    try:
        resp = rpc_call(final_node, "get_successor_list", {})
        for d in resp["successors"]:
            if d["id"] == final_node.id:
                continue
            try:
                rpc_call(NodeRef.from_dict(d), "replicate", {"owner_id": final_node.id, "key": key, "value": value})
            except RPCError:
                continue
    except RPCError:
        pass
    return final_node, hops + [final_node]
