# Quantum

An OS process scheduler + virtual memory manager, built from scratch.

**Status: Phase 2 (Core Build) complete.** All 4 required features are
implemented and verified against independent ground truth — see
[PLAN.md](PLAN.md) for the concept and architecture.

- `quantum/scheduler.py` — 6 CPU scheduling algorithms (FCFS, SJF, SRTF,
  Round Robin, Priority-with-aging, MLFQ) over a shared tick-driven engine.
  Validated against hand-computed Silberschatz-textbook examples (exact
  match on FCFS/SRTF/RR average waiting times).
- `quantum/memory.py` — page table + TLB + 4 replacement algorithms
  (FIFO, LRU, Clock, Optimal/Belady-MIN). Validated against the classic
  Silberschatz LRU/FIFO/Optimal example (15/12/9 faults, exact match) and
  reproduces Belady's Anomaly exactly (FIFO: 9 faults → 10 faults going
  from 3 to 4 frames).
- `quantum/workload.py` + `quantum/compare.py` — seeded realistic workload
  generation and a full algorithm-matrix comparison engine with automatic
  Belady's-Anomaly detection and an Optimal-minimality invariant check.
- `visualizer/index.html` — self-contained interactive Gantt chart, memory
  timeline, and comparison charts, driven by real exported JSON. Headless
  Chromium smoke-tested with zero console errors.

**Status: Phase 3 (Adversarial Review) complete.** See
[REVIEW.md](REVIEW.md) for the full writeup. Three real bugs were found
and fixed by attacking the code as a hostile reviewer, not just admiring
what already passed:

- Every I/O burst completed in 0 ticks (two redundant `Process` fields
  got mixed up on the CPU→IO transition).
- `context_switch_cost > 0` hung the simulation forever (a process was
  silently discarded mid-switch).
- The MLFQ Gantt trace's queue-level field was hardcoded to `0` — a real
  feature (visualizing demotions) was decoratively fake.

Plus 8 input-validation hardenings (duplicate PIDs, zero-division on
`aging_interval=0`, non-positive quantums, etc.) and 4 UX fixes (clipped
chart labels, overlapping bar labels, mobile horizontal overflow, a
missing chart legend).

97 pytest tests now pass (up from 73), including an independent
brute-force oracle that verifies Belady's MIN against exhaustive search on
small inputs, the LRU stack-property invariant checked tick-by-tick, and
regression tests for every bug above.

**Status: Phase 4 (Stretch + Polish) complete.** Both stretch features
from [PLAN.md](PLAN.md) are implemented and tested, not just one:

- `quantum/cow.py` — a copy-on-write `fork()` simulator with real
  reference-counted physical frames: a child shares every frame with its
  parent until either side writes, at which point exactly one real copy
  happens (verified: parent/child frames diverge only for the written
  page, everything else stays shared, refcounts never go negative,
  frames free correctly on exit). `python -m quantum.cli cow`.
- `quantum/thrash.py` — a multiprogramming/thrashing simulator (Denning's
  working-set model) with a single shared disk servicing page-ins one at
  a time. Sweeping the degree of multiprogramming against a fixed frame
  pool reproduces the real, counter-intuitive curve: throughput *rises*
  at first (concurrency hides fault latency) then *collapses* — in the
  default demo, peaking at degree 2 and falling 6.4× by degree 16, as a
  real FIFO disk queue backs up. `python -m quantum.cli thrash`.

117 pytest tests pass (up from 97).

**Status: Phase 5 (Verification) complete.** `./demo.sh` runs 9 checks
covering every required and stretch feature end to end — the full pytest
suite, the brute-force oracle against Belady's MIN, the full
scheduler/memory comparison matrix with the Optimal-minimality invariant,
Belady's Anomaly reproduced live (FIFO: 9 → 10 faults), the visualizer
built and headless-browser smoke tested with zero console errors, and
both stretch features (CoW fork, thrashing cliff) — and all 9 pass.

Next: Phase 6 (ship).
