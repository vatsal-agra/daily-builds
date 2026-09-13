"""OR-composition of Schnorr proofs (Cramer, Damgard, Schoenmakers, CRYPTO
'94): prove knowledge of the discrete log for ONE of N public keys, without
revealing which one.

This is the actual cryptographic primitive behind ring signatures and
anonymous credentials/membership proofs — "I'm a member of this group"
without "I'm member #3."

Idea: run N parallel Schnorr transcripts, one per public key. For the real
branch (the prover's own key, at secret index `k`), run the protocol
honestly with a real random nonce. For every other branch, run the Schnorr
*simulator* (see simulator.py for what this means and why it's valid even
without a witness): pick the response `s_i` and challenge `c_i` first, then
solve for the commitment `t_i = g^s_i * y_i^-c_i mod p` that makes the
verification equation hold — a real accepting transcript for a statement
the prover cannot actually prove.

The only step that ties the branches together is the challenge: the
Fiat-Shamir hash over ALL N commitments fixes an overall challenge `c`, and
the real branch's challenge is forced to be `c_k = c - sum(other c_i) mod
q`. The prover cannot control this without already having committed `t_k`
first — so they cannot simulate the real branch too (that would need
foreknowledge of `c` before choosing `t_k`, but `c` depends on `t_k`).

**Why this hides which index is real**: every accepting per-branch
transcript (t_i, c_i, s_i) is individually indistinguishable from a real
Schnorr transcript for y_i, honest or simulated, and the challenge split
c_k = c - sum(other c_i) makes c_k *uniformly distributed* exactly like
every other c_i (it's a random-looking value determined by subtraction from
independent uniform values). See tests/test_orproof.py for a statistical
check that this holds across real runs.

**Why this is sound**: verification requires ALL N branches to be
individually-accepting Schnorr transcripts AND requires sum(c_i) mod q to
equal the externally-fixed Fiat-Shamir hash. A prover with no witness for
any y_i can freely simulate every branch (pick c_i and s_i, solve for
t_i) — but must fix all N commitments t_i *before* learning what the
Fiat-Shamir hash of them will be, and then has no freedom left to make
sum(c_i) land on that hash except by guessing (probability 1/q,
negligible). A prover who genuinely knows a witness x_k for the real branch
can leave that branch's challenge as the *only* free variable and solve
sum(c_i) = c after the fact, which is exactly the honest algorithm below.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass

from veil.group import SchnorrGroup


@dataclass(frozen=True)
class ORProof:
    t_list: tuple[int, ...]
    c_list: tuple[int, ...]
    s_list: tuple[int, ...]


def _fiat_shamir_challenge(group: SchnorrGroup, t_list, context: bytes) -> int:
    h = hashlib.sha256()
    for t in t_list:
        h.update(str(t).encode())
        h.update(b"|")
    h.update(context)
    return int.from_bytes(h.digest(), "big") % group.q


def prove_or(
    group: SchnorrGroup,
    secret_index: int,
    x: int,
    public_keys: list[int],
    context: bytes = b"",
    rng: random.Random | None = None,
) -> ORProof:
    """Prove knowledge of the discrete log of public_keys[secret_index],
    without revealing secret_index, bound to `context` (e.g. a message)."""
    n = len(public_keys)
    if not (0 <= secret_index < n):
        raise ValueError("secret_index out of range")
    if group.pow_g(x) != public_keys[secret_index]:
        raise ValueError("x is not the discrete log of public_keys[secret_index]")

    rng = rng or random.Random()

    t_list: list[int | None] = [None] * n
    c_list: list[int | None] = [None] * n
    s_list: list[int | None] = [None] * n

    # Simulate every non-real branch: pick c_i, s_i freely, solve for t_i.
    for i in range(n):
        if i == secret_index:
            continue
        c_i = rng.randrange(0, group.q)
        s_i = rng.randrange(0, group.q)
        y_i_inv_c = pow(public_keys[i], (-c_i) % group.q, group.p)
        t_i = (group.pow_g(s_i) * y_i_inv_c) % group.p
        t_list[i] = t_i
        c_list[i] = c_i
        s_list[i] = s_i

    # Honest commitment for the real branch.
    r_k = group.random_exponent(rng)
    t_list[secret_index] = group.pow_g(r_k)

    # Fix the overall challenge only once every commitment is set.
    c = _fiat_shamir_challenge(group, t_list, context)
    c_others_sum = sum(c_list[i] for i in range(n) if i != secret_index) % group.q
    c_k = (c - c_others_sum) % group.q
    s_k = (r_k + c_k * x) % group.q

    c_list[secret_index] = c_k
    s_list[secret_index] = s_k

    return ORProof(t_list=tuple(t_list), c_list=tuple(c_list), s_list=tuple(s_list))


def verify_or(
    group: SchnorrGroup, public_keys: list[int], context: bytes, proof: ORProof
) -> bool:
    n = len(public_keys)
    if len(proof.t_list) != n or len(proof.c_list) != n or len(proof.s_list) != n:
        return False

    for i in range(n):
        y_i, t_i, c_i, s_i = public_keys[i], proof.t_list[i], proof.c_list[i], proof.s_list[i]
        if not (0 <= t_i < group.p and 0 <= c_i < group.q and 0 <= s_i < group.q):
            return False
        lhs = group.pow_g(s_i)
        rhs = (t_i * pow(y_i, c_i, group.p)) % group.p
        if lhs != rhs:
            return False

    expected_c = _fiat_shamir_challenge(group, proof.t_list, context)
    actual_c_sum = sum(proof.c_list) % group.q
    return actual_c_sum == expected_c
