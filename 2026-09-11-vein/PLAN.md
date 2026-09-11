# Vein — a from-scratch Proof-of-Work blockchain

## Concept

Every prior distributed-systems build in this repo picked a *coordinated*
model of agreement: Quorum (2026-06-15) implements Raft — one elected
leader, a crash-fault-tolerant log, agreement by majority vote among known
members. Concord (2026-09-09) implements an RGA CRDT — no leader, but also
no economics and no way to disqualify a bad actor's edits; every op is
simply merged, by construction. Neither model has anything to say about
the actual hard problem Nakamoto consensus solves: how do a set of
**mutually distrusting, unauthenticated, pseudonymous** parties, who don't
know each other and can't take a vote, agree on one shared history when
any of them might lie, and the network itself might partition them for a
while? Bitcoin's 2008 answer — make agreement *expensive* to fake (proof
of work) and make the tie-break a public, checkable rule (longest valid
chain) — is a genuinely different shape of consensus problem from anything
this repo has built, and it comes with its own genuinely new failure mode
neither Raft nor CRDTs have: the **51% attack** / chain reorg, where the
"right" answer for a node can retroactively change out from under it.

Vein is a real, from-scratch PoW blockchain: real secp256k1 elliptic-curve
signatures (the actual curve Bitcoin uses, implemented from the field
axioms up — Cryptex/Ironkey, 2026-06-30/07-01, implemented P-256 and
X25519, never secp256k1), a real UTXO ledger with a tiny Bitcoin-Script-like
locking/unlocking VM, real proof-of-work mining against a retargeting
difficulty, and a real multi-node P2P gossip network over TCP sockets —
independent OS processes, not function calls — that must independently
mine, validate, propagate, and reconcile forks to converge on one chain.
The demo's centerpiece is a live-orchestrated network partition: two
groups of nodes are cut off from each other, both keep mining and extend
different tips, and when the partition heals the shorter side must
**reorg** — roll back its own blocks, undo their UTXO effects, and replay
the winning chain — while every double-spend that briefly looked valid on
the losing fork is correctly rejected everywhere.

## Architecture

```
vein/
  crypto/
    curve.py       — secp256k1 field + point arithmetic from scratch (no `ecdsa`/`cryptography` libs)
    ecdsa.py        — keygen, deterministic (RFC 6979) ECDSA sign/verify
    hashes.py       — SHA-256 + RIPEMD-160 (both from scratch, no hashlib for these two;
                       hashlib.sha256 used only where Python has no stdlib RIPEMD-160 — see below)
    base58.py       — Base58Check address encoding
  core/
    transaction.py  — UTXO tx model, Merkle tree, txid, serialization
    script.py       — tiny stack-based Script VM (OP_DUP/HASH160/EQUALVERIFY/CHECKSIG/...)
    block.py        — block header, PoW target math, serialization
    chain.py         — Blockchain: validation, UTXO set, fork tracking, reorg
    mempool.py       — pending-tx pool, orphan tx handling, fee-based selection
  node/
    p2p.py           — TCP gossip: peer handshake, inv/getdata, block/tx relay, dedup
    miner.py          — PoW mining loop (separate thread), template building from mempool
    rpc.py            — small JSON-over-HTTP control API (balance, send, mine, peers, chain)
    server.py         — wires p2p + chain + mempool + miner + rpc into one runnable node process
  wallet/
    wallet.py          — key management, address derivation, coin selection, tx building/signing
  explorer/
    explorer.html      — self-contained block-explorer UI (chain view, mempool, network topology,
                          live via SSE), polling one node's RPC
  cli.py                — `vein` CLI: node, wallet, mine, explorer, demo, partition-demo
tests/
  ...                   — unit + property + multi-process integration tests
demo.sh
```

Design choices carried over from this repo's established patterns: pure
Python 3, stdlib only (`socket`, `http.server`, `threading`, `hashlib` used
*only* as a cross-check oracle in tests, not in the production code path —
see Feature 1); nodes are real independent OS processes talking over real
loopback TCP sockets (same "actually distributed, not simulated" bar as
Concord's SSE relay and Matchbook's exchange); a self-contained HTML
visualizer with no build step, screenshot-verified in headless Chromium.

