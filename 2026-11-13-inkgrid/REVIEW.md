# Adversarial review

Hostile pass over Phase 2. Each item was reproduced, then fixed; `test/run.js` / `test/ui.js`
carry a regression for each.

| # | Issue found | Severity | Fix |
|---|-------------|----------|-----|
| 1 | JSON import rejected `[0]` as an empty-line clue (the most common convention in other tools) | bug | `parsePuzzle` strips zeros from JSON clues |
| 2 | `solve()` truncated by the node budget could still return `count===1`, so a puzzle was *claimed* unique without proof (UI and `rate`) | correctness | `exhaustive`/`truncated` propagate; UI says "uniqueness unproven"; `rate` never reports unique when truncated |
| 3 | Rating a 60×60 pasted puzzle runs O(cells²) probing and freezes the tab | perf | boards over 1600 cells are labelled "unrated" in the UI (CLI `rate` forces it) |
| 4 | After winning, the "tidy" crosses were not in the undo entry, so Undo left stray ✕ marks | bug | tidy crosses are recorded in the winning stroke's history entry |
| 5 | Hint built deductions on top of wrong marks, giving misleading explanations | UX | with a known unique solution, Hint first reports wrong marks (red) instead |
| 6 | On narrow screens CSS shrank the canvas width but the inline height stayed fixed, so the board was **stretched** and pointer→cell mapping was off on both axes (found by the 360px UI test: clicks hit nothing) | bug | `height:auto`, smaller minimum cell size, pointer coords scaled independently per axis |
| 10 | A malformed share hash (`#p=@@@`) silently fell through to a random puzzle | UX | hash parsing accepts any token and reports "corrupt share link" |
| 7 | "Brutal (needs guessing)" difficulty could never be generated. Measured over >2,000 random noise/blob pictures from 8×8 to 20×20, **zero** unique puzzles survived one-level probing without needing guesses | infeasible feature | Replaced by making *Expert* (needs contradiction probing) the top generatable tier, removed Brutal from the UI. The engine still classifies tier 2 for imported puzzles. Generator additionally mixes in pure-noise pictures (every 3rd attempt) so Expert is reachable more often |
| 8 | Generator wrote `NaN`-ish sizes silently when fields were blank | UX | engine validates 2–40 range and the UI shows the error message |
| 9 | Auto-cross could mark cells on a line that "matches" its clue but contains a wrong cell | by design | noted: Check/Hint report the wrong cells; Undo reverts the whole stroke incl. auto-crosses |

Lazy shortcuts looked for and not found: no hard-coded puzzles, hint text is derived from real
line state, the solver visualiser replays real propagation traces, the rating comes from running
the solver. One honest limit: the search stage of `solve` is plain DFS with a most-constrained-cell
heuristic, fine for ≤40×40 pictures but not a competitive SAT-grade solver.
