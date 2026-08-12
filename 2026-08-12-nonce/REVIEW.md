# Adversarial review

Hostile-reviewer pass against Nonce's own core build, hunting for bugs,
broken edge cases, and lazy shortcuts. Every issue below was reproduced
with a standalone script before being fixed, and a regression check was
re-run after the fix (the exact commands are inlined per finding so
they're reproducible, and the same scenarios now live in `tests/`).

## Issues found and fixed

### 1. `Transaction.txid()` cached a stale id, silently defeating merkle tamper detection (CRITICAL)

**Found while building the demo's own "Phase D: tamper detection" step**,
not by guessing — trying to prove tamper detection worked is what broke it.

`Transaction.txid()` memoized its result in `self._txid_cache` the first
time it was called. `Blockchain.build_candidate` computes every tx's
txid once (to build the merkle root) at block-assembly time. If a
`Transaction` object is later mutated (e.g. `copy.deepcopy` then flip an
output amount — exactly what an attacker relaying a block would do, and
exactly what my own adversarial test tried to do), `txid()` kept
returning the pre-mutation cached value. That meant `Blockchain`'s own
re-validation — which recomputes the merkle root from `tx.txid()` for
every transaction and compares it to the block header's committed root —
recomputed the *same, stale* root and the tampered block sailed through.
The one check whose entire job is catching exactly this kind of
after-the-fact rewrite was silently defeated by an unrelated performance
optimization.

**Fix:** removed the cache; `txid()` always recomputes from current
state. At this project's scale (a same-day demo chain, not a production
mempool processing thousands of tx/sec) the performance cost is
negligible next to getting tamper-evidence actually right.

```
# before the fix, this passed when it should have failed:
tampered = copy.deepcopy(mined_block)
tampered.transactions[0].outputs[0].amount += 1
chain.add_block(tampered)   # -> was accepted (stale cached txid == stale merkle root)
                             # -> now correctly rejected: "merkle root does not match..."
```

### 2. ECDSA `verify()` accepted non-canonical (high-S) signatures — transaction malleability (HIGH)

ECDSA signatures are symmetric in `s`: both `s` and `N - s` verify
against the same `(r, z, pubkey)`. `sign()` always normalized to low-S,
but `verify()` didn't *require* low-S, so a third party intercepting a
broadcast, valid, low-S-signed transaction could republish it with
`s → N - s`. The signature is still valid, the transaction still spends
the same inputs to the same outputs, but `txid()` includes the raw
signature bytes, so **the transaction id changes** without the sender's
consent or knowledge — the exact bug class (transaction malleability)
that motivated Bitcoin's real BIP-62. A wallet or block explorer tracking
"has txid X confirmed yet?" could be fooled into thinking a payment
vanished and reappeared as something else.

**Fix:** `verify()` now rejects any signature with `s > N // 2`. Since
`sign()` never produces one, this makes low-S the single canonical
encoding a valid signature can have — the malleated high-S version is
simply invalid.

```
r, s = tx.inputs[0].signature
high_s = ec.N - s
assert ec.verify(pub, sighash, (r, s)) is True        # original: valid
assert ec.verify(pub, sighash, (r, high_s)) is False   # malleated: now correctly rejected
```

### 3. `Blockchain.mine_new_block` selected transactions against a static UTXO set — two real correctness bugs (HIGH)

The original selection loop checked every candidate mempool transaction's
inputs against `self.utxo_set` (the confirmed set) without ever updating
it as transactions were accepted. Two concrete failure modes:

- **Wasted, DOA mining work.** Two mempool transactions that both spend
  the *same* confirmed UTXO (a double-spend attempt) each look valid in
  isolation against the static set, so both would be selected into the
  same block. The block would then grind real proof-of-work... only to
  be rejected wholesale by `add_block`'s real validation the moment it's
  submitted, because the second transaction spends an already-spent
  output *within the block itself*. All of that mining work is thrown
  away for a block that could never have been accepted.
- **Legitimate chained transactions silently dropped.** If transaction B
  spends transaction A's own (not-yet-confirmed) output — completely
  valid the instant both land in the same block — the static-set check
  couldn't see A's new output yet, so B was silently excluded from every
  block template until A confirmed on its own first.

**Fix:** selection now walks a local scratch copy of the UTXO set and
applies each accepted transaction to it immediately, mirroring the exact
rules `_apply_transactions` uses for real block validation. A block
assembled this way can never contain an internal double-spend, and a
valid same-block transaction chain is now included correctly.

```
# conflicting txs spending the same UTXO: only one survives selection
blk = chain.mine_new_block([tx1, tx2], ...)   # tx1, tx2 both spend utxo_key
assert len([t for t in blk.transactions if not t.is_coinbase()]) == 1

# chained txs: both included together
blk2 = chain.mine_new_block([tx_a, tx_b], ...)  # tx_b spends tx_a's own new output
assert {tx_a.txid(), tx_b.txid()} <= {t.txid() for t in blk2.transactions}
```

