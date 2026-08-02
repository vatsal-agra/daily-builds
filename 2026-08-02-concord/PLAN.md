# Concord

## Concept

A cryptocurrency and blockchain built entirely from scratch in pure Python:
real elliptic-curve cryptography (secp256k1 — the actual curve Bitcoin and
Ethereum use), a UTXO transaction model, proof-of-work mining with
difficulty retargeting, and a real multi-node peer-to-peer network
(genuine TCP sockets, genuine independent OS threads acting as separate
nodes, no in-process shortcuts) that gossips blocks and transactions and
resolves forks by cumulative proof-of-work — the actual mechanism that
lets a network of mutually-distrusting nodes agree on one shared ledger
without a central authority.

## Why this is interesting

This repo has built a huge amount of "systems from scratch" — compilers,
JIT backends, chess engines, ray tracers, fluid simulators, a Raft
consensus simulator, several from-scratch transformers, search engines,
a git clone, a spreadsheet. It has never built a system whose entire
point is **adversarial, decentralized trust**: independent nodes that
don't trust each other, connected over a real network, agreeing on
history via computational cost rather than a designated leader (Raft's
consensus assumes a *benign* leader election; a blockchain must survive
someone actively trying to cheat). It's also the first project here to
implement public-key cryptography's actual field/group arithmetic
(modular inverse, elliptic-curve point addition/doubling, scalar
multiplication) rather than using symmetric ciphers (Cryptex, Ironkey did
AES/RSA/PBKDF2, not elliptic curves) or treating consensus as a scheduling
problem (Quorum's Raft has one leader at a time by design).

## Architecture

```
concord/
  curve.py       secp256k1 field + group arithmetic, ECDSA sign/verify,
                  base58check address encoding — all from scratch
  merkle.py       Merkle tree construction + inclusion proofs
  transaction.py  UTXO-model transactions, signing, hashing
  block.py        block header, block hashing, coinbase rules
  pow.py          proof-of-work target math + difficulty retargeting
  chain.py        the Blockchain: validation rules, UTXO set maintenance,
                  fork choice by cumulative work, reorg
  mempool.py      pending-transaction pool, double-spend rejection
  wallet.py       keypair + address management, balance, tx building
  node.py         P2P node: TCP server + peer connections, gossip
                  protocol (INV/GETBLOCK/GETDATA-style), sync-on-connect
  miner.py        mining loop (threaded, stoppable)
  explorer.py     stdlib http.server JSON API + serves the static UI
  cli.py          concord CLI: init/mine/send/balance/net/explorer/demo
web/
  index.html      block explorer UI (chain view, block/tx detail with a
                  live Merkle-proof visualizer, mempool, peer graph)
tests/            unit + integration test suite
demo.sh           runs a multi-node network, mines, transacts, attacks
                  it, and reports the outcome
```

## Features (required: 4, stretch: 2+)

1. **[REQUIRED] secp256k1 cryptography from scratch.** Finite-field
   arithmetic, elliptic-curve point addition/doubling/scalar
   multiplication, ECDSA keygen/sign/verify, and base58check address
   encoding — no `cryptography`/`ecdsa`/`secp256k1` package, no OpenSSL
   bindings beyond `hashlib`'s SHA-256.

2. **[REQUIRED] UTXO blockchain with full validation.** Blocks with a
   Merkle-committed transaction list, proof-of-work-linked headers, and a
   `Blockchain.add_block` that rejects: bad PoW, bad Merkle root, a
   transaction spending a UTXO that doesn't exist or is already spent,
   an invalid signature, inputs < outputs (excluding the coinbase), and
   a coinbase paying more than the block reward.

3. **[REQUIRED] Proof-of-work mining with real difficulty retargeting.**
   A threaded miner that searches nonces until `hash(header) < target`,
   with a Bitcoin-style retarget every N blocks based on actual observed
   block time vs. a target block time.

4. **[REQUIRED] Real multi-node P2P network with fork resolution.**
   Independent node processes/threads on real TCP sockets running a
   gossip protocol (inventory announce → fetch → relay, with a seen-set
   to stop flood loops), syncing a new peer's missing chain on connect,
   and resolving competing chains by total cumulative proof-of-work
   (not just chain length) — including actually orphaning blocks and
   restoring their transactions to the mempool on reorg.

5. **[STRETCH] Live web block explorer.** A server-backed (zero
   client-side chain logic) single-page UI: chain view, block detail
   with a real Merkle-proof visualizer (pick a tx, watch the sibling
   hashes combine up to the root), live mempool, and a peer-connectivity
   graph — polling a real running node's JSON API.

6. **[STRETCH] Double-spend / eclipse-style attack simulation.** A
   scripted demo where a dishonest node tries to broadcast conflicting
   transactions to different peers and privately mine an alternate
   chain to reverse a confirmed payment, with the honest network's
   cumulative-work fork choice defeating it — outcome measured and
   reported, not just asserted.

## Non-goals / honest simplifications (documented up front, not hidden)

- Addresses are `base58check(SHA256(SHA256(pubkey)))` truncated to 20
  bytes, not `RIPEMD160(SHA256(pubkey))` — Python's `hashlib` does not
  guarantee RIPEMD-160 availability (OpenSSL 3.x disables it by default
  on many distros). The two-SHA256 construction is not Bitcoin-bit-exact
  but uses the same base58check envelope and is exercised by the same
  from-scratch base58 code.
- Difficulty is kept low enough that mining finishes in seconds on this
  box, not ASIC-resistant real-world difficulty.
- The network is simulated on localhost (multiple real TCP ports, real
  threads, real sockets) rather than across real hosts, but the wire
  protocol has no localhost-specific shortcuts.
