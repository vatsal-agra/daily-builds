# Adversarial review

Methodology: attacked the engine with (1) known-reference perft positions,
(2) property-based stress tests (many seeded engine-vs-engine games with
tight time budgets, asserting every returned move is actually legal and
every exported PGN replays back to the identical final FEN), (3) hand-built
edge-case FENs for specific rules (insufficient material, stalemate,
threefold repetition, castling-rights revocation on rook capture,
promotion/underpromotion, SAN disambiguation), (4) a real browser driving
the web UI end-to-end via Playwright, and (5) directly hostile API inputs
(malformed JSON, bad FENs, garbage squares, unknown routes) against the
server. Every issue below was found *by actually running the thing*, not
by inspection alone.

## Bugs found and fixed

1. **Castling moves never generated (tuple-unpacking bug).** `_castle_moves`
   built each rights tuple with a redundant extra element, which shifted
   `king_to` one field over -- `e1g1`/`e1c1` were silently replaced by
   `e1f1`/`e1d1` (already-generated regular king steps), so perft against
   the Kiwipete reference position was off by exactly the castling subtree
   (94114 vs. the correct 97862 at depth 3, traced via a `perft_divide`
   diff against `python-chess` as an independent oracle). **Every castle in
   every game up to this point was actually a king sidestep with a stale
   flag.** Fixed by removing the redundant tuple element; all 5 reference
   perft positions now match published values exactly (see PLAN.md).

2. **Board corruption on search timeout (critical).** `_negamax` and
   `_quiescence` called `board.make_move()` / recursed / `board.unmake_move()`
   with no exception safety. When the time budget expired mid-recursion,
   `_TimeUp` unwound the stack *without* running the pending `unmake_move`
   calls, leaving the shared `Board` object permanently corrupted (moves
   applied but never undone). The corrupted board was then handed back to
   the caller and played on top of by the next real move. Reproduced
   reliably with a seeded-random stress harness using a deliberately tight
   0.2s time budget: within ~20 games it produced `board.to_move == white`
   returning a *black* knight's move as White's move. Fixed by wrapping
   every `make_move`/`unmake_move` pair in `try/finally` in both search
   functions. Re-ran the same 20-seed harness (and later a 15-seed x 40-ply
   harness) with zero failures after the fix.

3. **`game_state()` documented but never implemented threefold repetition**,
   despite it being explicitly promised as part of required feature #1 in
   PLAN.md. Added an optional `position_history` (list of Zobrist hashes of
   every position actually played in the game) threaded through
   `game_state()`, and wired it through the CLI and web server. Verified
   with a constructed knight-shuffle repetition and with a live stress test.

4. **PGN move numbering assumed White always moves first at ply 0.**
   `game_to_pgn` unconditionally numbered `moves_san[0]` as White's move 1,
   so a game starting from a custom FEN with Black to move mislabeled every
   move thereafter (`1. Nf6 Nf3` instead of `1... Nf6 2. Nf3`). Fixed to
   read the actual side-to-move and move number off the starting FEN, added
   `[SetUp]`/`[FEN]` headers for non-standard starts (standard PGN
   convention), and fixed the matching bug in `cli.py selfplay`'s live move
   printer (same wrong assumption, different code path).

5. **PGN parser mangled `0-0`/`0-0-0` castling notation.** The move-number
   stripper treated *any* leading digit as part of a move number, so the
   token `0-0` became `-0` before it ever reached the SAN resolver --
   castling games written with zeros instead of letter-O (extremely common
   in the wild) failed to load. Fixed to only strip a digit run that is
   actually followed by a dot (so `1.`, `12...`, and the no-space form
   `1.e4` are still handled), leaving `0-0`/`0-0-0` untouched.

6. **Web UI coordinate labels swapped.** File letters (a-h) were drawn down
   the rightmost *column* instead of along the bottom *row*, and rank
   numbers were drawn along the bottom row instead of the left column --
   caught immediately in a Playwright screenshot (every square in the right
   column showed "h"). Fixed the row/column conditions.

