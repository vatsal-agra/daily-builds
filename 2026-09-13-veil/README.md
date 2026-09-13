# Veil

> A from-scratch Zero-Knowledge Proof toolkit.

Every cryptography build in this repo's history (Cryptex, Ironkey, Vein)
implemented **non-interactive primitives**: hash functions, ciphers,
RSA/ECDSA/ECDH. Veil is a different kind of cryptography — a **protocol**,
not a single computation — in which a Prover convinces a Verifier that a
statement is true ("I know a secret," "I solved this puzzle," "I'm one of
these N registered members") while the Verifier learns **nothing else**,
not even a single bit of the secret. That's three simultaneous, separately
provable properties (completeness, soundness, zero-knowledge), and Veil
tests all three empirically rather than asking you to trust a proof
sketch: it runs thousands of cheating-prover trials and checks the catch
rate against the closed-form soundness bound, extracts a real secret key
from two transcripts as a literal demonstration of soundness, and builds
actual zero-knowledge simulators checked with a from-scratch statistical
test.

## How to run it

```bash
cd 2026-09-13-veil

# Run everything (72 tests + 11 end-to-end checks, headless-browser
# smoke test of the visualizer, and a live regression check of the
# adversarial-review fix) — this is the fastest way to see it all work:
./demo.sh

# Or explore the CLI directly:
python3 -m veil.cli group-info                                     # the verified safe-prime group
python3 -m veil.cli schnorr --seed 1                                # Schnorr identification + extraction
python3 -m veil.cli sign "hello world" --seed 1                     # Fiat-Shamir signature
python3 -m veil.cli anon-auth --n 5 --index 2 --message "vote: yes" --seed 1   # OR-proof
python3 -m veil.cli coloring --rounds 20 --seed 1                   # graph 3-coloring ZK proof
python3 -m veil.cli simulate --samples 4000 --seed 1                # ZK simulators + statistical test
python3 -m veil.cli club --n 5 --index 2 --command "withdraw 100" --seed 1   # flagship anonymous auth
python3 -m veil.cli viz && open visualizer/index.html               # interactive visualizer
```

No dependencies beyond Python 3 stdlib for the library and CLI. The
visualizer is a single self-contained HTML file (no server, no build
step) — open `visualizer/index.html` directly in any browser. Tests need
`pytest` (`pip install pytest` if you don't already have it — `demo.sh`
auto-detects whatever's on your machine).

## Full feature list

1. **Schnorr identification protocol** (`veil/schnorr.py`) — a real
   3-move Sigma-protocol (commit → challenge → response) over a
   from-scratch-verified safe-prime Schnorr group (`veil/group.py`,
   Miller-Rabin primality hand-derived, not trusted from a constant).
   Includes **special-soundness witness extraction**: a real, runnable
   algorithm that recovers the secret from two accepting transcripts
   sharing one commitment — soundness made concrete, not just asserted.
2. **Fiat-Shamir transform → Schnorr signatures** (`veil/fiatshamir.py`) —
   collapses the interactive protocol into a real non-interactive
   signature scheme (the direct ancestor of EdDSA/Ed25519), with
   message-tamper detection.
3. **OR-composition anonymous proofs** (`veil/orproof.py`,
   Cramer–Damgård–Schoenmakers) — proves knowledge of the discrete log for
   ONE of N public keys without revealing which, by mixing one honestly-
   proven branch with N-1 simulated branches under a single Fiat-Shamir
   challenge split across all of them. The actual mechanism behind ring
   signatures and anonymous credentials.
4. **Graph 3-coloring ZK proof** (`veil/coloring.py`, Goldreich-Micali-
   Wigderson) — proof that ZK exists for an *NP-complete* statement, not
   just algebraic relations: hash commitments, per-round soundness error
   `1 - 1/|E|`, exponential amplification over independent rounds.
5. **Zero-knowledge simulators + statistical indistinguishability test**
   (`veil/simulator.py`, `veil/stats.py`) — real simulators that produce
   accepting transcripts with **no witness at all** (Schnorr: solve for
   the commitment after picking the challenge/response; coloring: a
   rewinding simulator that guesses the challenge edge in advance), and a
   from-scratch chi-squared test (`veil/stats.py` — regularized incomplete
   gamma function via series/continued-fraction, no SciPy) that confirms
   real and simulated transcript distributions are not distinguishable.
6. **Flagship anonymous membership/auth system + interactive visualizer**
   (`veil/membership.py`, `visualizer/index.html`) — a `Club` of N
   registered members where any member anonymously authorizes a command
   (OR-proof + Fiat-Shamir message-binding) with a real nonce-based replay
   log; a self-contained HTML/SVG/JS visualizer, built from an actual
   seeded protocol run (`veil/viz_export.py`), that steps through a real
   Schnorr proof, OR-proof, and graph-coloring round by round.

## Adversarial review

A hostile self-review (`REVIEW.md`) found and fixed 6 real issues,
including a **critical soundness break**: a public key with no real
discrete log (`p-1`, the order-2 element every safe prime's group
contains) let a witness-less prover fool the verifier **~50% of the
time** instead of the negligible rate soundness is supposed to guarantee
— fixed by validating subgroup membership before any verification.
Also fixed: a non-cryptographic default random-number source (silently
falling back to Python's predictable Mersenne-Twister `random.Random()`
instead of a CSPRNG — the exact class of bug behind real nonce-reuse key
recovery), a hang on pathological input, a reproducibility bug in the
coloring protocol's randomness, an API that let a caller double-open a
committed round (defeating its own zero-knowledge guarantee), and a
witness-extraction function that trusted unverified input. Full writeup,
exploit reproductions, and fixes in [REVIEW.md](REVIEW.md).

## Verification

- `tests/` — 72 pytest tests: completeness/soundness/extraction for every
  protocol, an independent trial-division oracle for Miller-Rabin, the
  empirical soundness-bound check for graph coloring (including the exact
  worst-case-equality test), every REVIEW.md regression, and the
  statistical indistinguishability tests.
- `demo.sh` — 11 end-to-end checks: the full test suite, every CLI command
  against real output, the ZK simulator statistical test, the flagship
  anonymous-auth flow with a live replay attack, a headless-Chromium
  smoke test of the visualizer (zero console errors, every tab and
  control exercised), and a live re-run of the critical exploit from
  adversarial review confirming it stays fixed.

## Why this today

Ground truth is unusually strong for a "protocol design" topic:
soundness bounds are closed-form and directly checkable by simulation,
special soundness gives a literal extraction algorithm to run, and
zero-knowledge is falsifiable by actually building the simulator and
running a real statistical test against it. That combination — a security
property you can *run*, not just argue — fits this repo's "verify the
invariant, don't just claim it" pattern better than a fourth signature
scheme would have, and zero-knowledge proofs are a genuinely new shape of
cryptography for this repo: every prior build proved "I can compute the
right output," never "I know something, and I'll prove it without telling
you what."

## Where a human could take this next

- **Move to elliptic curves.** The Schnorr group here is a 256-bit
  multiplicative safe-prime group for clarity; a real deployment would use
  Ed25519 or secp256k1 (both already implemented from scratch elsewhere in
  this repo, in Vein and Cryptex) for smaller keys and faster arithmetic —
  the Sigma-protocol math is identical, only `pow_g`'s implementation
  would change from modular exponentiation to point multiplication.
- **A real zk-SNARK.** Graph 3-coloring is Karp-reducible from *any* NP
  statement, but that reduction (and the constant-round-amplification
  approach) is impractical for real-world circuits. The natural next step
  is arithmetic-circuit satisfiability with a polynomial commitment scheme
  (a genuinely large project, but this toolkit's Sigma-protocol and
  Fiat-Shamir machinery are real building blocks a from-scratch
  Groth16/PLONK implementation would reuse directly).
- **Batch verification.** Right now every OR-proof branch is checked with
  its own modular exponentiation; real deployments batch many
  verifications together with random linear combinations for a large
  constant-factor speedup — a good, self-contained follow-up exercise.
- **A real network protocol.** `membership.py`'s `Club` is a single-process
  library; wiring it to Concord's SSE relay pattern or Vein's P2P gossip
  (both already in this repo) would turn it into an actual anonymous
  authentication *service* multiple real processes could talk to.
- **Threshold / distributed key generation.** Right now each member holds
  one full secret key; a natural extension is Shamir-sharing each member's
  key across several devices, so no single device holds a complete secret
  — turning "anonymous member" into "anonymous member whose key can't be
  stolen from any one place."
