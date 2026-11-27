# Fathom

**Minesweeper with exact odds.** A from-scratch Minesweeper engine whose centrepiece is an *exact* probabilistic
solver: for any position it computes the true probability that every hidden cell is a mine — counted over every
consistent mine placement, including the global mine total — then uses it to power a no-guess board generator, a
live probability heat-map, a luck analyzer ("was that bad luck or a bad move?") and a solver benchmark.

Zero dependencies. Node ≥ 22 (ES modules) for the engine/CLI; any modern browser for the UI.

![status](https://img.shields.io/badge/tests-35%20unit%20%2B%2018%20e2e-brightgreen)

## Run it

```bash
cd 2026-11-27-fathom
node serve.js            # → http://localhost:8080/   (the web app)
node build.js            # → dist/fathom.html         (one self-contained file; just double-click it)
npm test                 # 35 unit/integration tests
bash test/demo.sh        # runs every feature end-to-end (+ browser e2e if Playwright is installed)
```

CLI (`node src/cli.js …`):

| command | what it does |
|---|---|
| `bench --level expert --games 100 [--no-guess] [--seed s]` | solver self-play win-rate / guesses per game |
| `solve board.txt --mines N` | exact odds for an ASCII board (`#`/`F` hidden, `.` zero, `1–8`); lists certain safe cells/mines, best guess, layout count. Use `-` for stdin |
| `generate --level expert --seed s [--first x,y] [--no-guess] [--json]` | reveal-all layout; `--no-guess` is solver-verified |
| `play --level beginner [--seed s]` | terminal game: `r x y`, `f x y`, `hint`, `odds`, `step`, `q`; ends with a luck report |

Web shortcuts: `H` hint · `S` step · `P` heat-map · `F` flag under cursor · `Space` reveal · `N` new game. Links like
`#d=expert&seed=abc&ng=1` reproduce a board; pasting one into an open tab starts that game.

## Features

1. **Game engine** – first-click-safe seeded layouts (clicked cell + neighbours are mine-free when the board has room), flood reveal that respects flags, chording, flags, win/loss, strict validation. Pure function of `(size, mines, seed, first click)`.
2. **Exact probability solver** – frontier/interior split → independent components → backtracking enumeration with constraint pruning → BigInt convolution of per-component mine-count distributions → binomial weighting of the unconstrained region. A probability is exactly 0/1 iff the cell is *certain*. Verified against brute-force enumeration on 150 random positions. Components too big for the node budget are *relaxed* (sound certain-deductions preserved, odds flagged approximate).
3. **No-guess generator** – rejection sampling with solver self-play: a board is only accepted if certain deductions alone clear it from the first click. Expert boards take ~1–10 candidates (tens of ms); a time budget guards dense setups and the UI says when it falls back.
4. **Web UI** – dark, responsive; probability heat-map with per-cell percentages, certain-safe ✓ / certain-mine ! markers, inspector (odds, frontier/interior/components, number of consistent layouts), Hint / Step / Auto, flag-sure-mines, touch flag mode and long-press, keyboard play, shareable seeds, custom boards.
5. **Luck analyzer** *(stretch)* – every reveal is scored with its exact mine risk at click time (chords are scored one cell at a time). End-of-game report: risks taken, P(surviving them all), risk-while-a-sure-move-existed, worse-than-best guesses, and a verdict (*Pure logic / Lucky / Unlucky / Forced gamble / Avoidable*).
6. **Benchmark** *(stretch)* – deterministic self-play. Sanity check against the literature: beginner ≈ 98 %, intermediate ≈ 82–86 %, expert ≈ 45 % win with the solver's lowest-risk guessing; every no-guess board: 100 %, 0 guesses.
7. **Standalone bundle** *(stretch)* – `build.js` inlines modules + CSS into one 51 KB HTML file.
8. **Terminal client & ASCII solver** *(stretch)* – see CLI table above.

## How it was verified

- `test/solver.test.js` – brute-force oracle, certainty soundness on real layouts, global-count certainty, inconsistent boards, truncated-budget soundness.
- `test/engine.test.js` – flood/flags/chord/win/loss rules, determinism, validation, generator guarantee, "ordinary boards really do need guesses".
- `test/features.test.js` – analyzer, benchmark, CLI (incl. exit codes and a scripted play session), bundler, static server (path traversal).
- `test/ui.e2e.cjs` – 18 browser checks (Playwright). Mutation-checked: deliberately broken solver/chord logic makes the suite fail.
- `REVIEW.md` – the adversarial review (12 findings, one critical, all fixed).

## Why I built it today

None of the earlier builds in this repo touched Minesweeper, and it hides a surprisingly rich inference problem:
a game everyone has played turns out to be a clean exercise in exact counting under constraints. I wanted something
where the "AI" is not a heuristic but a provably correct computation I could check against brute force — and where a
single number (the true mine probability) makes the game more fun to play, to analyze and to generate.

## Where a human could take this next

- **Smarter guessing:** replace "lowest risk, tie-break by zero-chance" with one-ply lookahead over *expected information* (or full minimax over the frontier) — published optimal expert win rates are a few points above this solver.
- **Better enumeration:** dynamic programming over a frontier profile (as in transfer-matrix methods) would remove the node budget on dense boards instead of relaxing.
- **Difficulty-rated puzzles:** grade generated boards by the deduction depth required (pairs/subset rules → global count → chains) and publish daily seeds.
- **Multiplayer / race mode:** same seed, shared first click; leaderboard on time and luck score.
- **Variants:** hex/triangular grids, wrap-around boards, or "knight-move" adjacency are small changes to `neighborTable` and the solver would still be exact.
- **Packaging:** PWA manifest + service worker for offline play; a WASM build of the solver for much larger boards.
