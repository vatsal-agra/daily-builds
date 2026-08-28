# LedgerLine

> **Status: Phase 3 — Adversarial review complete.** 5 real bugs found and
> fixed (2 critical — see [`REVIEW.md`](./REVIEW.md)). Stretch features +
> polish next.

A from-scratch proof-of-work blockchain and cryptocurrency network — real
secp256k1 ECDSA wallets, a UTXO ledger, proof-of-work mining, and a genuine
multi-node peer-to-peer network (real localhost TCP sockets) that gossips
blocks/transactions and resolves forks by the longest-valid-chain rule.

See [`PLAN.md`](./PLAN.md) for the full concept, architecture, and feature
list.

## Quick start

```bash
# from this directory
python3 -m ledgerline.cli keygen                       # generate a wallet
python3 -m ledgerline.cli network --nodes 4 --seconds 30 # headless multi-node network
python3 -m ledgerline.cli explorer --nodes 4             # network + live web explorer (http://127.0.0.1:8765)
python3 -m ledgerline.cli demo                            # scripted end-to-end walkthrough
python3 -m ledgerline.cli test                            # unit test suite
```

## What's implemented so far

1. **Blockchain core + proof-of-work mining** — real Merkle trees, PoW
   nonce search against a target, full block validation.
2. **secp256k1 ECDSA wallets + UTXO transactions** — from-scratch elliptic
   curve math, RFC 6979 deterministic signing, Base58Check addresses.
3. **P2P network with fork resolution** — real TCP sockets, gossip,
   partition/reconnect controls, cumulative-work-based reorgs.
4. **Mempool + live web block explorer** — fee-prioritized tx selection,
   a real-time browser UI backed by the actual running nodes.

See [`REVIEW.md`](./REVIEW.md) for the full adversarial review: 2 critical
bugs (a negative-output money-creation exploit, and a mempool-poisoning
bug that could permanently cripple a node's own mining), 1 high-severity
DoS (a malformed peer message could kill a connection's reader thread),
and 2 medium issues (unvalidated recipient addresses, and racy test
assertions that made Phase 2's demo intermittently flaky) — all fixed,
all covered by regression tests.

Remaining phases (stretch features, polish, verification, ship) still to
come — this README will be filled in fully at the end.
