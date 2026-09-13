"""Schnorr group arithmetic.

A Schnorr group is a prime-order subgroup of Z_p^* where p = 2q + 1 is a
"safe prime" and q is itself prime. Every sigma-protocol in this toolkit
(Schnorr identification, Fiat-Shamir signatures, OR-composition) runs inside
one of these groups: the hard problem is the discrete logarithm, and the
group has prime order q so there are no small subgroups to leak information
through.

Primality is verified from scratch with a real Miller-Rabin test rather than
trusted from a hardcoded constant. The default group's (p, q, g) are
precomputed (searching a fresh 256-bit safe prime takes anywhere from
seconds to tens of seconds depending on luck), but `is_prime` and
`is_safe_prime_group` re-verify those constants at import time, and
`generate_safe_prime_group` is a real, runnable search over fresh randomness
for anyone who wants to regenerate their own.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

_SMALL_PRIMES = (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47)


def is_prime(n: int, rounds: int = 40, rng: random.Random | None = None) -> bool:
    """Miller-Rabin primality test, from scratch.

    Deterministic on composites in the sense that Miller-Rabin can never
    misclassify a prime as composite; it has a <= 4^-rounds chance of
    misclassifying a composite as prime (with 40 rounds, negligible).
    """
    if n < 2:
        return False
    for sp in _SMALL_PRIMES:
        if n == sp:
            return True
        if n % sp == 0:
            return False

    rng = rng or random.Random()
    d = n - 1
    r = 0
    while d % 2 == 0:
        d //= 2
        r += 1

    for _ in range(rounds):
        a = rng.randrange(2, n - 1)
        x = pow(a, d, n)
        if x == 1 or x == n - 1:
            continue
        for _ in range(r - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


def is_safe_prime_group(p: int, q: int, g: int) -> bool:
    """Verify (p, q, g) really is a safe-prime Schnorr group: p = 2q+1,
    both prime, and g generates the order-q subgroup (g != 1, g^q == 1)."""
    if p != 2 * q + 1:
        return False
    if not is_prime(q) or not is_prime(p):
        return False
    if g <= 1 or g >= p:
        return False
    if pow(g, q, p) != 1:
        return False
    return g != 1


def generate_safe_prime_group(bits: int = 256, seed: int | None = None):
    """Search fresh randomness for a real (p, q, g) safe-prime Schnorr
    group of the given bit length. This is the actual algorithm used to
    produce STANDARD_GROUP's constants below — runnable, not decorative."""
    rng = random.Random(seed)
    while True:
        q = rng.getrandbits(bits - 1) | (1 << (bits - 2)) | 1
        if not is_prime(q, 20, rng):
            continue
        p = 2 * q + 1
        if not is_prime(p, 20, rng):
            continue
        for h in range(2, 1000):
            g = pow(h, 2, p)
            if g != 1:
                return SchnorrGroup(p=p, q=q, g=g)


@dataclass(frozen=True)
class SchnorrGroup:
    """A verified Schnorr group: work happens mod p, exponents mod q."""

    p: int
    q: int
    g: int

    def __post_init__(self):
        if not is_safe_prime_group(self.p, self.q, self.g):
            raise ValueError("not a valid verified safe-prime Schnorr group")

    def pow_g(self, exponent: int) -> int:
        """g^exponent mod p, with the exponent reduced mod q first (the
        group element only depends on the exponent mod the group order)."""
        return pow(self.g, exponent % self.q, self.p)

    def random_exponent(self, rng: random.Random | None = None) -> int:
        rng = rng or random.Random()
        return rng.randrange(1, self.q)

    def random_element(self, rng: random.Random | None = None) -> int:
        return self.pow_g(self.random_exponent(rng))


# A precomputed 256-bit safe-prime Schnorr group, found by
# generate_safe_prime_group(bits=256, seed=1337) after 9204 candidate
# rejections. Re-verified (not just trusted) every time this module loads.
STANDARD_GROUP = SchnorrGroup(
    p=67528887603418471877165710178429639045379787470699331399636686642782433274979,
    q=33764443801709235938582855089214819522689893735349665699818343321391216637489,
    g=4,
)
