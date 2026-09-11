# Vein

A from-scratch **Proof-of-Work blockchain** — real secp256k1 ECDSA (the
actual curve Bitcoin uses, built from the field axioms up), a UTXO ledger
with a tiny Bitcoin-Script-style stack VM, real proof-of-work mining with
difficulty retargeting, and a genuine multi-process P2P gossip network
that resolves forks by cumulative proof of work — including a real reorg,
with correct UTXO rollback and replay, the way actual Bitcoin nodes do
it.

No cryptography library, no blockchain framework, no `hashlib` on the
runtime path: SHA-256, RIPEMD-160, HMAC-SHA256, and the full secp256k1
elliptic-curve group law are all implemented from their published specs
in `vein/crypto/`. `hashlib` appears exactly once in this codebase's
runtime-adjacent code — as a differential test oracle, never as a
dependency.

## What it is

Vein is a small but *real* Nakamoto-consensus network. Independent node
processes — actual OS processes, not threads standing in for them —
generate real secp256k1 keys, mine real blocks against a real
proof-of-work target, gossip them over real TCP sockets, and reconcile
disagreements by comparing genuine cumulative work, not a vote or a
leader. The flagship demo (`vein partition-demo`) proves this the hard
way: it starts four node processes, lets them mine together, then
**severs the network into two groups mid-run**. Each side keeps mining
and — critically — each side accepts a transaction that spends the exact
same coin two different ways (a real double-spend attempt). When the
partition heals, every node reorgs onto whichever side did more work,
and the losing side's spend disappears from every single node's ledger,
everywhere, with no arbiter and no special-casing — just the same
`add_block()` validation rule every block on the network has to pass.

## How to run it

```bash
# Full verification suite — unit tests, core walkthrough, a live wallet
# payment + block-explorer check, and the network-partition demo:
./demo.sh

# Or individually:
python3 -m unittest discover -s tests -v      # 70 unit tests
python3 -m vein.cli demo                       # single-process walkthrough
python3 -m vein.cli partition-demo             # 4 real subprocesses, a partition, a resolved double-spend

# Run a real node and talk to it:
python3 -m vein.cli node start --p2p-port 19000 --rpc-port 19100 --mine
python3 -m vein.cli wallet new --out alice.json
python3 -m vein.cli wallet balance --wallet alice.json --rpc http://127.0.0.1:19100
python3 -m vein.cli wallet send --wallet alice.json --rpc http://127.0.0.1:19100 \
  --to <address> --amount 100000000 --fee 500
python3 -m vein.cli explorer --rpc http://127.0.0.1:19100 --out explorer.html   # open in a browser
```

Everything is pure Python 3 standard library — no `pip install` needed.
The explorer is a self-contained HTML/CSS/JS file with no build step and
no external dependencies once written out.

## Feature list

**Required (all 4 shipped, each demonstrated end-to-end by `demo.sh`):**

1. **secp256k1 + ECDSA from scratch** (`vein/crypto/`) — field and point
   arithmetic (modular inverse, point add/double, scalar multiplication),
   RFC 6979 deterministic signing (reproducible signatures, and closes
   the real-world nonce-reuse key-leak vulnerability), SHA-256 and
   RIPEMD-160 implemented from their specs, HMAC-SHA256, Base58Check
   addresses.
2. **UTXO ledger + Script VM** (`vein/core/script.py`,
   `vein/core/transaction.py`) — a real stack-machine interpreter
   (`OP_DUP`/`OP_HASH160`/`OP_EQUALVERIFY`/`OP_CHECKSIG`/
   `OP_CHECKMULTISIG`), P2PKH and bare *m*-of-*n* multisig, the classic
   Satoshi-style sighash (blank every input's script except the one
   being signed, replaced with its own previous output's locking
   script), a real Merkle tree with proofs.
3. **Proof-of-work mining + validation** (`vein/core/block.py`,
   `vein/core/chain.py`) — Bitcoin's compact-bits target encoding, a
   genuine nonce search, and difficulty retargeting that measures real
   elapsed block time and adjusts the target toward a configured block
   time (clamped to a 4x swing per period, same as real Bitcoin).
