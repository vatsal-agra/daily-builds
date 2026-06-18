# Gambit ♛

A from-scratch chess engine in pure Python 3 (stdlib only). See `PLAN.md` for design.

## Status
- **Phase 1 (plan):** done
- **Phase 2 (core build):** done — legal move generation (perft-verified on 5
  published positions), alpha-beta + quiescence search, tapered evaluation, and
  SAN/FEN/PGN I/O all work end-to-end via the `gambit` CLI.

## Quick start
```
python3 -m gambit.cli perft 5 --verify          # verify move-gen vs published counts
python3 -m gambit.cli analyse --fen '<FEN>'     # engine analysis of a position
python3 -m gambit.cli selfplay --depth 3        # engine vs engine, prints PGN
python3 -m gambit.cli play                       # play the engine in your terminal
```
