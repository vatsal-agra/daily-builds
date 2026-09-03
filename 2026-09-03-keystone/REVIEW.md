# Adversarial review

This build was attacked as a hostile reviewer would: forged signatures,
double-spends, malformed network input, deep orphan chains, network
partitions, and — most productively — just running the real multi-node
`keystone demo` CLI dozens of times in a row and refusing to accept
"usually converges" as good enough. Every finding below was reproduced,
root-caused, fixed, and then re-verified with the same repro that found it.

## Findings

### 1. Difficulty retarget cliff — the critical bug (`pow.py`, `chain.py`)

**Severity: critical — this was silently breaking the network's core
liveness guarantee.**

`keystone demo` failed to converge on one tip in roughly 40–60% of 5-node
runs once the chain crossed height 10 (the first `RETARGET_INTERVAL`
boundary). Debugging this needed real instrumentation, not guesswork:
`chain.tip_hash` diffs between nodes showed every node *already aware* of
both competing tips, tied at identical cumulative work — a legitimate
Nakamoto-consensus tie, not a gossip bug. Since a tie can only be broken by
someone finding the *next* block, the real question was why, with 5 threads
mining continuously, nobody found a block for 8+ seconds when the
difficulty should have needed ~65,537 expected hashes at ~30,000
hashes/sec/thread under GIL contention (should resolve in ~2s worst case).

Instrumenting `assemble_template()` to log the actual bits and expected
hash count per attempt found it immediately:

```
height=9  bits=0x1f00ffff  expected_hashes=65,537
height=10 bits=0x1d00ffff  expected_hashes=4,295,032,833   <- 65536x harder
```

Root cause: `pow.py`'s `MAX_TARGET` was set to `(1<<224)-1` with the comment
"genesis / easiest-allowed difficulty," but the CLI's own `DEMO_BITS`
(`0x1f00ffff`) decoded to a target of *roughly 2^240* — comfortably
**easier** than that ceiling. Nothing validated this invariant at genesis
time, so the chain mined perfectly well for the first `RETARGET_INTERVAL`
blocks. Then `next_bits()`'s clamp —

```python
new_target = min(new_target, MAX_TARGET)
```

— fired, and because it clamps the *result* rather than scaling smoothly,
it silently snapped the target all the way down to `MAX_TARGET` regardless
of the actual 1x–4x retarget ratio the timespan math had computed. The
result wasn't a difficulty *adjustment*, it was a **cliff**: a starting
difficulty needing 65,537 expected hashes suddenly needed 4.3 billion,
which at real achievable hash rates would take real *hours*, not seconds —
so of course an 8-second settle window (or even a much longer one) never
saw a tie-breaking block.

This was a genuine design bug, not a tuning knob: `MAX_TARGET` had been
carried over as a scaled-down echo of Bitcoin's own genesis-difficulty
*concept* without being calibrated against what this build actually needs
— a compressed `TARGET_BLOCK_TIME` of 0.5s against pure-Python hash rates of
tens of thousands of hashes/sec, not ASIC hashrate against a 10-minute
block time.

**Fix (two parts, defense in depth):**
- Raised `MAX_TARGET` to `(1<<250)-1` (~64 expected hashes at the ceiling
  itself), calibrated against this box's real hash rate so `DEMO_BITS`
  sits comfortably *below* (harder than) the ceiling with ~1024x of
  genuine headroom — several retarget periods' worth before the clamp
  could ever matter again for a realistic demo run.
- Added a loud constructor-time check in `Blockchain.__init__`: a genesis
  block whose difficulty is easier than `MAX_TARGET` now raises
  `ChainError` immediately, with an explanation of exactly this failure
  mode, instead of mining fine for one retarget period and then silently
  falling off a cliff.

**Verification:** 10/10 five-node `keystone demo` runs converged (was
failing ~40-60% before the fix); 3/3 longer 15-second runs crossing 2–3
retarget boundaries (heights 29–33) all converged cleanly.

### 2. Reorg counter undercounted orphan-triggered reorgs (`chain.py`, `network.py`)

Found while writing the very first multi-node network test: a node's
`net.reorg_count` stayed at 0 across a run that had *just* demonstrably
reorged (tips converged, one side's balances zeroed out). Root cause: the
counter lived in `Node._receive_block()`, incremented only for a reorg
triggered by the block *that message itself* carried. But `chain.add_block`
recursively resolves any orphans that block unblocks via its own internal
call, and *that* call's reorg (if any) never passed back through
`_receive_block` to be counted. Fix: moved the counter into
`Blockchain.total_reorgs`, incremented directly inside `add_block` itself
regardless of who called it, so both the direct path and the recursive
orphan-resolution path are covered by one authoritative source of truth.
`Node.reorg_count` is now a thin property delegating to it.

### 3. Negative coinbase output amount not rejected (`utxo.py`)

`validate_and_apply_block`'s only coinbase check was
`coinbase_out > block_reward + total_fees`. A negative `coinbase_out`
trivially satisfies "not greater than" a positive reward — so a
block with a coinbase output of `amount=-1000` sailed through validation
entirely unchecked. Reproduced directly: tampered a mined block's coinbase
output to a negative amount, confirmed it was accepted before the fix.
Fixed with an explicit non-negative check on every coinbase output amount,
independent of the reward/fee arithmetic.

### 4. Empty-input non-coinbase transaction accepted (`utxo.py`)

A non-coinbase `Transaction(inputs=[], outputs=[])` has `total_in=0` and
`total_out=0`; the existing `total_out > total_in` check (`0 > 0`) never
fires, so a completely empty, useless transaction was "valid." Not
directly exploitable for theft, but it's a real hole (unbounded junk-txid
spam with zero cost) that a hostile peer could use to bloat every honest
node's chain state for free. Fixed by rejecting any non-coinbase
transaction with zero inputs outright.

