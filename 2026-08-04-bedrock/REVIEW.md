# Adversarial review — Bedrock

Phase 3: attacking the Phase 2 build as a hostile reviewer. Every issue
below was reproduced with a standalone script *before* being fixed, and
re-verified after. Ordered worst-first.

## Fixed issues

### 1. CRITICAL — multi-input transactions had an invalid first signature

`Transaction.sighash()` originally hashed the whole transaction with every
input's *signature* blanked but every input's *pubkey* left as-is. Signing
input 0 first (with input 1's pubkey still unset) produced a signature over
a digest that didn't yet include input 1's pubkey bytes. Signing input 1
afterward set its pubkey — which silently changed the sighash every input
was supposed to share, retroactively invalidating input 0's already-computed
signature.

Reproduced directly: mining two blocks to one wallet, then building a send
that needed both UTXOs as inputs, showed input 0's signature failing
verification while input 1's passed. Any transaction spending more than one
UTXO was unspendable — a wallet with a single big balance built from many
small deposits could never combine them.

**Fix:** redesigned `sighash()` to commit only to `(prev_txid, prev_index)`
per input plus the outputs and coinbase data — never pubkey or signature
bytes. Every input now signs an identical digest regardless of signing
order, so inputs can be signed in any sequence (or independently, by
different owners) without invalidating each other. Verified with a
regression test building and confirming a real 2-input transaction on
chain.

### 2. CRITICAL — genesis block was non-deterministic across processes

`create_genesis_block()` built its coinbase via `Transaction.new_coinbase()`,
which mixes in 8 random bytes on every call (by design, so ordinary block
coinbases at the same height never collide). That randomness leaked into
the *one* transaction that's supposed to be bit-for-bit identical across
every independently started Bedrock process. Two calls to
`create_genesis_block()` — i.e. two separately started `bedrock serve`
processes with no shared `--data` file — produced two different genesis
hashes and could never sync, no matter how correct the P2P layer was.

Reproduced directly: two calls to `create_genesis_block()` in the same
process returned different hashes; every earlier network test had
accidentally masked this by explicitly passing a shared `genesis_block=`
object between nodes instead of letting each construct its own.

**Fix:** genesis's coinbase is now built directly with fixed content (no
random component), and the mined result is cached at module scope so
repeated `Node()` construction doesn't even re-run the proof-of-work search.
Verified across three separate `python3` process invocations (not just
in-process) that the hash is identical every time, and that two brand-new
`Node()`s with no shared object between them can gossip and converge.

### 3. MODERATE — ECDSA signature malleability

`sign()` always produced the canonical low-S form, but `verify()` accepted
*either* `s` or `N-s` for the same `(r, message, pubkey)` — both are
mathematically valid. Anyone observing a broadcast, unconfirmed transaction
could flip its signature to the other valid encoding, producing a different
`txid` for the same economic transaction (classic pre-SegWit-era
malleability). Not currently exploitable against Bedrock's own consensus
(the mempool only ever lets you spend *confirmed* UTXOs, never another
pending transaction's output, so there's no unconfirmed-transaction-chain to
break), but it's the kind of latent bug that turns into a real one the
moment that assumption changes.

**Fix:** `verify()` now rejects any `s > N // 2`. Regression test confirms
a hand-flipped high-S signature is rejected while the original still
verifies.

### 4. MODERATE — two independent locks guarding one shared node

`NetworkNode` and `explorer.ExplorerState` each created their own
`threading.RLock()`, but when `bedrock serve --peer ...` runs both against
the *same* `Node`, HTTP-handler threads (mining/sending via the explorer)
and P2P peer-reader threads (ingesting gossiped blocks/transactions) were
mutating `node.chain`/`node.mempool` under two locks that never excluded
each other — no real mutual exclusion at all.

**Fix:** `NetworkNode` now accepts an external lock; `ExplorerState` reuses
`network.lock` whenever a network is attached instead of creating its own.

### 5. MODERATE — netnode's auto-mining loop wasn't holding the network lock

`cmd_netnode`'s periodic mining loop called `node.mine_block()` and
`net.announce_block()` without holding `net.lock`, while peer-reader threads
mutate the same node under that lock. A block arriving from a peer mid-mine
could interleave with the local mining call's own chain/mempool mutations.

**Fix:** the mine-and-announce call is now wrapped in `with net.lock:`.

### 6. MODERATE — a malformed peer message could kill that connection's thread

