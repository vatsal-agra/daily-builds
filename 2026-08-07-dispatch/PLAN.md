# Dispatch — an OS process-scheduling & virtual-memory simulator, built from scratch

## Concept

Every operating systems course teaches the same two families of algorithm
that decide "what runs next" and "what stays in RAM": **CPU scheduling**
(FCFS, SJF, SRTF, Round Robin, Priority, MLFQ) and **page replacement**
(FIFO, LRU, Optimal/MIN, Clock). Textbooks show them as hand-worked
examples on a chalkboard. Dispatch implements the real algorithms as a
deterministic discrete-event simulation, computes the same metrics a
kernel scheduler cares about (waiting time, turnaround time, response
time, CPU utilization, throughput, page-fault rate), and cross-checks
every result against closed-form/definitional ground truth and classic
textbook worked examples — including reproducing **Belady's Anomaly**,
the famous counter-intuitive result where giving FIFO *more* memory frames
causes *more* page faults, which only a correct simulator gets right.

## Why it's interesting

This repo's 56 prior builds span renderers, language runtimes, LLMs,
crypto, compilers, physics engines, search engines, and a Raft consensus
simulator — but **none has touched operating-systems internals**: process
scheduling, memory management, or deadlock. It's a distinct algorithmic
family (discrete-event simulation over queues, not numerical/graph/parsing
algorithms), it has exceptionally strong closed-form ground truth (hand-
computable Gantt charts, a mathematically provable invariant that Optimal
page replacement is a lower bound on fault count for any algorithm, and a
named "gotcha" result — Belady's Anomaly — that a broken FIFO implementation
would fail to reproduce), and it naturally produces a great interactive
visualization (a Gantt chart timeline and a memory-frame animation), which
fits this repo's established visualizer culture.

## Architecture

```
dispatch/
  core/
    process.py      -- Process/PCB dataclass, workload loading
    scheduler.py     -- discrete-event CPU scheduler engine + 6 algorithms
    metrics.py       -- waiting/turnaround/response time, utilization, throughput
    vm.py            -- page-reference-string replacement engine + 4 algorithms
    deadlock.py       -- Banker's algorithm (avoidance) + RAG cycle detection (detection)
    aging.py          -- starvation-preventing priority aging policy
  workloads/          -- named preset workloads (JSON) incl. classic textbook cases
  cli.py               -- `dispatch` CLI: run/compare/vm/deadlock/report/demo
  html/report.py        -- self-contained interactive HTML Gantt + memory visualizer
  tests/                -- unit + textbook cross-check + Belady's-anomaly regression suite
```

Simulation core is a min-heap-driven discrete-event loop over
(arrival, burst, priority, I/O-burst) tuples — not a fixed-timestep
tick loop — so results are exact, not sampling-error-prone.

## Feature list

### Required (4)

1. **CPU scheduling engine with 6 real algorithms** — FCFS, SJF
   (non-preemptive), SRTF (preemptive-shortest-remaining-time), Round
   Robin (configurable quantum, correct tie-break/re-insertion order),
   Priority (non-preemptive and preemptive variants), and MLFQ
   (multi-level feedback queue with configurable per-level quanta and
   demotion/promotion rules). Produces a full per-process schedule
   (start/end intervals) plus waiting/turnaround/response-time metrics
   and system-wide CPU utilization/throughput, cross-checked against
   hand-worked textbook examples and definitional identities
   (turnaround = completion − arrival; waiting = turnaround − burst).

2. **Virtual memory page-replacement engine with 4 real algorithms** —
   FIFO, LRU, Optimal/MIN (Bélády's clairvoyant algorithm — the proven
   lower bound on any algorithm's fault count), and Clock/Second-Chance —
   run over arbitrary reference strings and a page-table/TLB model,
   reproducing **Belady's Anomaly** for FIFO on the classic
   `1,2,3,4,1,2,5,1,2,3,4,5` reference string (9 faults at 3 frames, 10
   faults at 4 frames — more memory, *more* faults) as a hard regression
   test, and proving LRU/Optimal are stack algorithms (monotonically
   non-increasing faults as frames increase) on the same string.

3. **Interactive HTML visualizer** — a self-contained page rendering a
   scrollable, color-coded Gantt chart per scheduling algorithm (idle
   gaps visible, context switches marked) with hoverable process detail,
   a side-by-side multi-algorithm comparison bar chart of the four
   metrics, and a frame-by-frame animated memory-timeline for the VM
   simulator showing which page occupies which frame at each reference
   and highlighting faults vs. hits.

4. **CLI + preset workload/report system** — `dispatch run/compare/vm/
   deadlock/report/demo`; a library of named preset workloads including
   at least one classic textbook scheduling example and the Belady's-
   Anomaly reference string; a `compare` command producing a metrics
   table across all 6 CPU-scheduling algorithms on the same workload.

### Stretch (2, ship ≥1) — **both shipped**

5. **Deadlock avoidance & detection** — Banker's Algorithm (safety
   algorithm over allocation/max/available matrices, returns a real safe
   sequence or proves none exists) plus resource-allocation-graph
   cycle detection for deadlock detection after the fact, both verified
   against classic textbook allocation matrices.

6. **Starvation-prevention aging policy + synthetic workload generator** —
   an aging variant of Priority scheduling that provably eliminates
   starvation (a process that would starve under plain priority
   scheduling is proven to eventually run), plus a configurable
   synthetic workload generator (Poisson arrivals, configurable burst
   distributions) for stress-testing beyond hand-authored presets.

## Verification strategy

- Every scheduling algorithm checked against at least one fully
  hand-worked textbook example (exact per-process waiting/turnaround
  times asserted, not just aggregate averages).
- Definitional identity checks (`turnaround == completion - arrival`,
  `waiting == turnaround - burst`, total busy time + idle time == makespan)
  hold for every algorithm on every workload, including randomized ones.
- Page-replacement invariant: Optimal's fault count is a lower bound
  for FIFO/LRU/Clock on the *same* reference string, for many randomized
  reference strings, not just the curated examples.
- Belady's Anomaly reproduced exactly (9 vs. 10 faults) as a named
  regression test.
- Banker's algorithm cross-checked against a brute-force safe-sequence
  search (try all permutations) on small matrices.
