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

Next: Phase 4 (stretch features + polish).
