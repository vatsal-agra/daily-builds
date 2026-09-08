#!/usr/bin/env python3
"""A randomized fuzz sweep across the whole engine at once.

Unlike the unit tests (which each isolate one feature), this drives every
feature together -- swarm bootstrap, lookups, churn, key/value STORE+GET,
and file-store PUT+GET -- across many random `(n, k, alpha, loss)`
configurations, specifically including small `k` values chosen to maximize
how often the full-bucket eviction race (REVIEW.md bug #3) actually
triggers. Exits non-zero if anything raises or a downloaded file doesn't
match what was uploaded.
"""
from __future__ import annotations

import random
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from meridian import nodeid
from meridian.filestore import get_file, put_file
from meridian.simulator import Simulation

SEEDS = range(60)


def run_one(seed: int) -> None:
    r = random.Random(seed)
    n = r.randint(3, 45)
    k = r.randint(1, 20)
    alpha = r.randint(1, 5)
    loss = r.choice([0.0, 0.02, 0.1, 0.3])

    sim = Simulation(seed=seed, loss_prob=loss, k=k, alpha=alpha)
    sim.bootstrap_swarm(n)
    sim.run_until(n * 30 + 500)

    live = sim.live_nodes()
    if not live:
        return

    for _ in range(5):
        src = sim.rng.choice(live)
        target = nodeid.random_id(sim.rng)
        box: dict = {}
        src.lookup_nodes(target, lambda c: box.update(done=True))
        sim.pump_until(lambda: box.get("done", False))

    ids = [nd.id for nd in sim.live_nodes()]
    if ids:
        sim.churn(ids, sim.network.time, sim.network.time + 2000, mean_interval=max(30, 2000 // 8))
        sim.run_until(sim.network.time + 2000)

    live2 = sim.live_nodes()
    if len(live2) < 2:
        return

    publisher = sim.rng.choice(live2)
    box = {}
    publisher.put(b"fuzzkey", b"fuzzval", on_complete=lambda ok, total: box.update(done=True))
    sim.pump_until(lambda: box.get("done", False))

    other = [x for x in live2 if x.id != publisher.id]
    fetcher = sim.rng.choice(other)
    gbox: dict = {}
    fetcher.get(b"fuzzkey", lambda v: gbox.update(v=v, done=True))
    sim.pump_until(lambda: gbox.get("done", False))

    data = bytes(r.getrandbits(8) for _ in range(r.randint(0, 3000)))
    pbox: dict = {}
    put_file(publisher, "f.bin", data, chunk_size=r.randint(1, 500), on_complete=lambda mk, mf, ok: pbox.update(mk=mk, done=True))
    sim.pump_until(lambda: pbox.get("done", False))

    dbox: dict = {}
    get_file(fetcher, pbox["mk"], lambda d, ok, err, mf: dbox.update(d=d, ok=ok, err=err, done=True))
    sim.pump_until(lambda: dbox.get("done", False))

    if dbox["ok"] and dbox["d"] != data:
        raise AssertionError(f"seed={seed}: downloaded bytes don't match what was uploaded")


def main() -> int:
    failures = 0
    for seed in SEEDS:
        try:
            run_one(seed)
        except Exception:
            print(f"--- seed={seed} FAILED ---", file=sys.stderr)
            traceback.print_exc()
            failures += 1
    total = len(list(SEEDS))
    if failures:
        print(f"\nfuzz_sweep: {failures}/{total} seeds FAILED", file=sys.stderr)
        return 1
    print(f"fuzz_sweep: {total}/{total} seeds passed (randomized n/k/alpha/loss, "
          "lookups + churn + STORE/GET + file-store PUT/GET)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
