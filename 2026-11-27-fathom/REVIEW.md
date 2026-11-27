# Phase 3 — Adversarial review

Method: stress the solver on adversarial boards (expert, 60×40/400, 31%-dense 30×16/150, sparse), fuzz it
against brute force, drive the UI with Playwright at desktop and phone sizes (flag/click races, invalid input,
new-game state), and read the code looking for shortcuts. Every finding below was reproduced, then fixed.

| # | Severity | Finding | Fix |
|---|----------|---------|-----|
| 1 | **CRITICAL** | When a frontier component blew the node budget it was silently *dropped* from the mine-count convolution. The mines it holds were unaccounted for, so on dense boards `Z` could reach 0 and `solve()` threw `InconsistentBoard` on a perfectly valid position (reproduced: 30×16/130 no-guess generation crashed). | Over-budget components are now **relaxed**: their constraints are dropped and their cells join the unconstrained pool. The real solution set is a subset of the relaxed one, so every certain-safe/certain-mine deduction stays sound (only probabilities for those cells go approximate, flagged `exact:false`). Test forces truncation with `maxNodes:300` and checks every certain cell against the true layout. |
| 2 | HIGH | Solver worst case 2.3 s per call at the 20M-node cap (dense boards); UI would freeze. | Default budget 5M nodes (worst ≈ 0.35–0.75 s on pathological 31 % density; real expert worst 16 ms). |
| 3 | HIGH | No-guess generation had no time bound: a dense custom board could spin through thousands of attempts and freeze the tab. | `timeBudgetMs` (3 s) on the generator; on failure the game falls back to a plain safe-first-click board and the UI **says so** (previously it would have silently handed out a guess-needing board labelled "no-guess"). |
| 4 | MEDIUM | Flood-fill opened *flagged* cells and decremented the flag counter — non-standard, and it destroyed player information. | Flood skips flagged cells; a wrongly flagged safe cell now also (correctly) blocks the win until removed. Test added. |
| 5 | MEDIUM | Timer kept the previous game's value after "New game". | Reset. Verified in browser. |
| 6 | MEDIUM | Expert board overflowed its card horizontally (cell size derived from window width, not container). | Size from container width; re-computed on resize. |
| 7 | MEDIUM | The "Custom…" size inputs were always visible — CSS `display` overrode the `hidden` attribute. | `[hidden]{display:none!important}`. |
| 8 | MEDIUM | Heat-map was visual noise: a 21 % cell rendered bright green, and every unconstrained cell carried a number. | Square-root colour ramp (hue shifts earlier), unconstrained cells desaturated and un-numbered (value lives in the inspector). |
| 9 | LOW | A 99.6 %-risk cell displayed "100" though only truly certain mines are 100 %. | Clamp to 99 unless certain. |
| 10 | LOW | Heat-map defaulted on, which spoils the puzzle (all ✓/! visible on move 1). | Default off (`P` toggles). |
| 11 | LOW | Board cells had no accessible names. | `aria-label` per cell (row/column/state). |
| 12 | LOW | Node 22 `node --test test/` treats the directory as a module. | `package.json` uses a glob. |

## Things checked that were NOT bugs
- Solver vs brute-force enumeration: 150 random positions agree on solution count and every cell probability (exact BigInt).
- Certain cells never wrong on real layouts (60 positions + all stress runs).
- Chording scores each revealed cell sequentially against the position it was actually taken in.

## Known limitations (documented, not hidden)
- Guess choice uses "lowest mine probability, tie-broken by approximate chance of opening a zero". That tie-break assumes neighbour independence, so it is a heuristic — not the optimal-information guess.
- Frontiers beyond the node budget (very dense custom boards) fall back to relaxed, approximate odds; the UI says so.

## Fresh run-through
After the fixes: full test-suite green, stress script (4 board families × 12 games) shows 0 crashes, Playwright adversarial run (390 px phone viewport) shows 0 page errors with all items above verified.
