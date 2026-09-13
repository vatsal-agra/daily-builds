# Veil — a from-scratch Zero-Knowledge Proof toolkit

## Concept

Every cryptography build in this repo's history (Cryptex, Ironkey, Vein) has
implemented **non-interactive primitives**: hash functions, symmetric ciphers,
RSA/ECDSA/ECDH signatures and key exchange. All of them answer the same kind
of question — "can you compute the right output from a key you hold?" — with
a single message.

Zero-knowledge proofs are a different animal entirely, and a genuinely new
domain for this repo. A ZK proof is a *protocol* (not a single computation)
in which a Prover convinces a Verifier that a statement is true — "I know a
secret x", "I solved this puzzle", "I'm one of these N registered members" —
while the Verifier learns **nothing else**, not even a single bit of the
secret. That's not one property, it's three simultaneous, individually
provable properties any real ZK protocol must satisfy:

- **Completeness** — an honest Prover who really knows the secret always
  convinces an honest Verifier.
- **Soundness** — a cheating Prover who does *not* know the secret gets
  caught, except with quantifiable, vanishingly small probability.
- **Zero-knowledge** — everything the Verifier sees in a real proof could
  have been produced by a *simulator* that doesn't know the secret at all.
  If a simulator can fake the transcript, the transcript itself can't be
  carrying any information about the secret.

Unlike most cryptography, none of these three properties is "trust the
paper" — every one of them is empirically testable, and Veil tests all
three for real, the same way this repo has always preferred "run it and
watch the invariant hold" over "the algorithm is correct because a proof
sketch says so": run thousands of trials of a cheating prover and confirm
the catch rate matches the closed-form soundness bound; build the actual
zero-knowledge simulator and run a real statistical distinguisher against
it; use two accepting transcripts from a real run to literally extract the
witness (special soundness), not just assert that it's possible.

## Architecture

```
veil/
  group.py        # Schnorr group arithmetic: safe prime p, subgroup order q,
                   # generator g; Miller-Rabin primality (from scratch) used
                   # to *verify* p and q are prime rather than trust a constant
  commit.py        # Hash-based commitment scheme (SHA-256 + random nonce),
                   # used by the graph-coloring protocol
  schnorr.py       # Sigma-protocol: interactive Schnorr identification,
                   # special-soundness witness extraction from two
                   # accepting transcripts sharing one commitment
  fiatshamir.py    # Fiat-Shamir transform: interactive Schnorr -> a
                   # non-interactive proof, and a full Schnorr *signature*
                   # scheme (message-bound, replay-checked)
  orproof.py       # Cramer-Damgard-Schoenmakers OR-composition: prove
                   # knowledge of ONE of N discrete logs without revealing
                   # which; the anonymous-membership building block
  coloring.py      # Graph 3-coloring ZK proof: commit-reveal rounds,
                   # per-round soundness error, t-round amplification
  simulator.py     # Zero-knowledge simulators for Schnorr and coloring
                   # (produce transcripts *without* the witness) plus a
                   # statistical indistinguishability test comparing real
                   # vs. simulated transcript distributions
  membership.py    # The flagship product: an anonymous membership/auth
                   # system built on the OR-proof + Fiat-Shamir signatures
                   # ("prove you're a registered member, sign a message as
                   # that anonymous membership, without revealing who")
  cli.py           # `veil` command-line tool tying every feature together
  viz_export.py    # Exports real protocol transcripts as JSON for the
                   # HTML visualizer
visualizer/
  index.html       # Self-contained interactive HTML/JS: step through a
                   # real Schnorr proof, a real graph-coloring round, and a
                   # real OR-proof, round by round
tests/
  test_*.py        # pytest unit + property suite
demo.sh            # Runs every feature end-to-end, exits non-zero on failure
```

No external crypto library, no `pycryptodome`, no `ecdsa` package — pure
Python 3 stdlib. `hashlib.sha256` is used as the random-oracle hash function
(this repo's Vein already hand-derived SHA-256 from spec as its own exercise;
re-deriving it again here would just be repetition, not rigor — Veil's "from
scratch" claim is about the *protocols*, which do not exist anywhere in any
standard library). Modular exponentiation uses Python's built-in three-arg
`pow()`, which is how every real implementation does modexp — hand-rolling
square-and-multiply would not make the group arithmetic any more "from
scratch," only slower.

## Feature list

**Required (core, Phase 2):**

1. **Schnorr identification protocol** — a real Σ-protocol over a verified
   Schnorr group (safe prime `p = 2q+1`, both primality-checked from
   scratch via Miller-Rabin) proving knowledge of discrete log `x` in
   `y = g^x mod p`: commit → challenge → response, with a real verifier.
   Includes **special-soundness witness extraction**: given two accepting
   transcripts that share a commitment but differ in challenge, recover `x`
   directly — a concrete, runnable proof that soundness isn't just
   asserted.
2. **Fiat-Shamir transform → non-interactive Schnorr signatures** — collapse
   the 3-move protocol into a single message by deriving the challenge as
   `H(commitment, message)`; yields a real signature scheme (sign/verify)
   that is message-bound (tampering with the message invalidates the
   signature) and includes a replay/malleability check.
3. **OR-composition (Cramer–Damgård–Schoenmakers)** — prove knowledge of the
   discrete log for *one of N* public keys without revealing which one:
   the real branch is proven honestly, the other N-1 are simulated using
   the Schnorr simulator, and a single overall Fiat-Shamir challenge is
   split across branches so the transcript is indistinguishable across
   which branch was real. This is the anonymous-authentication primitive.
4. **Graph 3-coloring ZK proof** — proof that ZK exists for an NP-complete
   statement, not just algebraic relations: hash-commitment to a randomly
   relabeled coloring each round, verifier opens one random edge, repeated
   `t` independent rounds. Computes and empirically verifies the per-round
   and amplified soundness error `(1 - 1/|E|)^t` over many trials against
   both a real valid coloring and a deliberately invalid one.

**Stretch (Phase 4, at least 1 required, both planned):**

5. **Zero-knowledge simulators + statistical indistinguishability test** —
   real simulators (no witness access) for Schnorr and graph-coloring that
   produce accepting-transcript distributions, plus a distinguisher
   (chi-squared-style comparison over transcript features) run against
   real vs. simulated transcripts to empirically confirm they can't be
   told apart.
6. **Flagship anonymous membership/auth demo + interactive HTML
   visualizer** — a small "club" of N members register public keys; any
   member anonymously authenticates and signs a command via OR-proof +
   Fiat-Shamir without revealing which member they are, with replay
   protection (message binding) and a real test that an outsider (no valid
   secret key) cannot forge a proof. The visualizer steps through a real
   Schnorr proof, a real coloring round, and a real OR-proof transcript
   captured from an actual run (not scripted/fake data).

## Why this today

Ground truth is unusually strong here even though the topic is more
"protocol design" than "data structure": soundness bounds are closed-form
and checkable by direct simulation (run 10,000 cheating-prover attempts,
compare empirical catch rate to the formula), special soundness gives a
literal extraction algorithm to run, and zero-knowledge is falsifiable by
building the actual simulator and testing it. That combination — a security
property you can *run* rather than only argue — fits this repo's pattern
better than a fourth signature scheme would have.

## Where a human could take this next

See README.md (written in Phase 6).
