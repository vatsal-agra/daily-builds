# Gambit — Plan

## Concept
**Gambit** is a complete chess engine written from scratch in pure Python: a 0x88
mailbox board with full rules (castling, en passant, promotion, fifty-move,
threefold repetition), fully-legal move generation, a negamax alpha-beta search
with iterative deepening, quiescence search and move ordering, a tapered
material+piece-square evaluation, and a Zobrist transposition table — plus a
`perft` verifier, a human-vs-engine CLI with SAN, PGN export, and a self-contained
HTML viewer that replays an engine self-play game move-by-move with an evaluation
graph and principal variation.

## Why it's interesting
Chess move generation is a *notorious* correctness trap — en passant pins,
castling through check, promotion captures, discovered checks. The beautiful
thing is that it is **objectively verifiable**: `perft` (counting the exact number
of leaf nodes at a fixed depth) has published reference values for standard
positions (startpos, "Kiwipete", and several adversarial endgame positions).
Hitting those exact counts is an unforgeable proof that the rules are implemented
*perfectly* — there is nowhere to hide. On top of that correctness bedrock sits a
real adversarial search that actually plays chess. It's a satisfying blend of
"provably correct kernel" + "emergent intelligent behavior."

Nothing like it exists in the ledger (which is heavy on SAT solvers, plus a
regex engine, a database, Raft, a physics engine, and an autodiff lib).

## Architecture
```
gambit/
  board.py     # 0x88 board, FEN <-> board, make/unmake, Zobrist, repetition
  movegen.py   # pseudo-legal + legal move generation; SAN <-> move
  perft.py     # perft + perft divide (the correctness gate)
  eval.py      # tapered material + piece-square tables + a few terms
  search.py    # negamax alpha-beta, iterative deepening, quiescence, ordering, TT
  engine.py    # high-level Engine: best_move(time/depth), self-play
  viz.py       # generate the self-contained HTML replay viewer
  cli.py       # argparse CLI: perft / play / selfplay / analyze / viz / demo
tests/         # unittest suite incl. perft reference gate
demo.sh        # runnable end-to-end demo
README.md
```

Representation: **0x88 mailbox**. A 16×8 = 128-entry array where a square is
off-board iff `sq & 0x88`. This makes sliding-piece move generation and
off-board detection a single AND — clean and fast enough for pure Python.

Move encoding: a small immutable tuple/int (from, to, flags, promo). Make/unmake
restores castling rights, EP square, halfmove clock, and captured piece via an
undo record (no board copying in the hot path).

## Feature list

### Required (core)
1. **Board + FEN + make/unmake** — full state: side to move, castling rights, EP
   square, halfmove/fullmove counters; FEN parse *and* serialize (round-trips);
   incremental Zobrist hash; make/unmake with exact restoration.
2. **Fully-legal move generation** — all piece moves incl. castling (rights +
   empty + not-through/into-check), en passant (incl. the EP-discovered-check
   edge case), promotions (all 4 pieces, incl. capture-promotions). Legality by
   make + king-safety test. **Verified by `perft`** against published counts for
   ≥5 standard positions.
3. **Search** — negamax with alpha-beta pruning, iterative deepening, quiescence
   search (captures + promotions to quiet the horizon), and move ordering
   (MVV-LVA + TT move + killers). Returns best move + score + principal variation.
4. **Evaluation** — tapered (middlegame↔endgame) material + piece-square tables,
   plus bishop pair / doubled-pawn / mobility terms; mate/stalemate aware.

### Stretch
5. **Zobrist transposition table** — depth-preferred replacement, stores
   bound type (exact/lower/upper) + best move; measurably cuts node count.
6. **HTML self-play replay viewer** — single self-contained file: board that
   steps through a real engine-vs-engine game, SAN move list, evaluation graph,
   PV readout, keyboard/transport controls. No external assets, no Graphviz.
7. **Human-vs-engine CLI + PGN export** — play against the engine from the
   terminal with SAN/coordinate input, legal-move validation, and a valid PGN
   written at game end (loadable in any chess GUI).

## Verification strategy
- `perft` reference gate: startpos→depth 5 (4,865,609), Kiwipete→depth 4
  (4,085,603), plus positions 3/4/5 from the standard Chess Programming Wiki
  perft suite (each with published counts). Exact match = movegen is correct.
- Search sanity: finds forced mate-in-1 / mate-in-2 in test positions; never
  returns an illegal move; TT-on vs TT-off yield identical best scores.
- Eval symmetry: a position and its color-mirror evaluate to exact negatives.
- FEN round-trip on a corpus of positions.
- A `demo.sh` that runs perft, a tactical solve, and a short self-play game.
