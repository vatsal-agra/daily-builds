# Adversarial Review (Phase 3)

Methodology: attacked the Phase 2 build as a hostile reviewer, not just a
happy-path tester. Four techniques used, in order:

1. **An independent tick-based oracle.** A completely separate, dead-simple
   1-unit-at-a-time simulator (`scratchpad/oracle_fuzz.py`, not shipped —
   its findings are promoted into `tests/`) that re-implements FCFS, SJF,
   SRTF, Priority (both variants), and Round Robin from the algorithm
   definitions, not by reading `core/scheduler.py`. Ran 300 randomized
   workloads (1–8 processes, random arrivals/bursts/priorities) through
   both the event-driven engine and the tick oracle and diffed every
   process's start/completion time. **0 mismatches.**
2. **Definitional invariant fuzzing.** For 200 more randomized workloads
   across all 7 CPU-scheduling algorithm variants: Gantt-chart segments
   must be contiguous and non-overlapping, and total busy time must equal
   the sum of every process's burst time exactly. **0 failures.**
3. **The Optimal-is-a-lower-bound invariant.** For 300 randomized page-
   reference strings/frame counts, `optimal()`'s fault count must never
   exceed FIFO/LRU/Clock's fault count on the same string. **0
   violations.** (Note: this does *not* mean LRU always beats FIFO — on
   the Belady string itself LRU actually takes *more* faults than FIFO at
   3 frames, 10 vs. 9, which is a real, correct result, not a bug: LRU is
   only proven to never do *worse than itself* with more frames, not to
   beat every other algorithm on every string.)
4. **Manual edge-case and security probing** (below) — malformed input,
   degenerate workloads, arithmetic edge cases, and treating the HTML
   report as attacker-facing output.

## Bugs found and fixed

1. **CRITICAL — `mlfq(..., boost_interval=0)` or a negative value hangs
   forever.** `do_boost`'s loop condition `now - last_boost >= boost_interval`
   is trivially always true when `boost_interval <= 0` (0: every check
   passes immediately and `last_boost` never catches up to `now`;
   negative: `last_boost` gets walked toward -∞ every iteration), so the
   simulation never leaves the boost loop. Reproduced directly with a
   `SIGALRM`-guarded call that confirmed the hang before touching the fix.
   Fixed by validating `boost_interval` is positive (or `None`, meaning
   "boosting disabled") up front in `mlfq()`, raising a clean
   `SchedulerError` instead. The same guard protects the CLI's `--boost`
   flag since it flows straight into `mlfq()`.

2. **HIGH — stored-XSS-shaped bug in the HTML report.** `html_report.py`
   built several DOM regions (`renderProcessTable`'s table HTML, and the
   Gantt/comparison-grid hover tooltips) by directly string-interpolating
   process `pid` values into template literals assigned via
   `element.innerHTML = ...`. Since `pid` comes straight from a
   user-supplied `--workload some.json` file, a pid like
   `<img src=x onerror="...">` runs arbitrary JS the moment the report is
   opened or a Gantt bar is hovered. Reproduced with a real headless-
   Chromium run that confirmed a `window.__xss` marker actually fired,
   both on page load and on tooltip hover, before fixing. Fixed by adding
   an `escapeHtml()` helper and routing every pid (and, defensively, the
   internally-generated algorithm-name strings) through it before they
   reach an `innerHTML` sink; re-ran the same exploit afterward and
   confirmed it no longer fires, with zero console errors. This is the
   same bug *class* previous entries in this ledger (Palimpsest,
   2026-07-04; Loom, 2026-07-14) have hit and fixed — worth specifically
   testing for on every report generator in this repo, not just trusting
   "it renders fine on my own test data."

3. **MEDIUM — CLI comparison table misaligned for real output.** `dispatch
   compare`'s table used a hardcoded 14-character column width for the
   `algorithm` column, which fits `"FCFS"`/`"SJF"` but not
   `"Priority (non-preemptive)"` (26 chars) — every column after it in
   that row silently shifted right of the header, undetected by anything
   that only checked individual cell *values* rather than the *rendered
   table's* column alignment. Fixed by sizing the column to the longest
   algorithm name actually present in the result set.

## Verified, not bugs

- **MLFQ's `boost_interval` doesn't change final completion time in a
  100%-CPU-utilization stress test, but does fix real starvation.** Built
  a scenario (one 30-unit process against a continuous stream of 99
  arriving 1-unit jobs) where, without boosting, the long process is
  starved from `t=2` to `t=101` — a single 99-tick wait — after which it
  finishes at the same makespan as the boosted run (`t=129`, since total
  busy time is fixed and *someone* has to finish last when CPU
  utilization never drops below 100%). With `boost_interval=15`, the same
  process instead gets scheduled roughly every ~17 ticks throughout,
  never enduring a wait remotely close to 99 ticks. Confirmed this by
  diffing the actual Gantt segments for that process between the two
  runs, not just the final completion time — the right metric for
  "did boosting fix starvation" is the longest gap between service, not
  final completion time, and checking only the latter would have wrongly
  read this as "boosting does nothing."
- **Duplicate pid, zero/negative quantum, zero/negative frame count, empty
  reference string, empty process list, an unknown `--workload`/`--ref`
  preset, and a malformed JSON workload** all already raised a specific,
  clean `error: ...` message and exit code 1 — no raw Python traceback in
  any case tried.
- Single-process workloads, an oversized Round-Robin quantum (degenerates
  correctly to FCFS-like behavior), and page-replacement frame counts
  larger than the number of unique pages in the reference string all
  produce correct, sane output.

## What's still open going into Phase 4

- The categorical color palette used by the HTML report has 8 slots;
  a workload with more than 8 processes will visually reuse colors
  across processes in the Gantt legend. None of this repo's shipped
  preset workloads hits that (max 6 processes), and it degrades
  gracefully (still functional, just two processes could share a hue) —
  documented here rather than "fixed" since a truly unbounded categorical
  palette isn't colorblind-safe past the dataviz skill's own validated
  slot count.
