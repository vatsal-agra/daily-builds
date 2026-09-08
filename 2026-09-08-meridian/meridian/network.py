"""A deterministic, seeded discrete-event network simulator.

No real sockets, no threads, no wall-clock: time is a virtual integer tick
counter, and everything that happens -- a message arriving, a timeout
firing, a node's periodic maintenance running -- is a callback scheduled
onto a min-heap ordered by tick. Because the *only* source of randomness is
one `random.Random` instance seeded once at the top, the exact same seed
reproduces the exact same sequence of drops, delays, and events, byte for
byte, run after run. That determinism is what makes any bug this simulator
turns up 100% reproducible -- the same property Quorum's Raft simulator
(2026-06-15) leaned on for the same reason.

A message can fail to arrive two ways, matching real UDP-based Kademlia:
- the target is offline (crashed or hasn't joined yet) -- dropped silently
- the target is live, but the link randomly loses the packet -- also
  dropped silently
Either way the caller sees nothing but a timeout; Meridian never
distinguishes "offline" from "message lost" at the protocol level, because
real Kademlia can't either.
"""
from __future__ import annotations

import heapq
from itertools import count
from typing import Callable


class Network:
    def __init__(
        self,
        rng,
        latency_range: tuple[int, int] = (5, 50),
        loss_prob: float = 0.05,
    ):
        if latency_range[0] < 1 or latency_range[1] < latency_range[0]:
            raise ValueError(f"invalid latency_range: {latency_range}")
        if not (0.0 <= loss_prob < 1.0):
            raise ValueError(f"loss_prob must be in [0, 1): {loss_prob}")
        self.rng = rng
        self.latency_range = latency_range
        self.loss_prob = loss_prob

        self.time = 0
        self._events: list[tuple[int, int, Callable[[], None]]] = []
        self._seq = count()

        self.nodes: dict[int, object] = {}
        self.live: set[int] = set()

        self.stats = {"sent": 0, "delivered": 0, "dropped_offline": 0, "dropped_loss": 0}
        self.on_event = None  # optional callback(kind, **fields) for tracing

    # -- topology -----------------------------------------------------
    def register(self, node) -> None:
        self.nodes[node.id] = node

    def set_live(self, node_id: int, live: bool) -> None:
        if live:
            self.live.add(node_id)
        else:
            self.live.discard(node_id)

    def is_live(self, node_id: int) -> bool:
        return node_id in self.live

    # -- scheduling -----------------------------------------------------
    def schedule_at(self, when: int, fn: Callable[[], None]) -> None:
        heapq.heappush(self._events, (when, next(self._seq), fn))

    def schedule_in(self, delay: int, fn: Callable[[], None]) -> None:
        if delay < 0:
            raise ValueError(f"negative delay: {delay}")
        self.schedule_at(self.time + delay, fn)

    def run_until(self, end_time: int) -> None:
        while self._events and self._events[0][0] <= end_time:
            when, _, fn = heapq.heappop(self._events)
            self.time = when
            fn()
        self.time = max(self.time, end_time)

    def run_all(self, safety_limit: int = 2_000_000) -> int:
        """Drain every scheduled event (used for tests that don't need a
        fixed wall-clock length, e.g. "run one lookup to completion")."""
        processed = 0
        while self._events:
            if processed >= safety_limit:
                raise RuntimeError("run_all exceeded safety_limit -- likely an infinite retry loop")
            when, _, fn = heapq.heappop(self._events)
            self.time = when
            fn()
            processed += 1
        return processed

    # -- message delivery -----------------------------------------------------
    def send(self, sender_id: int, target_id: int, deliver: Callable[[], None]) -> None:
        """Attempt to deliver `deliver` (a zero-arg callback that performs
        the actual message handling) from `sender_id` to `target_id` after
        a random latency, subject to random loss and target liveness."""
        self.stats["sent"] += 1
        if target_id not in self.live:
            self.stats["dropped_offline"] += 1
            if self.on_event:
                self.on_event("drop_offline", sender=sender_id, target=target_id)
            return
        if self.rng.random() < self.loss_prob:
            self.stats["dropped_loss"] += 1
            if self.on_event:
                self.on_event("drop_loss", sender=sender_id, target=target_id)
            return
        delay = self.rng.randint(*self.latency_range)
        self.stats["delivered"] += 1
        self.schedule_in(delay, deliver)
