# Adversarial review

All 4 required features and both stretch features were fully built (core
crypto/chain/mining/network in Phase 2, the explorer UI and the attack
simulation in Phase 4) before this review pass, so the review could attack
the complete system — including the two stretch features — rather than
just the required core. Findings below are grouped by how they were found:
live bugs caught while building the demos, bugs found by deliberately
trying to break the system (the attack simulation itself doubles as
adversarial review), and issues found by re-reading the code looking for
lies — checks that don't actually check anything.

## Found and fixed

### 1. CRITICAL — nodes silently forked and never resynced (found while building the demo, before this review pass even started)

`Node._handle_message`'s `inv_block` handler fetched only the single
announced block. If a peer had fallen behind by more than one block —
trivially easy the moment mining ran continuously — `chain.add_block`
rejected the fetched block with "unknown parent" and the node just gave
up, forever. Two of three nodes in the very first end-to-end demo run
diverged onto a permanent fork (one node reached height 15 while the
other two sat at height 7 on a different tip) with zero errors reported
anywhere. Fixed by making `inv_block` trigger a full chain-hash-list
comparison and pull every missing block, the same logic already used at
connect time (`Node._sync_with_peer`), instead of assuming one fetch is
always enough.

Fixing this exposed a second problem: the naive fix (call the
request/response sync logic from inside the message-handling loop that
also *reads* the responses) deadlocks — a connection's single reader
thread can't wait on its own queue for a reply it would have to read
itself. Fixed by giving every request/response exchange its own
worker thread while a dedicated per-connection reader thread does
nothing but read-and-route, plus a per-socket send lock (concurrent
workers on one connection could otherwise interleave two messages'
raw bytes) and a per-socket request lock (so a reply is never delivered
to the wrong waiter). See the concurrency-model docstring at the top of
`concord/node.py`.

### 2. Miner could select two mutually-conflicting mempool transactions into the same candidate block

`build_candidate` checked each pending transaction against the live
chain UTXO set independently, not against a running "already spent by
an earlier transaction in this same candidate" set. If a double-spend
pair (two transactions spending the same input) both happened to be
sitting in one node's mempool at once, the miner could pick both into
one block, `_apply_block` would then correctly reject the whole block
for a within-block double-spend — but only *after* real proof-of-work
had been spent mining it. Fixed by giving `build_candidate` a working
UTXO copy that's debited as each transaction is tentatively included, so
a conflicting second transaction is skipped up front instead of
poisoning the block after the fact. Directly exercised by the attack
simulation's Part A.

### 3. Mempool never purged the losing side of a resolved double-spend

