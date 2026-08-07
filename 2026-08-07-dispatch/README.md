# Dispatch

**Status: Phase 5 — verification complete.** An OS process-scheduling &
virtual-memory simulator built entirely from scratch.

**80/80 automated tests pass** (`python3 -m unittest discover -s tests`) and
**`./demo.sh`'s 10-step end-to-end walkthrough passes** (runs the full test
suite plus a live exercise of every CLI feature against real output, not
mocked). See [Testing](#testing) below.

Phase 3 found and fixed 3 real bugs (see [`REVIEW.md`](./REVIEW.md)): an
`mlfq(boost_interval=0)` infinite hang, a stored-XSS-shaped bug in the HTML
report (unescaped process-id strings reaching `innerHTML`), and a CLI table
misalignment for long algorithm names — verified via an independent
tick-based oracle (300 randomized workloads, 0 mismatches vs. the
event-driven engine), 200 more definitional-invariant fuzz runs, a 300-trial
"Optimal is a lower bound" VM fuzz check, and a real headless-Chromium XSS
repro/fix confirmation.

## What's working right now

- **CPU scheduling** (`core/scheduler.py`): FCFS, SJF, SRTF, Round Robin,
  Priority (non-preemptive + preemptive), and MLFQ (with optional
  starvation-preventing priority boosting), over a real discrete-event
  simulation engine. Every algorithm's aggregate waiting time has been
  cross-checked against hand-worked examples (see
  `workloads/textbook_*.json` for the exact numbers).
- **Virtual memory** (`core/vm.py`): FIFO, LRU, Optimal/MIN, Clock page
  replacement, with a full per-step trace. FIFO on the classic
  `1,2,3,4,1,2,5,1,2,3,4,5` string reproduces Belady's Anomaly exactly:
  9 faults @3 frames, 10 @4 frames.
- **Deadlock avoidance & detection** (`core/deadlock.py`, stretch feature
  5): Banker's Algorithm safety check + resource request evaluation
  (cross-checked against a brute-force all-permutations oracle), and
  resource-allocation-graph cycle detection for single-instance resources.
- **Starvation-prevention aging + synthetic workloads** (`core/aging.py`,
  stretch feature 6): preemptive priority scheduling with a decaying
  effective priority, proven to cut a starved process's longest wait from
  59 ticks (plain preemptive priority) to 20 (aging) in a constructed
  worst case; plus a configurable Poisson-arrival workload generator.
- **CLI** (`cli.py`): `run` (7 algorithm choices incl. `priority-aging`),
  `compare`, `vm`, `deadlock`, `generate`, `report`, `demo`.
- **HTML visualizer** (`html_report.py`): Gantt charts per algorithm,
  a 4-panel metrics comparison, an animated VM frame-by-frame replay,
  and a Belady's-Anomaly fault-vs-frames line chart. Self-contained,
  screenshot-verified in light and dark mode with zero console errors.

## Try it

```bash
python3 cli.py run --algo srtf --workload textbook_srtf
python3 cli.py run --algo priority-aging --workload mixed_general --aging-rate 2 --aging-period 4
python3 cli.py compare --workload mixed_general
python3 cli.py vm --algo all --ref belady --frames 3
python3 cli.py deadlock --mode bankers --available "[3,3,2]" \
  --max "[[7,5,3],[3,2,2],[9,0,2],[2,2,2],[4,3,3]]" \
  --allocation "[[0,1,0],[2,0,0],[3,0,2],[2,1,1],[0,0,2]]"
python3 cli.py deadlock --mode detect \
  --assignment '[["R0","P0"],["R1","P1"]]' --request-edges '[["P0","R1"],["P1","R0"]]'
python3 cli.py generate --n 10 --rate 0.3 --seed 42 --output synth.json
python3 cli.py report --workload mixed_general --vm-ref belady --frames 3 --output report.html
python3 cli.py demo
```

## Testing

```bash
python3 -m unittest discover -s tests -v   # 80 tests
./demo.sh                                  # full suite + a live CLI walkthrough, 10 steps
```

`tests/` includes hand-worked textbook examples, an independently
re-implemented tick-based oracle cross-checked against the event-driven
engine over 250 randomized workloads, definitional-invariant fuzzing,
a 200-trial "Optimal is a lower bound" fuzz check for virtual memory, a
brute-force cross-check for Banker's Algorithm, CLI subprocess tests
(happy-path and error-path), and a real headless-Chromium test that
confirms the Phase-3 XSS bug stays fixed (not just that the source code
looks escaped).

## Coming next

Phase 6 (final ledger entry).

See [`PLAN.md`](./PLAN.md) for the full architecture and feature list, and
[`REVIEW.md`](./REVIEW.md) for the adversarial-review findings.
