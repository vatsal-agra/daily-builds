"""A seeded, adversarial, discrete-tick network for exercising CRDT peers.

Every run is driven by a `random.Random(seed)`, so any bug this network
triggers replays byte-for-byte from its seed — the same debugging property
this ledger's Raft simulator (Quorum, 2026-06-15) leans on for a leader-
based system, applied here to a leaderless one.

Chaos knobs, applied independently per message:
- **latency**: every send gets a random delivery delay in `latency_range`
  ticks, which by itself produces **reordering** — two messages sent back
  to back can be delivered in either order.
- **loss_p**: probability a message is dropped and never delivered at all
  — a genuine, permanent loss, not merely delayed. A pure op-broadcast
  system with loss_p > 0 and no additional mechanism will NOT converge in
  general (see `verify/convergence.py`, which demonstrates exactly that,
  honestly, before showing anti-entropy fixes it).
- **dup_p**: probability a message is delivered twice (independently
  delayed) — exercises `apply_remote`'s idempotence.
- **partitions**: a partition blocks delivery between two peer groups for
  a window of ticks; blocked messages are neither lost nor reordered
  outside the block — they simply wait (like a stalled TCP connection)
  and get delivered once the partition heals, still routed through the
  same latency/loss/dup pipeline for that final hop.
"""

from __future__ import annotations

import random


class SimNetwork:
    def __init__(
        self,
        peer_ids,
        seed: int = 0,
        latency_range=(1, 4),
        loss_p: float = 0.0,
        dup_p: float = 0.0,
    ):
        self.peer_ids = list(peer_ids)
        self.rng = random.Random(seed)
        self.latency_range = latency_range
        self.loss_p = loss_p
        self.dup_p = dup_p
        self.time = 0
        self._in_flight: list[dict] = []  # {deliver_at, src, dst, op, dup_of}
        self._partitions: list[dict] = []  # {a:set, b:set, until:int}
        self.events: list[dict] = []  # audit trail: sent/lost/duplicated/delivered/partitioned

    # ------------------------------------------------------------------
    # chaos controls
    # ------------------------------------------------------------------

    def partition(self, group_a, group_b, ticks: int) -> None:
        self._partitions.append(
            {"a": frozenset(group_a), "b": frozenset(group_b), "until": self.time + ticks}
        )
        self.events.append(
            {"tick": self.time, "kind": "partition", "a": list(group_a), "b": list(group_b), "ticks": ticks}
        )

    def heal_all(self) -> None:
        self._partitions.clear()
        self.events.append({"tick": self.time, "kind": "heal_all"})

    def is_currently_partitioned(self, peer_id: str) -> bool:
        """True if `peer_id` is on either side of any active partition —
        i.e. cut off from *someone*. Used to keep any side-channel (e.g.
        anti-entropy resync) honest: a peer that deliberately partitioned
        itself shouldn't get healed by a "reliable" backup path a real
        network split would also have severed."""
        return any(
            p["until"] > self.time and (peer_id in p["a"] or peer_id in p["b"])
            for p in self._partitions
        )

    def _is_partitioned(self, src: str, dst: str) -> bool:
        for p in self._partitions:
            if p["until"] <= self.time:
                continue
            if (src in p["a"] and dst in p["b"]) or (src in p["b"] and dst in p["a"]):
                return True
        return False

    # ------------------------------------------------------------------
    # sending
    # ------------------------------------------------------------------

    def send(self, src: str, dst: str, op: dict) -> None:
        if src == dst:
            return
        if self.rng.random() < self.loss_p:
            self.events.append({"tick": self.time, "kind": "lost", "src": src, "dst": dst, "op": op.get("type", "?")})
            return
        n_copies = 2 if self.rng.random() < self.dup_p else 1
        for copy_i in range(n_copies):
            delay = self.rng.randint(*self.latency_range)
            self._in_flight.append(
                {"deliver_at": self.time + delay, "src": src, "dst": dst, "op": op}
            )
        if n_copies > 1:
            self.events.append({"tick": self.time, "kind": "duplicated", "src": src, "dst": dst, "op": op.get("type", "?")})
        self.events.append({"tick": self.time, "kind": "sent", "src": src, "dst": dst, "op": op.get("type", "?")})

    def broadcast(self, src: str, op: dict, dsts=None) -> None:
        for dst in (dsts if dsts is not None else self.peer_ids):
            if dst != src:
                self.send(src, dst, op)

    # ------------------------------------------------------------------
    # stepping
    # ------------------------------------------------------------------

    def step(self, deliver_fn) -> int:
        """Advance one tick; deliver everything due, respecting active
        partitions (a still-partitioned message is re-queued for the next
        tick rather than delivered or dropped). Returns count delivered.
        `deliver_fn(dst, op)` is called for each delivery."""
        self.time += 1
        still_in_flight = []
        delivered = 0
        for msg in self._in_flight:
            if msg["deliver_at"] > self.time:
                still_in_flight.append(msg)
                continue
            if self._is_partitioned(msg["src"], msg["dst"]):
                msg["deliver_at"] = self.time + 1  # retry next tick, like a stalled link
                still_in_flight.append(msg)
                continue
            deliver_fn(msg["dst"], msg["op"])
            self.events.append(
                {"tick": self.time, "kind": "delivered", "src": msg["src"], "dst": msg["dst"],
                 "op": msg["op"].get("type", "?")}
            )
            delivered += 1
        self._in_flight = still_in_flight
        return delivered

    def run_until_quiescent(self, deliver_fn, max_ticks: int = 100_000) -> int:
        """Step until nothing is in flight (and no active partition could
        ever resolve anything, i.e. all partitions have healed). Returns
        ticks actually run. Raises if it can't quiesce within max_ticks
        (a real bug — e.g. a permanent partition that's never healed)."""
        ticks = 0
        while self._in_flight and ticks < max_ticks:
            self.step(deliver_fn)
            ticks += 1
        if self._in_flight:
            raise RuntimeError(
                f"network did not quiesce within {max_ticks} ticks — "
                f"{len(self._in_flight)} messages still stuck (unhealed partition?)"
            )
        return ticks

    def pending_count(self) -> int:
        return len(self._in_flight)
