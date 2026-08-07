# Dispatch

**Status: Phase 3 — adversarial review complete.** An OS process-scheduling &
virtual-memory simulator built entirely from scratch.

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
  Priority (non-preemptive + preemptive), and MLFQ, over a real
  discrete-event simulation engine. Every algorithm's aggregate waiting
  time has been cross-checked against hand-worked examples (see
  `workloads/textbook_*.json` for the exact numbers).
- **Virtual memory** (`core/vm.py`): FIFO, LRU, Optimal/MIN, Clock page
  replacement, with a full per-step trace. FIFO on the classic
  `1,2,3,4,1,2,5,1,2,3,4,5` string reproduces Belady's Anomaly exactly:
  9 faults @3 frames, 10 @4 frames.
- **CLI** (`cli.py`): `run`, `compare`, `vm`, `report`, `demo`.
- **HTML visualizer** (`html_report.py`): Gantt charts per algorithm,
  a 4-panel metrics comparison, an animated VM frame-by-frame replay,
  and a Belady's-Anomaly fault-vs-frames line chart. Self-contained,
  screenshot-verified in light and dark mode with zero console errors.

## Try it

```bash
python3 cli.py run --algo srtf --workload textbook_srtf
python3 cli.py compare --workload mixed_general
python3 cli.py vm --algo all --ref belady --frames 3
python3 cli.py report --workload mixed_general --vm-ref belady --frames 3 --output report.html
python3 cli.py demo
```

## Coming next

Phase 3 (adversarial review), Phase 4 (Banker's algorithm deadlock
avoidance/detection + starvation-preventing aging scheduler + polish),
Phase 5 (full test suite + demo script), Phase 6 (final README + ledger).

See [`PLAN.md`](./PLAN.md) for the full architecture and feature list.
