"""A seeded, deterministic discrete-event network simulator.

Same justification as this repo's Quorum (2026-06-15, a Raft simulator):
a bug in "independent nodes converge on one chain" needs to be 100%
reproducible from a seed, not a flaky race against real localhost sockets.
Messages (new blocks, new transactions) are queued with randomized-but-
seeded latency and delivered in timestamp order; an optional partition set
lets a demo show nodes disagreeing and then reconverging once the
partition heals.
"""
from __future__ import annotations

import heapq
import itertools
import random
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set, Tuple


@dataclass(order=True)
class _Event:
    deliver_time: float
    seq: int
    sender: str = field(compare=False)
    recipient: str = field(compare=False)
    kind: str = field(compare=False)
    payload: object = field(compare=False)


class SimNetwork:
    def __init__(self, seed: int = 0, latency_range: Tuple[float, float] = (0.01, 0.25)):
        self.rng = random.Random(seed)
        self.latency_range = latency_range
        self.now = 0.0
        self._queue: List[_Event] = []
        self._seq = itertools.count()
        self.handlers: Dict[str, Callable[[str, str, object], None]] = {}
        self.partitions: List[Set[str]] = []  # if non-empty, delivery only within same group
        self.delivered_count = 0
        self.dropped_count = 0

    def register(self, name: str, handler: Callable[[str, str, object], None]) -> None:
        """`handler(sender_name, kind, payload)` is called on delivery."""
        self.handlers[name] = handler

    def set_partitions(self, groups: Optional[List[Set[str]]]) -> None:
        self.partitions = groups or []

    def _same_partition(self, a: str, b: str) -> bool:
        if not self.partitions:
            return True
        for group in self.partitions:
            if a in group and b in group:
                return True
        return False

    def send(self, sender: str, recipient: str, kind: str, payload: object) -> None:
        if recipient == sender:
            return
        if not self._same_partition(sender, recipient):
            self.dropped_count += 1
            return
        latency = self.rng.uniform(*self.latency_range)
        heapq.heappush(self._queue, _Event(self.now + latency, next(self._seq), sender, recipient, kind, payload))

    def broadcast(self, sender: str, kind: str, payload: object, exclude: Optional[Set[str]] = None) -> None:
        skip = exclude or set()
        for name in self.handlers:
            if name != sender and name not in skip:
                self.send(sender, name, kind, payload)

    def advance_to(self, t: float) -> None:
        """Deliver every queued event with deliver_time <= t, then set now=t."""
        while self._queue and self._queue[0].deliver_time <= t:
            ev = heapq.heappop(self._queue)
            self.now = ev.deliver_time
            handler = self.handlers.get(ev.recipient)
            if handler is not None:
                handler(ev.sender, ev.kind, ev.payload)
                self.delivered_count += 1
        self.now = max(self.now, t)

    def drain(self) -> None:
        """Deliver everything still queued, advancing time as needed."""
        while self._queue:
            ev = heapq.heappop(self._queue)
            self.now = ev.deliver_time
            handler = self.handlers.get(ev.recipient)
            if handler is not None:
                handler(ev.sender, ev.kind, ev.payload)
                self.delivered_count += 1

    def pending(self) -> int:
        return len(self._queue)
