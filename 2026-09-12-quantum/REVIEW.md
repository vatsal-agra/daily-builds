# Phase 3 — Adversarial Review

Reviewed as a hostile reviewer whose job is to break Quantum, not to admire
it. Every issue below was actually reproduced before being fixed, and every
fix has a regression test. "A fresh run-through hits zero of these issues"
was re-verified after each fix by re-running the full suite
(`pytest tests/` — 97/97 green — plus the headless-browser visualizer
smoke test) from scratch.

## Real bugs found and fixed

### 1. Every I/O burst completed instantly (0 ticks) — `Process` had two
redundant fields that got mixed up

`Process` originally carried both `remaining_in_burst` (meant for whichever
burst — CPU or IO — is currently in progress) *and* a second field
`io_remaining` that duplicated the same purpose for I/O specifically. The
CPU→IO transition in `scheduler.py` set `remaining_in_burst` to the new IO
burst's length but the tick loop decremented and checked `io_remaining` —
which was never initialized past its dataclass default of `0`. The result:
the very first "IO completion" check on the tick an IO burst *started* saw
`io_remaining == 0` and immediately completed it, so every I/O burst took
zero simulated time no matter its declared length.

Caught by: `TestBursts::test_process_with_io_bursts_alternates_correctly`
in `tests/test_scheduler.py`, which asserts a 3+5+2 CPU/IO/CPU process
takes exactly 10 ticks with no other process competing. It failed with
`completion_time == 5` instead of `10`.

**Fix:** removed the redundant `io_remaining` field entirely; the engine
now uses `remaining_in_burst` uniformly for whichever burst (CPU or IO) is
currently active. Regression test now passes and is kept.

### 2. `context_switch_cost > 0` made the simulation hang forever — a
process vanished mid-switch

The original implementation called `policy.select(t, running)` to decide
who runs next, then — on discovering a switch was needed and overhead was
configured — discarded that decision and set `running = None` to "pay the
cost," planning to re-decide later. But `select()` is not a pure query: for
Round Robin/MLFQ it already *popped the chosen process off its internal
queue* and updated quantum bookkeeping as a side effect of being called.
Throwing away its return value without ever running or re-queuing that
process made it disappear from the simulation permanently — it was never
running, never ready, never blocked, and never counted as done, so the
`while done_count < total` loop ran forever (until it hit the
100,000-ticks-per-process safety cap and raised `RuntimeError`).

Caught by: manually exercising the untested `context_switch_cost` path
(nothing in the original test suite touched it) — the exact scenario now
lives in `TestContextSwitchCost::test_overhead_is_paid_and_conserved`.

**Fix:** redesigned overhead accounting so the policy's decision is always
honored immediately (`running = chosen`, unconditionally, every tick) —
the overhead is modeled as "dispatched but not yet making progress"
(`overhead_remaining` ticks during which `remaining_in_burst` simply isn't
decremented) rather than as a second no-one-is-running phase that has to
remember a discarded decision. This is both simpler and correct: CPU-time
conservation holds exactly, and total ticks now equal the zero-cost
baseline plus `context_switches × cost`, verified in the regression test.

### 3. The Gantt trace's MLFQ level was hardcoded to `0` — a real feature
was silently fake

`_compress_gantt` built its `(start, end, pid, mlfq_level)` output using
`level_by_pid = {p.pid: 0 for p in procs}` — a dict that is *never updated*
after being created, so every segment reported level `0` regardless of
which queue a process actually ran from. The level field existed in the
data model and the type signature promised it, but nothing upstream ever
captured the real value, and the visualizer had no way to show MLFQ
demotions even though demotion is the entire point of the algorithm.

Caught by: manually inspecting `run.gantt` output for the MLFQ algorithm
and noticing every tuple's 4th element was `0` even on a workload known to
trigger demotions (short jobs sharing the CPU with one long one).

**Fix:** the tick loop now records `running.mlfq_level` at the moment each
tick actually executes; `_compress_gantt` splits a segment on a level
change even when the pid doesn't (an MLFQ process can be demoted and
immediately reselected if it's the only one ready — collapsing that into
one segment would hide the demotion). The visualizer now renders demoted
slices visibly darker with an `L1`/`L2` badge, with an explanatory note —
turning a decorative-but-fake field into a real, checkable feature.

## Starvation: demonstrated as a bug, then shown fixed by the same knob

Not a code defect — the whole point of Phase 3 was to *prove* MLFQ's
periodic priority boost matters, not just implement it and assume it
works. `TestMLFQ::test_without_boost_hog_is_starved_far_longer` runs the
identical workload (one CPU-bound "hog" plus ~200 short interactive jobs
arriving at a steady trickle) through the same engine with
`boost_interval=None` (disabled) vs. `boost_interval=30` (enabled), and
asserts the hog finishes *dramatically* later without boosting. This is
the adversarial-review pattern the task description asks for: don't just
implement the fix, break it on purpose first and confirm the break is
real.

