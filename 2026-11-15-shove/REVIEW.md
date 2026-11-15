# REVIEW — adversarial pass (Phase 3)

Method: attacked the solver's *soundness* with an independent unpruned brute-force oracle, fed the CLI malformed/edge
inputs (CRLF, comment-only chunks, solved start, unsolvable, boxes on the edge, 0 boxes, bad flags, missing files),
stress-generated big levels, and drove the HTML game with a real browser.

## Findings

| # | Sev | Finding | Fix |
|---|-----|---------|-----|
| 1 | high | **Generator starvation:** rejecting every candidate that had *any* box on a goal meant a 10-box request rated only 1 of 30 candidates, so large levels were practically ungenerable and "hardest of N" was a lie. | Allow up to `boxes/4` pre-placed boxes; report `rated`/`skipped` counts in CLI output. |
| 2 | high | **0-push levels:** with `-boxes 1` a candidate could start already solved; `-min-pushes` defaulted to 0 so it would be returned as a "level". | Minimum is clamped to 1 push. |
| 3 | high | **Unbounded memory:** the solver stores every generated state; an unlucky hard level with no node cap would grow until OOM instead of failing cleanly. | `Options.MaxGenerated` (default 6M states, 4×node-budget in the generator) → `ErrBudget`. |
| 4 | med | **HTML: modifier keys hijacked** — Ctrl+R (reload), Ctrl+S, Cmd+A/D were swallowed because `r`/`s`/`a`/`d` are bound to the game. | Ignore key events with ctrl/meta/alt. |
| 5 | med | **HTML: watching the solution counted as solving** — after "Show solution" finished, the level was marked ✓ and the replayed solution saved as *your best*. | `peeked` flag: playback shows "Solution shown — press R", never records a score; reset on restart/level change. |
| 6 | low | **Pack parser name bug:** with two comment lines above a map, the *first* became the name; convention (and expectation) is the line directly above. | Last comment above the map wins. |
| 7 | low | CLI smell: `gen` mutated a `count` pointer to fake "one level"; `-count` was silently ignored by `gen`. | Replaced by a plain `n`; documented as pack-only. |
| 8 | info | **Freeze-deadlock soundness** is the classic place a Sokoban solver silently loses solutions (false "unsolvable"). | Added an independent brute-force oracle test (`sok/diff_test.go`): 250 random levels × {full, no-freeze, no-matching} all agree with the oracle on optimal push count — no unsoundness found. A heavier run (3–5 boxes, 250 levels) also agreed. |

## Known limitations (documented, not bugs)
* Optimality is in **pushes**; the walking `moves` count is not minimised (state keys use player *regions*).
* The solver is single-threaded A* without PI-corral / tunnel macros, so levels needing >~10⁶ expansions are out of reach.
* `Verify` accepts either letter case for any move (XSB convention: uppercase = push is informational).

## Fresh run-through (after fixes)
`go vet`, brute-force oracle test, edge-case CLI sweep (crlf/solved/unsolvable/malformed/OOB `-n`), 10-box generation
(12 rated vs 1 before), and a browser run (Ctrl+R ignored; solution playback leaves "your best" empty; a real solve
records `8p/33m` and "Perfect — push-optimal!") — none of the findings above reproduce.
