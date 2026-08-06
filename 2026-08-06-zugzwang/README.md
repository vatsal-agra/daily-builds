# Zugzwang

A complete chess engine built from scratch in pure Python — board
representation, full legal move generation, alpha-beta search, evaluation,
and two playable interfaces. **No chess library dependency anywhere in the
stack** (no `python-chess`, no engine bindings) — every rule, every search
node, every evaluation term is hand-written and verified.

## What it is

- `zugzwang/board.py` — 0x88-free 8×8 board representation, FEN import/
  export, make/unmake move with full undo.
- `zugzwang/movegen.py` — pseudo-legal + legal move generation for every
  piece, castling (with all legality conditions), en passant, promotion,
  check/pin detection, checkmate/stalemate/draw detection.
- `zugzwang/perft.py` — the standard move-generator correctness harness;
  matches published reference node counts exactly for 5 test positions.
- `zugzwang/zobrist.py` — Zobrist hashing for the transposition table and
  repetition detection.
- `zugzwang/evaluate.py` — material + tapered midgame/endgame piece-square
  tables + mobility + king safety + pawn structure, in centipawns.
- `zugzwang/search.py` — iterative-deepening alpha-beta with quiescence
  search, a Zobrist-keyed transposition table, and move ordering (TT move,
  MVV-LVA captures, killers, history heuristic).
- `zugzwang/pgn.py` — SAN generation (with disambiguation and check/mate
  suffixes) and a real PGN parser/replay (handles comments, `0-0`/`O-O`,
  no-space move numbers, non-standard start positions).
- `zugzwang/book.py` — a curated opening book of 16 real lines.
- `zugzwang/cli.py` — terminal interface: play a full game against the
  engine, or watch two engine instances play each other.
- `zugzwang/server.py` + `web/index.html` — a zero-dependency local web
  server exposing a JSON API, backing an interactive clickable board with
  captured-piece tray, live engine evaluation, move list, and PGN
  export/replay. The browser never computes chess logic itself — every
  legality check and every engine move comes from this same engine over
  HTTP.

## How to run it

```bash
cd 2026-08-06-zugzwang

# Play a game against the engine in the terminal (you're White by default)
python3 -m zugzwang.cli play --side white --time 3

# Watch the engine play itself
python3 -m zugzwang.cli selfplay --time 1 --max-moves 60 --pgn game.pgn

# Verify move generation against published perft reference values
python3 -m zugzwang.cli perft --depth 4

# Launch the web UI (then open http://127.0.0.1:8765/)
python3 -m zugzwang.server

# Run the full test suite (56 tests, stdlib unittest, zero dependencies)
python3 -m unittest discover -s tests

# Run everything end-to-end in one shot
./demo.sh
```

No `pip install` needed to run any of the above — the engine, search,
evaluation, PGN, opening book, CLI, and web server are all pure Python 3
standard library. (The test suite that exercises `move_to_san`/`san_to_move`
happens to be the same code the CLI and web server use live, so there's no
separate "demo-only" logic path.)

## Full feature list

**Required (all 4 work end-to-end):**

1. **Full legal move generation** — castling (both sides, all legality
   conditions including not castling through/out of check), en passant
   (including the discovered-check pin case), promotion with all 4 choices,
   check/pin detection, checkmate/stalemate, fifty-move rule, threefold
   repetition, insufficient material. Verified via perft against 5
   published reference positions (start position through depth 4, plus
   Kiwipete and 3 other standard stress positions) — every value matches
   exactly.
2. **Alpha-beta search** — iterative deepening, quiescence search (with
   full check-evasion, not just captures, so it doesn't misjudge
   in-check positions), Zobrist transposition table, MVV-LVA/killer/
   history move ordering, and a time-budgeted `choose_move()`.
3. **Position evaluation** — material, tapered midgame/endgame
   piece-square tables, mobility, king safety (pawn shield), pawn
   structure (doubled/isolated/passed).
4. **Two playable interfaces** — a terminal CLI with full game support
   (SAN or UCI input, resignation, PGN export) and a web UI with a
   clickable board, legal-move highlighting, captured-piece tray with
   live material count, check/checkmate highlighting, move list, and
   PGN export/import — all backed by the real engine over a JSON API.

**Stretch (all 3 implemented, not just the required 1):**

5. **Transposition table with Zobrist hashing** — speeds up search and
   powers repetition detection.
6. **PGN export and replay** — correct SAN, a PGN parser robust to real
   from-the-wild formatting quirks, and a "Load & replay" button in the
   web UI.
7. **Curated opening book** — 16 real lines across major openings.

## Why I chose this today

Chess engines sit at the intersection of a few genuinely hard, well-studied
problems that are unusually satisfying to get *exactly* right, and unusually
easy to get *subtly* wrong. Move generation has more corner cases than it
looks like it should (en passant discovered checks, castling through check,
underpromotion) — and the field has a real, standard way to *prove*
correctness rather than eyeball it: perft, where the answer either matches
a published number exactly or it doesn't. That made today's adversarial
review genuinely productive rather than performative — I found a
tuple-unpacking bug that had silently turned every castling move into a
king sidestep, purely because Kiwipete's perft count was off by exactly the
castling subtree. I also found, and fixed, a much scarier bug: an aborted
search on a timeout left `make_move` calls un-undone on the stack,
permanently corrupting the shared board — the kind of bug that's invisible
in a quick manual playtest and only shows up under a tight, repeated stress
test. Both are documented in detail in [`REVIEW.md`](./REVIEW.md). Beyond
the algorithms, it's also just *legible* in a way a lot of systems-y daily
builds aren't: you can play it and watch whether it's any good.

## Where a human could take this next

- **Strength**: the current search is pure alpha-beta + quiescence with no
  null-move pruning, no late-move reductions, no futility pruning, and a
  hand-rolled Python interpreter loop (no bitboards) — a real strength
  boost would come from either those standard pruning techniques or
  rewriting the hot path (`is_square_attacked`, move generation) with
  bitboards for 10-100x node throughput.
- **UCI protocol support** so it can be plugged into any standard chess
  GUI (Arena, CuteChess, or as a Lichess bot via the Lichess Bot API)
  instead of only its own CLI/web UI.
- **Endgame tablebases** (Syzygy) for perfect endgame play once material
  is low enough.
- **Multiplayer web sessions**: the server currently holds one global game
  session; adding per-session cookies/IDs would let it host many
  simultaneous games.
- **A stronger opening book**: today's 16 hand-curated lines could be
  replaced with a real Polyglot book or one derived from a large PGN
  database.
- **Search-aware draw detection**: right now threefold repetition and the
  fifty-move rule are only checked against the actually-played game, not
  inside the search tree itself (documented as an accepted limitation in
  `REVIEW.md`) — threading position history through the search would let
  the engine proactively steer toward/away from a repetition it can see
  coming.
