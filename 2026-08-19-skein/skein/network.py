"""A simulated, deliberately unreliable network between Skein sites.

Every knob a real network actually has, modeled explicitly and driven
by a seeded RNG so any run is exactly reproducible from its seed:

  * latency jitter (a random per-message delay, which — since
    different messages get different delays — is itself the main
    source of reordering)
  * an extra explicit reorder shuffle of everything that becomes
    deliverable in the same tick
  * duplication (a message occasionally delivered twice)
  * drop (a message occasionally never delivered at all)
  * partition / heal (a site can be cut off from everyone; messages
    sent to or from a partitioned site during the cut are lost, not
    queued — matching how a real network drops in-flight packets
    rather than magically holding them for later)

What it will never do: silently corrupt a message that *is* delivered.
Byzantine-fault tolerance is a different, harder problem than the one
this project is about (see PLAN.md) — Skein assumes a merely unreliable
network, not a malicious one.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple


@dataclass
class _InFlight:
    deliver_at: int
    dest: str
    op: object


@dataclass
class SimNetwork:
    site_ids: List[str]
    seed: int = 0
    latency_range: Tuple[int, int] = (1, 3)
    drop_prob: float = 0.0
    dup_prob: float = 0.0

    def __post_init__(self) -> None:
        self.rng = random.Random(self.seed)
        self.tick_no = 0
        self._in_flight: List[_InFlight] = []
        self._partitioned: Set[str] = set()
        # counters for the eventual chaos report / demo transparency
        self.stats = {"sent": 0, "delivered": 0, "dropped": 0, "duplicated": 0, "partition_blocked": 0}

    # -- partition control --------------------------------------------------

    def partition(self, site_id: str) -> None:
        self._partitioned.add(site_id)

    def heal(self, site_id: str) -> None:
        self._partitioned.discard(site_id)

    def heal_all(self) -> None:
        self._partitioned.clear()

    def is_partitioned(self, site_id: str) -> bool:
        return site_id in self._partitioned

    # -- sending --------------------------------------------------------------

    def send(self, origin_site: str, op: object) -> None:
        """Broadcast `op` from `origin_site` to every other site."""
        for dest in self.site_ids:
            if dest == origin_site:
                continue
            self.stats["sent"] += 1
            if origin_site in self._partitioned or dest in self._partitioned:
                self.stats["partition_blocked"] += 1
                continue
            if self.rng.random() < self.drop_prob:
                self.stats["dropped"] += 1
                continue
            copies = 2 if self.rng.random() < self.dup_prob else 1
            if copies == 2:
                self.stats["duplicated"] += 1
            for _ in range(copies):
                delay = self.rng.randint(*self.latency_range)
                self._in_flight.append(_InFlight(self.tick_no + delay, dest, op))

    def resync(self, site_id: str, ops: List[object]) -> None:
        """Deliver a full op backlog directly to `site_id` with no delay
        or chaos applied — models the anti-entropy catch-up sync a real
        system performs when a site reconnects after a partition (it
        can't magically un-drop a specific lost packet, but it *can*
        ask "what have I missed?" and get resent everything; duplicate
        ops arriving this way are, as always, idempotent to apply)."""
        for op in ops:
            self._in_flight.append(_InFlight(self.tick_no, site_id, op))

    # -- delivery --------------------------------------------------------------

    def step(self) -> List[Tuple[str, object]]:
        """Advance one tick. Returns [(dest_site, op), ...] delivered now,
        in randomized order (extra reordering on top of latency jitter)."""
        self.tick_no += 1
        ready = [m for m in self._in_flight if m.deliver_at <= self.tick_no]
        self._in_flight = [m for m in self._in_flight if m.deliver_at > self.tick_no]
        self.rng.shuffle(ready)
        self.stats["delivered"] += len(ready)
        return [(m.dest, m.op) for m in ready]

    def has_in_flight(self) -> bool:
        return bool(self._in_flight)

    def in_flight_count(self) -> int:
        return len(self._in_flight)

    def drain(self, max_ticks: int = 100_000) -> List[Tuple[str, object]]:
        """Step until nothing is left in flight. Returns every
        (dest, op) delivered, in delivery order."""
        delivered: List[Tuple[str, object]] = []
        ticks = 0
        while self._in_flight:
            delivered.extend(self.step())
            ticks += 1
            if ticks > max_ticks:  # pragma: no cover - defensive only
                raise RuntimeError("network.drain() exceeded max_ticks — possible bug feeding it a message that never expires")
        return delivered
