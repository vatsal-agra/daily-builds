"""Deterministic discrete-event network simulator.

Messages are not delivered instantly. Each send schedules a delivery at
``now + latency`` on a seeded priority queue. The network models, all driven by a
single seeded RNG so a (seed, scenario) pair replays identically:

  * variable latency (which naturally causes reordering),
  * message loss,
  * message duplication,
  * crashed nodes (cannot send or receive),
  * network partitions via a connectivity check evaluated **at delivery time**,
    so a message in flight when a partition forms does not cross it.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field


@dataclass
class NetConfig:
    latency_min: int = 1
    latency_max: int = 3
    loss_prob: float = 0.0
    dup_prob: float = 0.0


class Network:
    def __init__(self, rng, config: NetConfig):
        self.rng = rng
        self.cfg = config
        self._queue: list = []  # heap of (deliver_time, seq, envelope)
        self._seq = 0
        # Connectivity: partition groups. None => fully connected.
        self._partitions: list[set[int]] | None = None
        self.crashed: set[int] = set()
        # Stats for reporting.
        self.sent = 0
        self.delivered = 0
        self.dropped = 0
        self.duplicated = 0

    # ------------------------------------------------------------------ #
    # Connectivity control
    # ------------------------------------------------------------------ #
    def set_partitions(self, groups: list[set[int]] | None):
        """groups is a list of disjoint id-sets; nodes communicate iff co-grouped."""
        self._partitions = [set(g) for g in groups] if groups else None

    def heal(self):
        self._partitions = None

    def crash(self, node_id: int):
        self.crashed.add(node_id)

    def restart(self, node_id: int):
        self.crashed.discard(node_id)

    def connected(self, a: int, b: int) -> bool:
        if a in self.crashed or b in self.crashed:
            return False
        if self._partitions is None:
            return True
        for g in self._partitions:
            if a in g and b in g:
                return True
            if (a in g) != (b in g):
                return False
        return True

    # ------------------------------------------------------------------ #
    # Sending and delivering
    # ------------------------------------------------------------------ #
    def send(self, env, now: int):
        self.sent += 1
        # Drop at send time if the link is currently down.
        if not self.connected(env.src, env.dst):
            self.dropped += 1
            return
        if self.cfg.loss_prob and self.rng.random() < self.cfg.loss_prob:
            self.dropped += 1
            return
        self._schedule(env, now)
        if self.cfg.dup_prob and self.rng.random() < self.cfg.dup_prob:
            self.duplicated += 1
            self._schedule(env, now)

    def _schedule(self, env, now: int):
        latency = self.rng.randint(self.cfg.latency_min, self.cfg.latency_max)
        heapq.heappush(self._queue, (now + latency, self._seq, env))
        self._seq += 1

    def deliver_due(self, now: int) -> list:
        """Pop and return all envelopes whose delivery time has arrived and whose
        link is still up at delivery time."""
        out = []
        while self._queue and self._queue[0][0] <= now:
            _, _, env = heapq.heappop(self._queue)
            if not self.connected(env.src, env.dst):
                self.dropped += 1
                continue
            self.delivered += 1
            out.append(env)
        return out

    def in_flight(self) -> int:
        return len(self._queue)
