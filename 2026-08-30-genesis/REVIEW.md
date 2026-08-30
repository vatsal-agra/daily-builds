# Adversarial review

Attacking my own work as a hostile reviewer, hunting specifically for
correctness bugs, security holes, and shortcuts that would look fine in a
demo but fall over under real use.

## Findings, fixed

### 1. (Correctness/security) Genesis block was never actually validated
`Blockchain.__init__` applied the genesis block's transactions to build the
initial UTXO set but never checked the genesis block's own merkle root or
proof-of-work. Every code path in this project happens to call
`Block.mine()` on genesis before constructing a `Blockchain`, so nothing
visibly broke — but the class itself would silently accept an unmined or
merkle-tampered genesis, which means the "every block, no exceptions"
security story this project is built on had an unenforced exception at
block zero. **Fix:** `Blockchain.__init__` now runs the same merkle-root
and PoW checks on genesis as `accept_block` runs on every other block, and
raises `ChainError` if either fails. Covered by
`tests/test_blockchain.py::TestGenesisValidation`.

### 2. (Architecture/fidelity) The "network" was passing live Python objects, not bytes
`SimNetwork` messages carried `Block`/`Transaction` objects directly; a
receiving node's handler got the exact same object the sender built. That
meant the hand-rolled binary (de)serialization code (`Transaction.serialize`/
`deserialize`, `Block.serialize`/`deserialize`) — supposedly "the actual
wire format" — was dead code outside of unit tests, and it also meant two
"different" nodes were silently sharing memory, which is not what a P2P
network of independent machines does. **Fix:** `Node` now serializes every
outbound block/transaction to bytes before calling `network.broadcast`/
`send`, and deserializes on receipt in `_on_message`. A peer's block is now
a genuinely independent object reconstructed from bytes, not a shared
reference — checked directly in
`tests/test_network.py::TestWireSerialization`.

### 3. (Security) The explorer's static file handler had a directory-traversal hole, and bound to 0.0.0.0
The fallback branch of `Handler.do_GET` served `os.path.join(STATIC_DIR,
path.lstrip("/"))` for any unmatched request path — a request for
`/../../../../etc/passwd` (or any other path outside `static/`) would be
read and returned verbatim, and the server defaulted to binding
`0.0.0.0`, exposing that hole to the whole network, not just localhost.
**Fix:** removed the generic static-file fallback entirely (the explorer
page is a single self-contained `index.html` with no other static assets
to serve, so there was nothing legitimate that fallback was for); the
server now 404s anything that isn't `/`, `/index.html`, or a known `/api/*`
route, and defaults to binding `127.0.0.1` (a `host` parameter is available
for an explicit opt-in to something else).

