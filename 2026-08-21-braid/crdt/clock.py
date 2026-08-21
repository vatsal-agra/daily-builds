"""Logical clocks and causal-delivery buffering.

Braid's ops are not delivered in a global order — the network simulator
(and, on the real WebSocket server, actual network jitter) can hand a peer
an `insert` before the `insert` it was placed after, or a `delete` before
the character it deletes. Two mechanisms fix this:

- `LamportClock` generates the (counter, peer_id) ids RGA nodes use, and
  keeps every peer's counter monotonically ahead of everything it has
  seen (the standard Lamport clock rule), which is what gives concurrent
  inserts a consistent, peer-independent priority order.
- `CausalDeliveryBuffer` holds an op until the ids it explicitly declares
  as dependencies (`op['deps']`) are present locally, then releases it —
  and anything that was waiting on *it* — in one cascade. This is a
  dependency-DAG buffer, not a full vector-clock broadcast: Braid's ops
  each depend on at most one prior id (an insert's parent, a delete's
  target), so tracking that directly is simpler and just as correct as
  general causal broadcast for this data type.

`VectorClock` is kept separate because it answers a different question
than delivery ("what has peer P seen from everyone, and is that state
comparable to mine, or are we concurrent?") — used by the causal-history
visualizer and by peer sync-status reporting, not by the buffer itself.
"""

from __future__ import annotations


class LamportClock:
    """A single peer's logical clock."""

    def __init__(self, peer_id: str):
        self.peer_id = peer_id
        self.counter = 0

    def tick(self) -> int:
        """Advance for a new local event; returns the new counter value."""
        self.counter += 1
        return self.counter

    def observe(self, remote_counter: int) -> int:
        """Fold in a counter value seen on an incoming remote op."""
        self.counter = max(self.counter, remote_counter)
        return self.counter


class VectorClock:
    """A peer -> counter map summarizing "everything I've seen from whom"."""

    def __init__(self):
        self._v: dict[str, int] = {}

    def get(self, peer_id: str) -> int:
        return self._v.get(peer_id, 0)

    def increment(self, peer_id: str) -> int:
        self._v[peer_id] = self._v.get(peer_id, 0) + 1
        return self._v[peer_id]

    def observe(self, peer_id: str, counter: int) -> None:
        if counter > self._v.get(peer_id, 0):
            self._v[peer_id] = counter

    def merge(self, other: "VectorClock") -> None:
        for peer_id, counter in other._v.items():
            self.observe(peer_id, counter)

    def snapshot(self) -> dict:
        return dict(self._v)

    def leq(self, other: "VectorClock") -> bool:
        """True if self happened-before-or-equal other (self <= other)."""
        peers = set(self._v) | set(other._v)
        return all(self.get(p) <= other.get(p) for p in peers)

    def concurrent_with(self, other: "VectorClock") -> bool:
        return not self.leq(other) and not other.leq(self)

    def __eq__(self, other):
        return isinstance(other, VectorClock) and self._v == other._v

    def __repr__(self):
        return f"VectorClock({self._v!r})"


class CausalDeliveryBuffer:
    """Holds ops until their declared `deps` ids are locally present.

    `has_id_fn(id) -> bool` must reflect state *as it is updated by
    apply_fn* — each release re-checks the whole pending set so a chain
    of several waiting ops cascades through in one `submit()` call.
    """

    def __init__(self, has_id_fn):
        self._has = has_id_fn
        self._pending: list[dict] = []

    def submit(self, op: dict, apply_fn) -> int:
        """Add `op` to the buffer and release everything now deliverable.

        Returns the number of ops actually applied in this call (>= 0;
        0 means `op` itself, and everything already waiting, is still
        blocked on a dependency that hasn't arrived).
        """
        self._pending.append(op)
        applied = 0
        progressed = True
        while progressed:
            progressed = False
            still_pending = []
            for pending_op in self._pending:
                deps = pending_op.get("deps") or ()
                if all(self._has(dep) for dep in deps):
                    apply_fn(pending_op)
                    applied += 1
                    progressed = True
                else:
                    still_pending.append(pending_op)
            self._pending = still_pending
        return applied

    def __len__(self):
        return len(self._pending)
