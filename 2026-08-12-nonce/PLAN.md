# Nonce — a blockchain / cryptocurrency built entirely from scratch

## Concept

Every prior "distributed systems" build in this ledger has been **crash-fault
tolerant** consensus (Quorum's Raft: trusted nodes, majority vote, no
adversary). Every prior "crypto" build (Cryptex, Ironkey) has been a bag of
primitives — AES, RSA, ECDSA — wired into a password vault or a messaging
session, never into a ledger. Nobody in this repo has built a
**Byzantine / trustless** consensus system: a network of mutually
un-trusting nodes that agree on a shared, tamper-evident history *without*
a majority vote, using proof-of-work instead. That's what a blockchain is,
and it's genuinely new ground here.

Nonce is a small but real Nakamoto-consensus blockchain:

- **Real proof-of-work.** SHA-256d block hashing, an adjustable difficulty
  target, an actual mining loop that grinds nonces until it finds a hash
  under the target — not a mocked "block is valid because I said so."
- **Real signatures.** A from-scratch secp256k1 elliptic-curve implementation
  (the actual Bitcoin/Ethereum curve) with real ECDSA sign/verify, checked
  against RFC 6979-style deterministic-k test vectors and round-tripped
  through thousands of random messages.
- **Real UTXO accounting.** Transactions spend previous outputs and create
  new ones; a node that doesn't know about a UTXO, or sees it spent twice,
  rejects the transaction. No "balance" field anywhere — balances are a
  *query* over the UTXO set, exactly like real Bitcoin.
- **A real (simulated) P2P network.** Multiple independent `Node` objects,
  each with its own chain, mempool, and validation logic, gossiping blocks
  and transactions over an in-memory message bus that can drop/delay
  messages and partition the network. Consensus (longest valid chain,
  a.k.a. Nakamoto consensus) emerges from independent nodes reaching the
  same state, not from one shared object pretending to be many.

## Why this is interesting

Because it's the one thing conspicuously missing from a repo that has built
CDCL SAT solvers, three flavors of transformer, a version-control system, a
relational database, and a Raft cluster: an adversarial, trust-minimized
protocol where "correctness" isn't just "does the algorithm terminate" but
"can an honest node be tricked by a dishonest one." Building it forces real
engineering on double-spend prevention, chain reorganization, orphan block
handling, and signature/hash tamper-detection — all independently
verifiable (flip one byte anywhere in history and the whole chain must be
provably invalid).

## Architecture

```
nonce/
  crypto/
    sha256.py        # from-scratch SHA-256 (FIPS 180-4), used for SHA-256d
    secp256k1.py      # from-scratch EC point arithmetic + ECDSA sign/verify
  core/
    merkle.py         # merkle tree build + inclusion proof + verify
    transaction.py     # TxIn/TxOut, UTXO model, signing, (de)serialization
    block.py           # BlockHeader + Block, hashing, POW check
    blockchain.py       # chain state, UTXO set, validation, reorg logic
    miner.py            # mining loop (nonce grinding to target)
    difficulty.py        # retarget algorithm
  network/
    bus.py              # in-memory message bus: delay/drop/partition
    node.py              # full node: mempool, chain, gossip, peer set
  wallet.py               # keypair + address generation, tx building
  explorer_server.py       # stdlib http.server backing the HTML explorer
  explorer.html             # self-contained interactive block explorer UI
  cli.py                     # `nonce` command-line entry point
  tests/                      # unit + integration + adversarial test suite
  demo.sh                      # end-to-end scripted walkthrough
```

Data flow: a `Wallet` builds and signs a `Transaction` spending known
UTXOs → broadcast onto a `Node`'s mempool → gossiped to peers over the
`Bus` → a `Miner` on some node assembles a block from mempool txs, builds
the merkle root, and grinds nonces until `sha256d(header) < target` →
the mined `Block` is gossiped → every receiving node independently
re-validates every transaction, the merkle root, the POW, and the link to
its own chain tip before accepting it → nodes on a shorter fork discard
their chain and reorg onto the longer valid one, restoring any of their
own now-orphaned transactions back to their mempool.

## Feature list

**Required (core, must work end-to-end):**

1. **Proof-of-work blockchain core** — SHA-256d block hashing, adjustable
   difficulty target, genesis block, header linking (`prev_hash`), and a
   real mining loop that finds valid nonces.
2. **secp256k1 ECDSA wallets & signed UTXO transactions** — from-scratch
   elliptic-curve point arithmetic, deterministic-k ECDSA sign/verify,
   address derivation, and a UTXO transaction model where every input must
   carry a valid signature over the tx and reference an unspent output.
3. **Merkle-tree transaction commitment** — every block commits to its
   transaction set via a merkle root; single-transaction inclusion proofs
   can be built and verified without the whole block.
4. **P2P network simulation with Nakamoto consensus** — multiple
   independently-validating `Node`s gossiping over an in-memory bus
   (with configurable delay/drop/partition), longest-valid-chain rule,
   automatic reorg onto a longer fork, orphan-block buffering, and
   double-spend / bad-signature / bad-POW rejection enforced independently
   by every node (not a shared oracle).

**Stretch (implement at least one):**

5. **Difficulty retargeting** — every N blocks, adjust the POW target
   toward a configured target block time, exactly like Bitcoin's 2016-block
   retarget but compressed to a demo-friendly window; demonstrated by
   forcing a hash-rate change and showing the target move.
6. **Interactive HTML block explorer** — a self-contained page (served by a
   stdlib `http.server` backend, zero client-side ledger logic) that shows
   the live chain, per-block transactions, the mempool, per-node views
   during a simulated network partition, and a visualized reorg event.

## Verification plan

- Crypto layer: SHA-256 checked against FIPS 180-4 / NIST test vectors;
  secp256k1 checked against known Bitcoin test vectors and thousands of
  random sign→verify round trips, plus negative tests (flipped bit in
  message/signature/pubkey must fail).
- Chain layer: tamper tests (flip one byte in any past block → chain
  validation fails at exactly that block); double-spend tests (same UTXO
  in two transactions → second rejected); orphan/reorg tests (two miners
  fork, longer chain wins, mempool of the losing node is restored).
- Network layer: partition a running network, mine on both sides, heal
  the partition, assert every node converges on the same tip and same
  UTXO set.
- `demo.sh` runs a scripted multi-node scenario end-to-end and a `tests/`
  suite covers unit + adversarial cases; both must pass green before ship.
