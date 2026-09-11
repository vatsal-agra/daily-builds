# Adversarial Review

This is a genuine hostile-reviewer pass over Vein's own code — not a
retrospective summary. Every issue below was found by actually running
the system (unit-testing the crypto primitives against independent oracle
values, running the multi-process partition demo repeatedly under load,
and deliberately constructing adversarial inputs), reading stack traces,
and fixing the root cause, not the symptom. Findings are grouped by when
they surfaced; all were fixed before Phase 2 was called "done," and are
listed here anyway because "found and fixed during development" is not
the same as "never happened."

## Cryptography layer

### 1. RIPEMD-160: right-line round constants used the wrong order (CRITICAL — wrong hash output)
While bringing up `hashes.py`, RIPEMD-160 initially failed its very first
differential check against `hashlib.new("ripemd160")` for the empty
string. Root cause: the algorithm's *right* processing line reverses the
order of its five non-linear functions (f5→f4→f3→f2→f1) relative to the
left line, and I'd mistakenly also reversed the *round constants*
(`K'`) to match — but the spec only reverses the functions, not the
constants, which stay in their natural round order. Fixed by indexing
`_RMD_K_RIGHT` with the un-reversed round number. Caught immediately by
the "hashlib as differential oracle" test design described in PLAN.md —
exactly the point of building that check before anything else depended
on the hash function.

### 2. secp256k1 generator point Gy: a transcribed constant was missing a digit (CRITICAL — every signature would be wrong)
The hand-copied `GY` constant in `curve.py` was 63 hex characters instead
of 64 — one trailing digit silently dropped in transcription. This is
exactly the failure mode "verify against a hard-coded test vector I also
typed by hand" doesn't catch (I made the *same* transcription mistake in
my first draft of a "known" 2G x-coordinate value used as a test double
-check, and it also silently passed as "looks about right"). Fixed by
deriving `Gy` independently, from the curve equation itself
(`y² = x³+7 mod p`, using `p ≡ 3 (mod 4)` to compute a modular square
root) rather than trusting a second hand-typed string, and validating the
whole curve going forward with self-consistency checks (`is_on_curve`,
additive homomorphism `aG+bG == (a+b)G` over dozens of random scalar
pairs, `N·G == ∞`) instead of point-value literals.

## Chain / consensus layer

### 3. Miner could reject its own just-mined block ("timestamp does not advance")
At the low, demo-friendly difficulties this project deliberately runs at,
a miner can find two blocks inside the same wall-clock second — and
`chain.add_block` correctly requires a strictly increasing timestamp.
`Miner._build_template()` was stamping `int(time.time())` verbatim, so
the miner would occasionally hand its own real, valid proof-of-work to
`chain.add_block()` and watch it get rejected by its own rule. Fixed by
stamping `max(int(time.time()), parent_timestamp + 1)`.

### 4. Sync never triggers between two nodes at *equal* height on different chains
`P2PNode._maybe_sync()` only requested a peer's chain when the peer was
*strictly taller*. That is exactly wrong for the one scenario a
partition-and-heal demo depends on: two sides of a healed partition can
easily be at equal height on genuinely different chains (equal block
count is not equal cumulative work, and even when it is, a height-only
gate means *neither* side ever asks the other for anything). Result: the
network would silently never re-converge. Fixed by always requesting on
handshake (a no-op, cheap round trip when there's nothing new) and by
having `heal()` explicitly trigger a sync request on that link, since a
healed link is an existing TCP connection with no fresh handshake to
piggyback on.

### 5. `_on_getblocks` crashed on a hash it knew about but hadn't adopted
`chain_hashes.index(have)` assumed "a hash in `self.chain.meta`" implies
"a hash in `self.chain.active_chain`" — but a validated side-branch block
is in `meta` and never in `active_chain`. A peer asking "send me
everything after *your competing side-branch tip*" (precisely what
happens mid-partition-heal) raised an uncaught `ValueError`, silently
dropping that sync request. Combined with #4, this is what actually made
the network hang rather than reconverge in early partition-demo runs.
Fixed with a safe scan that falls back to "send the whole active chain
from genesis" when `have` isn't actually on it.

