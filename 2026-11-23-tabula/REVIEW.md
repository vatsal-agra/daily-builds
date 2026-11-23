# REVIEW — adversarial pass on Tabula (phase 3)

I attacked the Phase-2 build as a hostile reviewer: stress instances, malformed input, determinism,
cross-checking the incremental cost against the independent verifier, and the UI at phone width / dark mode.
Every item below was **reproduced first, then fixed**; the "Re-test" column is what I ran afterwards.

| # | Severity | Finding (how it was found) | Fix | Re-test |
|---|----------|----------------------------|-----|---------|
| 1 | **Critical** | Tight but *guaranteed-feasible* instances (generator, load 0.85–0.95, 10 groups/6 rooms) made the backtracking constructor give up after the full 20 s budget ("no feasible timetable"). Plain MRV + random restarts thrashes on bottlenecks. | (a) Variable ordering is now **dom/wdeg** (domain ÷ accumulated dead-end count, persisted across restarts). (b) New second engine `repair.go`: **min-conflicts + tabu search** over infeasible timetables that drives hard violations to 0; used when backtracking exhausts a short (≤1 s) budget. | seeds 9,10 × loads .85/.9/.95 all solve (≤ 7 s, mostly 2 s); 25-instance mixed sweep clean |
| 2 | High | A failed solve said only "no feasible timetable found within the time budget" plus event names — useless to a user. | `Repair` reports the residual clashes ("teacher T3 double-booked on Tue period 4…") and hardest sessions in the error. | read the error on a forced failure |
| 3 | High | Slot arrays were silently mis-parsed: `[0,1,5]` truncated to `[0,1]`, `[1]` zero-filled to `[1,0]` — a typo changed the problem with no warning. | `Slot.UnmarshalJSON` demands exactly two integers. | `tabula check bad1.json` → clear error |
| 4 | High | **Re-solve semantic bug**: if the previous timetable used a room that no longer exists, the solver dropped the placement (no stability credit for keeping the time slot) while the verifier counted it as moved — solver cost ≠ verifier cost. | Previous placements keep their time slot with room = "gone"; stability then compares slot only. Solver, verifier, `CountMoved`, constructor hint agree. | resolve demo: removing a used room + blocking 2 sessions moves 2/33 sessions (fresh solve moves 28/33), verifier cost = solver cost |
| 5 | Medium | Diagnostics printed one line **per session** (a 4-session lesson with no room gave 4 identical lines). | De-duplicated by message. | `check examples/impossible.json` |
| 6 | Medium | Hand-written example `examples/school.json` was itself impossible (a 54-student science class, 30-seat lab). The diagnostics caught it — which is a good sign — but the example had to be fixed. | Enlarged lab/hall, added a 60-seat classroom; the impossible example is kept deliberately as `examples/impossible.json`. | both examples behave as intended |
| 7 | Medium | Viewer: horizontal page overflow of 300 px on a 390 px phone (grid min-width escaped its scroller). | `minmax(0,1fr)` track + `min-width:0` on cards. | Playwright at 390 px: overflow 0, no page errors |
| 8 | Medium | Viewer embedded data with only `</` escaped; `<!--` inside a lesson name could still derail the script block (HTML script-data double-escape state). | All `<` in the embedded JSON become `<`. | test with `</script><!--` lesson name (in the test-suite) |
| 9 | Low | `.ics` lines were never folded (RFC 5545 caps lines at 75 octets); long subjects/groups would be rejected by strict clients. | Folding that never splits a UTF-8 sequence. | unit test parses folded output back |
| 10 | Low | No way to give the feasibility search more than 20 s from the CLI. | `-construct` flag. | flag works |
| 11 | Low | Dead code (`SortedCats`, discarded variables) and two `_ =` hacks. | Removed. | `go vet` clean |

## Things I attacked that held up (no change needed)
* Empty problem (no groups/lessons) → solves, renders, writes 0 calendars.
* Unknown JSON field, truncated JSON, missing file, missing/extra positional args → one-line errors, non-zero exit.
* Two fixed sessions of one lesson on the same day → caught by the diagnostics (one-session-per-day rule).
* Determinism: `-iters N` with the same seed produces byte-identical JSON (`cmp`).
* Incremental annealing cost vs. the independent verifier's from-scratch cost: equal on every instance of the sweep (the CLI aborts if they ever differ).

## Known limits (documented, not hidden)
* One session of a lesson per day is a **hard** rule (it matches nearly all real timetables but is a modelling choice).
* A lesson has exactly one teacher; team teaching is modelled by two lessons at fixed identical slots.
* Time-limited annealing is not bit-reproducible (only `-iters` mode is).

**Gate:** after the fixes a fresh run-through of every item above reproduces none of them.
