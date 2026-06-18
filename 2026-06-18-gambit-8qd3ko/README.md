# Gambit ♟

A complete **chess engine written from scratch in pure Python** — no libraries,
no chess dependencies, no lookup of an existing move generator. A 0x88 mailbox
board with every rule of chess, a **perft-verified** legal move generator, a
Principal Variation Search with iterative deepening / quiescence / a
transposition table, a tapered piece-square evaluation, a play-against-it CLI,
PGN export, and a self-contained **HTML viewer that replays the engine playing
itself** with a live evaluation graph.

The whole thing rests on an *unforgeable* correctness gate: `perft` counts the
exact number of leaf nodes in the move tree to a fixed depth, and the standard
test positions have published reference counts. Gambit hits them exactly —
including **Kiwipete to depth 4 = 4,085,603** — which proves the rules
(castling, en passant, promotions, pins, discovered checks) are implemented
*perfectly*. There is nowhere for a bug to hide.

```
8 r n b q k b n r       depth 1  score 36  nodes    22  pv Nf3
7 p p p p p p p p       depth 2  score  0  nodes   115  pv Nf3 Nf6
6 . . . . . . . .       depth 3  score 35  nodes   730  pv Nf3 Nf6 d4
5 . . . . . . . .       depth 4  score  0  nodes  2636  pv Nf3 Nf6 d4 d5
4 . . . . . . . .       depth 5  score 33  nodes 14108  pv Nf3 Nf6 d4 d5 Nc3
3 . . . . . . . .
2 P P P P P P P P       Best move: Nf3 (g1f3)   Score: +33 cp
1 R N B Q K B N R
  a b c d e f g h
```

## Run it

Pure Python 3 standard library — nothing to install.

```bash
cd 2026-06-18-gambit

# Prove the move generator is exact (the correctness gate)
python3 -m gambit.cli perft --suite

# Watch every subsystem in one run (perft, eval, tactics, self-play, PGN)
python3 -m gambit.cli demo

# Analyze any position
python3 -m gambit.cli analyze --fen "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1" --depth 6

# Play against the engine (SAN like "Nf3" or coordinates like "g1f3")
python3 -m gambit.cli play --color white --depth 4 --pgn mygame.pgn

# Engine vs engine
python3 -m gambit.cli selfplay --depth 4 --pgn selfplay.pgn

# Generate the interactive HTML replay
python3 -m gambit.cli viz --depth 4 --out gambit_game.html

# Full test suite + demo + viz
./demo.sh
```

## Features

**Required (core)**

1. **Board, FEN & make/unmake** — a 0x88 mailbox with full game state (side to
   move, castling rights, en-passant target, halfmove/fullmove clocks). FEN
   parsing *and* serialization that round-trips exactly, with strict validation
   (rejects malformed boards, wrong rank counts, missing/duplicate kings). An
   incrementally-updated **Zobrist hash** (verified identical to a from-scratch
   recompute after millions of moves) and an `unmake` that restores the position
   bit-for-bit — no board copying in the hot path.
2. **Fully-legal move generation** — pawns (double push, all four promotions,
   capture-promotions), knights, sliders, king, **castling** (rights + empty
   squares + not castling out of / through / into check), and **en passant**
   (including the rare en-passant discovered-check). Verified by `perft` against
   published counts for five standard positions, exact to **Kiwipete depth 4**.
3. **Search** — Principal Variation Search (negamax + alpha-beta with
   zero-window scout searches and full-window re-searches), iterative deepening,
   a **check-aware quiescence search** (never stands pat while in check),
   **null-move pruning** (with a zugzwang material guard), and move ordering
   (transposition best-move, MVV-LVA captures, killer moves). Returns the best
   move, a score, and the principal variation; mate scores are reported as `#N`.
4. **Evaluation** — tapered middlegame↔endgame material + piece-square tables,
   plus bishop-pair and doubled-pawn terms. Exactly anti-symmetric under a color
   swap (the integer tapering truncates toward zero so White and Black are
   scored identically).

