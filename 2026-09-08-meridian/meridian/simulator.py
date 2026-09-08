"""Orchestrates a whole simulated swarm of DHTNodes over one Network:
staged bootstrap joins, periodic per-node maintenance, and scripted churn
(graceful leaves and random crashes). Everything is driven by one seeded
`random.Random`, so a `Simulation(seed=N)` reproduces byte-for-byte.
"""
from __future__ import annotations

import random

from . import nodeid
from .dht import DEFAULT_TTL, MAINTENANCE_INTERVAL, DHTNode
from .network import Network


class Simulation:
    def __init__(
        self,
        seed: int = 0,
        latency_range: tuple[int, int] = (5, 50),
        loss_prob: float = 0.05,
        k: int = 20,
        alpha: int = 3,
        trace: bool = True,
    ):
        self.seed = seed
        self.rng = random.Random(seed)
        self.network = Network(self.rng, latency_range=latency_range, loss_prob=loss_prob)
        self.nodes: dict[int, DHTNode] = {}
        self.trace: list[dict] = [] if trace else None
        self.k = k
        self.alpha = alpha

    # -- tracing -----------------------------------------------------
    def _log(self, kind: str, **fields) -> None:
        if self.trace is not None:
            self.trace.append({"t": self.network.time, "kind": kind, **fields})

    def _trace_cb(self, kind: str, **fields) -> None:
        self._log(kind, **fields)

    # -- node lifecycle -----------------------------------------------------
    def create_node(self, node_id: int | None = None) -> DHTNode:
        if node_id is None:
            node_id = nodeid.random_id(self.rng)
        if node_id in self.nodes:
            raise ValueError(f"duplicate node id: {nodeid.short(node_id)}")
        node_rng = random.Random(self.rng.getrandbits(64))
        node = DHTNode(node_id, self.network, k=self.k, alpha=self.alpha, rng=node_rng, trace=self._trace_cb)
        self.nodes[node_id] = node
        return node

    def join(self, node: DHTNode, bootstrap_id: int | None, delay: int = 0) -> None:
        def do_join():
            self.network.set_live(node.id, True)
            self._log("join", node=node.id)
            if bootstrap_id is not None:
                node.bootstrap(
                    bootstrap_id,
                    on_complete=lambda contacts: self._log("bootstrap_done", node=node.id, contacts=len(contacts)),
                )

        self.network.schedule_in(delay, do_join)

    def leave(self, node_id: int, delay: int, graceful: bool = True) -> None:
        kind = "leave" if graceful else "crash"

        def do_leave():
            self.network.set_live(node_id, False)
            self._log(kind, node=node_id)

        self.network.schedule_in(delay, do_leave)

    def schedule_maintenance(self, node: DHTNode, start: int = 0, interval: int = MAINTENANCE_INTERVAL, jitter: int = 20) -> None:
        def tick():
            if self.network.is_live(node.id):
                node.tick_maintenance()
            nxt = interval + self.rng.randint(-jitter, jitter)
            self.network.schedule_in(max(1, nxt), tick)

        self.network.schedule_in(start, tick)

    def bootstrap_swarm(self, n: int, join_step: int = 30, jitter: int = 10) -> list[DHTNode]:
        """Create `n` nodes: the first is live from tick 0 with nothing to
        bootstrap from (the network's first node necessarily has no one to
        join through -- every real Kademlia swarm starts this way); every
        later node joins, at a staggered delay, through a bootstrap contact
        chosen from the nodes that have already joined."""
        if n < 1:
            raise ValueError("n must be >= 1")
        first = self.create_node()
        self.network.set_live(first.id, True)
        self._log("join", node=first.id, seed=True)
        self.schedule_maintenance(first)
        joined_ids = [first.id]
        for i in range(1, n):
            node = self.create_node()
            bootstrap_target = self.rng.choice(joined_ids)
            delay = max(1, i * join_step + self.rng.randint(-jitter, jitter))
            self.join(node, bootstrap_target, delay=delay)
            self.schedule_maintenance(node, start=delay + 1)
            joined_ids.append(node.id)
        return [self.nodes[i] for i in joined_ids]

    def churn(self, node_ids: list[int], start: int, end: int, mean_interval: int) -> None:
        """Schedule random crashes (Poisson process, one crash roughly
        every `mean_interval` ticks) among `node_ids` in [start, end)."""
        if mean_interval <= 0:
            raise ValueError("mean_interval must be positive")
        t = float(start)
        rate = 1.0 / mean_interval
        while True:
            t += self.rng.expovariate(rate)
            if t >= end:
                break
            victim = self.rng.choice(node_ids)
            self.network.schedule_at(int(t), lambda victim=victim: self._crash(victim))

    def _crash(self, node_id: int) -> None:
        if self.network.is_live(node_id):
            self.network.set_live(node_id, False)
            self._log("crash", node=node_id)

    # -- oracle (for tests/demos only -- never used by DHTNode itself) -----------------------------------------------------
    def true_k_closest(self, target: int, k: int, live_only: bool = True) -> list[int]:
        ids = [nid for nid in self.nodes if (not live_only or self.network.is_live(nid))]
        ids.sort(key=lambda nid: nodeid.distance(target, nid))
        return ids[:k]

    def live_nodes(self) -> list[DHTNode]:
        return [self.nodes[nid] for nid in self.nodes if self.network.is_live(nid)]

    # -- running -----------------------------------------------------
    def run_until(self, t: int) -> None:
        self.network.run_until(t)

    def run_all(self) -> int:
        return self.network.run_all()

    def pump_until(self, predicate, step: int = 500, max_ticks: int = 300_000) -> bool:
        """Advance the simulation in `step`-tick increments until
        `predicate()` is true (typically "has this callback fired yet").

        A fixed guessed number of ticks is the wrong tool here: a single
        RPC round trip and a 40-chunk sequential file transfer need wildly
        different amounts of simulated time, and guessing a constant large
        enough for the slowest case wastes time on the common one (or,
        worse, is *still* too small for some slower case nobody tried).
        Pumping until the actual condition holds is correct for both.
        `max_ticks` is a bound against a genuine bug/deadlock hanging the
        loop, not a tuning knob to raise per call site.
        """
        start = self.network.time
        while not predicate():
            if self.network.time - start > max_ticks:
                return False
            if not self.network._events:
                # Nothing left scheduled and still not done: this will
                # never complete (e.g. the callback this predicate waits
                # on was never wired to fire). Don't spin forever.
                return predicate()
            self.network.run_until(self.network.time + step)
        return True
