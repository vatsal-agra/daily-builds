# Veil

> A from-scratch Zero-Knowledge Proof toolkit.

**Status: Phase 4 (stretch features + polish) complete.** All 6 planned
features are implemented (4 required + both stretch): the core protocols,
a hostile self-review with 6 fixed findings ([REVIEW.md](REVIEW.md)), real
zero-knowledge simulators with a from-scratch statistical
indistinguishability test, the flagship anonymous membership/auth system,
and an interactive HTML visualizer built from a real protocol run. See
[PLAN.md](PLAN.md) for the concept and architecture. Verification (tests +
demo script) and the final polished usage docs land in the next phases.

## Quick look (works today)

```
python3 -m veil.cli group-info
python3 -m veil.cli schnorr --seed 1
python3 -m veil.cli sign "hello world" --seed 1
python3 -m veil.cli anon-auth --n 5 --index 2 --message "vote: yes" --seed 1
python3 -m veil.cli coloring --rounds 20 --seed 1
python3 -m veil.cli simulate --samples 4000 --seed 1
python3 -m veil.cli club --n 5 --index 2 --command "withdraw 100" --seed 1
python3 -m veil.cli viz    # regenerates visualizer/index.html — open it in a browser
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
5. **Zero-knowledge simulators + statistical indistinguishability test**
   (`veil/simulator.py`, `veil/stats.py`) — real simulators that produce
   accepting transcripts with NO witness, checked against real transcripts
   with a from-scratch chi-squared test.
6. **Flagship anonymous membership system + interactive visualizer**
   (`veil/membership.py`, `visualizer/index.html`) — anonymous
   authentication with real replay protection, and a browser visualizer
   built from an actual protocol run.

Adversarial review already found and fixed 6 real issues, including a
critical soundness break — see [REVIEW.md](REVIEW.md).

Not yet done: the test suite and `demo.sh` (Phase 5), and the final
polished usage docs / "where a human could take this" writeup (Phase 6).
