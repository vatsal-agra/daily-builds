"""The actual CRDT proof, put under randomized adversarial test.

Two independent claims get checked here, many times over, with random
seeds so failures are always reproducible:

1. **Order independence of application.** Take a fixed set of ops (any
   set — including causally "invalid" orderings, since RGA.apply()
   must buffer and eventually resolve those) and feed it to a *fresh*
   RGA replica in many different random permutations. Every permutation
   must produce byte-identical final text — that's the literal
   definition of a CRDT's merge being commutative/associative/
   idempotent (a join-semilattice), not just "usually converges."

2. **Full end-to-end chaos convergence**, cross-checked against an
   independently-coded oracle (`oracle.py`). Run a multi-site session
   through a network that reorders, drops, duplicates, and partitions
   messages; after everything drains, every site's document must match
   every other site's, *and* match what the oracle computes from the
   ops' true creation order — ruling out the case where all replicas
   agree with each other but have all converged to the *wrong* answer.
"""

from __future__ import annotations

import random
from typing import Dict, List

from .oracle import OracleRGA
from .rga import RGA
from .simulate import Simulation


def compute_oracle_text(all_ops: List[object]) -> str:
    oracle = OracleRGA()
    for op in all_ops:
        oracle.apply(op)
    return oracle.text


def replay_any_order(ops: List[object], site_id: str = "replay") -> str:
    """Feed `ops` (any order at all) through a fresh RGA via .apply(),
    relying entirely on its causal-buffering. Raises if anything is
    left pending at the end (a genuine bug, or an incomplete op set —
    e.g. a delete whose insert was never included)."""
    replica = RGA(site_id)
    for op in ops:
        replica.apply(op)
    if replica.has_pending():
        raise AssertionError("replay finished with pending (causally orphaned) ops")
    return replica.text


def random_shuffles_converge(all_ops: List[object], trials: int = 200, seed: int = 0) -> dict:
    rng = random.Random(seed)
    baseline = compute_oracle_text(all_ops)
    mismatches = []
    for i in range(trials):
        shuffled = list(all_ops)
        rng.shuffle(shuffled)
        got = replay_any_order(shuffled, site_id=f"shuffle-{i}")
        if got != baseline:
            mismatches.append({"trial": i, "got": got, "expected": baseline})
    return {"trials": trials, "baseline": baseline, "mismatches": mismatches, "ok": not mismatches}


def run_chaos_trial(
    seed: int,
    num_sites: int = 3,
    num_edits: int = 60,
    drop_prob: float = 0.05,
    dup_prob: float = 0.05,
    use_partitions: bool = True,
) -> dict:
    site_ids = [f"site{i}" for i in range(num_sites)]
    sim = Simulation(site_ids, seed=seed, drop_prob=drop_prob, dup_prob=dup_prob)
    rng = random.Random(seed ^ 0xC5A05)
    for _ in range(num_edits):
        sim.step()  # let some ops be mid-flight when the next edit happens
        if use_partitions and rng.random() < 0.08:
            sim.partition(rng.choice(site_ids))
        if use_partitions and rng.random() < 0.08:
            sim.heal(rng.choice(site_ids))
        sim.random_edit()
    sim.heal_all()
    sim.drain()

    texts = sim.texts()
    expected = compute_oracle_text(sim.all_ops)
    pending_sites = [sid for sid in sim.sites if sim.sites[sid].has_pending()]
    ok = len(set(texts.values())) <= 1 and all(t == expected for t in texts.values()) and not pending_sites
    return {
        "seed": seed,
        "ok": ok,
        "texts": texts,
        "expected": expected,
        "num_ops": len(sim.all_ops),
        "pending_sites": pending_sites,
        "network_stats": dict(sim.network.stats),
    }


def run_many_chaos_trials(trials: int = 100, seed_base: int = 0, **kwargs) -> dict:
    failures = []
    for t in range(trials):
        result = run_chaos_trial(seed=seed_base + t, **kwargs)
        if not result["ok"]:
            failures.append(result)
    return {"trials": trials, "failures": failures, "ok": not failures}
