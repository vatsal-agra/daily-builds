"""RGA — Replicated Growable Array, a sequence CRDT for collaborative text.

Every character ever typed becomes a `Node` with a globally unique id
`(lamport_counter, peer_id)` and a `parent` pointer to the id of the
character it was inserted immediately after (`None` means "start of
document"). Deleting a character never removes its node — it flips a
`tombstone` flag — so a node's id stays a valid, permanent target for
anyone else's concurrent operation to reference (an insert can always
say "after node X" even if X gets deleted a moment later on another
peer; a duplicate delivery of the same op is a no-op).

Where two peers concurrently insert right after the *same* character,
the new nodes are siblings in the tree rooted at their shared parent.
`_integrate` breaks that tie the same way on every peer — by descending
id, i.e. the sibling with the numerically larger `(counter, peer_id)`
tuple always ends up to the left — which is exactly what gives RGA its
core guarantee: apply the same set of insert/delete ops in *any* order,
on any peer, and the resulting visible text is byte-identical.

Known, accepted limitation (a real, published property of RGA, not a
Braid-specific bug — see REVIEW.md): if two peers are offline and each
types a multi-character run at the *same* position, the runs can
converge *interleaved* character-by-character rather than as two clean
blocks. It's a real tradeoff every character-level sequence CRDT without
extra move-detection machinery makes, well known from CRDT literature,
and it does not violate convergence (every peer still converges to the
same interleaving) — it's a text-quality property, not a correctness one.
"""

from __future__ import annotations

from .clock import LamportClock

# Sentinel meaning "the very start of the document" — deliberately not a
# real node id, so it can never collide with an actual (counter, peer_id).
HEAD = None


class Node:
    __slots__ = ("id", "value", "parent", "tombstone")

    def __init__(self, id_, value, parent, tombstone=False):
        self.id = id_
        self.value = value
        self.parent = parent
        self.tombstone = tombstone

    def __repr__(self):
        t = "†" if self.tombstone else ""
        return f"Node({self.id}{t}={self.value!r} <- {self.parent})"


class RGA:
    def __init__(self, peer_id: str):
        self.peer_id = peer_id
        self.clock = LamportClock(peer_id)
        self.nodes: dict = {}       # id -> Node
        self.order: list = []       # ids, left-to-right document order (incl. tombstones)
        self.pos: dict = {}         # id -> index into self.order (kept in sync)
        # Defensive robustness: if a delete somehow arrives before the
        # insert it targets (should never happen when routed through
        # CausalDeliveryBuffer, but RGA stays correct standalone too),
        # remember it and apply the tombstone the moment the node shows up.
        self.pending_deletes: set = set()
        # Full history of every op this peer has actually applied (local or
        # remote), deduped by (type, id) — the record anti-entropy resync
        # and the causal-history/undo features replay against.
        self.op_log: list = []
        self._logged: set = set()

    # ------------------------------------------------------------------
    # local edit API — plain 0-based visible-character indices in, ops out
    # ------------------------------------------------------------------

    def local_insert(self, index: int, value: str) -> dict:
        after_id = self._visible_id_before(index)
        counter = self.clock.tick()
        node_id = (counter, self.peer_id)
        node = Node(node_id, value, after_id)
        self._integrate(node)
        op = {
            "type": "insert",
            "id": node_id,
            "parent": after_id,
            "value": value,
            "deps": () if after_id is None else (after_id,),
        }
        self._log(op)
        return op

    def local_delete(self, index: int) -> dict:
        target_id = self._visible_id_at(index)
        if target_id is None:
            raise IndexError(f"delete index {index} out of range")
        self.nodes[target_id].tombstone = True
        op = {"type": "delete", "id": target_id, "deps": (target_id,)}
        self._log(op)
        return op

    def _log(self, op: dict) -> bool:
        """Append to op_log iff not already recorded; returns True if new."""
        key = (op["type"], op["id"])
        if key in self._logged:
            return False
        self._logged.add(key)
        self.op_log.append(op)
        return True

    def known_op_keys(self) -> set:
        return set(self._logged)

    def text(self) -> str:
        return "".join(
            self.nodes[nid].value for nid in self.order if not self.nodes[nid].tombstone
        )

    def __len__(self):
        return sum(1 for nid in self.order if not self.nodes[nid].tombstone)

    # ------------------------------------------------------------------
    # remote application — idempotent, order-tolerant
    # ------------------------------------------------------------------

    def has_id(self, node_id) -> bool:
        return node_id is None or node_id in self.nodes

    def apply_remote(self, op: dict) -> None:
        if op["type"] == "insert":
            node_id = op["id"]
            self.clock.observe(node_id[0])
            if node_id in self.nodes:
                return  # duplicate delivery: no-op, keeps apply idempotent
            node = Node(node_id, op["value"], op["parent"])
            self._integrate(node)
            self._log(op)
            if node_id in self.pending_deletes:
                node.tombstone = True
                self.pending_deletes.discard(node_id)
        elif op["type"] == "delete":
            target_id = op["id"]
            existing = self.nodes.get(target_id)
            if existing is not None:
                existing.tombstone = True
                self._log(op)
            else:
                self.pending_deletes.add(target_id)
                self._log(op)
        else:
            raise ValueError(f"unknown op type {op['type']!r}")

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _visible_ids(self) -> list:
        return [nid for nid in self.order if not self.nodes[nid].tombstone]

    def _visible_id_before(self, index: int):
        """Id of the visible char currently at `index - 1`, or HEAD."""
        vis = self._visible_ids()
        if index <= 0 or not vis:
            return None
        return vis[min(index, len(vis)) - 1]

    def _visible_id_at(self, index: int):
        vis = self._visible_ids()
        if 0 <= index < len(vis):
            return vis[index]
        return None

    def _idx(self, node_id) -> int:
        return -1 if node_id is None else self.pos[node_id]

    def _subtree_end(self, root_idx: int) -> int:
        """Index just past the contiguous subtree rooted at order[root_idx].

        RGA's placement rule keeps every node's descendants immediately
        to its right, so "the subtree of X" is always a contiguous run —
        it ends at the first later node whose parent lies *before*
        root_idx (i.e. outside the subtree entirely).
        """
        j = root_idx + 1
        n = len(self.order)
        while j < n:
            parent = self.nodes[self.order[j]].parent
            if self._idx(parent) < root_idx:
                break
            j += 1
        return j

    def _integrate(self, node: Node) -> None:
        parent_idx = self._idx(node.parent)
        i = parent_idx + 1
        n = len(self.order)
        while i < n:
            other = self.nodes[self.order[i]]
            other_parent_idx = self._idx(other.parent)
            if other_parent_idx < parent_idx:
                break  # left the region that grew after node.parent
            if other_parent_idx == parent_idx:
                # direct sibling of `node`: real competition, tie-break by id
                if other.id > node.id:
                    i = self._subtree_end(i)  # other wins: skip its whole subtree
                    continue
                break  # node wins: goes immediately before `other`
            i += 1  # deeper descendant of an already-skipped sibling
        self.order.insert(i, node.id)
        self.nodes[node.id] = node
        for j in range(i, len(self.order)):
            self.pos[self.order[j]] = j
