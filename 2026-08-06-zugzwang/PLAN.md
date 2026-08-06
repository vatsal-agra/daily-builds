# Zugzwang — a chess engine from scratch

## Concept

A complete chess engine written in pure Python, from board representation up
through a playable interface — no `python-chess`, no external chess library
of any kind. Every rule (castling, en passant, promotion, check/pin/mate
detection) is implemented by hand, every move the engine considers is scored
by a hand-written evaluation function, and every search is a hand-written
alpha-beta tree walk.

## Why this is interesting

Chess engines sit at the intersection of a few genuinely hard, well-studied
problems that are each satisfying to get *exactly* right:

- **Move generation is a correctness minefield.** Pins, discovered checks,
  en passant capture of a pawn that isn't on the target square, castling
  through check, promotion underpromotion — a huge fraction of hobby chess
  engines silently generate illegal moves in some corner case. The standard
  way to *prove* a move generator correct is **perft** (performance test):
  count leaf nodes of the full game tree to depth N and compare against
  published reference values. Perft either matches exactly or it doesn't —
  no partial credit, no "basically works." That's a great forcing function
  for Phase 5 verification.
- **Search is a real algorithms exercise**: minimax collapses combinatorially
  without alpha-beta pruning, alpha-beta needs good move ordering to prune
  well, and a naive fixed-depth search has the classic "horizon effect"
  (stopping mid-capture-sequence and misjudging the position) which
  quiescence search fixes.
- **It's end-to-end verifiable by actually playing it.** Unlike a lot of
  systems-y daily builds, "does this work" has an extremely legible test:
  play a game and see if the engine makes legal, sane, improving moves.

## Architecture

```
zugzwang/
  board.py     Board state: 8x8 array, side to move, castling rights,
               en-passant target, halfmove/fullmove counters, FEN
               import/export, make_move/unmake_move with full undo info.
  movegen.py   Pseudo-legal move generation per piece type, attack-square
               computation, legal-move filtering (simulate + check-detection),
               check/checkmate/stalemate/draw detection.
  zobrist.py   Zobrist hashing (random 64-bit keys per piece/square/castling/
               ep/side) for transposition-table keys and repetition detection.
  evaluate.py  Static evaluation: material, piece-square tables (separate
               midgame/endgame tables, tapered by game phase), mobility,
               king safety (pawn shield), pawn structure (doubled/isolated/
               passed).
  search.py    Iterative-deepening alpha-beta with quiescence search at
               leaf nodes, a transposition table, move ordering (TT move,
               MVV-LVA captures, killer moves, history heuristic), and a
               time budget so search is cooperative for a live UI.
  pgn.py       SAN move notation generation + PGN export, and a PGN replay
               reader for the "replay a game" stretch feature.
  book.py      A small curated opening book (SAN lines) so the engine
               doesn't burn search time reinventing known openings.
  perft.py     Standalone perft node-counter used both as a library
               function and as the Phase 5 correctness harness.
  cli.py       Terminal game loop: human vs engine, engine vs engine,
               ASCII board rendering, algebraic move input.
  server.py    Zero-dependency stdlib http.server exposing a small JSON API
               (new game, legal moves for a square, make a move, engine
               move, position state) that the web UI talks to.
web/
  index.html   Self-contained interactive chessboard (HTML/CSS/JS, no CDN)
               — click-to-move, legal-move highlighting, captured-piece
               tray, move list in SAN, game-over banner. Talks to
               server.py's local JSON API; no chess logic is duplicated
               in JS — the server (i.e. the real engine) is the single
               source of truth for legality and evaluation.
tests/
  test_perft.py, test_movegen.py, test_search.py, test_pgn.py, test_eval.py
demo.sh        Runs perft verification, an engine-vs-engine game, and a
               PGN export, printing everything so the whole pipeline is
               visibly exercised without a human at a board.
```

## Feature list

### Required (core, must work end-to-end)

1. **Full legal move generation for every rule in chess** — normal moves,
   captures, castling (both sides, with all legality conditions including
   "not castling through/out of check"), en passant, promotion (with
   underpromotion choices), check detection, pin detection, checkmate and
   stalemate detection, and the draw rules that are cheap to get right
   (fifty-move rule, threefold repetition, insufficient material).
   **Proof of correctness: perft node counts matching published reference
   values** for the standard start position and at least one tricky
   "Kiwipete"-style test position through several plies.

2. **Alpha-beta search engine** — minimax with alpha-beta pruning, iterative
   deepening (so the engine always has a best move ready within its time
   budget), quiescence search on captures at leaf nodes to avoid the horizon
   effect, and a time-budgeted `choose_move(board, seconds)` entry point.

3. **Position evaluation function** — material with standard piece values,
   tapered midgame/endgame piece-square tables, mobility, and basic king
   safety/pawn-structure terms, combined into a single centipawn score used
   to drive the search.

4. **Playable end-to-end interface** — a terminal CLI (`play` command) where
   a human plays full legal games against the engine with algebraic input,
   AND a local web UI (`serve` command) with a clickable board backed by the
   real engine over a JSON API — not a static mockup.

### Stretch (2+, implement at least 1)

5. **Transposition table with Zobrist hashing** — caches search results
   keyed by position hash to prune re-exploration and speed up iterative
   deepening, plus threefold-repetition detection reusing the same hashes.
6. **PGN export and replay** — every played/engine-vs-engine game can be
   exported as standard PGN (correct SAN including check/mate suffixes,
   disambiguation), and the web UI can load a PGN and step through it.
7. **Curated opening book** — a small table of known strong opening lines
   the engine plays from instantly instead of searching, until the position
   leaves the book.

## Verification strategy (Phase 5 preview)

- `perft` against known reference counts is the ground truth for move
  generation — this is the standard technique used by real engine authors
  and it either passes exactly or it doesn't.
- Automated engine-vs-engine games as smoke tests that a full game reaches
  a legal terminal state (checkmate/stalemate/draw) without ever producing
  an illegal move.
- Unit tests for SAN/PGN generation, evaluation symmetry (flipping the board
  and colors should flip the score), and the opening book.
- `demo.sh` runs all of the above plus a short engine-vs-engine game printed
  move-by-move so the whole system is visibly exercised in one shot.
