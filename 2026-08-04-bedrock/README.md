# Bedrock

A from-scratch proof-of-work blockchain and cryptocurrency network:
secp256k1 wallets, a UTXO ledger, real PoW mining with difficulty
retargeting, full block/transaction validation, chain reorganization,
a gossiping multi-process P2P network, and a live block explorer.

**Status: Phase 5 — verification complete.** 134 unittest tests plus
`demo.sh` (full test suite → scripted feature walkthrough → CLI workflow
against persisted state → a real 2-*process* P2P sync over TCP sockets) all
pass. See [PLAN.md](PLAN.md) for architecture and [REVIEW.md](REVIEW.md)
for the adversarial review. Shipping next.

## Quick look

```
python3 -m bedrock.demo
```

runs a scripted walkthrough: mining, wallets, signed transactions,
double-spend/forgery rejection, chain reorganization, a 3-node P2P
network converging after a simultaneous fork, and the block explorer's
live HTTP API.
