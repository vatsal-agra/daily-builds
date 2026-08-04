# Bedrock

A from-scratch proof-of-work blockchain and cryptocurrency network:
secp256k1 wallets, a UTXO ledger, real PoW mining with difficulty
retargeting, full block/transaction validation, chain reorganization,
a gossiping multi-process P2P network, and a live block explorer.

**Status: Phase 4 — stretch features and polish complete.** All 4 required
features and both stretch features (a real multi-process gossiping P2P
network, and a server-backed block explorer + wallet web UI) are
implemented, adversarially reviewed (see [REVIEW.md](REVIEW.md)), and
polished: clean error messages (never a raw traceback) across every CLI
command and HTTP endpoint, validated addresses/amounts, and a genuinely
dark/light-theme-aware UI (screenshot-verified in headless Chromium, zero
console errors). See [PLAN.md](PLAN.md) for the architecture. A formal
test suite and `demo.sh` are next.

## Quick look

```
python3 -m bedrock.demo
```

runs a scripted walkthrough: mining, wallets, signed transactions,
double-spend/forgery rejection, chain reorganization, a 3-node P2P
network converging after a simultaneous fork, and the block explorer's
live HTTP API.
