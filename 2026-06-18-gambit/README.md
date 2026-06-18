# Gambit ♛

A from-scratch chess engine in pure Python 3 (stdlib only). See `PLAN.md` for design.

## Status
Phases 1–4 complete. All 4 required features + all 3 stretch features shipped.

## Quick start
```
python3 -m gambit.cli perft 5 --verify          # verify move-gen vs published counts
python3 -m gambit.cli analyse --fen '<FEN>'     # engine analysis of a position
python3 -m gambit.cli selfplay --depth 3        # engine vs engine, prints PGN
python3 -m gambit.cli play                       # play the engine in your terminal
python3 -m gambit.cli viz --out game.html        # play a game, emit an HTML viewer
python3 -m gambit.cli serve                       # browser board vs the real engine
python3 -m gambit.cli demo                         # full feature demo
```
