"""Fault-injection scenarios and a randomized chaos driver.

The chaos driver hammers a cluster with a seeded stream of faults (crashes,
restarts, partitions, heals) interleaved with client operations, while the safety
monitor watches every step. It always ends with a heal-and-settle phase so every
in-flight client op reaches a definite outcome (committed or aborted), giving the
linearizability checker a clean, complete history.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from .cluster import Cluster
from .raft import Config
from .network import NetConfig


@dataclass
class ChaosResult:
    seed: int
    ticks: int
    ops_total: int
    ops_committed: int
    faults_injected: int
    safety_ok: bool
    linearizable: bool
    violation: str | None = None
    settled: bool = False
    events: list = field(default_factory=list)


def random_partition(rng, ids: list[int]) -> list[set[int]]:
    """Split the node ids into 2 (sometimes 3) random non-empty groups."""
    shuffled = list(ids)
    rng.shuffle(shuffled)
    k = 2 if len(ids) < 5 or rng.random() < 0.7 else 3
    k = min(k, len(ids))
    cut_points = sorted(rng.sample(range(1, len(ids)), k - 1)) if k > 1 else []
    groups = []
    prev = 0
    for c in cut_points:
        groups.append(set(shuffled[prev:c]))
        prev = c
    groups.append(set(shuffled[prev:]))
    return groups


def run_chaos(seed: int = 0, n: int = 5, ticks: int = 1200,
              fault_every: int = 25, op_every: int = 6,
              loss_prob: float = 0.05, dup_prob: float = 0.03,
              keyspace: int = 4, verbose: bool = False) -> ChaosResult:
    """Run a randomized chaos test and return the result (with safety verdict)."""
    from .invariants import SafetyViolation
    from .linearizer import LinearizabilityChecker, history_from_ops

    rng = random.Random(seed ^ 0xC0FFEE)
    cluster = Cluster(
        n=n, seed=seed,
        config=Config(election_min=8, election_max=16, heartbeat_interval=1),
        net_config=NetConfig(latency_min=1, latency_max=4,
                             loss_prob=loss_prob, dup_prob=dup_prob),
    )
    ids = list(range(n))
    faults = 0
    violation = None
    safety_ok = True
    partitioned = False

    try:
        for t in range(1, ticks + 1):
            # Inject a client op periodically.
            if t % op_every == 0:
                if rng.random() < 0.7:
                    k = f"k{rng.randrange(keyspace)}"
                    v = rng.randrange(1000)
                    cluster.client_request(("put", k, v))
                else:
                    k = f"k{rng.randrange(keyspace)}"
                    cluster.client_request(("get", k))

            # Inject a fault periodically.
            if t % fault_every == 0:
                faults += 1
                choice = rng.random()
                live = sorted(cluster.alive)
                if choice < 0.30 and len(live) > (n // 2 + 1):
                    cluster.crash(rng.choice(live))
                elif choice < 0.50:
                    dead = [i for i in ids if i not in cluster.alive]
                    if dead:
                        cluster.restart(rng.choice(dead))
                elif choice < 0.80:
                    cluster.partition(random_partition(rng, ids))
                    partitioned = True
                else:
                    cluster.heal()
                    partitioned = False

            cluster.step()

        # Heal-and-settle so every op gets a definite outcome.
        for i in ids:
            if i not in cluster.alive:
                cluster.restart(i)
        settled = cluster.run_until_quiescent(max_ticks=600)

    except SafetyViolation as e:
        safety_ok = False
        violation = str(e)
        settled = False

    # Linearizability over the committed history.
    linearizable = True
    if safety_ok:
        checker = LinearizabilityChecker()
        hist = history_from_ops(cluster.committed_history())
        linearizable = checker.check(hist)
        if not linearizable:
            violation = "non-linearizable client history"

    return ChaosResult(
        seed=seed,
        ticks=cluster.time,
        ops_total=len(cluster.ops),
        ops_committed=sum(1 for o in cluster.ops if o.committed),
        faults_injected=faults,
        safety_ok=safety_ok,
        linearizable=linearizable,
        violation=violation,
        settled=settled,
        events=[],
    )
