# Quantum

An operating system's two central resource-allocation problems, built
entirely from scratch: **CPU scheduling** (six real algorithms, from FCFS
to a genuine multi-level feedback queue) and **virtual memory management**
(page table + TLB + four replacement algorithms, including Belady's
provably-optimal MIN). Plus two systems-level extras: a copy-on-write
`fork()` simulator, and a multiprogramming simulator that reproduces the
classic thrashing cliff.

Every number in every chart and table below comes from a real simulation
run of this code — nothing is mocked, hand-authored, or hardcoded.

## What it is

- **`quantum/scheduler.py`** — a tick-driven, single-core CPU scheduler
  engine running six algorithms (FCFS, SJF, preemptive SRTF, Round Robin,
  Priority-with-aging, and a 3-level MLFQ with periodic priority boost)
  over processes with realistic alternating CPU/I/O burst sequences.
- **`quantum/memory.py`** — a page table + a small LRU TLB + demand
  paging + four replacement algorithms (FIFO, LRU, Clock/second-chance,
  and Belady's MIN/Optimal).
- **`quantum/workload.py`** + **`quantum/compare.py`** — a seeded
  generator producing realistic workloads (locality-of-reference memory
  traces, CPU/IO-bursty processes) and a comparison engine that runs the
  full algorithm matrix, auto-detects Belady's Anomaly, and checks the
  Optimal-minimality invariant.
- **`visualizer/index.html`** — a self-contained, dependency-free
  interactive page: a scrubable Gantt chart (with MLFQ demotions actually
  visible as darkened `L1`/`L2` slices), a per-tick memory/frame
  occupancy heatmap with fault markers, and algorithm-comparison bar
  charts.
- **`quantum/cow.py`** — copy-on-write `fork()` with real
  reference-counted physical frames.
- **`quantum/thrash.py`** — Denning's working-set model: several
  processes sharing a fixed frame pool through a single FIFO-queued disk,
  reproducing the real throughput-rises-then-collapses thrashing curve.

## How to run it

```bash
cd 2026-09-12-quantum

# the full verification suite (117 pytest tests + every CLI feature +
# a headless-browser check of the visualizer) -- see it all pass:
./demo.sh

# or drive individual pieces:
python3 -m quantum.cli schedule --algo mlfq --n 8 --seed 1
python3 -m quantum.cli memory --belady --algo fifo --frames 4
python3 -m quantum.cli compare --n 8                     # full algorithm matrix
python3 -m quantum.cli cow                                # copy-on-write fork demo
python3 -m quantum.cli thrash                             # the thrashing cliff
python3 -m quantum.cli oracle --ref 7,0,1,2,0,3 --frames 3 # Optimal vs. brute force

# rebuild the interactive visualizer (bakes a fresh run into one HTML file):
python3 -m quantum.build_visualizer
open visualizer/index.html   # or just open the file in any browser
```

No dependencies beyond the Python 3 standard library for the simulation
engine itself. `pytest` runs the test suite; the visualizer's headless
smoke test uses Playwright/Chromium (`tests/visualizer_smoke.js`) but the
visualizer itself needs nothing but a browser.

## Full feature list

**Required**
1. Multi-algorithm CPU scheduler (FCFS, SJF, SRTF, Round Robin,
   Priority-with-aging, MLFQ) with full metrics and a Gantt trace.
2. Virtual memory manager (page table, TLB, FIFO/LRU/Clock/Optimal) with
   fault/hit-rate metrics and a per-tick frame-occupancy trace.
3. Realistic workload generator + comparison engine with automatic
   Belady's-Anomaly detection and an Optimal-minimality invariant check.
4. Interactive HTML visualizer (Gantt chart, memory timeline,
   comparison charts) driven entirely by real exported simulation JSON.

**Stretch (both shipped)**
5. Copy-on-write fork simulator with reference-counted frame sharing.
6. Multiprogramming/thrashing simulator reproducing Denning's classic
   throughput-rises-then-collapses curve.

## Correctness, not just plausibility

This domain has unusually strong ground truth available, and the build
leans on all of it:

- **Matches published textbook numbers exactly**: the classic
  Silberschatz FCFS (avg wait 3.33), SRTF (avg wait 6.5), and Round Robin
  q=4 (avg wait 5.67) scheduling examples; the classic Silberschatz
  FIFO/LRU/Optimal paging example (15/12/9 faults on the same reference
  string).
- **Reproduces Belady's Anomaly on demand**: FIFO's fault count goes from
  9 (3 frames) to 10 (4 frames) on the classic counter-example string —
  more memory making things *worse* is the whole point, and the
  simulator gets it right rather than papering over it with a simplified
  model that would hide the effect.
- **An independent brute-force oracle** (`quantum.cli oracle`,
  `compare.brute_force_min_faults`) confirms Belady's MIN matches the
  true information-theoretic minimum fault count on small inputs via
  exhaustive search over every possible eviction decision — not just
  "looks close to optimal."
- **The LRU stack property**, checked tick-by-tick across dozens of
  random workloads: the set of pages resident under *k* frames is always
  a subset of the set resident under *k+1* frames — the structural reason
  LRU can never exhibit Belady's Anomaly, verified directly rather than
  assumed.
- **MLFQ starvation demonstrated, then fixed, by the same knob**: the
  test suite runs one identical workload through the engine twice — once
  with the periodic priority boost disabled, once enabled — and asserts
  the CPU-bound process is starved dramatically longer without it.

Three real bugs were found and fixed during an adversarial-review pass
(see [REVIEW.md](REVIEW.md)): I/O bursts that completed in zero ticks (two
redundant `Process` fields got mixed up), `context_switch_cost` hanging
the simulation forever (a scheduling decision was discarded instead of
honored), and the MLFQ Gantt trace's queue-level field being silently
hardcoded to `0`. Each has a regression test.

## Why this today

Every prior "from scratch" build in this repo has modeled a language
runtime, a data structure, a renderer, or a solved/fully-observable
system — never the operating system layer underneath all of them, the one
that decides who gets the CPU and which page gets evicted, under real
contention, where the "right" answer is a trade-off (fairness vs.
throughput vs. starvation-freedom) rather than a single pass/fail check.
That made the interesting engineering problem here different in kind: not
"does this compute the right output" but "does this system's *emergent
behavior over time* — who starves, when memory thrashes, what a real
textbook example predicts — actually match reality." Having Belady's MIN
as a provable lower bound, Belady's Anomaly as a known counter-intuitive
target to reproduce on purpose, and Denning's thrashing curve as a
specific real-world shape to hit gave this build unusually sharp,
falsifiable correctness criteria for a domain that's normally graded on
vibes.

## Where a human could take this next

- **A real multi-core scheduler**: extend the tick engine from one CPU to
  N, with per-core ready queues, load balancing, and CPU affinity — a
  genuinely different fairness/throughput trade-off space.
- **Segmentation + paging combined**, or a real page-table walk with
  multi-level page tables and TLB entries that model actual x86-style
  page table structures instead of a flat lookup.
- **A real disk scheduler** (FCFS/SSTF/SCAN/C-SCAN for the thrashing
  simulator's single disk) — right now it's FIFO-only, which is itself a
  simplification worth studying.
- **Feed the scheduler's own metrics back into an admission controller**:
  use the thrashing-cliff detector to automatically throttle the degree
  of multiprogramming in the scheduler, closing the loop between the two
  subsystems that are currently simulated independently.
- **Interactive parameter tuning in the visualizer** — sliders for
  quantum size, MLFQ boost interval, or frame count that re-run the
  simulation live in the browser (the core engines are pure functions of
  their inputs, so this is mostly a matter of shipping a WASM/Pyodide
  build or a small JS port).
