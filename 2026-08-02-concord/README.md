# Concord

A cryptocurrency and blockchain built from scratch in pure Python: real
secp256k1 elliptic-curve cryptography, a UTXO ledger, proof-of-work mining,
and a genuine multi-node peer-to-peer network that gossips and resolves
forks by cumulative work.

**Status: Phase 3 (adversarial review) complete.** All 4 required
features and both stretch features (block explorer UI, double-spend
attack simulation) are built and working, and have been through a
hostile self-review — see [REVIEW.md](REVIEW.md) for 9 real findings
(including one critical silent-forking bug) and their fixes. See
[PLAN.md](PLAN.md) for architecture and the full feature list. The
formal test suite and final polish pass are still to come — this
README will be filled in fully at ship time.
