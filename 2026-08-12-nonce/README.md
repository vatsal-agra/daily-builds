# Nonce

A blockchain / cryptocurrency built entirely from scratch: SHA-256,
secp256k1 ECDSA, merkle trees, UTXO transactions, proof-of-work mining,
and a simulated multi-node P2P network reaching Nakamoto consensus — no
crypto library, no blockchain framework, nothing imported that does the
interesting part for you.

![Nonce block explorer](docs/explorer-screenshot.png)

## What it is

Every prior "distributed systems" build in this repo (Quorum, 2026-06-15)
has been **crash-fault-tolerant** consensus: trusted nodes, majority
vote, no adversary. Every prior "crypto" build (Cryptex, Ironkey) has
been a bag of primitives wired into a vault or a messaging session, never
into a ledger. Nonce is a **Byzantine / trustless** system instead: a
network of mutually un-trusting nodes agreeing on a shared, tamper-evident
history *without* a majority vote, using proof-of-work — the one thing
conspicuously missing from a repo that has otherwise built CDCL SAT
solvers, three flavors of transformer, a version-control system, a
relational database, and a Raft cluster.

It's small, but everything in it is real:

- **Real proof-of-work.** SHA-256d block hashing, an adjustable
  difficulty target, a mining loop that actually grinds nonces until it
  finds a hash under the target.
- **Real signatures.** A from-scratch secp256k1 elliptic-curve
  implementation (the actual Bitcoin/Ethereum curve) with RFC-6979
  deterministic ECDSA, low-S canonicalization, and point/pubkey encoding
  checked against known values.
- **Real UTXO accounting.** Transactions spend previous outputs and
  create new ones; there's no "balance" field anywhere — a balance is a
  *query* over the UTXO set, exactly like real Bitcoin.
- **A real (simulated) P2P network.** Independent `Node` objects, each
  with its own chain, mempool, and validation logic, gossiping over an
  in-memory bus that can drop, delay, and partition messages. Consensus
  (longest-*work* chain, a.k.a. Nakamoto consensus) is an emergent
  property of every node applying the same rules independently — not a
  shared oracle.

## How to run it

```bash
cd 2026-08-12-nonce

python3 -m nonce wallet              # generate a keypair + address
python3 -m nonce mine --blocks 10    # mine a small isolated chain, print progress
python3 -m nonce demo                # full scripted multi-node scenario (see below)
python3 -m nonce explorer            # live block explorer at http://127.0.0.1:8420

# a persisted wallet + chain you can genuinely mine/send with across separate commands:
python3 -m nonce local init
python3 -m nonce local mine --blocks 5
python3 -m nonce local send <address> 1.5
python3 -m nonce local balance
python3 -m nonce local history

./demo.sh                            # full verification: 100 tests + scripted demo + CLI checks
```

`nonce demo` walks through, on real running nodes: mining and gossip
convergence, a signed payment confirming network-wide, a double-spend
attempt getting rejected, a tampered block getting caught by merkle
re-validation, a forged signature getting rejected, a network partition
forking the chain and a heal reconverging it, and a difficulty retarget
actually changing the proof-of-work target. Every phase is a real
assertion against real running code, not a printed narrative.

## Full feature list

**Required (all 4 work end-to-end):**

1. **Proof-of-work blockchain core** — SHA-256d hashing, genesis block,
   header linking, adjustable difficulty target, real nonce-grinding
   miner.
2. **secp256k1 ECDSA wallets & signed UTXO transactions** — from-scratch
   curve arithmetic, RFC-6979 deterministic signing, low-S enforcement,
   base58check addresses, a UTXO transaction model with real
   double-spend and forged-signature rejection.
3. **Merkle-tree transaction commitment** — every block commits to its
   tx set via a merkle root; single-tx inclusion proofs build and verify
   independently of the rest of the block.
4. **P2P network simulation with Nakamoto consensus** — independently
   validating nodes, gossip with a configurable-drop/delay/partition bus,
   longest-*work*-chain fork resolution with deterministic tie-breaking,
   automatic reorg with mempool restoration, orphan-block buffering.

**Stretch (both implemented):**

5. **Difficulty retargeting** — a Bitcoin-style retarget algorithm
   (compressed to a demo-friendly window) that visibly moves the target
   in response to actual block-arrival timing, clamped to ±4x per step.
6. **Interactive HTML block explorer** — a self-contained page (stdlib
   `http.server` backend, zero client-side ledger logic) showing the
   live chain, per-block transactions, per-node state, a live partition
   demonstration, and the network log — all real data polled from a
   real running multi-node simulation.

**Also shipped, beyond the plan:**

- A persisted `nonce local` CLI (`init` / `mine` / `send` / `balance` /
  `history` / `address`) — a wallet + chain you can genuinely use across
  separate command invocations, not just inside one in-memory demo run.
  Loading replays every block through real `add_block` validation, so a
  hand-tampered save file is caught exactly like a bad block from the
  network would be.
- A 100-test suite (`tests/`) covering every module, plus `demo.sh` that
  runs it alongside the scripted demo and a CLI sanity pass.

## Why I chose this today

I read `LEDGER.md` first, as instructed. This repo has built an enormous
amount of adjacent machinery — real cryptographic primitives (AES, RSA,
SHA-256, ECDSA, X25519 — Cryptex, Ironkey), a Raft consensus cluster
(Quorum), a from-scratch VCS with a real object store (Graft), a
relational database (Strata) — but never combined them into the one
system where they're all load-bearing *together* and where the interesting
failure mode is an adversary, not a crash. That gap is what made this
worth building: it's not a bag of primitives, it's the thing primitives
are *for*.

## Where a human could take this next

- **Script-based spending conditions.** Right now every output locks to
  a single pubkey hash (P2PKH-equivalent). A tiny Forth-like scripting
  layer (a handful of opcodes: `OP_CHECKSIG`, `OP_EQUAL`, `OP_DUP`,
  `OP_HASH160`, `OP_CHECKMULTISIG`) would unlock multisig wallets, time
  locks, and hash-locked contracts — the actual seed of what Bitcoin
  Script and, eventually, smart contracts became.
- **Real networking.** The P2P layer is an honest simulation (drop/delay/
  partition, independent validation) but runs in one process. Swapping
  the in-memory `Bus` for real TCP sockets (or even just separate OS
  processes talking over local ports) would be a natural, contained next
  step — the `Node` class's public interface (`handle_message`,
  `request_sync`) is already shaped like a wire protocol.
- **SPV / light clients.** The merkle-proof machinery (`merkle_proof` /
  `verify_merkle_proof`) is already there and tested but unused by any
  client — a light wallet that trusts only block headers plus an
  inclusion proof, rather than syncing the whole chain, would put it to
  work.
- **Mempool fee-priority mining.** Block templates currently include
  mempool transactions in arrival order; sorting by fee-per-byte (and
  handling child-pays-for-parent) would make the miner behave like a
  real economically-rational one.
- **Persistent multi-node explorer.** The explorer's simulation state
  lives only in memory; wiring `store.py`'s save/load into it would let
  the live network survive a server restart.

## Verification

See [PLAN.md](PLAN.md) for the original plan, [REVIEW.md](REVIEW.md) for
the adversarial review (8 real bugs found and fixed — including one that
silently defeated the tamper-detection check the review itself was
trying to prove worked), and run `./demo.sh` for the full green
end-to-end verification (100 tests + the scripted multi-node demo + a
persisted-CLI sanity pass).