## Features

### Required (core, must work end-to-end)

1. **secp256k1 + ECDSA from scratch.** Full elliptic-curve field and point
   arithmetic (modular inverse, point add/double via the group law,
   scalar multiplication via double-and-add) over secp256k1's real curve
   parameters; RFC 6979 deterministic ECDSA sign/verify; SHA-256 and
   RIPEMD-160 implemented from the published specs (not `hashlib`) since
   Base58Check addresses need HASH160 = RIPEMD160(SHA256(pubkey)) and no
   from-scratch RIPEMD-160 exists anywhere in this repo's history.
   `hashlib.sha256`/`hashlib.sha1` are used *only* inside the test suite
   as a differential oracle against the hand-rolled implementations, the
   same "real tool as test oracle, never as runtime dependency" pattern
   Graft used against real `git`.
2. **UTXO ledger + Script VM.** Transactions spend prior outputs by
   reference and create new ones; a minimal stack-based Script
   interpreter (OP_DUP, OP_HASH160, OP_EQUALVERIFY, OP_CHECKSIG,
   OP_CHECKMULTISIG, push-data) evaluates real locking/unlocking script
   pairs — a P2PKH transaction only spends when its unlocking script
   supplies a signature and pubkey that actually satisfy the previous
   output's locking script against the current UTXO set.
3. **Proof-of-work block validation + mining.** Real block headers
   (prev-hash, Merkle root, timestamp, bits/target, nonce) with a genuine
   nonce search against a difficulty target, a retargeting rule
   (adjusts every N blocks toward a target block time), and full block
   validation (PoW meets target, Merkle root matches transactions, every
   tx valid against the UTXO set as of that block, coinbase reward
   correct).
4. **P2P gossip network + fork resolution.** Independent node processes
   connect over real TCP sockets, handshake, and gossip new
   transactions/blocks (inv/getdata style, with a seen-hash cache so
   messages don't loop forever); each node tracks *all* chain tips it has
   seen (not just its own), and reorganizes — rolling back and replaying
   UTXO-set changes — to whichever valid chain has the greatest
   cumulative proof of work the moment it learns about it, exactly the
   real Bitcoin fork-choice rule (not merely "longest chain" by block
   count, since difficulty can vary).

### Stretch

5. **Live block-explorer web UI.** A self-contained HTML page (SSE-driven,
   no build step) visualizing one node's live view: chain of blocks with
   real hashes/Merkle roots, per-block transaction detail, a live mempool
   feed, address balance lookup, and a network topology diagram of known
   peers — the same "browser holds no logic of its own, everything comes
   from a real running backend" discipline as Matchbook/Concord/Beacon's
   visualizers.
6. **CLI wallet + orchestrated network-partition demo.** A `vein wallet`
   CLI (keygen, address, balance, send) that builds and signs a real
   transaction and broadcasts it into the live P2P network; a
   `vein partition-demo` scenario that starts N nodes, lets them mine and
   sync, severs the P2P links between two groups mid-run so each group
   mines its own competing fork (including a real double-spend attempt on
   the losing fork), heals the partition, and asserts every node
   converges on byte-identical chain tip + UTXO set, with the losing
   fork's double-spend correctly absent everywhere.

## Why this is interesting

Nakamoto consensus is the one major "how do distributed systems agree"
paradigm this repo hasn't touched — Raft assumes known, semi-trusted
membership and a leader; CRDTs assume no adversary and no scarcity at all.
PoW is the only one of the three where a participant can be flat-out lying
(mining a fraudulent fork) and the protocol's job is to make the honest
chain win anyway through pure accumulated work, verifiable by anyone with
no vote and no leader — and it is the one whose failure mode (a
reorg silently invalidating a transaction you already trusted) is worth
seeing actually happen against real UTXO state, not just asserted.