### 6. Unsynchronized concurrent mutation of `Blockchain`/`Mempool` from multiple threads
Every peer connection runs its own reader thread, all calling into the
same `Blockchain`/`Mempool` objects with **no lock** — plus the miner
thread and RPC handler threads doing the same. Under real concurrent load
(two peers delivering competing blocks at once, which the partition demo
does by design) this produced genuine corruption: a `KeyError` in
`undo_log.pop(bh)` during `_reorganize_to`, and a `KeyError` in
`chain.meta[h]` reached through a completely different code path — two
distinct symptoms of the same missing-lock root cause, reproduced by
running the multi-process demo repeatedly until it broke. Fixed by
wrapping the full block-ingestion and tx-ingestion critical sections in
`P2PNode`'s existing lock, so `chain.add_block`, mempool updates, and the
seen-hash bookkeeping for one message complete atomically before another
thread can interleave.

### 7. Orphan-buffered blocks crashed the message handler
`_ingest_block` called `self.chain.meta[h]` unconditionally after
`chain.add_block()` returned — but `add_block()` returns `False` in two
different situations: a rejected (invalid) block, and a block that was
merely *buffered* as an orphan because its parent isn't known yet. In the
orphan case, `h` (this block's own hash) was never added to `chain.meta`
at all, so the very next line crashed with `KeyError`. This silently
swallowed the block's mempool-cleanup/broadcast side effects every time
it fired (masked, in early testing, by the fact that the block usually
*did* eventually get applied via the orphan-cascade path — the crash was
in bookkeeping, not correctness, but a crash on legitimate network input
is still a bug). Fixed by checking `chain.has_block(h)` before treating
the call as a successful application.

### 8. A long orphan cascade could exceed Python's recursion limit
`_accept_orphans_of()` called `self.add_block(blk)` for each buffered
orphan, and `add_block()` itself calls `_accept_orphans_of()` again at
the end of every successful application — so accepting a cascade of `N`
out-of-order blocks recursed `N` levels deep through normal Python call
frames. A hostile (or just slow/reordering) peer relaying a few hundred
blocks out of order would eventually hit `RecursionError` and crash the
node. Added a regression test that constructs a 300-block cascade
delivered in fully reversed order and asserts it applies cleanly, and
rewrote the drain as an explicit iterative queue instead of mutual
recursion between `add_block` and `_accept_orphans_of`.

### 9. A transaction spending the same UTXO twice within itself passed mempool validation
`Mempool._validate_against` tracked cross-transaction conflicts (two
*different* pending transactions claiming the same coin) but not a
single malformed transaction listing the *same* input twice. Each
occurrence added that coin's value into `fee_in` again, so the computed
fee was inflated and an actually-underfunded transaction could pass
mempool validation. The bug was self-limiting in one sense (chain-level
validation's `spent_this_block` check correctly rejects the transaction
when a block containing it is actually applied) but that's exactly the
problem: a miner could burn real proof-of-work on a block that
`chain.add_block()` then rejects outright, for a transaction the mempool
should never have accepted in the first place. Fixed with an explicit
per-transaction duplicate-input check in the mempool, before a miner
ever gets the chance to build on it.

### 10. Degenerate zero-input / zero-output transactions were vacuously "valid"
Neither the mempool nor `_apply_block_to_utxo` rejected a transaction
with no inputs and no outputs — `fee_in = 0`, `out_total = 0`,
`0 > 0` is false, so it sailed through as a valid, fee-free, functionless
transaction. Fixed by explicitly requiring at least one input and one
output for any non-coinbase transaction, in both the mempool and the
chain-level validator (the latter as defense in depth for a block
submitted directly via RPC, bypassing the mempool).

## Demo / harness correctness

### 11. Two miner groups racing for the same block height can tie exactly — and that's real, not a bug
Early partition-demo runs sometimes never converged even with fixes #4–6
in place, for a *different* reason: with both sides of the partition
mining concurrently and stopped only once each crossed a target height,
they could occasionally finish with genuinely equal cumulative work
(identical difficulty, similar block counts finishing around the same
wall-clock moment). Nakamoto consensus does not resolve a true tie by
itself — neither side's `work > tip.work` ever fires, by design, exactly
like real Bitcoin nodes sitting on two equal-work tips until the next
block breaks the tie. That's correct protocol behavior, not a defect in
`chain.py`, but it made the demo's outcome a coin flip. Restructured the
demo to mine group 1 to completion, stop it, *then* mine group 2 strictly
further with group 1 stopped (a deterministic work advantage instead of a
race), and added a settle step that mines one extra block within group 2
alone if its own two nodes tie with *each other* for the final block —
so the scenario reaches an unambiguous winner every run instead of
occasionally stalling on a coin flip.

### 12. Mempool block-template selection ranked by flat fee, not fee rate
`select_for_block()` sorted pending transactions by absolute fee, so a
large, low-fee-per-byte transaction could out-rank a small transaction
paying a much higher rate for the same block space — backwards from what
a revenue-maximizing miner would actually do. Fixed to rank by
`fee / serialized_size`, with a regression test asserting a small
high-rate transaction is selected ahead of a large transaction with a
bigger flat fee but a much lower rate.

## Considered and deliberately left as-is (documented, not a gap)

- **`OP_CHECKMULTISIG` doesn't replicate Bitcoin's historical
  off-by-one extra-pop bug.** This is Vein's own Script dialect, not a
  wire-compatible reimplementation of Bitcoin Script; there's no
  interoperability reason to carry forward a documented historical
  accident, so the multisig opcode just consumes exactly the values it
  needs.
- **No consensus-level script size / stack-depth limits.** Real Bitcoin
  bounds script and stack size to prevent a hostile transaction from
  costing disproportionate CPU to validate. At the scale this project
  runs at (toy chain, demo/test transactions, no adversarial fee market),
  that DoS surface isn't exercised, and adding limits without a realistic
  attacker to size them against would be security theater rather than a
  real mitigation.
- **Deserializing malformed wire bytes from a hostile peer doesn't do
  field-by-field bounds validation.** `Transaction.deserialize` /
  `Block.deserialize` will happily produce garbage-but-well-typed objects
  from truncated input rather than raising immediately. This was checked,
  not ignored: every message handler in `p2p.py` is wrapped in a broad
  `except Exception` that logs and moves on rather than crashing the
  node, and garbage that does deserialize successfully has to pass real
  proof-of-work and a real Merkle-root check before anything downstream
  ever trusts it — both practically impossible to satisfy by accident.
  Field-level wire validation would be the right thing to add before this
  code ever talked to a public, adversarial network; for a same-machine
  demo network it's a real but low-priority gap, recorded here rather
  than silently skipped.
- **`_replay_utxo_at` rebuilds a side branch's UTXO state from genesis on
  every call**, making side-branch validation of a growing minority chain
  O(n²) in the worst case rather than incremental. Correct and simple at
  the block counts this project ever reaches (dozens, not millions);
  called out in the code itself as a deliberate simplicity-over-speed
  tradeoff, not an oversight.

## Verification after fixes

- Full unit suite (`tests/`, 70 tests covering hashing, curve/ECDSA,
  Base58/addresses, Script VM, transactions/Merkle trees, and
  chain/mempool/reorg behavior including the specific regressions above):
  green.
- `vein demo` (single-process crypto → mining → spend → retargeting
  walkthrough): green.
- `vein partition-demo` (4 real OS subprocesses, a genuine network
  partition, a real double-spend attempt on each side, healing, and
  convergence verification): run 15+ times consecutively after the fixes
  above with zero failures, after being the thing that surfaced nearly
  every finding in this document in the first place.
