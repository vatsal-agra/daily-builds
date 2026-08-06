# Zugzwang

A chess engine built from scratch in pure Python — board representation,
full legal move generation, alpha-beta search, evaluation, and a playable
CLI and web UI. No chess library dependency anywhere in the stack.

**Status: Phase 4 (stretch + polish) complete.** All 4 required features
work end-to-end, 10 real bugs found by actually attacking the engine are
fixed (see [`REVIEW.md`](./REVIEW.md)), and all 3 stretch features are
fully implemented (not just 1) plus a genuine UI polish pass -- a real
captured-piece tray with live material-advantage counting, and a
game-over banner -- both promised in PLAN.md's architecture and previously
unbuilt.

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

Stretch features shipped:

5. **Transposition table with Zobrist hashing** -- caches search results by
   position hash; also powers threefold-repetition detection.
6. **PGN export and replay** -- correct SAN (disambiguation, check/mate
   suffixes, castling, promotion), a robust PGN parser (handles comments,
   `0-0`/`O-O` castling notation, no-space move numbers like `1.e4`,
   non-standard starting positions with `[SetUp]`/`[FEN]` headers), and a
   "Load & replay" button in the web UI.
7. **Curated opening book** -- 16 real opening lines across the Italian,
   Ruy Lopez, Sicilian, French, Caro-Kann, Queen's Gambit, Nimzo/King's
   Indian, London, and English, all verified to replay as legal SAN.

See [`PLAN.md`](./PLAN.md) for the full architecture and feature list.
Next: Phase 5 verification (formal test suite + demo script).

## Quick start (preview -- full instructions land in Phase 6)

```
python3 -m zugzwang.cli play --side white --time 3
python3 -m zugzwang.cli selfplay --time 1 --max-moves 40
python3 -m zugzwang.server   # then open http://127.0.0.1:8765/
```
