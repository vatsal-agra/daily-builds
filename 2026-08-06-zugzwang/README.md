# Zugzwang

A chess engine built from scratch in pure Python — board representation,
full legal move generation, alpha-beta search, evaluation, and a playable
CLI and web UI. No chess library dependency anywhere in the stack.

**Status: Phase 3 (adversarial review) complete.** All 4 required features
work end-to-end, and 10 real bugs found by actually attacking the engine
(including a critical board-corruption bug on search timeout, and a
tuple-unpacking bug that silently disabled castling entirely) are fixed --
see [`REVIEW.md`](./REVIEW.md) for the full writeup.

The 4 required features:

1. Full legal move generation (castling, en passant, promotion, checks/
   pins, checkmate/stalemate/draw detection) — verified against published
   perft reference values for 5 standard test positions.
2. Alpha-beta search with iterative deepening, quiescence search, and a
   Zobrist-keyed transposition table.
3. Material + tapered piece-square-table + mobility + king-safety +
   pawn-structure evaluation.
4. Two playable interfaces: a terminal CLI (`zugzwang play` / `zugzwang
   selfplay`) and a local web UI (`zugzwang serve`) with a clickable board
   backed by the real engine over a JSON API.

A curated opening book (stretch feature) is also wired in already since the
CLI/server needed *something* to play out of book with; it'll be credited
properly as a stretch feature in Phase 4.

See [`PLAN.md`](./PLAN.md) for the full architecture and feature list.
Next: Phase 4 stretch features + polish.

## Quick start (preview -- full instructions land in Phase 6)

```
python3 -m zugzwang.cli play --side white --time 3
python3 -m zugzwang.cli selfplay --time 1 --max-moves 40
python3 -m zugzwang.server   # then open http://127.0.0.1:8765/
```
