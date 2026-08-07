# Dispatch

An operating-system **process-scheduling and virtual-memory simulator**,
built entirely from scratch: six CPU-scheduling algorithms (FCFS, SJF,
SRTF, Round Robin, Priority — non-preemptive/preemptive/aging, MLFQ), four
page-replacement algorithms (FIFO, LRU, Optimal/MIN, Clock), a
Banker's-Algorithm deadlock-avoidance engine plus resource-allocation-graph
deadlock detection, and an interactive HTML visualizer — over a real
discrete-event simulation core, not a fixed-timestep tick loop.

**80/80 automated tests pass** and **`./demo.sh`'s 10-step end-to-end
walkthrough passes.** See [Testing](#testing).

## Why this, today

56 prior daily builds in this repo span 3D renderers, path tracers,
9 different from-scratch Transformer/LLM implementations, 5 CDCL SAT
solvers, 5 full-text search engines, crypto suites, a WASM toolchain, a
JIT compiler, a Hindley-Milner type inferencer, and a Raft consensus
simulator — but **none had touched operating-systems internals**: process
scheduling, memory management, or deadlock. It's a genuinely different
algorithmic family (discrete-event simulation over queues, not
numerical/parsing/graph algorithms), and it comes with unusually strong
ground truth to verify against: every scheduling algorithm has a fully
hand-worked textbook example with an exact expected average waiting time,
Optimal page replacement is a *mathematically proven* lower bound on any
other algorithm's fault count on the same input, and Belady's Anomaly is
a named, published, checkable "gotcha" result — if your FIFO
implementation is subtly wrong, it simply won't reproduce it.

## How to run it

```bash
# CPU scheduling
python3 cli.py run --algo srtf --workload textbook_srtf
python3 cli.py run --algo priority-aging --workload mixed_general --aging-rate 2 --aging-period 4
python3 cli.py compare --workload mixed_general

# Virtual memory
python3 cli.py vm --algo all --ref belady --frames 3

# Deadlock avoidance / detection
python3 cli.py deadlock --mode bankers --available "[3,3,2]" \
  --max "[[7,5,3],[3,2,2],[9,0,2],[2,2,2],[4,3,3]]" \
  --allocation "[[0,1,0],[2,0,0],[3,0,2],[2,1,1],[0,0,2]]"
python3 cli.py deadlock --mode detect \
  --assignment '[["R0","P0"],["R1","P1"]]' --request-edges '[["P0","R1"],["P1","R0"]]'

# Synthetic workloads + the interactive HTML report
python3 cli.py generate --n 10 --rate 0.3 --seed 42 --output synth.json
python3 cli.py report --workload mixed_general --vm-ref belady --frames 3 --output report.html

# a scripted walkthrough of everything above
python3 cli.py demo
```

No dependencies beyond Python 3's standard library — `cli.py`, `core/`,
and `workloads/` run with nothing installed. (Only the *dev-time*
screenshot verification of the HTML report used the sandbox's pre-installed
Playwright/Chromium; the shipped report is a static, dependency-free file.)

## Full feature list

**Required:**

1. **CPU scheduling engine** (`core/scheduler.py`) — a real discrete-event
   simulator (the clock jumps between arrivals/completions/quantum
   expiries, not fixed timesteps) implementing FCFS, SJF (non-preemptive),
   SRTF (preemptive), Round Robin (configurable quantum), Priority
   (non-preemptive and preemptive), and MLFQ (configurable per-level
   quanta plus an optional starvation-preventing priority-boost interval).
   Waiting/turnaround/response time per process, and system-wide CPU
   utilization/throughput/context-switch count.
2. **Virtual memory page-replacement engine** (`core/vm.py`) — FIFO, LRU,
   Optimal/MIN, and Clock/Second-Chance, each producing a full per-step
   trace (frame contents + fault/hit/eviction at every reference).
   Reproduces **Belady's Anomaly** exactly on the canonical
   `1,2,3,4,1,2,5,1,2,3,4,5` string: FIFO takes 9 faults at 3 frames but
   10 at 4 frames — more memory, *more* faults.
3. **Interactive HTML visualizer** (`html_report.py`) — a self-contained
   page (Gantt charts per algorithm, a 4-panel small-multiples metrics
   comparison, an animated VM frame-by-frame replay with play/step/scrub,
   and a Belady's-Anomaly fault-vs-frames line chart), built to the
   dataviz skill's method (validated categorical palette, light + dark
   mode, hover tooltips, legends, no dual-axis charts), screenshot- and
   headless-Chromium-verified with zero console errors.
4. **CLI + preset workload library** (`cli.py`, `workloads/`) —
   `run/compare/vm/deadlock/generate/report/demo`; 5 named preset
   workloads including the textbook and Belady examples plus 3 VM
   reference-string presets.

**Stretch (both shipped):**

5. **Deadlock avoidance & detection** (`core/deadlock.py`) — Banker's
   Algorithm safety check + resource-request evaluation (cross-checked
   against a brute-force all-permutations oracle; reproduces the classic
   Silberschatz safe sequence `<P1,P3,P4,P0,P2>` exactly), plus
   resource-allocation-graph cycle detection for single-instance
   resources.
6. **Starvation-prevention aging + synthetic workloads** (`core/aging.py`)
   — preemptive priority scheduling with a decaying effective priority,
   proven by construction to cut a starved process's longest wait from
   59 ticks (plain preemptive priority) down to 20 (aging) in a
   constructed worst case — not just asserted from theory; plus a
   configurable Poisson-arrival synthetic workload generator.

## Testing

```bash
python3 -m unittest discover -s tests -v   # 80 tests
./demo.sh                                  # full suite + a live CLI walkthrough, 10 steps
```

`tests/` includes the 5 hand-worked textbook examples asserted exactly;
an independently re-implemented tick-based oracle (`tests/oracle.py`,
written from the algorithm definitions, sharing no code with
`core/scheduler.py`) cross-checked against the event-driven engine over
250 randomized workloads with 0 mismatches; definitional-invariant
fuzzing (Gantt contiguity, busy time == sum of bursts, no negative
waiting times); a 200-trial fuzz check that Optimal page replacement is
never beaten by FIFO/LRU/Clock; a brute-force cross-check for Banker's
Algorithm; CLI subprocess tests (happy-path and 8 error-paths); and a
real headless-Chromium test confirming the Phase-3 stored-XSS bug stays
fixed (source code alone can't prove a browser won't execute something).

See [`PLAN.md`](./PLAN.md) for the full architecture, and
[`REVIEW.md`](./REVIEW.md) for the adversarial-review process and the 3
real bugs it found and fixed (an `mlfq(boost_interval=0)` infinite hang,
a stored-XSS-shaped bug in the HTML report, and a CLI table-alignment
bug).

## Where a human could take this next

- **A real preemption-on-I/O model.** Every process here is a single pure
  CPU burst; real schedulers interleave CPU and I/O bursts, which is
  where Round Robin/MLFQ's design tradeoffs (I/O-bound vs. CPU-bound
  process fairness) actually show up.
- **Multi-core scheduling.** Everything here assumes one CPU; load
  balancing, CPU affinity, and work-stealing across cores are a
  substantial next algorithmic layer.
- **A live/animated Gantt chart driven by `deadlock`/`aging` together** —
  e.g. a scenario where a scheduling decision and a resource-allocation
  decision interact (priority inversion is the classic case: a
  high-priority process blocked on a mutex held by a low-priority one).
- **Multi-instance resource-allocation-graph deadlock detection** (the
  current `detect_cycle` assumes one instance per resource type, the
  standard textbook simplification — real OSes have multiple instances of
  a resource type, which needs a different, more expensive detection
  algorithm than a simple cycle check).
- **A second, independent memory-access-pattern generator** (e.g. a
  Zipfian/LRU-stack-distance model) to stress-test the VM algorithms
  against something more realistic than hand-authored reference strings.
