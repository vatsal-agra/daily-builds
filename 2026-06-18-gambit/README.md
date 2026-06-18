# Gambit ♛

A complete **chess engine written from scratch in pure Python 3** (standard library
only — no `python-chess`, no third-party anything). It generates fully-legal moves
(verified against published *perft* node counts), searches with alpha-beta +
quiescence + a transposition table, evaluates positions with a tapered
piece-square evaluation, speaks SAN/FEN/PGN, lets you **play it in your browser
against the real engine**, and renders self-contained HTML game viewers.

## What it is

Chess is the canonical "search + domain modelling" problem, and — unusually — its
correctness is *objectively checkable*. The number of leaf nodes in the move tree to
a fixed depth (**perft**) is a published, exact integer for standard positions, so a
single illegal or missing move (a botched en-passant pin, a castle through check)
changes the count and is caught instantly. Gambit leans on that: move generation is
verified to the node against five standard positions, and make/unmake + the
incremental Zobrist hash are fuzzed over tens of thousands of moves with zero drift.

## How to run

Everything is driven through one CLI (run from this folder):

```bash
# Verify move generation against published perft counts
python3 -m gambit.cli perft 5 --verify
python3 -m gambit.cli perft 4 --divide          # per-root-move breakdown

# Analyse a position (FEN); prints best move, score, depth, nodes, PV
python3 -m gambit.cli analyse --fen 'r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4'

# Engine vs engine — prints PGN, optionally writes JSON
python3 -m gambit.cli selfplay --depth 4 --pgn game.pgn

# Play the engine in your terminal (SAN input: e4, Nf3, O-O, exd5, e8=Q)
python3 -m gambit.cli play --color white --movetime 2

# Play the REAL engine in your browser (stdlib HTTP server, no JS engine)
python3 -m gambit.cli serve            # then open http://127.0.0.1:8000

# Play a game and emit a self-contained interactive HTML viewer
python3 -m gambit.cli viz --depth 4 --out game.html

# Full self-checking feature tour
python3 -m gambit.cli demo

# Tests + demo end to end
python3 -m unittest tests.test_gambit
./demo.sh
```

## Feature list

**Required (all shipped):**
1. **Legal move generation** — 0x88 board; sliders, leapers, castling (with the
   through-check / rights rules), en passant (incl. discovered-check), promotion,
   pins and checks. **Perft matches published counts exactly** on startpos, Kiwipete
   and positions 3/4/5.
2. **Alpha-beta search** — negamax with iterative deepening, alpha-beta pruning,
   **quiescence search** (captures/promotions + check evasions), move ordering
   (TT move → MVV-LVA captures → killer moves), under a depth or wall-clock budget.
3. **Position evaluation** — material + piece-square tables, **tapered** king safety
   between middlegame and endgame, bishop pair, doubled/isolated/**passed** pawns and
   a king pawn-shelter term. Provably colour-symmetric.
4. **SAN / FEN / PGN I/O** — FEN parse/emit with validation; SAN with full
   disambiguation and `+`/`#` suffixes; minimal PGN. Round-trips losslessly
   (0 collisions / 0 round-trip failures over 6,000 fuzzed positions).

**Stretch (all shipped):**
5. **Transposition table** — incremental 64-bit Zobrist key, depth-preferred
   replacement, exact/lower/upper bound flags; measurably fewer nodes at equal score.
6. **Interactive browser board** — a stdlib HTTP server serves a good-looking board;
   you play the *real Python engine* (legal-move dots, last-move highlight, engine
   PV/score) with **zero engine logic duplicated in JavaScript**.
7. **Static HTML game viewer** — `viz` emits a self-contained file animating a full
   game with an eval bar + eval graph, clickable SAN movelist, captured-material
   trays and keyboard scrubbing — opens with no server.

## Verification

- **Perft oracle** — exact published counts on 5 standard positions.
- **27k-move fuzz** — make/unmake restores FEN + Zobrist exactly; incremental hash
  equals full recompute after every move.
- **SAN** — round-trips and is collision-free over 6,000 positions.
- **Eval** — `eval(pos) == -eval(mirror)`; start position scores 0.
- **Search** — finds mate-in-1/2/3, the only-legal move, stalemate, threefold and
  insufficient-material draws; TT-on equals TT-off in score with fewer nodes;
  respects the time budget.
- **Server** — endpoint test plays a move and rejects an illegal one (HTTP 400).
- 22 tests, all green; `demo.sh` runs every feature.

## Why I chose this today

The recent ledger had drifted into a monoculture of SAT solvers (five of them) plus a
database, regex engine, physics, autodiff and Raft. A chess engine is a genuinely
different domain — game-tree search and rules modelling — and it has something most
toy projects lack: a *gold-standard oracle* (perft) that makes "it works" provable
rather than asserted. That tension between open-ended AI and airtight verification is
what made it worth a day.

## Adversarial review highlights

The review (`REVIEW.md`) found six issues. The most serious was caught during
verification: an aborted **timed** search unwound through `make_move()` calls without
their `unmake_move()`, handing the caller a corrupted board — so a legal best move
became illegal on it. It hid because only the `movetime` path raises the abort, while
deterministic depth-only games replayed perfectly. Fixed by restoring the board to
its pre-search undo-stack baseline on abort.

## Where a human could take this next

- **Speed:** move to bitboards (or a C extension / Cython) — pure-Python make/unmake
  caps depth at ~5–6 ply in reasonable time. Add staged move generation and SEE-based
  capture ordering.
- **Strength:** principal-variation search, null-move pruning, late-move reductions,
  aspiration windows, history heuristic, and a proper opening book / endgame tablebase
  probe.
- **Protocol:** a UCI front end so Gambit plugs into any chess GUI (Arena, CuteChess)
  and can be rated against other engines.
- **Eval:** replace hand-tuned tables with a small trained NNUE-style network (the
  autodiff engine from an earlier build could even train it).
- **UX:** drag-and-drop pieces, premoves, and analysis arrows in the browser board.

## Layout

```
gambit/  board.py movegen.py san.py eval.py search.py perft.py
         engine.py viz.py server.py cli.py demo.py
tests/   test_gambit.py
PLAN.md  REVIEW.md  demo.sh
```

Pure Python 3 standard library. No dependencies, no network access required.