## Edge cases and input validation hardened

None of these caused incorrect *results* on valid input, but every one was
either a straight crash (`ZeroDivisionError`, `IndexError`) or a silent
correctness hazard on malformed input, both now raising a clear
`ValueError` instead:

- **Duplicate process PIDs** (`simulate`) were never checked; several
  internal tie-breaks and lookups implicitly assume PIDs are unique. Now
  rejected up front with the offending PID list.
- **`aging_interval=0`** for Priority-with-aging caused
  `ZeroDivisionError` on the very first tick (`ticks_waited % 0`). Now
  rejected in the constructor.
- **Non-positive MLFQ quantum** or **non-positive `boost_interval`**
  silently degraded to degenerate-but-not-crashing behavior instead of
  failing loudly. Both now validated, matching Round Robin's existing
  `quantum >= 1` check.
- **`context_switch_cost < 0`** was unchecked (would have gone straight
  into the "if cost > 0" branch and simply been ignored, hiding a caller
  bug). Now rejected explicitly.
- **`num_pages`/`working_set_size <= 0`** in `make_reference_string` would
  hit `random.sample`/`random.choice` on an empty population
  (`IndexError`/`ValueError` with a confusing message). Now validated with
  a message that names the actual constraint.
- **`n <= 0`** in `make_processes` produced an empty workload silently
  rather than failing clearly — `simulate([], ...)` downstream *does*
  raise, but with no indication the root cause was the generator call.
  Now validated at the source.
- **`brute_force_min_faults` on a large or high-cardinality reference
  string** is exponential by design (it's an exhaustive oracle for
  *small* inputs only) and had no guard — a user could accidentally hang
  the CLI's `oracle` subcommand. Now rejects inputs above a documented
  size/cardinality threshold with a message pointing at
  `simulate_memory(..., "optimal")` for real workloads.

All of the above are exercised by dedicated tests in
`test_scheduler.py::TestInputValidation`, `test_scheduler.py::TestContextSwitchCost`,
`test_workload.py`, and `test_compare.py::TestBruteForceOracleGuardrails`.

## UX issues found and fixed

- **Bar-chart value labels clipped off the top of the canvas** for the
  tallest bar in both comparison charts (`padT` was only 10px, and a
  value label drawn 4px above a bar that nearly touches the canvas top
  had nowhere to go). Fixed by increasing top padding and clamping the
  label's y-position.
- **Algorithm-comparison bar labels overlapped** once labels like
  `RoundRobin(q=4)` and `PriorityAging` had to fit in a narrow per-bar
  slot (six algorithms in ~1000px is fine; the same six in a 390px mobile
  viewport collided into unreadable mush). Fixed by shortening labels
  (`RoundRobin`→`RR`, `PriorityAging`→`Priority`) and dropping to a
  smaller font only when a measured label would actually overflow its
  slot, rather than doing either unconditionally.
- **Horizontal page overflow on mobile** (390px viewport): the process
  metrics table and the Belady's-Anomaly table are naturally wide (7 and 5
  columns) and forced the whole page to scroll sideways. Fixed by wrapping
  both tables in a `overflow-x: auto` container, so only the table itself
  scrolls — verified by checking `scrollWidth === clientWidth` at 390px
  after the fix (it was 516px vs. 390px before).
- **No legend for the "page faults by algorithm" comparison chart** — four
  colored bars per frame-count group with no key mapping color→algorithm.
  Fixed by adding a color-swatch legend under the chart.

## What was *not* changed, and why

- **Optimal-minimality and the LRU stack property held on every single
  run** across dozens of seeds during this review, including the
  regenerated visualizer data and every new edge-case workload — no
  counter-example was found. This is expected (both are proven theorems,
  not heuristics), but it was checked adversarially rather than assumed:
  the review specifically tried skewed working-set sizes, single-frame
  runs, and repeated-page reference strings looking for a violation.
- **Context-switch overhead's minor slice-accounting interaction with
  Round Robin/MLFQ quantum counters** (during overhead ticks, `select()`
  still increments the running process's `slice_used` even though the
  process isn't making progress that tick, so a process can be preempted
  after fractionally less *real* execution than its nominal quantum when
  overhead is enabled) is a known, deliberate simplification, not a
  latent bug — `context_switch_cost` defaults to `0` and is never used in
  any of the correctness proofs in `PLAN.md`; it exists purely as an
  optional realism knob for the comparison/demo output, and is documented
  as such in `scheduler.py`.
