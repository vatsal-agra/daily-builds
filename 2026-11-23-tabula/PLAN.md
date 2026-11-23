# Tabula — PLAN

## Concept
A from-scratch **school/university timetabling solver**. Give it a JSON problem (teachers, rooms,
student groups, weekly lessons, availability, preferences) and it produces a complete weekly
timetable with **zero hard-constraint violations** and a **minimised, itemised soft-constraint cost**,
then renders it as a self-contained HTML viewer (per group / teacher / room) and iCalendar files.

## Why it's interesting
Timetabling is a classic NP-hard problem (it is what real schools and universities struggle with every
term) and nothing in this repo touches scheduling-with-resources. It needs two different algorithmic
halves working together: an exact-style **constraint search** to find *any* feasible schedule, and a
**local-search metaheuristic** (simulated annealing with incremental delta-evaluation) to polish it —
while never leaving the feasible region. Plus a human-facing part: when no schedule exists, explain *why*.

## Architecture
```
problem.json ──► model.Load/Validate ──► Diagnose (pre-flight infeasibility proofs)
                                   └──► Construct (MRV backtracking + forward checking, restarts)
                                              └──► Anneal (move/swap neighbourhood, bitmask occupancy,
                                                           incremental cost deltas)
                                                      └──► Verify (independent re-check from scratch)
                                                      └──► JSON / HTML viewer / ICS
```
Packages: `tabula/` (model, diagnose, construct, anneal, cost, verify, render, gen), `cmd/tabula` (CLI).
Pure Go stdlib. Deterministic given `--seed`.

## Feature list
| # | Feature | Status |
|---|---------|--------|
| 1 | Problem model: teachers (unavailable slots, max/day), rooms (capacity, kind), groups (size), lessons (n sessions/week, duration 1–3 periods, multi-group, room kind, fixed slot), breaks that sessions can't span; strict validation with precise error messages | **required** |
| 2 | Constructive solver: MRV backtracking + forward checking + randomised restarts producing a hard-feasible timetable | **required** |
| 3 | Annealing optimiser: move + swap neighbourhood, incremental cost, itemised soft costs (gaps, long days, late periods, teacher days-present, same-lesson spacing, avoid-slots, room waste) | **required** |
| 4 | Pre-flight infeasibility diagnostics: explains *why* a problem is unsolvable (teacher overload, group overload, no room fits, empty domains) before/after search | **required** |
| 5 | Self-contained HTML viewer: per-group / teacher / room grids, subject colours, light+dark, cost breakdown | stretch |
| 6 | Independent verifier + cost recomputation from scratch (`verify`) | stretch |
| 7 | Seeded random instance generator with a planted solution (guaranteed feasible) for benchmarks | stretch |
| 8 | Minimal-disruption re-solve: change the problem (teacher falls ill), keep as much of the previous timetable as possible | stretch |
| 9 | iCalendar (.ics) export per group / teacher | stretch |

Targets: all 4 required + as many stretch as fit (aim: all).