### 4. (Efficiency/hygiene) Gossip echoed every block/tx straight back to whoever sent it
`Node._on_block`/`_on_tx` re-broadcast to all peers except itself — which
includes the node that just sent the message. It cost nothing
correctness-wise (the sender's own duplicate-detection just no-ops), but
it silently doubled network traffic and isn't how a real gossip protocol
behaves. **Fix:** `SimNetwork.broadcast` gained an `exclude` set, and
`Node`'s re-broadcast calls now exclude the immediate sender.

### 5. (Efficiency) Every new block re-derived the parent's UTXO state from genesis, even when just extending the tip
`Blockchain.accept_block`'s state reconstruction (`_utxo_snapshot_at`)
replays a candidate block's entire ancestor chain from genesis — a
deliberate, documented simplification for handling *fork candidates*
correctly and simply (see `blockchain.py`'s module docstring). But it was
being used unconditionally, including for the overwhelmingly common case
of a block that simply extends the current tip, where the already-cached
UTXO set *is* the exact state needed and no replay is required at all.
**Fix:** `accept_block` now takes an O(1) fast path (reuse the UTXO cache)
when the new block's parent is the current tip, and only falls back to the
full from-genesis replay for an actual competing branch.

### 6. (Correctness, live server only) Gossip never actually delivered anything
After building the explorer (`server.py`), running it end to end (not just
reading the code) turned up a real functional bug that no unit test caught,
because the unit tests drive `SimNetwork` with their own explicit,
monotonically-advancing round counter (see `tests/test_network.py`), which
happened to paper over the exact mistake this file made. `Network.tick()`
called `self.net.advance_to(self.net.now)` right after scheduling a
broadcast — but a broadcast is scheduled for `self.net.now + latency`
(a small positive number), so advancing *to* `self.net.now` (unchanged)
delivers nothing: every scheduled message stayed queued forever. Watching
the live server confirmed it: `blocks_accepted_from_peers` stayed at 0 and
`reorgs_seen` stayed at 0 for every node indefinitely, no matter how long
it ran — three nodes were silently mining three completely disconnected
private chains, the opposite of this project's core subject. **Fix:**
`SimNetwork`'s virtual clock in the live server is now driven by real
elapsed wall-clock time (`self.net.advance_to(time.time())`), so scheduled
deliveries actually become due. Confirmed live after the fix: nodes now
show real `blocks_accepted_from_peers` and `reorgs_seen` counts and the
network visibly converges (`"converged": true` in `/api/status`).

### 7. (Correctness, live server only) Difficulty drifted easier forever, never settled
Also only visible by watching the live server run for a couple of minutes:
`target` kept increasing (easier) block after block with no sign of
reaching equilibrium. Root cause: block timestamps are whole seconds, but
this demo's low mining difficulty means several blocks can legitimately be
found within the same real wall-clock second — `_next_timestamp()` was
unconditionally forcing `last_ts + 1` in that case, with no mechanism to
let the recorded clock fall back in step with real time afterward. Once
the recorded clock gets even slightly ahead of real time, every subsequent
call keeps taking the `last_ts + 1` branch forever (since `last_ts` is now
always ≥ real `now`), so the *recorded* clock runs at up to one full
"second" per tick — faster than real elapsed time — making every
difficulty retarget conclude blocks are arriving slower than they truly
are, and ease off indefinitely. **Fix:** `_next_timestamp()` now throttles
with a real `time.sleep()` whenever the recorded clock has gotten ahead of
real time, capping its long-run rate at one timestamp-second per real
second. Confirmed live: target rose once after the first retarget window
then held steady (251 bits, unchanged across 4 checks 15s apart spanning
height 17→32) instead of climbing every window.

Both of these were only found by actually running the shipped server for
several minutes and reading its own `/api/status` output adversarially,
not by reading the code — a reminder that "the unit tests pass" and "the
feature works" are different claims for anything involving real time or
real concurrency.

## Findings, deliberately not "fixed" (documented scope choices)

- **No coinbase maturity rule.** Real Bitcoin forbids spending a coinbase
  reward until it's 100 blocks deep, specifically to bound the cost of a
  deep reorg unwinding a spend of a reward that reorg itself removed. This
  project's reorg model doesn't need that rule for *correctness*: a
  candidate branch's UTXO state is always fully reconstructed by replaying
  only that branch's own blocks from genesis (`_utxo_snapshot_at`), so a
  transaction on branch B can never end up referencing an output that only
  ever existed on a different branch A — there's no code path where that
  could happen. Omitting the maturity rule is a real, intentional
  divergence from Bitcoin (it exists there as a DoS/reorg-depth
  mitigation, not a ledger-consistency requirement), not an oversight.
- **One shared sighash per transaction, not Bitcoin's per-input, scriptPubKey-
  substituted sighash.** Documented in `transaction.py`'s module docstring:
  every input is signed over a hash committing to *all* inputs' outpoints
  and pubkeys plus all outputs, rather than Bitcoin's scheme of swapping in
  the specific previous output's locking script per input. It still gives
  the important property (nothing about the transaction can change after
  signing without invalidating every signature on it); it just isn't
  bit-for-bit Bitcoin's exact preimage construction, which exists mainly to
  support script types this project doesn't have (P2SH, multisig, etc).
- **Full-chain replay is O(height) per fork-candidate block, not O(1).**
  Stated plainly in `blockchain.py`'s module docstring as a simplicity/
  correctness trade-off appropriate at this project's scale (demo chains:
  tens to low hundreds of blocks). A production node keeps incremental
  per-block undo diffs instead. Finding 5 above already gives the common
  case (extending the tip) its fast path; only genuine competing branches
  pay the replay cost.

## Verification after fixes

Full suite re-run after every fix above (87 tests, including regression
tests for findings #1, #2, #3, #6, and #7 -- the last two only exist
because actually *running* the shipped explorer server surfaced bugs no
amount of reading the code, or running the pre-existing unit suite, had
caught):

```
$ python3 -m unittest discover -s tests
.......................................................................................
----------------------------------------------------------------------
Ran 87 tests in ~13s

OK
```

A fresh manual run-through (`python3 cli.py demo`: mining, retargeting, a
real spend, an attempted double-spend, an attempted wrong-key spend, a
fork + reorg, and the wallet CLI's own persistence) was repeated after the
fixes and hits none of the issues listed above. The live explorer server
was also run for several minutes end to end after the fixes (not just
imported) and observed to: gossip real blocks between nodes, produce real
reorgs, converge to one chain, reject a live path-traversal attempt with a
plain 404, and successfully process a real signed send from the UI down to
a mined, balance-reflected confirmation.
