# Genesis — a from-scratch blockchain (PoW + UTXO + P2P consensus)

## The concept

Build the actual mechanism behind a Bitcoin-style blockchain, from the bytes
up: proof-of-work mining with real difficulty retargeting, a UTXO ledger
where every spend is authorized by a real elliptic-curve signature, Merkle
trees for transaction commitment and light-client proofs, and — the part
that makes it a *blockchain* rather than just "a chain of hashes" — multiple
independent nodes that mine concurrently, disagree, and converge on one
canonical history via the longest-valid-chain rule, including rolling back
a chain reorg when a longer fork appears.

This repo has built a lot of cryptography (Cryptex, Ironkey) and a lot of
distributed consensus (Quorum's Raft), but never the specific combination
that makes a public blockchain interesting: **economic consensus** — nodes
that don't trust each other and have no leader, agreeing on a shared ledger
purely because the longest chain of expended computational work wins, and
a spend is only valid if it is signed by the key that actually owns the
coin. Graft (2026-07-02) built Git's object model; this builds Bitcoin's,
which looks similar (hash-linked blocks, content addressing) but solves a
completely different problem: not "track history of files I trust myself
to write" but "let mutually distrusting parties agree on one ledger with
no central authority."

## Why it's interesting

Three real, previously-unbuilt ideas come together and each is checkable
against ground truth, not just "looks plausible":

1. **Proof-of-work with real difficulty retargeting.** The target adjusts
   every N blocks based on actual observed mining time vs. the desired
   block interval — the same feedback loop that keeps Bitcoin's block time
   near 10 minutes regardless of total network hashrate. Verifiable: mine
   with a burst of extra (simulated) hashrate and check the target tightens
   within one retarget window, then check it loosens again when hashrate
   drops.
2. **UTXO + ECDSA authorization.** A transaction is only valid if it is
   signed by the private key matching the public key hash the referenced
   output actually locked to. From-scratch secp256k1 (the actual curve
   Bitcoin uses) point arithmetic, signing, and verification — no
   `ecdsa`/`cryptography` package. Verifiable: a transaction signed with
   the wrong key is provably rejected; a double-spend (two transactions
   racing to spend the same output) is provably rejected by whichever one
   loses the race.
3. **Multi-node consensus without a leader.** A deterministic, seeded
   discrete-event network (same pattern as Quorum, 2026-06-15) runs several
   nodes that each mine independently, gossip blocks to each other with
   simulated latency, and — this is the part that must be *demonstrated*,
   not asserted — when two nodes each mine a competing block at the same
   height, the network converges on one chain the moment a longer fork
   appears, and every node's UTXO set is provably identical afterward
   (including a real reorg that un-applies the losing fork's transactions
   and re-applies the winning fork's).

## Architecture

```
genesis/
  src/
    crypto.py       secp256k1 field/point arithmetic, ECDSA sign/verify,
                     keypair generation, base58check address encoding
    merkle.py        Merkle tree build, root, inclusion-proof gen + verify
    transaction.py   TxIn/TxOut/Transaction, signing, signature verification,
                     coinbase construction, (de)serialization, txid
    block.py         BlockHeader + Block, PoW mining loop, header hash
    blockchain.py    Chain: UTXO set, block validation, difficulty
                     retargeting, fork choice (cumulative work), reorg
    mempool.py       Pending-transaction pool, fee-priority selection,
                     conflict (double-spend) rejection
    node.py          A full node: chain + mempool + wallet + message
                     handlers (new block / new tx / get-blocks)
    network.py       Seeded discrete-event simulated network: latency,
                     gossip/broadcast, optional partitions
    wallet.py        Keypair + address management, UTXO-scan balance,
                     transaction construction
    server.py        stdlib http.server block-explorer backend + SSE feed
  static/index.html  Block explorer UI (zero client-side chain logic —
                     every view is data the server computed)
  tests/             unittest suite, one file per module + integration
  cli.py             Command-line entry point (mine / wallet / demo / serve)
  demo.sh            Scripted end-to-end run of every feature
```

Design choices, and why:
- **Hashing** uses `hashlib.sha256` (double-SHA256, as Bitcoin does) — the
  point of this project is the *protocol* (consensus, UTXO, PoW economics),
  not re-deriving SHA-256's bit-diffusion from scratch (Ironkey/Cryptex
  already did that). **Signing** (secp256k1 ECDSA) *is* built from scratch,
  because transaction authorization is the actual subject of feature 2.
- **Network** is a deterministic, seeded discrete-event simulation (not
  real sockets) — same justification as Quorum: a bug in "nodes converge
  on one chain" must be 100% reproducible from a seed, not a flaky timing
  race against real localhost sockets.
- **Server-backed explorer**, zero client-side chain logic (same pattern
  as Gambit/Formulate/Sift) — the browser only renders JSON the real chain
  computed; there is no parallel "pretend" implementation in JS.

## Features

**Required (core, Phase 2):**
1. **Proof-of-work mining with real difficulty retargeting** — SHA-256d
   header hashing against a numeric target, adjusted every N blocks from
   actual vs. expected elapsed time, clamped to a max 4x swing per window.
2. **UTXO ledger with from-scratch secp256k1 ECDSA** — every transaction
   input must carry a signature that verifies against the public-key hash
   the referenced output locked to; unsigned/wrongly-signed/double-spent
   transactions are rejected with a specific reason.
3. **Merkle tree commitment + inclusion proofs** — every block's
   transactions are committed to a Merkle root in the header; a
   light-client-style proof lets you verify one transaction is in a block
   without downloading the rest of it.
4. **Multi-node P2P consensus with fork resolution** — several simulated
   nodes mine independently, gossip blocks/transactions with latency, and
   converge on the cumulative-work-longest chain, including a real reorg
   (unwind losing fork's UTXO effects, apply winning fork's) when it wins
   after having already been behind.

**Stretch (Phase 4, at least 1 required):**
5. **Wallet**: keypair generation, base58check address derivation, balance
   by UTXO scan, and constructing+broadcasting a signed spend end to end.
6. **Interactive block explorer web UI**: browse the real chain, inspect a
   block's transactions and Merkle proof, watch mempool + mining + network
   convergence live via Server-Sent Events.

## Gates

Phase 2 is done when: a difficulty retarget is observed to move in both
directions from real mining; a tampered/wrongly-signed/double-spend
transaction is rejected with the correct reason; a Merkle proof for a real
transaction verifies and a forged one doesn't; and a simulated 3+ node
network demonstrably reorgs onto a longer fork with identical resulting
UTXO sets across all nodes.
