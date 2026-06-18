# Gambit — Adversarial Review (Phase 3)

I attacked my own engine with invariant tests (zobrist consistency, make/unmake
round-trips, best-move legality, TT vs no-TT agreement, SAN edge cases, mate
detection, malformed input). The move generator survived everything — perft is
exact to Kiwipete depth 4 — but the **search and input layers had real bugs**.

## Findings

### 1. CRITICAL — Transposition table changes the root score (unsound cutoffs)
**Test:** TT-on vs TT-off at depth 8 on `8/8/8/8/8/5k2/8/4RK2 w - - 0 1`
gave **520 vs 513** — the TT altered the backed-up root value.

**Cause:** the search was plain negamax alpha-beta that took *bound* cutoffs
from the TT at every node. A `LOWER`-bound entry on the eventual best child,
when that child is searched with a finite window, can fail-high early and return
the (looser) bound instead of the true value. That bound propagates to the root,
so the root score is no longer exact — and if a sibling's exact score lands
between the bound and the truth, **the engine can pick the wrong move.** This
silently undermines the whole point of the search.

**Fix (first attempt):** rewrote the search as **Principal Variation Search
(PVS)** with TT bound-cutoffs only at non-PV nodes. That fixed the 7cp case but a
1cp wobble survived on a KQ-vs-K position — because *any* TT value cutoff (even an
exact-but-deeper entry) changes the value a fixed-depth search returns versus a
TT-less search. So the strong "TT never changes the result" invariant is
incompatible with TT value cutoffs in a fail-soft searcher.

**Fix (final):** the TT is now used for **move ordering only** — it stores the
best move found at each position and seeds the search with it. Reordering moves
cannot change the value alpha-beta returns (only how fast it gets there), so the
result is *provably* identical to a TT-less search. PVS is kept purely for
efficiency. Re-verified across 20+ positions: with the exact search (null-move
off), **TT-on score == TT-off score in 100% of cases**, while the TT still cuts
node counts by ~25% on its own (and the chosen move stays optimal — only ties
among equal-value moves break differently). The mate-score TT normalization
(finding #3) became moot and was removed with the value field.

### 2. MAJOR — King-less / malformed FEN parses silently into a broken board
**Test:** `Board.from_fen("8/8/8/8/8/8/8/8 w - - 0 1")` succeeded with
`king_sq == [-1, -1]`; `in_check()` then indexed `squares[-1]` (an off-board
cell) and returned a meaningless answer instead of failing.

**Fix:** `from_fen` now validates exactly one king of each color and that every
piece letter is legal, raising `ValueError` with a clear message otherwise.

### 3. MINOR — Mate scores stored in the TT without ply normalization
Mate scores are encoded as `MATE - ply`. Storing that raw and reading it back at
a different ply reports the wrong mate distance (and can mis-order mates).

**Fix:** initially normalized mate scores on TT store/probe; this became moot
once the TT was reduced to move-ordering-only (finding #1) — no scores are stored
in the TT at all anymore, so there is nothing to mis-normalize.

### 4. MINOR — Quiescence was blind to being in check
The quiescence search did a static "stand-pat" and only looked at captures, so a
position that is *in check* at the horizon (possibly checkmate) could be scored
optimistically, hiding tactics.

**Fix:** when the side to move is in check at a quiescence node, the full set of
legal evasions is searched instead of standing pat; no legal evasion returns a
mate score `-MATE + ply`.

### 5. MINOR — Dead code: `make_null` / `unmake_null` were unused
They were added for null-move pruning that wasn't wired in.

**Resolution:** null-move pruning is implemented in Phase 4 (search polish), so
these become live and tested rather than dead. (If it had not been, they would
have been removed.)

## Re-verification gate
After the fixes, a fresh run hits **zero** of the above:
- perft suite still exact (movegen untouched).
- TT-on score == TT-off score on every test position (incl. the 520 case).
- Best move legal in 100% of random positions.
- Malformed FENs raise `ValueError`; valid FENs round-trip.
- Mate-in-1/2 found with correct, ply-consistent mate scores.
