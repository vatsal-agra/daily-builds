"""Seeded synthetic workload generation.

Two kinds of realism matter here, and both are easy to get wrong by
accident:

1. **CPU/IO burst processes** should look like real programs — a mix of
   CPU-bound (few, long CPU bursts) and I/O-bound (many, short CPU bursts
   interleaved with I/O) processes, not identical clones.
2. **Memory reference strings** should exhibit *locality of reference* —
   real programs spend most of their time looping over a small "working
   set" of pages and occasionally jump elsewhere (a new function, a new
   data structure) — not uniform random access. Uniform-random access
   defeats the entire premise of caching/paging (every algorithm converges
   to the same fault rate), so a generator that produces it would quietly
   make the whole memory subsystem look pointless.
"""
from __future__ import annotations

import random

from .process import Burst, BurstKind, Process


def make_processes(
    n: int,
    seed: int = 0,
    max_arrival_spread: int = 10,
    cpu_bound_fraction: float = 0.4,
) -> list[Process]:
    """Generate `n` processes with realistic alternating CPU/IO bursts.

    A `cpu_bound_fraction` of processes get few, long CPU bursts and short
    I/O bursts (batch/compute-heavy); the rest get many short CPU bursts
    and longer I/O bursts (interactive/I/O-bound) — the same two archetypes
    every OS scheduling textbook contrasts.
    """
    if n < 1:
        raise ValueError("n must be >= 1")
    rng = random.Random(seed)
    procs = []
    for pid in range(1, n + 1):
        arrival = rng.randint(0, max_arrival_spread)
        cpu_bound = rng.random() < cpu_bound_fraction
        bursts: list[Burst] = []
        if cpu_bound:
            num_cycles = rng.randint(1, 3)
            for i in range(num_cycles):
                bursts.append(Burst(BurstKind.CPU, rng.randint(8, 20)))
                if i < num_cycles - 1:
                    bursts.append(Burst(BurstKind.IO, rng.randint(1, 4)))
        else:
            num_cycles = rng.randint(2, 6)
            for i in range(num_cycles):
                bursts.append(Burst(BurstKind.CPU, rng.randint(1, 4)))
                if i < num_cycles - 1:
                    bursts.append(Burst(BurstKind.IO, rng.randint(3, 10)))
        priority = rng.randint(0, 4)
        procs.append(Process(pid=pid, arrival_time=arrival, bursts=bursts, priority=priority))
    return procs


def make_reference_string(
    length: int,
    num_pages: int = 12,
    seed: int = 0,
    working_set_size: int = 4,
    jump_probability: float = 0.15,
) -> list[int]:
    """Generate a memory reference string with locality of reference: a
    random walk within a small "working set" of pages, with occasional
    jumps to a brand new working set (simulating a phase change — a new
    function called, a new data structure traversed).
    """
    if num_pages < 1:
        raise ValueError("num_pages must be >= 1")
    if working_set_size < 1:
        raise ValueError("working_set_size must be >= 1")
    if working_set_size > num_pages:
        raise ValueError("working_set_size cannot exceed num_pages")
    rng = random.Random(seed)
    ref: list[int] = []
    working_set = rng.sample(range(num_pages), working_set_size)
    for _ in range(length):
        if rng.random() < jump_probability:
            working_set = rng.sample(range(num_pages), working_set_size)
        ref.append(rng.choice(working_set))
    return ref


def make_belady_anomaly_string() -> list[int]:
    """The classic reference string that demonstrates Belady's Anomaly
    under FIFO: page faults go *up* from 3 frames (9 faults) to 4 frames
    (10 faults) — verified against `simulate_memory` in tests, not just
    asserted from memory."""
    return [1, 2, 3, 4, 1, 2, 5, 1, 2, 3, 4, 5]
