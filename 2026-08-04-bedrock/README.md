# Bedrock

A from-scratch proof-of-work blockchain and cryptocurrency network:
secp256k1 wallets, a UTXO ledger, real PoW mining with difficulty
retargeting, full block/transaction validation, chain reorganization,
a gossiping multi-process P2P network, and a live block explorer.

**Status: Phase 2 — core build complete.** All 4 required features and
both stretch features are implemented and passing an end-to-end scripted
demo (`python3 -m bedrock.demo`). See [PLAN.md](PLAN.md) for the
architecture. Adversarial review, polish, and a full test suite are next.

## Quick look

```
python3 -m bedrock.demo
```

runs a scripted walkthrough: mining, wallets, signed transactions,
double-spend/forgery rejection, chain reorganization, a 3-node P2P
network converging after a simultaneous fork, and the block explorer's
live HTTP API.
