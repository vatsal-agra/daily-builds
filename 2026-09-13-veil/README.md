# Veil

> A from-scratch Zero-Knowledge Proof toolkit.

**Status: Phase 2 (core build) complete.** All four required features are
implemented and demonstrably work end-to-end via the CLI. See
[PLAN.md](PLAN.md) for the full concept and architecture. This README will
gain full usage docs, the complete feature list, and design rationale as
later phases (adversarial review, stretch features, verification) land.

## Quick look (works today)

```
python3 -m veil.cli group-info
python3 -m veil.cli schnorr
python3 -m veil.cli sign "hello world"
python3 -m veil.cli anon-auth --n 5 --index 2 --message "vote: yes"
python3 -m veil.cli coloring --rounds 20
```

## What's implemented so far

1. **Schnorr identification protocol** (`veil/schnorr.py`) — a real
   Sigma-protocol over a from-scratch-verified safe-prime Schnorr group
   (`veil/group.py`, Miller-Rabin primality from scratch), including
   special-soundness witness extraction from two accepting transcripts.
2. **Fiat-Shamir transform → Schnorr signatures** (`veil/fiatshamir.py`) —
   non-interactive proofs and a real sign/verify signature scheme, with
   message tamper-detection.
3. **OR-composition anonymous proofs** (`veil/orproof.py`,
   Cramer–Damgård–Schoenmakers) — prove membership in a set of N public
   keys without revealing which one, the building block behind ring
   signatures and anonymous credentials.
4. **Graph 3-coloring ZK proof** (`veil/coloring.py`, Goldreich-Micali-
   Wigderson) — a ZK proof for an NP-complete statement via hash
   commitments and round-based soundness amplification.

Not yet done: adversarial review, the zero-knowledge simulator +
statistical indistinguishability test, the flagship anonymous-membership
demo, the interactive HTML visualizer, and the test suite.
