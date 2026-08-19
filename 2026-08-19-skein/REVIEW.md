# Adversarial review — Phase 3

Hostile-reviewer pass over the Phase 2 core build. Three real bugs found
and fixed; one design tradeoff considered and deliberately kept as-is
(documented below rather than silently left alone).

## Bugs found and fixed

### 1. CRITICAL — pending-op replay cascade recursed and could blow the stack

`RGA._apply_insert` called `self._replay_pending(op.id)` at the end of
every successful insert, and `_replay_pending` called back into
`_apply_insert` for every op it unblocked. That's a Python call chain
whose depth equals however many buffered ops get unblocked in one
cascade — and the most ordinary possible scenario produces a long one:
someone types a passage of N characters straight through (each new
character's `origin` is the previous character, so it's a single chain
of length N), and that op set is then delivered to another replica in
**exactly reversed order**. The first op received depends on the last
character typed, which depends on the second-to-last, and so on all
the way down — applying the *one* op whose dependency finally exists
unblocks the entire chain in a single cascade, recursing N deep.

Reproduced directly: typing 3,000 characters into one site, then
feeding that site's own op log to a fresh replica in reversed order,
raised `RecursionError: maximum recursion depth exceeded` — not a
contrived adversarial input, just "someone was offline and their
client delivers the backlog newest-first," or ordinary network
reordering happening to produce a long unlucky run.

**Fix:** rewrote `RGA.apply()` around an explicit worklist (a plain
list used as a stack) instead of recursion — applying an op that
unblocks pending ops pushes them onto the worklist rather than calling
back into itself. Same cascade, zero call-stack growth. Verified fixed
with the identical 3,000-char reversed-order reproduction (now passes)
and a 5,000-char version for margin; see `tests/test_rga.py::test_long_reversed_delivery_does_not_recurse`.

This is the second time this exact bug class has shown up in this
build: `_preorder()` (materializing the document text) was written
iteratively from the start for precisely this reason — a straight-typed
document is a linked-list-shaped tree, so *anything* that walks it via
Python recursion is one long paragraph away from `RecursionError`. The
replay cascade was the one place that lesson wasn't applied yet.

### 2. CRITICAL — healing one site leaked its edits to a still-partitioned site

`Simulation.heal(site_id)` resynced *every* site's full op history
unconditionally, not just the one reconnecting. Reproduced: partition
both `b` and `c`, make an edit, heal only `b` — `c`, still supposedly
cut off from the network, received the edit anyway, because the
anti-entropy resync loop didn't check whether `c` itself was still
partitioned before syncing it.

This is a real correctness bug in the network model, not a cosmetic
one: it silently breaks the one guarantee a "partition" is supposed to
make (an isolated site sees *nothing* until *it* is healed), which
would have quietly weakened every chaos trial that partitions more than
one site at a time and healed them independently — exactly the kind of
multi-partition scenario `run_chaos_trial`'s randomized partition/heal
choices produce.

**Fix:** the resync loop in `Simulation.heal()` now skips any site that
`self.network.is_partitioned()` still reports as cut off. Verified with
a direct repro (`tests/test_network.py::test_heal_does_not_leak_to_still_partitioned_site`)
and confirmed the 500-trial chaos sweep (which partitions/heals
multiple sites per run) still converges 500/500 after the fix.

### 3. CLI crashed with a raw traceback on invalid input

`skein sim --sites 0` (or `--sites 1`, or an out-of-range `--drop`)
threw an unhandled `IndexError` from deep inside `random.choice()` on
an empty site list, instead of a clean, actionable error. Same failure
mode Vignette/Loom/Unify's own reviews caught in this ledger's history
— didn't repeat it here.

**Fix:** added input validation (`--sites >= 2`, `--edits >= 0`,
`--trials >= 1`, `--drop`/`--dup` in `[0, 1]`) raising a small
`SkeinCliError`, caught once in `main()` and reported as `error: ...`
on stderr with a non-zero exit instead of a traceback.

## Considered, not changed

**In-flight messages sent just before a partition still get delivered.**
`SimNetwork.partition()` only affects future calls to `send()`; a
message already queued in `_in_flight` when its destination gets
partitioned is still delivered on schedule. This is intentional, not
an oversight: the docstring's claim is specifically about messages
*sent* "during the cut," which this doesn't violate, and a real network
partition doesn't retroactively un-deliver packets already in the pipe
either. Changing this would make partitions *more* absolute than real
ones and would remove a legitimately interesting edge case (a message
that "just barely" gets through) from the chaos sweep's coverage.

**`_sorted_insert_desc` and `_reindex_from` are O(n) per op.** Fine at
this project's scale (chaos trials run in the tens-to-hundreds of ops,
`demo.sh` and the unit suite never approach a size where this matters)
but would need a different per-parent data structure — a proper
order-statistics tree — before this became a production-scale sequence
CRDT. Documented in the code and in README's "where a human could take
this next," not hidden.

**Multi-codepoint grapheme clusters (flag emoji, ZWJ sequences) count
as more than one `char`.** `InsertOp` requires `len(char) == 1`, which
is Python codepoint length, not grapheme-cluster length — a family
emoji built from a ZWJ sequence would need multiple InsertOps, one per
codepoint (each individually a valid single character to Python, just
not what a human perceives as "one character"). This matches how the
overwhelming majority of real text — including most emoji — behaves,
and grapheme-cluster segmentation is a substantial, orthogonal Unicode
feature that would meaningfully bloat this project's scope; disclosed
as a known limitation rather than silently unhandled.

## Verification after fixes

- `python3 -m skein.cli demo` — clean pass, all 4 sections green.
- `python3 -m skein.cli chaos --trials 500` — 500/500 converged, every
  site matching the independent oracle.
- `python3 -m skein.cli shuffle-proof --trials 300 --edits 80` —
  300/300 random delivery orders converged to the identical document.
- The exact reversed-order-recursion and partition-leak repros above
  both now pass and are captured as permanent regression tests in
  Phase 5's test suite.
