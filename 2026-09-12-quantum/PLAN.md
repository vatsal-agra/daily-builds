# Quantum — an OS scheduler + virtual memory simulator, built from scratch

## The concept

Every prior "from scratch" build in this repo has modeled a *language*, a
*data structure*, a *renderer*, or a *solved/fully-observable system*
(compilers, transformers, SAT solvers, path tracers, a chess engine, a
blockchain). None has modeled the operating system underneath all of them —
the layer that decides *which process gets the CPU right now* and *which
page gets evicted from RAM right now*, under real resource contention, with
policies whose only real judge is emergent behavior over time (fairness,
starvation, thrashing) rather than a single pass/fail check.

**Quantum** is a from-scratch discrete-time simulator of the two central OS
resource-allocation problems:

1. **CPU scheduling** — six real scheduling algorithms (FCFS, SJF,
   preemptive SRTF, Round Robin, Priority-with-aging, and a genuine
   multi-level feedback queue) running realistic processes that alternate
   CPU bursts and I/O bursts, exactly like Silberschatz-style OS textbook
   process models.
2. **Virtual memory management** — a page table + TLB + four page
   replacement algorithms (FIFO, LRU, Clock/second-chance, and Belady's
   Optimal/MIN), driven by realistic reference strings that exhibit
   locality of reference rather than uniform noise.

The name is a pun that is also accurate: a scheduling *quantum* (time
slice) is the central knob in Round Robin and MLFQ, and the project studies
exactly what happens as you turn it.

## Why this is interesting

Unlike a compiler or a solver, there is no single "correct output" to check
against for most of this — a scheduler's job is to trade off fairness,
throughput, and starvation-freedom, and a page-replacement policy's job is
to guess the future without seeing it. That means the *right* kind of
correctness evidence here is different from prior builds:

- **A closed-form optimum exists for paging** (Belady's MIN: evict the page
  used farthest in the future) — proven optimal in the literature — so we
  can verify our from-scratch replacement algorithms against a real
  information-theoretic lower bound, not just "looks plausible."
- **A textbook counter-intuitive anomaly exists** (Belady's Anomaly: FIFO
  can get *worse* with *more* physical memory) — reproducing it on purpose
  is a real correctness signal that the simulator models frame allocation
  faithfully rather than through a simplified shortcut that would hide it.
- **Starvation is a qualitative property that only shows up over time** —
  MLFQ needs a periodic priority boost specifically to prevent CPU-bound
  jobs from starving interactive ones forever; we can demonstrate the bug
  by disabling the boost and watching starvation actually happen, then
  show it fixed.

## Architecture

```
quantum/
  process.py     Process model: PID, arrival time, CPU/IO burst sequence, priority
  scheduler.py   Tick-driven CPU scheduler core + 6 algorithms + metrics
  memory.py      PageTable, TLB, frame pool, 4 replacement algorithms, demand paging
  workload.py    Seeded synthetic workload generator (bursts + locality-based ref strings)
  compare.py     Runs the full algorithm matrix, computes aggregate reports,
                 auto-detects Belady's Anomaly, verifies Optimal-minimality
  cow.py         Copy-on-write fork simulator (reference-counted frame sharing)
  thrash.py      Multiprogramming / working-set thrashing simulator
  viz_export.py  Serializes a simulation run to the JSON the visualizer consumes
  cli.py         `python -m quantum.cli <subcommand>` entry point
visualizer/
  index.html     Self-contained interactive Gantt chart + memory timeline +
                  comparison charts, driven entirely by real exported JSON
tests/           pytest unit tests + a brute-force ground-truth oracle +
                 a headless-browser smoke test of the visualizer
```

Design choices, and why:

- **Tick-driven, single-core simulation.** Real OS schedulers are event
  driven, but a tick-driven model (1 tick = 1 time unit) is exactly
  equivalent for integer burst/quantum lengths, far easier to verify
  (every invariant can be checked tick-by-tick), and is the model every OS
  textbook uses when teaching Gantt charts. One CPU core keeps fairness
  analysis unambiguous.
- **Processes have real CPU/IO burst sequences**, not a single number. A
  process that is doing I/O is off the ready queue and off the CPU
  entirely, which is what makes MLFQ's interactive-vs-CPU-bound behavior
  meaningful to demonstrate at all.
- **No numpy, no external dependencies** for the core engine — pure
  stdlib Python, matching this repo's established "from scratch means from
  scratch" convention. The visualizer is one dependency-free HTML file.
- **Optional, explicit context-switch cost.** Off by default (matches the
  classic textbook idealization used for the correctness proofs above), but
  a real non-zero cost can be turned on to show its throughput impact — a
  detail most toy scheduler simulators skip entirely.

## Feature list

### Required
1. **Multi-algorithm CPU scheduler** — FCFS, SJF (non-preemptive),
   SRTF (preemptive), Round Robin, Priority-with-aging, and MLFQ (3 queues,
   periodic priority boost), over processes with real CPU+I/O burst
   sequences, producing a full Gantt trace and per-process/aggregate
   metrics (waiting, turnaround, response, CPU utilization, throughput).
2. **Virtual memory manager** — page table + demand paging + a small
   fully-associative LRU TLB + four replacement algorithms (FIFO, LRU,
   Clock, Optimal/Belady-MIN), with fault/hit-rate metrics and a per-tick
   frame-occupancy trace.
3. **Realistic workload generator + comparison engine** — a seeded
   generator producing locality-of-reference memory traces and
   CPU/IO-bursty processes (not uniform noise), plus a `compare` engine
   that runs the full algorithm × parameter matrix, auto-detects Belady's
   Anomaly when it occurs, and checks the Optimal-minimality invariant on
   every run.
4. **Interactive HTML visualizer** — a single self-contained page driven
   by real exported simulation JSON: a scrubable Gantt chart of CPU
   scheduling, a per-tick memory/frame occupancy heatmap with fault
   markers, and algorithm-comparison bar charts. No placeholder or
   hand-authored numbers — every pixel comes from a real simulation run.

### Stretch
5. **Copy-on-write fork simulator** — a parent process forks a child that
   shares every physical frame by reference count; a write from either
   side triggers a real copy only for that page, verified by tracking
   frame identity divergence and correct refcounting (frames only freed
   when refcount hits zero).
6. **Multiprogramming / thrashing simulator** — Denning's working-set
   model: run several processes concurrently against a shared, fixed pool
   of physical frames, vary the degree of multiprogramming, and reproduce
   the classic thrashing cliff (throughput rises then collapses once
   aggregate working-set size exceeds available frames).

## Ground-truth verification strategy (used in Phase 5)

- **Optimal vs. brute force**: for small reference strings (alphabet ≤ 4,
  length ≤ 10, frames ≤ 3) compute the true minimum fault count via
  exhaustive search over eviction decisions and confirm Belady's MIN
  matches it exactly on every case.
- **Optimal-minimality invariant**: on every randomly generated workload,
  assert Optimal's fault count is ≤ FIFO's, LRU's, and Clock's.
- **LRU stack property**: the set of resident pages under *k* frames is
  always a subset of the set under *k+1* frames for LRU, checked
  tick-by-tick on random workloads (LRU is stack-based and must never
  exhibit Belady's Anomaly — a strong differential check against FIFO).
- **Scheduler conservation law**: total CPU-busy ticks across a run must
  equal the sum of every process's CPU burst time, for every algorithm.
- **Hand-derived textbook examples**: fixed 3–5 process FCFS/SJF/RR
  scenarios with independently hand-computed waiting/turnaround times,
  asserted exactly.
