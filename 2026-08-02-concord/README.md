# Concord

A cryptocurrency and blockchain built from scratch in pure Python: real
secp256k1 elliptic-curve cryptography, a UTXO ledger, proof-of-work mining,
and a genuine multi-node peer-to-peer network that gossips and resolves
forks by cumulative work.

**Status: Phase 2 (core build) complete.** All 4 required features work
end-to-end: from-scratch secp256k1 signing/verification, a UTXO chain
with full validation, threaded proof-of-work mining with difficulty
retargeting, and a real multi-node TCP network that gossips and
resolves forks by cumulative work — verified live with a 3-node network
in `concord/demo.py` (`python3 -m concord.demo`). See [PLAN.md](PLAN.md)
for architecture and the full feature list. Adversarial review, the
explorer UI, the attack simulation, and the test suite are still to
come — this README will be filled in fully at ship time.