### 5. Deep orphan-chain resolution used unbounded Python recursion (`chain.py`)

`add_block` resolved newly-unblocked orphans by calling itself directly,
and *that* call did the same for its own newly-unblocked orphans — a chain
of N buffered orphans arriving in reverse order recursed N Python stack
frames deep. A node genuinely catching up after falling behind (or a
burst of blocks arriving out of order over a lossy connection) could hit
`RecursionError` and silently stop syncing. Verified concretely: with
`sys.setrecursionlimit(50)`, feeding an 80-block chain in reverse order
crashed under the old recursive implementation; refactored to an explicit
work-queue (`deque`) driving the same orphan-resolution logic iteratively,
verified against the same lowered recursion limit with zero crashes and
full, correct resolution to the right tip.

Also added a `MAX_ORPHANS` cap (100) with oldest-first eviction, since an
unbounded orphan pool is itself a memory-exhaustion vector against a node
that's fed blocks from a chain it will never actually be able to complete
(a different genesis entirely, or deliberate spam). This is a genuine,
disclosed trade-off, not a fixed bug: a worst-case reverse-order burst
*larger* than the cap will not fully resolve (some orphans get evicted
before their parent arrives) — the same trade-off real Bitcoin Core's own
bounded orphan pool makes. Verified separately that (a) the cap never
causes a crash regardless of burst size, and (b) any realistic catch-up
scenario within the cap resolves completely and correctly.

### 6. A single malformed network message could kill a peer connection with an uncaught traceback (`network.py`)

`_peer_loop` only caught `(ConnectionClosed, OSError, ValueError)`. A
`"block"` message missing its `block` key, or a `"tx"` message carrying a
string instead of a transaction dict, raised `KeyError`/`TypeError` from
inside `_dispatch` — uncaught, killing that reader thread with a stack
trace dumped to stderr. Not a crash of the whole node (each peer connection
has its own daemon thread), but ugly and not what a hardened P2P node
should do facing a misbehaving or malicious peer. Reproduced with a raw
rogue socket sending four different malformed messages in a row; before
the fix, the connection's thread died on the first one. Fixed by widening
the catch around message dispatch specifically (not the whole peer loop)
to also cover `KeyError`/`TypeError`/`AttributeError`, dropping just the
bad message and continuing — verified the same node stayed fully
responsive to a legitimate message sent immediately afterward.

### 7. CLI demo's payment sender was hardcoded, making it a flaky no-op (`cli.py`)

The original demo sent a wallet-to-wallet payment from `node0`/`wallet0`
specifically, once, at the run's midpoint. But which node's coinbase
rewards actually end up matured and unspent (not orphaned by a reorg) is
down to real mining variance — `node0` isn't guaranteed to ever have a
spendable balance. Observed directly: a run where `node0`'s only mined
block lost every race and got reorged out, so wallet0's balance stayed 0
all run, and the "payment" silently never happened while the demo still
reported success. Fixed by scanning every node/wallet each tick and
sending from whichever one first has a real matured, spendable UTXO
(> fee), with the final report explicitly checking (via a captured
before-snapshot on the same node) that the recipient's balance strictly
increased — turning "the demo *tries* to show a payment" into "the demo
*proves* a payment landed," and it does now, reliably (10/10 runs).

### 8. Settle window waited passively instead of continuing to mine through a tie (`cli.py`)

A secondary, compounding issue on top of finding #1: even once the
retarget cliff was fixed, the demo's original "settle" phase called
`stop_mining()` immediately after the timed run and then just *waited* for
convergence. A genuine equal-work tie (two nodes finding a block at
virtually the same instant) is a normal, expected outcome of real Nakamoto
consensus — and it can *only* be broken by someone finding the next block,
never by waiting longer for messages that have already fully propagated.
Fixed by keeping mining active through the whole settle window and only
stopping once convergence is actually observed (or the window expires),
matching how a real network — and this build's own successful
partition/reconnect test — actually resolves a tie.

## Verified, not found broken: the OpenSSL independent-oracle cross-check

PLAN.md committed to cross-verifying the from-scratch secp256k1 ECDSA
implementation against real `openssl`, the same pattern this repo's Ironkey
build used. This was implemented (`tests/test_openssl_oracle.py` +
`tests/der_helpers.py`, hand-rolled minimal ASN.1 DER — no `cryptography`/
`pyasn1` package) and passes in both directions: our signatures verify
under real `openssl dgst -verify`, real `openssl`-produced signatures
verify under our `crypto.verify()`, a tampered signature is correctly
rejected by openssl, and `openssl ec -pubout` derives the same public key
from a raw private scalar we generated. This is reported here because it
was an explicit commitment worth confirming was actually delivered, not
just claimed.

## What this leaves disclosed rather than "fixed"

- **MAX_ORPHANS eviction** (finding #5): a genuine capacity/liveness
  trade-off, not a bug — documented above.
- **No persistence across process restarts.** Every chain/mempool lives
  in memory only, by design (PLAN.md never promised durability); a real
  production chain would need this, a demo doesn't.
- **No peer discovery beyond an explicit seed list.** Nodes connect to
  peers they're told about; there's no DNS-seed or peer-exchange protocol.
  Fine for a demo network of a handful of nodes, a real limitation at any
  larger scale.
