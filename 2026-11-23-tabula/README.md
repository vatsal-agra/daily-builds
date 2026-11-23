# Tabula

A from-scratch **school/university timetabling solver** in Go (standard library only). Describe your
teachers, rooms, student groups and weekly lessons in JSON; Tabula builds a complete week with **zero
clashes**, then optimises how *pleasant* it is, and gives you an interactive HTML viewer, calendars
(`.ics`) and an independent verifier. If no timetable can exist it tells you **why**.

~3,600 lines of Go including tests, 0 dependencies.

## Quick start
```bash
cd 2026-11-23-tabula
go build -o tabula ./cmd/tabula

./tabula solve examples/school.json -o sol.json -html timetable.html -ics calendars/
open timetable.html                         # self-contained viewer, light/dark, per group/teacher/room
./tabula verify examples/school.json sol.json
./tabula check  examples/impossible.json    # explains exactly why it cannot be solved

./tabula gen -seed 7 -groups 20 -teachers 20 -rooms 12 -o big.json   # random, guaranteed-feasible instance
./tabula solve big.json -time 10s -html big.html

# a teacher falls ill: change the problem, keep as much of the old timetable as possible
./tabula resolve school-changed.json sol.json -o sol2.json
```
Run everything (CLI acceptance script + Go tests): `./demo.sh` → `demo: 32 passed, 0 failed`.

### Commands
| command | what it does |
|---|---|
| `gen` | seeded random problem, feasible by construction (a timetable is planted, constraints are derived from it) |
| `check problem.json` | validate + pre-flight proofs of impossibility |
| `solve problem.json` | diagnose → construct → anneal → verify → write `-o` JSON / `-html` / `-ics DIR`; `-seed`, `-time`, `-iters` (deterministic), `-construct` |
| `resolve problem.json prev.json` | like solve, but penalises moving anything that was already scheduled |
| `verify problem.json sol.json` | independent re-check of every hard constraint + from-scratch soft cost |
| `show problem.json sol.json` | text timetable per group |

## The problem model (JSON)
* `days`, `periods`, optional `breaks_after` (a double period may not straddle these), `period_starts` (for calendars)
* **teachers**: `unavailable` slots (hard), `avoid` slots (soft), `max_per_day` (hard)
* **rooms**: `capacity`, `kind` (`""` = ordinary classroom, `"lab"`, `"gym"`, …)
* **groups**: `size`
* **lessons**: `teacher`, `groups` (one or several taught together), `sessions` per week, `duration` in periods (double/triple lessons), `room_kind`, `fixed` (pin the first N sessions to given `[day, period]`)
* **weights**: every soft penalty is tunable

**Hard rules** (never violated): nobody is in two places; rooms are single-use, big enough and of the right kind; teachers are available and within `max_per_day`; sessions fit inside a day and don't straddle a break; pinned sessions stay put; the sessions of one lesson are on different days.
**Soft costs** (minimised, itemised in the output): empty periods in a group's / teacher's day, over-long days, late periods, number of days a teacher must attend, same-lesson sessions on adjacent days, teacher "avoid" slots, wasted room seats, and (re-solve only) instability.

## Features
1. **Strict problem model & validation** — every structural problem is reported at once, unknown JSON fields and malformed slots are rejected.
2. **Constructive solver** — MRV/dom-wdeg backtracking with forward checking and restarts, backed by a **min-conflicts tabu repair** engine that handles tight instances (load 0.9+) where backtracking thrashes.
3. **Annealing optimiser** — simulated annealing that never leaves the feasible region; moves, room changes, slot swaps and **Kempe chains**; bitmask occupancy and incremental delta costs (≈1.5 M steps/s).
4. **Impossibility diagnostics** — teacher/group overload, `max_per_day` overload, rooms that don't exist, Hall-style room pigeonholes, lessons with too few usable days, fixed-slot clashes — in plain English, before any search.
5. **HTML viewer** — one file, no network: per group / teacher / room grids, subject colours, double periods as tall cells, teacher unavailability hatching, cost bars, in-browser clash re-check, light/dark, phone-friendly, print-friendly.
6. **Independent verifier** — naive per-slot maps; recomputes the soft cost from the definitions and must agree with the optimiser's incremental number (the CLI aborts if not).
7. **Instance generator** — planted solution ⇒ always feasible; deterministic per seed.
8. **Minimal-disruption re-solve** — change the problem, keep the schedule stable (2 sessions moved vs 23–30 for a fresh solve in the demo).
9. **iCalendar export** — weekly-recurring `.ics` per group and per teacher (RFC 5545 folding/escaping).

## Numbers (this container, 5 s annealing)
| groups | sessions | cost after construction | after annealing |
|---|---|---|---|
| 6 | 123 | 921 | 208 |
| 10 | 205 | 1795 | 485 |
| 20 | 400 | 2868 | 1407 |
| 40 | 824 | 5936 | ~3100 |

Planted-feasible instances at 90–95 % load are solved in 2–7 s.

## Layout
```
cmd/tabula/        CLI
tabula/model.go    problem types, validation, event expansion
tabula/state.go    bitmask occupancy
tabula/cost.go     soft-cost terms (full + incremental)
tabula/diagnose.go impossibility proofs
tabula/construct.go backtracking   tabula/repair.go min-conflicts tabu
tabula/anneal.go   optimiser       tabula/verify.go independent checker
tabula/gen.go export.go viewer.html  generator, text/HTML/ICS output
examples/          school.json (hand-written), impossible.json, school.html (rendered sample)
PLAN.md REVIEW.md demo.sh
```

## Why I built it today
Nothing in this repo schedules scarce resources. Timetabling is NP-hard, real, and has a nice split personality: a *satisfiability* half (find anything legal) and an *optimisation* half (make it good) that want different algorithms, plus a human half (explain failure, stay stable when things change). It also let me do something I enjoy: a second, independent implementation (the verifier) that cross-checks the first — and the adversarial review found real bugs that way (a jammed neighbourhood, an ICS folding off-by-one, a re-solve cost mismatch).

## Limits worth knowing
* One session of a lesson per day is a hard rule; one teacher per lesson (model team-teaching as two pinned lessons).
* Timed annealing isn't bit-reproducible; `-iters N` is.
* Soft-cost weights trade off against each other: with the default `stability=8`, a re-solve may move a few more sessions than strictly forced if it saves more than 8 cost units each.

## Where a human could take this next
* A drag-and-drop editor in the viewer with live clash/cost feedback (the cost functions are already pure and portable).
* More constraint types: student electives (overlapping group membership), teacher room preferences, consecutive-day rules, per-week rotation (A/B weeks), travel time between buildings.
* Exam timetabling mode (graph-colouring-like, capacity-sum constraints), or multi-campus.
* Parallel annealing with replica exchange / adaptive operator selection; an exact CP-SAT/ILP back-end for proving optimality gaps on small instances.
* Import from common formats (XML from FET/UniTime, CSV), and a web service wrapper.
