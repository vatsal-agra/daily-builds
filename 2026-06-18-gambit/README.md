# Gambit

> A from-scratch chess engine in pure Python. Status: **Phase 4 — stretch + polish.**

See [PLAN.md](PLAN.md) for the concept, architecture, and feature list.

A complete chess engine: 0x88 board with full rules, perft-verified legal move
generation, alpha-beta search with a transposition table, tapered evaluation, a
human-vs-engine CLI, and an HTML self-play replay viewer.

## Core status (Phase 2)
All four required features implemented and demonstrably working:

1. **Board + FEN + make/unmake** — full state, FEN round-trip, incremental
   Zobrist, exact unmake. (`gambit/board.py`)
2. **Fully-legal move generation** — castling / en passant / promotions, all
   verified by `perft`. **Kiwipete depth 4 = 4,085,603 exact.** (`gambit/movegen.py`)
3. **Search** — negamax alpha-beta, iterative deepening, quiescence, MVV-LVA +
   killer + TT ordering. (`gambit/search.py`)
4. **Evaluation** — tapered material + piece-square tables + bishop pair /
   doubled pawns; color-symmetric. (`gambit/eval.py`)

```bash
python3 -m gambit.cli perft --suite      # verify the rules
python3 -m gambit.cli analyze --depth 6  # search the start position
python3 -m gambit.cli selfplay --depth 4 # engine vs engine
```