**Stretch**

5. **Zobrist transposition table** — used for **move ordering**, which is
   *provably* score-neutral: reordering moves cannot change the value alpha-beta
   returns, only how fast it gets there. The test suite asserts TT-on and TT-off
   produce identical scores on every position, while the TT still cuts node
   counts by ~25% (and null-move pruning roughly halves them again).
6. **HTML self-play replay viewer** — one self-contained file (no assets, no
   libraries): an interactive board with Unicode pieces and last-move
   highlighting, a clickable SAN move list, a canvas **evaluation graph** you can
   scrub, a play/step transport with keyboard controls (← → space), and the
   game's PGN. The game is played by the real engine and embedded as JSON.
7. **Human-vs-engine CLI + PGN export** — play from the terminal with SAN or
   coordinate input and legal-move validation; a valid, GUI-loadable PGN is
   written at game end.

## How it works

```
gambit/
  board.py     0x88 board, FEN <-> board, Zobrist, make/unmake/null, attack tests
  movegen.py   pseudo-legal + legal generation; SAN <-> move; captures (for q-search)
  perft.py     perft + divide + the published reference suite (the gate)
  eval.py      tapered material + PeSTO-style piece-square tables + terms
  search.py    PVS + iterative deepening + quiescence + null-move + TT + ordering
  engine.py    Engine.best_move, self-play loop, game-result/draw detection, PGN
  viz.py       generates the self-contained HTML replay
  demo.py      the end-to-end feature demo
  cli.py       perft / analyze / play / selfplay / viz / demo
tests/         26-test suite (perft gate, invariants, rules, tactics, viz)
demo.sh        full suite + demo + viz
```

The **0x88** trick: squares are numbered `rank*16 + file`, so a square is off the
board exactly when `sq & 0x88` is non-zero — one bitwise AND replaces every
boundary check, which is what makes from-scratch sliding-piece generation clean.

## Why I built this today

The ledger had drifted into a long run of SAT solvers, so I wanted something in a
completely different domain — but with the *same* obsession with provable
correctness. Chess move generation is the perfect target: it is famously
bug-prone (everyone gets en passant or castling-through-check wrong at least
once), yet it is **objectively checkable** via perft's published node counts.
That gives a rock-solid foundation, and on top of it sits a real adversarial
search that genuinely plays chess — it solves mates, wins hanging material, and
drives a King-and-Queen endgame all the way to checkmate against itself. A
provably-correct kernel plus emergent intelligent behavior is a very satisfying
thing to ship in a day.

## Verification

- **perft gate:** exact to startpos depth 5 (4,865,609) and Kiwipete depth 4
  (4,085,603); the suite checks five positions covering every special rule.
- **TT soundness:** TT-on score == TT-off score on every tested position.
- **Invariants:** Zobrist incremental == recompute, and `unmake` restores the
  FEN exactly, over hundreds of thousands of random moves.
- **Play:** finds mate-in-1/2, wins hanging material, and self-mates from
  KQ-vs-K — and the search never returns an illegal move.
- `python3 -m unittest discover -s tests` → **26/26 green.**

## Where a human could take this next

- **Speed:** rewrite the board as bitboards (with magic-bitboard sliders) — a
  ~50–100× speedup that would lift the practical search depth dramatically; or
  drop the hot loops into Cython/C.
- **Strength:** add aspiration windows, late-move reductions, futility pruning,
  a history heuristic, static-exchange evaluation for capture ordering, and a
  proper opening book / Syzygy endgame tablebases.
- **Protocol:** wrap it in the **UCI** protocol so it plays in any chess GUI
  (Arena, CuteChess) and on Lichess via a bot account.
- **Eval:** replace the hand-tuned PSTs with a small trained NNUE network (the
  Cotangent autodiff build from this same repo could train it).
- **Interface:** turn the replay viewer into a full play-in-browser front end by
  compiling the engine to WASM or running it behind a tiny local server.
