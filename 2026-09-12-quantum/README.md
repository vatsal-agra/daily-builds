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

73 pytest tests pass, including an independent brute-force oracle that
verifies Belady's MIN against exhaustive search on small inputs, and the
LRU stack-property invariant checked tick-by-tick.

Next: Phase 3 (adversarial review).
