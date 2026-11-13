# Inkgrid — nonogram studio

A complete nonogram (Picross) toolkit: a dependency-free solver engine, a generator that
**proves every puzzle has exactly one solution and measures its difficulty**, a polished
playable web app with hints that *explain themselves*, and a CLI.

## Run it
- **Web app:** open `index.html` in any modern browser (works from `file://`, no build, no server).
- **CLI:** `node cli.js gen 15x15 --seed 7 --difficulty hard --format ascii`
  `node cli.js gen 12x12 > p.non && node cli.js solve p.non && node cli.js rate p.non && node cli.js hint p.non`
- **Tests:** `./verify.sh` (26 engine checks + 32 headless-browser checks; needs Node 18+, Playwright optional).

Controls: click/drag to fill (drags lock to a row or column), right-click or `Shift` to cross,
`X` toggles tool, `H` hint, `Ctrl+Z` / `Ctrl+Y` undo/redo.

## Features
1. **Line solver** — O(n·k) dynamic program that returns every cell forced by a clue and a partial line, or a contradiction. Verified against brute-force enumeration on thousands of random cases.
2. **Full solver** — propagation to fixpoint, then most-constrained-cell backtracking; counts solutions to prove uniqueness and honestly reports when the search budget ran out.
3. **Difficulty rating** — tier 0 (line logic: easy/medium/hard by propagation rounds), tier 1 (needs one-level contradiction probing: *expert*), tier 2 (needs deeper search); score derived from real solver work.
4. **Generator** — seeded blob/noise pictures at a chosen size and density; ambiguity is repaired by flipping a cell where two solutions differ, until the solution is unique and meets the requested difficulty. Reproducible by seed.
5. **Playable UI** — canvas board, drag painting, live clue dimming, auto-cross of finished lines, mistake check, undo/redo, timer, win detection, light/dark theme, mobile layout.
6. **Explaining hints** — finds a deduction from *your* current state and says why ("Row 6 [11]: the blocks can only slide 4 cells…"); falls back to contradiction-probing hints; refuses to hint on top of mistakes.
7. **Solver visualiser** — watch the real propagation trace step by step (speed control, step, replay), ending with the search stage if logic stalls.
8. **Import / export / share** — `.non` and JSON (incl. `[0]` empty clues), clipboard share link (clues in the URL hash), `.non` download.
9. **Image → puzzle** — Otsu-thresholded downsample, then uniqueness repair; tells you how many pixels were altered.
10. **CLI** — `gen`, `solve`, `rate`, `hint`, clean errors and exit codes.

## Why this today
The ledger is full of compilers, protocols, and graphics; none touched constraint-puzzle
generation with *measured* difficulty. Nonograms look trivial but force real design decisions
(what counts as "logically solvable", how to generate pictures that stay unique), and the finished
thing is something a person can actually sit down and play.

## Honest limits
- "Brutal" (unique, needs deep guessing) puzzles could not be generated: over 2,000 sampled grids none survived one-level probing without being solved by it. See REVIEW.md #7. The engine still classifies such puzzles when imported.
- Search is plain DFS; fine to 40×40 pictures, not a SAT-grade solver. Very large pasted puzzles skip rating.
- Colour nonograms are not supported.

## Where a human could take this next
- Colour / multi-hue nonograms (clue blocks with colour, generalised line DP).
- A daily-puzzle server with seeds-of-the-day, shared leaderboards, and Elo-ish ratings from real solve times.
- Mosaic-style generators from silhouettes with symmetry constraints; a puzzle-pack exporter (PDF print layouts).
- Stronger deduction levels (e.g. 2-line "glue" and mercury reasoning) for finer-grained difficulty and richer hints.
- Persist progress/stats in localStorage; touch gestures such as long-press to cross.

Files: `src/engine.js` (engine) · `app.js`, `index.html`, `style.css` (UI) · `cli.js` · `test/` · `PLAN.md` · `REVIEW.md`.