7. **`GameSession.reset()` corrupted the active session on a rejected
   FEN.** `self.start_fen` was assigned *before* `Board.from_fen()` had a
   chance to raise on a malformed FEN, so a failed `POST /api/new` left the
   previous, still-in-progress game's `start_fen` overwritten with the
   rejected string (silently breaking that game's later PGN export headers)
   while every other session field stayed on the old game. Fixed by
   validating into local variables and only committing state after the FEN
   parses successfully.

8. **No time-budget floor -- `--time 0` could hang indefinitely.**
   `seconds=0` was falsy, which the code treated as "unlimited," so
   iterative deepening would run to `max_depth=64` with no cutoff. Clamped
   any non-positive numeric budget to a small positive floor; `seconds=None`
   remains an explicit "actually unlimited" sentinel for library/test
   callers.

9. **No concurrency guard on the shared game session.** `ThreadingHTTPServer`
   hands each HTTP request its own thread, but all requests mutate one
   global `GameSession`/`Board`. Two overlapping requests (two browser
   tabs, or a double-click firing two `/api/move` calls) could interleave
   mid-search and corrupt the board the same way bug #2 did internally.
   Added a single process-wide lock around the entire request-handling path
   so each request is atomic end-to-end.

10. **CLI had no graceful handling for bad `--fen`, Ctrl-C, or closed
    stdin.** A malformed `--fen` raised an unhandled `IndexError`/`ValueError`
    with a raw traceback; Ctrl-C during `selfplay`'s search, or EOF on
    stdin during `play`, did the same. Added a single FEN-loading helper
    with a clean error message and exit code, `try/except` around `input()`
    for EOF/interrupt (treated as resignation), and a top-level
    `KeyboardInterrupt` handler in `main()`.

## Things checked and found correct (no change needed)

- Perft matches published reference values exactly for the standard start
  position (depths 1-4) and four additional reference positions
  (Kiwipete, and positions 3/4/5 from the standard perft test suite) that
  specifically stress castling, en passant, pins, and promotion.
- SAN disambiguation (file-only, rank-only, and full-square fallback) --
  verified against constructed two-knight and rook-triangulation positions.
- All 8 promotion/underpromotion combinations, including a capturing
  underpromotion, with correct check annotation on the ones that actually
  give check and none on the ones that don't.
- Insufficient-material detection: K v K, K+minor v K, same-color bishops
  both true; opposite-color bishops and K+Q correctly *not* flagged.
- Stalemate and checkmate detection on constructed reference positions.
- Castling-rights revocation when a rook is *captured* on its home square
  (not just when it moves).
- Evaluation symmetry: flipping a position's colors and files flips the
  score sign exactly, checked across three structurally different
  positions (opening, developed middlegame, sparse endgame).
- All 16 curated opening-book lines replay as legal, correctly-notated SAN
  sequences from the start position (a wrong token would have silently
  fallen back to search rather than crash, so this needed an explicit
  check to catch quietly-broken lines).
- Hostile API input (malformed JSON body, missing fields, out-of-range
  squares, unknown routes) all degrade to clean 4xx JSON responses with no
  server-side tracebacks.

## Known, accepted limitations (not bugs -- scope decisions)

- **Search does not know about draws during lookahead.** Threefold
  repetition and the fifty-move rule are only checked against the *actual
  played game* (via the externally-threaded `position_history`), not
  inside the recursive search tree itself. A full fix means threading
  position history through every node of the search, which is a
  meaningfully larger engineering task than today's scope. In practice
  this means the engine won't proactively steer into/away from a
  repetition it can see coming a few moves out -- a known, common
  simplification in hobby engines.
- **En passant rights are slightly over-strict for repetition purposes.**
  `ep_square` is set (and hashed) whenever a pawn double-pushes, regardless
  of whether an enemy pawn could actually capture en passant. FIDE's strict
  definition only counts positions as identical when en passant capture is
  *currently available*. Since this engine applies the same (slightly
  broader) rule consistently both times a position recurs, it cannot
  produce an incorrect repetition claim in practice -- it's a difference
  from strict rules-text, not an inconsistency.
- **Custom start FENs are not validated for chess sanity** (e.g. a FEN
  missing a king, or with pieces on impossible squares, is accepted
  as-is). Verified this degrades gracefully rather than crashing --
  `is_in_check` returns `False` for a missing king, castling generation
  no-ops if the king/rook aren't where rights claim -- but it will produce
  nonsensical evaluation/play rather than a rejection. Full legality
  validation of arbitrary input FENs was judged out of scope for a
  from-scratch hobby engine's custom-position feature.
- **K+N+N vs K is not flagged as insufficient material.** This is the
  conservative/correct choice: unlike K+minor vs K, two knights can
  (artificially) force mate against imperfect defense, so most rule
  implementations leave it drawable only via the fifty-move rule or
  repetition rather than an automatic material-based draw.