Once one side of a double-spend confirmed, the mempool removed that
transaction by txid (`remove_confirmed`) but had no mechanism to notice
that the *other*, still-pending transaction's input no longer existed in
the UTXO set. It would sit in the pool forever — never minable (the
miner's own UTXO check would always skip it) but also never reported as
rejected, and a naive future feature (e.g. "notify wallet when its
transaction is dropped") would have no signal to key off. Added
`Mempool.prune_conflicts(utxo)`, called everywhere the mempool is
already pruned for confirmed transactions, so a double-spend's loser is
explicitly, visibly dropped the moment its rival wins — verified
directly by the attack simulation's Part A assertion that both
transactions are gone from every mempool.

### 4. Tautological "merkle root mismatch" validation

`Blockchain._apply_block` compared a freshly computed Merkle root
against `block.merkle_root_hex` — but `merkle_root_hex` is *itself*
computed fresh from the same `block.transactions` list on every access
(and `Block.from_dict` discards the wire header's `merkle_root` field
entirely rather than trusting it). The comparison was checking a value
against itself: it could never fail, on any input, ever. This is
exactly the kind of check that reads as a real safeguard but does
nothing — caught only by tracing where each side of the comparison's
data actually came from, not by any test (a test can't fail a check
that structurally cannot fail). The system was not actually vulnerable
because of this — `block.hash()` (used for the real proof-of-work
check) is *also* always derived from the live transaction list, so
content-tampering still breaks the PoW match — but the dead code
implied an independent safeguard existed when it didn't. Removed it and
replaced with a comment explaining why block-content integrity doesn't
depend on it. See the comment in `concord/chain.py::_apply_block`.

### 5. No upper bound on block timestamps

`add_block` rejected a timestamp *before* its parent's but never
rejected one absurdly far in the *future*. Since difficulty retargeting
(`Blockchain.expected_target`) reads real ancestor timestamps to compute
elapsed wall-clock time for a retarget window, an unbounded future
timestamp would let a single miner manufacture an artificially long
"elapsed" window and inflate the next difficulty target (make the chain
easier) with no countervailing cost. Added a `MAX_FUTURE_DRIFT_SECONDS`
(1 hour) bound, the same category of defense real chains use (Bitcoin:
2 hours), sized generously for a toy chain rather than tuned tight.

### 6. ECDSA signature malleability

`verify()` checked `1 <= s < N` but not the canonical low-s form. ECDSA's
verification equation is symmetric under `s -> N - s`: *anyone* — not
just the private key holder — can flip a valid signature into a
different-but-still-valid one for the exact same message. Since a
transaction's txid hashes its own signature bytes, that flip mints a
second, different txid for a semantically identical, already-signed
transaction (the exact well-known "transaction malleability" bug class
from pre-SegWit Bitcoin). `sign()` already only ever emitted low-s
signatures, so this was latent — nothing in the demos exercised it — but
it's real and cheap to close: `verify()` now rejects any signature with
`s > N // 2`.

### 7. Invalid destination address silently accepted and un-spendably burned funds

`Wallet.build_transaction` never validated `to_address`. A typo'd or
malformed address wouldn't bounce — it would be accepted as a completely
normal output, and since no private key can ever produce a signature
whose pubkey hashes to a malformed/mistyped address, the funds would be
gone with no error at any point, ever. Added an
`curve.is_valid_address()` check that fails loudly at construction time
instead. Also added a `fee < 0` guard alongside it. The CLI's `send`,
`genesis-create`, and wallet-loading commands were also silently letting
raw tracebacks reach the user on bad input (missing wallet file,
unreachable node, malformed genesis) — wrapped with clean `error:`
messages and exit code 1, matching the "no raw tracebacks on bad input"
bar every other command already met.

### 8. Uncanonical EC point encoding accepted

`decompress_pubkey` computed `y` from `x` without checking `x < P`
first. An out-of-range `x` (a value that fits in 32 bytes but isn't a
valid field element) would still run through the modular arithmetic and
produce *some* answer rather than being rejected as the malformed
encoding it is. Added the range check.

### 9. Flaky demo/attack-script assertions (test bugs, not Concord bugs)

While stress-testing the fixes above, `concord.demo` and
`concord.attack_demo` both failed intermittently (~1 in 4-5 runs) with
"transaction did not propagate to every node's mempool" — even though
tracing the failure showed the payment had actually succeeded (the
recipient's balance was correct and the transaction was already
confirmed on-chain). Root cause: mining can be fast enough (sub-100ms
blocks under light load with 3 concurrent miners) to confirm a
transaction — and prune it out of the mempool — in *less time than the
polling loop's interval*, so "is it sitmempool ting in the mempool
right now" can be transiently, correctly false on both sides of the
pending window: before it arrives, and after it's already confirmed.
Fixed by adding `_netutil.tx_is_known()` (true if a transaction is
pending in the mempool *or* already present in a confirmed block) and
using it everywhere a script was waiting for "has the network seen this
transaction" rather than literally "is this specific transaction
pending right now". Re-ran each script multiple times back to back after
the fix (`concord.demo` x8, `concord.attack_demo` x3) with zero further
failures.
This wasn't a defect in Concord's actual consensus or gossip logic —
mining fast enough to beat a 100ms polling loop is a *good* problem to
have — but it was a real bug in the verification code, and a flaky demo
that "usually passes" is exactly the kind of shortcut this phase exists
to catch.

### 10. Attack script assumed forks can't happen between honest miners (found while writing `demo.sh`)

`concord.attack_demo`'s Part B, after confirming `tx_pay`, re-read
`merchant2.balance(...)` a second time and assumed the confirming block
was positionally "one block before whatever the current tip is". Both
assumptions break under completely normal operation: with 3 independent
miners racing concurrently, short 1-block forks between them are
expected, and a block that confirms a payment can itself transiently
lose a fork moments later (the payment goes back to the mempool and gets
re-mined shortly after) — so a second balance check performed slightly
later isn't guaranteed to still read 300, and by the time the network
converges, more blocks may have been mined on top of the confirming one,
making "tip's parent" the wrong block entirely. Both are visible only
under real timing with real concurrent miners — nothing about them is
wrong in a single-miner or synchronous test. Fixed by searching the
chain directly for the block that actually contains `tx_pay`, re-running
that search after convergence rather than trusting an earlier snapshot,
and deriving the fork point from *that* block's parent rather than from
whatever the tip happens to be. Re-ran 3 times after the fix with zero
failures.

## Deliberately not changed (real limitations, disclosed rather than hidden)

- **Mempool has no fee-market ordering.** `Mempool.select_for_block`
  returns pending transactions in FIFO insertion order, not
  highest-fee-first. For a demo chain with no real fee pressure this is
  fine and honest; a production mempool would need a fee-prioritized
  data structure.
- **No mempool chaining.** A transaction spending an *unconfirmed*
  parent transaction's output is rejected outright (the parent's output
  isn't yet in `chain.utxo`) rather than tracked as a dependent. This
  fails safely (the child is just rejected, nothing corrupts) rather
  than silently — a reasonable simplification for a from-scratch system
  built in a day, but real wallets sending rapid change-chained payments
  would need this.
- **Addresses use `SHA256(SHA256(pubkey))`, not `RIPEMD160(SHA256(pubkey))`.**
  Documented up front in `PLAN.md` — Python's `hashlib` does not
  guarantee RIPEMD-160 is available (OpenSSL 3.x disables legacy digests
  on many distros), so this uses a second SHA-256 round through the same
  from-scratch base58check envelope instead.
- **The explorer's `/api/submit_tx` trusts the client-supplied
  `Content-Length` header** for a local demo HTTP server with no
  authentication — a large bogus length could tie up a handler thread.
  Acceptable for a same-box demo API; a production version would cap
  request size.
- **Difficulty is tuned for demo speed, not security.** `GENESIS_TARGET`
  is deliberately low (~65,536 expected attempts, well under a second
  per block on this box) so a full multi-node demo finishes in seconds
  rather than modeling real-world ASIC difficulty. Called out in
  `PLAN.md` from the start.
