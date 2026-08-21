"""PN-Counter — a state-based CRDT, deliberately built the *other* way
from RGA.

RGA is op-based: peers exchange individual insert/delete events, and
correctness rests on those events commuting. A PN-Counter is
state-based: each peer holds a small piece of state (two per-peer
tallies), and two replicas converge by `merge`-ing their *entire state*
together — merge is just a pairwise max, which makes it trivially
commutative, associative, and idempotent (`merge(a, merge(a, b)) ==
merge(a, b)`), the textbook definition of a join-semilattice CRDT. There
is no causal delivery to worry about at all: you can merge two states in
any order, any number of times, and never get a wrong answer — the
tradeoff is you must ship the *whole* state (or a delta) rather than a
compact single event.

`increment`/`decrement` never go negative in what they track: an
increment and a decrement are tracked in *separate* per-peer tallies
(`P` and `N`), and `value()` is their difference — so two peers can
concurrently increment and decrement without one clobbering the other's
delta, unlike a naive shared integer.
"""

from __future__ import annotations


class PNCounter:
    def __init__(self, peer_id: str):
        self.peer_id = peer_id
        self._p: dict = {}  # peer_id -> total incremented by that peer
        self._n: dict = {}  # peer_id -> total decremented by that peer

    def increment(self, amount: int = 1) -> None:
        if amount < 0:
            raise ValueError("increment() amount must be >= 0; use decrement() for negative deltas")
        self._p[self.peer_id] = self._p.get(self.peer_id, 0) + amount

    def decrement(self, amount: int = 1) -> None:
        if amount < 0:
            raise ValueError("decrement() amount must be >= 0")
        self._n[self.peer_id] = self._n.get(self.peer_id, 0) + amount

    def value(self) -> int:
        return sum(self._p.values()) - sum(self._n.values())

    def state(self) -> dict:
        """The full state to ship to another peer for merge()."""
        return {"p": dict(self._p), "n": dict(self._n)}

    def merge(self, other_state: dict) -> None:
        """Join with another peer's state — pairwise max per peer, per
        tally. Safe to call with the same state repeatedly (idempotent),
        in any order relative to other merges (commutative/associative)."""
        for peer_id, total in other_state.get("p", {}).items():
            if total > self._p.get(peer_id, 0):
                self._p[peer_id] = total
        for peer_id, total in other_state.get("n", {}).items():
            if total > self._n.get(peer_id, 0):
                self._n[peer_id] = total

    def __repr__(self):
        return f"PNCounter(value={self.value()})"
