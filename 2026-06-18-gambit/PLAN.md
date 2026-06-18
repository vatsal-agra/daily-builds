# Gambit — PLAN

## Concept
**Gambit** is a complete chess engine written from scratch in pure Python 3 (stdlib
only), plus the surrounding product: a legal move generator verified against
published **perft** node counts, an alpha-beta search with quiescence and a
transposition table, a positional evaluator, full SAN/FEN/PGN I/O, a terminal
UI to play against the engine, and a **server-backed browser board** where you
play the *real* Python engine (no duplicated JS brain) through a stdlib HTTP
server — plus a static, self-contained HTML game viewer with an eval graph.

## Why it's interesting
Chess is the canonical search + domain-modelling problem, and its correctness is
*objectively checkable*: the number of leaf nodes in the move tree (perft) is a
published, exact integer for standard positions. A single illegal or missing
move — a botched en-passant pin, a castling-through-check bug — changes the count
and is caught immediately. That makes a chess engine a rare combination of "rich,
open-ended AI" and "has a gold-standard oracle", which fits a build that must
*prove* it works rather than merely look like it does. It is also a completely
different domain from the recent ledger (SAT solvers, DB, regex, physics, autodiff).

## Architecture
```
gambit/
  board.py      0x88 board, piece encoding, FEN in/out, make/unmake, Zobrist keys
  movegen.py    pseudo-legal + fully-legal move generation, attack/check detection
  san.py        Standard Algebraic Notation parse + format; FEN; minimal PGN
  eval.py       material + piece-square tables + tapered eval + mobility/king terms
  search.py     negamax alpha-beta, iterative deepening, quiescence, MVV-LVA,
                killer moves, transposition table (Zobrist), time/depth limits
  perft.py      perft, perft-divide, bulk-counting verification harness
  engine.py     high-level API: best_move(), analyse(), play a full annotated game
  viz.py        emit a self-contained HTML game viewer (board + eval graph + PV)
  server.py     stdlib http.server: serve board UI + /api/move against real engine
  cli.py        subcommands: perft, play, selfplay, analyse, viz, serve, demo
tests/          unit + perft oracle + SAN round-trip + search-sanity suite
demo.sh         exercises every feature end-to-end
```

## Features

### Required
1. **Legal move generation** — every rule: sliding/leaper moves, castling (with
   the through-check and rights rules), en passant (incl. the discovered-check
   edge case), promotions, pins, checks. Verified by **perft** against published
   node counts for the start position *and* the standard test positions
   (Kiwipete, Position 3/4/5) to depth where counts are known-exact.
2. **Alpha-beta search** — negamax with iterative deepening, alpha-beta pruning,
   **quiescence search** (captures/promotions to avoid the horizon effect), and
   move ordering (TT move, MVV-LVA captures, killer moves). Returns best move +
   principal variation + score, under a depth or time budget.
3. **Position evaluation** — tapered material + piece-square tables interpolated
   between middlegame and endgame, plus mobility, doubled/isolated/passed pawns,
   bishop pair, and king safety/shelter terms. Symmetric (eval(pos) == -eval(mirror)).
4. **SAN / FEN / PGN I/O** — parse and emit FEN; parse and emit SAN (with
   disambiguation, check `+`, mate `#`, castling, promotion); read/write a minimal
   PGN of a played game. Round-trips losslessly.

### Stretch
5. **Transposition table with Zobrist hashing** — incremental zobrist key updated
   in make/unmake, TT with depth-preferred replacement and exact/lower/upper
   bound flags, measurably cutting nodes searched.
6. **Interactive browser board** — a stdlib HTTP server serves a good-looking
   single-file board; you play against the *real* engine (legal-move hints,
   highlights, eval bar, engine PV) with zero engine logic duplicated in JS.
7. **Static HTML game viewer** — `viz` emits a self-contained file animating a
   full engine-vs-engine game move-by-move with an eval graph, SAN movelist,
   captured-material tray, and keyboard scrubbing — opens with no server.

## Verification strategy
- **perft oracle**: exact published counts for 5 standard positions — any move-gen
  bug shifts a count and fails the test. This is the primary correctness gate.
- **SAN round-trip**: generate legal moves, format to SAN, parse back, assert the
  same move; over many random positions.
- **make/unmake invariants**: board + zobrist + FEN identical after make→unmake on
  every legal move of many positions (fuzzed).
- **eval symmetry**: mirrored position evaluates to the negation.
- **search sanity**: finds forced mates (mate-in-1/2/3) and the only-legal move;
  TT on vs off returns the same best score with fewer nodes.
- **demo.sh**: runs every subcommand green.

## Definition of done
All 6 gates pass, 4 required + ≥1 stretch (targeting all 3) shipped, adversarial
review findings fixed, demo + tests green, README written, LEDGER appended.
