# Gambit — Adversarial Review (Phase 3)

I attacked my own engine. Move generation is the part most likely to harbour
silent bugs, so it gets the strongest evidence; the rest I probed by hand.

## What held up under fire
- **Move generation is correct.** Perft matches the published node counts *exactly*
  on all 5 standard positions (startpos, Kiwipete, positions 3/4/5) — including the
  ones specifically designed to expose en-passant, pin, promotion and castling bugs.
- **make/unmake + incremental Zobrist are exact.** A 27,483-move recursive fuzz
  (4 seed positions, depth 4) found **zero** discrepancies: after every unmake the
  FEN and Zobrist key are byte-identical to before, and after every make the
  incremental Zobrist equals a full from-scratch recompute.
- **SAN round-trips losslessly** over every legal move of several positions, and
  **evaluation is colour-symmetric** (eval(pos) == -eval(mirror)).
- Search finds forced mates (mate-in-1/2/3) and reports them with correct mate
  distance; TT-on returns the same scores as TT-off with fewer nodes.

## Issues found and fixed

### F1 — Insufficient-material draw was too aggressive (correctness)
`_insufficient_material` returned `True` for **KB vs KB** and **KN vs KN**, which
are *not* automatic draws under the rules (KN vs KN can be checkmated; opposite-
coloured KB vs KB is not a dead position). This could end a still-playable game in a
premature draw. **Fix:** only declare a material draw for the universally dead
positions — at most a single minor piece on the whole board (K-vs-K, KN-vs-K,
KB-vs-K), with no pawns/rooks/queens.

### F2 — Ugly tracebacks on bad user input (UX)
A malformed FEN or an unparseable position string handed to the CLI dumped a raw
Python traceback at the user. **Fix:** the CLI now catches `ValueError` and prints
a clean `error: ...` line, exiting non-zero.

### F3 — Transposition table could overwrite a deeper entry with a shallower one
The TT store was unconditional, so re-visiting a position at a *lower* depth threw
away the more valuable deep result. **Fix:** depth-preferred replacement — keep the
existing entry unless the new search reached at least its depth.

### F4 — Malformed en-passant square gave a cryptic error
`from_fen` on `... w KQkq z9 0 1` raised `ValueError: substring not found` (from an
internal `str.index`). **Fix:** the en-passant and rank/file parsing now validate
their input and raise a clear, located message.

### F5 — FEN with the wrong number of kings was accepted
A placement with two white kings (or none) silently used the last-seen king square.
**Fix:** `from_fen` now requires exactly one king per side.

### F6 — Aborted timed search left the board corrupted (CRITICAL, found in Phase 5)
The verification suite's "every move in a full game is legal" test crashed with
`KeyError: 0` inside `to_san` — a "best move" whose origin square was empty. Root
cause: when the time check raised `TimeUp` deep in the recursion, the exception
unwound through every `board.make_move(...)` **without** running the matching
`unmake_move()` (the `finally` only popped the repetition stack). `search()` caught
`TimeUp` and returned the previous iteration's (legal) best move, but handed the
caller a **mutated board** with half a search tree's worth of moves still applied —
so that move was now illegal on the corrupted position. This only triggered under a
`movetime` budget (the only path that raises `TimeUp`), which is exactly why
deterministic depth-only games had replayed perfectly. **Fix:** `search()` records
the undo-stack depth before searching and, on `TimeUp`, pops the board back down to
that baseline before returning — guaranteeing the board is byte-for-byte restored.
Verified: after a timed search the FEN and undo stack are identical to before, and
8 independent timed games now replay with zero illegal moves.

## Re-verification after fixes
A fresh run-through hits **zero** of the listed issues: KB-vs-KB and KN-vs-KN are no
longer auto-drawn, K-vs-K / KN-vs-K / KB-vs-K still are; bad FEN/ep/king inputs raise
clear errors and the CLI prints them cleanly; the TT keeps deeper entries; and the
full test suite (perft oracle, fuzz invariants, SAN, eval symmetry, mate-finding)
passes green.