4. **P2P gossip network + fork resolution** (`vein/node/p2p.py`,
   `vein/core/chain.py`) — real TCP sockets between independent
   processes, inv/getdata-style announce-then-fetch gossip with a
   seen-hash cache, and reorg by *greatest cumulative work* (not just
   "longest chain") with correct UTXO-set rollback and replay across the
   fork point.

**Stretch (both shipped):**

5. **Live block-explorer web UI** (`vein/explorer/explorer.html`) — a
   dark-themed, single-file page (no build step) showing a node's real
   chain, a clickable per-block transaction detail modal, live mempool,
   balance lookup, peer/severed-link status, chain-tips view, and a
   genuinely live Server-Sent-Events log — verified with a real
   headless-Chromium pass (zero console errors) against a live mining
   node.
6. **CLI wallet + orchestrated network-partition demo** — `vein wallet
   new/address/balance/send` builds and signs a real transaction and
   broadcasts it into a live network; `vein partition-demo` is the
   scenario described above, run against 4 real `vein node start`
   subprocesses talking only over their RPC APIs, exactly as an external
   operator would.

## Why I built this today

Every prior distributed-systems build in this repo picked a *coordinated*
model of agreement — Quorum implements Raft (a known leader, a
crash-fault-tolerant vote among trusted members); Concord implements a
CRDT (no leader, but no adversary and no scarcity either — every op just
merges by construction). Neither has anything to say about the one
problem Nakamoto consensus was actually invented to solve: how do
mutually distrusting, pseudonymous parties with no vote and no leader
agree on one history when any of them might be lying? Proof of work's
answer — make agreement *expensive* to fake, and make the tie-break a
public rule anyone can check — is a genuinely different shape of
consensus from anything else in this repo, and it comes with a failure
mode neither Raft nor CRDTs have: a reorg that retroactively invalidates
a transaction you already trusted. That's worth watching actually happen
against real UTXO state, not just asserted in a design doc — which is
exactly what `partition-demo` does.

## Adversarial review

Twelve real, distinct bugs were found and fixed while building this —
not retrofitted for the write-up. Two are worth calling out because of
how they were caught: a hand-transcribed elliptic-curve constant was
missing a single trailing hex digit (every signature would have silently
verified against the *wrong* curve point), caught only by deriving the
value independently from the curve equation rather than trusting a
second hand-typed "known-good" test value, which turned out to have the
*same* transcription mistake. And a real, unsynchronized-thread race
condition in the P2P layer (`Blockchain`/`Mempool` mutated from every
peer's own thread with no lock) only ever showed up under genuine
concurrent load — running the 4-process partition demo repeatedly until
it broke, not from reading the code. Full write-up with root causes and
fixes in [`REVIEW.md`](REVIEW.md).

## Where a human could take this next

- **Segregated witness / malleability-immune signing.** The current
  sighash (classic Satoshi-style) signs over scriptSigs implicitly by
  position; a witness-style split (signature data outside the
  transaction that determines the txid) is the real fix Bitcoin shipped
  for third-party transaction malleability, and would make an interesting
  follow-up build in its own right.
- **A real fee market + mempool eviction policy** under a block-size
  cap, so "which transactions get in" becomes an actual economic game
  rather than "everything that fits."
- **SPV / light-client mode**: Merkle proofs already exist
  (`transaction.py`'s `merkle_proof`) but nothing consumes them yet — a
  client that verifies payments from block headers alone, without ever
  downloading a full block, is most of the way there already.
- **A second, competing implementation** cross-validated against this
  one (the way this repo's Graft/Palimpsest git builds used real `git`
  as an oracle) — two independent chains that must produce byte-identical
  blocks from the same inputs would catch consensus-rule bugs neither
  implementation's own test suite would ever find alone.
- **Persistence.** Everything here lives in memory; a node restart loses
  its whole chain. A real on-disk block/UTXO store (and the crash-
  recovery discipline Matchbook's write-ahead journal already
  demonstrates elsewhere in this repo) is the natural next piece.
