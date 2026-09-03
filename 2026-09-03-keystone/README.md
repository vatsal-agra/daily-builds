# Keystone

A from-scratch proof-of-work blockchain & cryptocurrency, built entirely in
pure Python: secp256k1 elliptic-curve wallets, UTXO transactions locked by
a small stack-based scripting VM, Merkle-committed blocks, a real
hashcash-style mining search with Bitcoin-style difficulty retargeting,
full chain validation with fork resolution by cumulative proof-of-work,
and a genuine peer-to-peer network of independent nodes gossiping over
real TCP sockets.

## What it is

Every piece of a real cryptocurrency protocol, implemented and wired
together for real — not a simulation of one:

- **secp256k1 wallets**, hand-rolled: elliptic-curve point arithmetic,
  RFC-6979 deterministic ECDSA signing/verification, RIPEMD-160 (also
  from scratch — OpenSSL 3 dropped it, so it has to exist here or not at
  all), base58check addresses. Cross-verified against real `openssl` as
  an independent oracle, in both directions.
- **UTXO transactions & Merkle-committed blocks**: outputs are locked by
  a tiny stack-based scripting VM supporting both plain P2PKH and *m-of-n*
  multisig; blocks commit to their transaction set via a real Merkle root
  with inclusion proofs.
- **Proof-of-work mining**: a genuine nonce search against a compact-bits
  target, plus a periodic Bitcoin-style difficulty retarget from real
  elapsed mining time — calibrated for a runnable demo timescale
  (fractions of a second per block on this box), not Bitcoin's real-world
  10-minute/ASIC-hashrate scale.
- **A real P2P network**: independent `FullNode`s, each with its own
  chain and mempool, connected over actual `socket.socket` TCP
  connections, speaking an INV/GETDATA-style gossip protocol — a block or
  transaction is only ever sent in full to a peer that doesn't already
  have it. Forks are resolved by cumulative proof-of-work (not block
  count), with real reorgs and an orphan-block pool for out-of-order
  arrivals.
- **A block explorer** and **multisig scripting demo** as stretch
  features — see below.

## How to run it

```bash
cd 2026-09-03-keystone

python3 -m keystone keygen
# private key: ...
# public key:  ...
# address:     1EtqNn1pYcTmPDWLZAo16ucQNFmYoRg5LE

python3 -m keystone demo --nodes 4 --seconds 8
# spins up 4 independent nodes on real sockets, mines, gossips, sends a
# real wallet-to-wallet payment mid-run, and proves every node converges
# on identical UTXO balances

python3 -m keystone explorer --nodes 3 --seconds 20 --port 8080
# same demo network, plus a live block-explorer web UI at
# http://127.0.0.1:8080

python3 -m keystone script-demo
# standalone demonstration of 2-of-3 multisig locking/unlocking

./demo.sh
# the whole thing: 129 unit/integration tests, every CLI path, and a
# real headless-Chromium check of the explorer — all in one script
```

No dependencies beyond the Python 3 standard library for the actual
protocol. `demo.sh`'s optional browser check uses `playwright` +
pre-installed Chromium if available, and skips that one step cleanly
otherwise (everything it would check is also covered by plain-HTTP tests
in `tests/test_explorer.py`).

## Full feature list

**Required (all 4 shipped, demonstrably working end-to-end):**
1. secp256k1 wallets — from-scratch EC math, RFC-6979 ECDSA, RIPEMD-160,
   base58check addresses; cross-verified against real OpenSSL.
2. UTXO transactions & Merkle-committed blocks (P2PKH scripting, Merkle
   proofs, genesis anchoring).
3. Proof-of-work mining with Bitcoin-style difficulty retarget, and full
   chain validation (PoW, signatures, UTXO spends, no double-spends).
4. A real P2P gossip network with fork resolution by cumulative work,
   reorgs, and orphan-block handling.

**Stretch (both shipped):**
5. A server-rendered block explorer web UI (chain, blocks, transactions,
   address balances, live mempool — the browser holds zero ledger logic).
6. An *m*-of-*n* multisig scripting layer alongside plain P2PKH, on the
   same generic stack-based script executor.

## Why this, today

This repo has an unusually dense history of "from scratch" systems
builds — language runtimes and VMs, a CPU pipeline simulator, a Raft
consensus simulator, physics engines, several version-control systems and
full-text search engines, and (closest in spirit) Ironkey, a suite of
cryptographic *primitives*. None of that is a distributed ledger. Quorum
simulates consensus over an abstract log of opaque entries — it never has
to answer "whose money is this, and how do you prove you're allowed to
spend it?" Ironkey builds the crypto primitives but never puts a protocol
on top of them that has to resist an *economically* motivated adversary,
not just a cryptographic one — a double-spend, a fork, more hash power
than everyone else. Keystone is the first build here where several
byzantine, only-locally-informed nodes have to converge on one shared
truth with no central authority — the actual hard problem Bitcoin solved
in 2008, wired together end to end rather than sketched.

## Adversarial review, honestly

`REVIEW.md` has the full writeup. The headline finding: a **difficulty-
retarget cliff** was silently stalling the whole demo network at the very
first retarget boundary in roughly 40-60% of runs — `pow.MAX_TARGET` (the
documented "easiest allowed difficulty") was *harder* than the CLI's own
demo difficulty, so the chain mined fine for exactly one retarget period
and then the retarget clamp snapped difficulty from an expected 65,537
hashes/block to 4,295,032,833 (exactly 65536x) in one step — not a gradual
adjustment, a cliff. Root-caused by direct instrumentation (not
guesswork), fixed by recalibrating `MAX_TARGET` against this box's real
hash rate and adding a constructor-time check that catches the
misconfiguration loudly instead of letting it cliff a period later.

Eight more real bugs were found and fixed the same way — by actually
running the thing adversarially, not just reading the code: a reorg
counter that undercounted reorgs triggered via orphan-resolution
recursion, a negative-amount coinbase output that sailed through
validation, an empty-input transaction that was technically "valid," a
deep orphan chain that could blow Python's recursion limit, a malformed
network message that could kill a peer connection with a raw traceback, a
flaky demo payment that hardcoded a sender not guaranteed to ever have
funds, a settle phase that waited passively instead of continuing to mine
through a legitimate consensus tie, and — found while polishing the
"already shipped" explorer stretch feature — a `SyntaxError` that meant it
had never actually been imported before Phase 4, despite having been
written and reviewed by eye in Phase 2. That last one is worth sitting
with: writing code and reading it back is not the same as running it.

## Where a human could take this next

- **Real persistence.** Everything here lives in memory; a durable
  on-disk block/UTXO store (with the same kind of undo-log the in-memory
  reorg path already uses) would make a node survive a restart.
- **Peer discovery.** Nodes only ever connect to an explicit seed list —
  no DNS seeds, no peer-exchange (`ADDR`-style) protocol, so it doesn't
  scale past a demo-sized network as written.
- **SegWit-style malleability fix / real binary wire format.** Keystone
  hashes/serializes via canonical JSON rather than a bespoke binary
  format; a from-scratch binary serializer (with the transaction-
  malleability considerations that come with it) would be a genuinely
  meaty follow-on project in the same spirit as this one.
- **Lightning-style payment channels** on top of the existing multisig
  scripting primitive — Keystone already has the one ingredient (m-of-n
  locking) a simple two-party channel needs.
- **A real light-client / SPV mode**, using the Merkle inclusion proofs
  that already exist but currently go unused by anything except the test
  suite.
