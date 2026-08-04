# Bedrock — a from-scratch blockchain & cryptocurrency network

## Concept

Bedrock is a working proof-of-work blockchain built entirely from first
principles: elliptic-curve wallets, Merkle-committed blocks, a real mining
loop with difficulty retargeting, a UTXO ledger with double-spend
prevention, a gossiping peer-to-peer network of independent node
processes, and a live block explorer. Give it a genesis block and some
CPU time and it behaves like a tiny, real Nakamoto-consensus network:
miners compete for block rewards, wallets sign and broadcast
transactions, nodes independently validate everything they receive, and
if two miners find a block at the same time the network provably
converges on the chain with more accumulated work.

## Why this is interesting

Every primitive Bedrock needs (SHA-256, elliptic-curve signatures) has
been built from scratch in this repo before (Cryptex, Ironkey) — but
never assembled into the system those primitives exist to power. The
closest neighbors are:

- **Cryptex / Ironkey** — cryptographic primitive libraries with a CLI,
  no ledger, no consensus, no network.
- **Quorum** — a *permissioned*, single-leader replicated log (Raft).
  Bedrock's consensus is the opposite shape: permissionless, leaderless,
  proof-of-work, and resolved by "most accumulated work wins," not by
  majority vote among known peers.
- **Graft / Strata / Palimpsest** — content-addressed DAGs (Git), but
  with no economic layer, no signatures over value transfer, and no
  network protocol.

Nothing in the ledger combines *economic double-spend prevention*,
*proof-of-work consensus*, and *a real multi-process gossip network*
into one system. That combination — not any single algorithm in
isolation — is the genuinely new territory today's build claims.

Ground truth is unusually strong for this domain: block hashes,
Merkle roots, and signatures are all independently re-derivable and
checkable bit-for-bit; double-spends, tampered blocks, and forged
signatures are supposed to be *rejected*, so adversarial tests have an
unambiguous correct answer (reject) rather than a fuzzy "looks right."

## Architecture

```
bedrock/
  crypto.py      secp256k1 field + point arithmetic, ECDSA sign/verify,
                  keypair generation, Bedrock address derivation
  merkle.py       Merkle tree build / root / inclusion proof + verify
  transaction.py  UTXO-model Tx/TxIn/TxOut, signing, sighash, coinbase
  block.py        BlockHeader + Block, canonical serialization, hashing
  pow.py          compact difficulty target encoding, mining loop,
                  retargeting algorithm
  chain.py        multi-branch block index, UTXO set, full validation,
                  fork-choice by cumulative work, reorg
  mempool.py      pending-tx pool validated against current UTXO set
  wallet.py       keypair/address management, coin selection, send()
  node.py         ties chain + mempool + wallet + miner into one node
  network.py      TCP socket P2P layer: handshake, inv/getdata gossip
                  of blocks & transactions, peer sync
  explorer.py     stdlib http.server block explorer + wallet UI
                  (server holds all logic, browser only renders)
  cli.py          `bedrock` command-line entry point
tests/            unit + property + adversarial test suite
demo.sh           end-to-end walkthrough of every feature
```

Data flows one direction for trust: a `Wallet` builds and signs a
`Transaction` → submits it to a `Node`'s `Mempool` (validated against the
current UTXO set) → a miner assembles a candidate `Block` from the
mempool and runs `pow.mine()` → once found, `Chain.add_block()`
re-validates everything independently (nothing is trusted just because
"this node produced it") → on the P2P network, every other `Node`
receiving the block via `network.py` runs the *exact same*
`Chain.add_block()` validation path before accepting it.

## Feature list

**Required (4):**

1. **Core chain data structure** — blocks with Merkle-committed
   transaction lists, canonical byte serialization, SHA-256d block
   hashing, a hash-linked chain from a hardcoded genesis block.
2. **Proof-of-Work mining with real difficulty retargeting** — a mining
   loop that searches nonce space for a hash under a compact-encoded
   target, and a retargeting algorithm that adjusts difficulty toward a
   target block interval based on actual elapsed mining time.
3. **secp256k1 wallets over a UTXO ledger** — from-scratch elliptic
   curve point arithmetic and ECDSA, address derivation, transaction
   signing/verification, balance computation from the UTXO set, and
   double-spend prevention (a UTXO can be spent at most once).
4. **Mempool, full validation, and chain reorganization** — pending
   transactions validated before block inclusion, every incoming block
   independently re-validated (PoW, Merkle root, signatures, no
   double-spends), and automatic reorg to whichever valid fork has the
   most cumulative work when chains diverge.

**Stretch (2+):**

5. **Real peer-to-peer network** — independent OS processes, each a
   full Bedrock node, gossiping new blocks and transactions to each
   other over real TCP sockets and converging on the same chain.
6. **Interactive block explorer + wallet web UI** — a server-backed
   browser UI (same zero-client-logic pattern as this repo's
   Gambit/Formulate/Faraday) to browse blocks/transactions, watch the
   mempool, create wallets, send coins, and mine — all live against a
   real running node.

## Verification strategy

- Merkle tree checked against an independent brute-force recursive
  hasher.
- ECDSA checked for sign→verify round-trips, rejection of any
  single-bit-flipped signature/message/pubkey, and rejection of a
  signature from the wrong key.
- Mining checked at low difficulty for speed; every found nonce
  independently re-hashed and compared against the target outside the
  miner.
- Adversarial chain tests: tampering with a transaction after mining
  (Merkle root must reject), double-spending a UTXO within a block and
  across two competing blocks, forging a signature, spending someone
  else's UTXO, replaying a transaction — all must be rejected with a
  named reason, never silently accepted.
- A real two/three-node network test on localhost: mine on one node,
  confirm the block and its coinbase reward propagate and every peer's
  UTXO set converges to the same state; force a fork (mine
  simultaneously on two nodes) and confirm the whole network reorgs
  onto the branch with more accumulated work.