### 4. Explorer's partition demo silently never ran on a 2-node network (LOW)

`Simulation._start_partition` required `len(self.node_names) >= 3`, but a
network partition is a perfectly meaningful thing to demonstrate with
exactly 2 nodes (`{N1}` vs `{N2}`) — the guard was needlessly conservative
and would make `nonce explorer --nodes 2` silently never show its
headline P2P-consensus behavior. Loosened to `>= 2`.

### 5. No validation that a destination address is well-formed — a typo silently burns funds (HIGH, UX/correctness)

**Found by my own test-harness mistake while manually poking the new
`nonce local send` command**: a shell one-liner extracting a wallet
address from `nonce wallet`'s output had a field-splitting bug and fed
the literal string `notAnAddress` in as a payment destination. The
transaction built, signed, mined, and confirmed *without a single
complaint*. `TxOut` never validates its own `to_address`, and nothing
upstream of it did either — `Wallet.build_transaction` just drops
whatever string it's given straight into a `TxOut`. Since nothing can
ever produce a private key whose address matches a garbage string,
those coins are gone: not stolen, just permanently unspendable, and the
sender has no way to find out until they go looking for funds that never
arrive. This is precisely the "empty/invalid input behavior" this phase
exists to shake out — it took an accidental bad input to surface it, but
a real user fat-fingering an address would hit the exact same silent
failure.

**Fix:** `Wallet.build_transaction` now calls `address_to_pkh(to_address)`
up front and raises `ValueError` with a clear message before doing any
UTXO selection or signing if the address doesn't decode as valid
base58check. Also tightened `base58.b58decode`/`b58check_decode` to raise
readable `ValueError`s (naming the bad character, or flagging a
too-short string) instead of leaking a raw `substring not found` /
index-out-of-range from the alphabet lookup.

```
nonce local send notAnAddress 1
# before: "sent 1.0 NCE to notAnAddress" (mined, funds gone)
# after:  "error: invalid recipient address — 'notAnAddress' is not a
#          valid Nonce address: bad base58check checksum"
```

### 6. Equal-work forks could leave the network *permanently* split after a partition heals (HIGH — found live, via the explorer)

Caught by actually watching the live explorer under Playwright, not by
reasoning about the code: the network log showed `partition healed,
resynced — STILL DIVERGENT at height 17` after a scripted
partition/heal cycle. Root cause: `add_block` only switched the active
tip when a competing block's cumulative work was *strictly greater* than
the current tip's ("first-seen wins" on a tie). Two independent miners
finding a block at nearly the same time — a routine, expected event in
any POW network, not an attack — produces exactly one such tie whenever
both sides of a partition mine the same number of blocks at the same
difficulty. With first-seen-wins as the *only* rule, different nodes
each keep whichever side *they personally* saw first, and since neither
side's work is ever strictly greater than the other's, nothing in
`resync_all` could ever force them back into agreement — the split
could persist forever, not just until the next block (in this run it
happened to self-resolve once mining continued and one side pulled
ahead, which is why the explorer's node panel later showed reconvergence
by tick 22 — but that resolution was luck, not a guarantee).

**Fix:** ties now break deterministically by hash (`work == tip_work and
new_hash < tip_hash`). Every node evaluates the exact same comparison
over the exact same two blocks once it has learned about both, so as
soon as a resync makes every node aware of every candidate, all of them
converge on the identical winner immediately — no need to wait for a
third block to break the tie. Verified with a 20-seed sweep forcing
exact-work ties under partition + heal: 0 failures to converge.

## Things considered and deliberately *not* changed

- **CVE-2012-2459-style merkle ambiguity.** Bitcoin's real merkle
  construction (odd-leaf-count duplication) has a known historical
  vulnerability where a block containing a literal duplicate transaction
  can produce the same root as a shorter list. `_apply_transactions`
  already rejects any block containing a duplicate txid outright (see
  `seen_txids` check), which closes this off completely — a block can
  never reach the merkle-ambiguous state in the first place. No further
  change needed; documented in `blockchain.py`.
- **Difficulty floor.** `next_bits` clamps any single retarget step to
  [0.25x, 4x] and clamps the resulting target to `>= 1`, but a
  target of literally 1 would make mining practically impossible. This
  is unreachable within any realistic demo run because the wall-clock
  feedback in the retarget formula is self-correcting long before the
  target could collapse that far — verified by running 40+ blocks and
  observing the difficulty stabilize rather than run away (see
  `tests/test_blockchain.py`). Documented rather than over-engineered.
- **No CLI `send` command / no mempool eviction / no cascading
  mempool invalidation.** Real gaps, but they're feature-completeness
  and UX items, not correctness bugs — addressed in the Phase 4 polish
  pass instead of here.

## Verification

Re-ran the full `nonce demo` scripted scenario and every standalone
repro script above after each fix — all green, zero regressions. The
scenarios above (plus the pre-existing full demo run) now live as
permanent regression tests in `tests/`, run by `demo.sh`.