`_handle_message` was called outside any exception handler broad enough to
catch a malformed/adversarial message (bad hex, truncated block bytes,
missing fields) — only `(OSError, ConnectionError)` was caught around the
whole read loop. Reproduced by hand-sending `{"type":"block","data":"not
valid hex!!"}` over a raw socket: the peer thread died mid-message with an
uncaught exception, a one-line way for any peer to end that connection's
message processing.

**Fix:** each message dispatch is now individually wrapped; a bad message
is logged and skipped, and the connection keeps serving subsequent valid
messages. Verified live: after three different malformed messages, the
same connection still answered a `get_chain` request correctly.

### 7. MINOR — an unvalidated miner address silently burned the block reward

`Node.mine_block()` took a raw address string with no format check. A typo
in a reward address would still "successfully" mine a block — the coins
just become permanently unspendable, with no warning anywhere. The CLI's
own `cmd_mine` already validated this, but the underlying library call
(used directly by the explorer and by anyone using Bedrock as a library)
did not.

**Fix:** `Node.mine_block()` now validates the address up front and raises
`ChainError` with a clear message instead of mining silently.

### 8. MINOR — mempool block-selection docstring didn't match behavior

`Mempool.select_for_block()` claimed "greedy-by-fee-rate selection" but
actually returned transactions in plain dict-insertion order — the
docstring described a feature that didn't exist.

**Fix:** implemented real fee-priority ordering (highest absolute fee
first), backed by a new `Chain.transaction_fee()` helper that also replaced
a second, separately-maintained fee-computation copy that used to live in
`Node._tx_fee` — one implementation instead of two that could drift apart.
(Still a simplification vs. real fee-*rate*: nothing here tracks serialized
transaction byte size, so this ranks by absolute fee, not fee/byte —
documented, not hidden.)

### 9. MINOR — CLI amount parsing went through `float`

`parse_coin()` computed `round(float(s) * COIN)`. `float` can't exactly
represent most decimal fractions; for a currency's own amount parser,
"close enough" rounding is exactly the wrong failure mode.

**Fix:** rewritten on `decimal.Decimal`, which also now rejects an amount
specifying more precision than Bedrock's 8 decimal places support, rather
than silently rounding it away.

### 10. Cosmetic — dead/confusing code

`cmd_serve` had a no-op `for w in wallets.values(): pass` loop left over
from an earlier draft, and `cmd_netnode` had a redundant `if
args.miner_address: miner_wallet = args.miner_address` where a direct
assignment does the same thing. Both cleaned up.

## Reviewed and explicitly accepted (not bugs, documented limitations)

- **Timestamp rule is "> parent" + a future-drift cap, not full
  median-time-past.** A single miner could nudge retargeting within the
  existing ±4x-per-interval clamp by timestamp choice. Bounded impact,
  matching real Bitcoin's own exposure to the same class of manipulation;
  implementing full BIP113-style median-of-11 hardening was judged not
  worth the added complexity for a demo-scale chain.
- **No cross-chain replay protection** (no chain-id committed in the
  sighash). Irrelevant within a single chain; out of scope since nothing in
  PLAN.md promises multi-network interop.
- **Orphan pool and gossip seen-sets have no eviction policy or size cap.**
  Unbounded memory growth is possible under sustained adversarial flooding.
  Acceptable at the demo/localhost scale this build targets; called out
  rather than silently shipped.
- **No mempool fee floor, anti-spam policy, or per-node transaction cap.**
- **Reorg replays the entire candidate chain from genesis** rather than
  using incremental undo/redo. O(chain length) per reorg — fine at demo
  scale (tested up to a few dozen blocks), a deliberate simplicity-over-
  performance tradeoff.
- **Merkle duplicate-transaction attack (the real-world CVE-2012-2459
  class)** — checked explicitly: `Chain._validate_block_structure` rejects
  any block containing a duplicate transaction id outright, independent of
  what the Merkle math alone would allow, so a bogus block can't get a
  colliding root by duplicating a transaction.
- **Sending to a syntactically-invalid Bedrock address is only rejected by
  `Wallet.build_transaction`, not at chain-consensus level.** A
  hand-crafted transaction that bypassed the wallet layer could still
  confirm with a garbage output address — no correctness/inflation risk
  (those funds are then providably unspendable, the same economic effect as
  a burn), so left as a wallet-layer guard rather than a consensus rule.

## Verification

Every fix above was reproduced as a failing standalone script first, then
re-run passing after the fix (see the fix descriptions for what each
regression check covers). All of these became permanent regression tests in
Phase 5's test suite, not just one-off scripts.
