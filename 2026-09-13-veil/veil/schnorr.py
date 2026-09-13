"""The Schnorr identification protocol: a real Sigma-protocol.

Statement: "I know x such that y = g^x mod p" (a discrete-log relation).
The protocol has three moves:

    Prover                              Verifier
    ------                              --------
    r <- random in [1, q)
    t = g^r mod p          --- t --->
                           <-- c ---    c <- random in [0, q)
    s = (r + c*x) mod q    --- s --->
                                        accept iff g^s == t * y^c mod p

**Completeness**: if the prover really knows x, g^s = g^(r + c*x) =
g^r * (g^x)^c = t * y^c mod p always — the verifier always accepts.

**Special soundness**: this is the property that makes the protocol
*provably* sound rather than just "hard to fool in practice." Given TWO
accepting transcripts (t, c1, s1) and (t, c2, s2) that share the same first
message t but have different challenges c1 != c2, a witness x can be
extracted directly: x = (s1 - s2) * (c1 - c2)^-1 mod q. `extract_witness`
below is that extractor, and it's a real, runnable algorithm, not just an
assertion — see tests/test_schnorr.py for it recovering a genuine secret
key from two transcripts with no other information. This is what "sound"
means for a Sigma-protocol: not merely "we couldn't find a way to cheat,"
but "any prover who could pass the same commitment twice for two different
challenges must actually know the secret, because knowing the secret is the
*only* way that's possible."

**Honest-verifier zero-knowledge**: a working simulator lives in
simulator.py — see that module's docstring for what property it proves.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from veil.group import SchnorrGroup


@dataclass(frozen=True)
class KeyPair:
    x: int  # secret
    y: int  # public: g^x mod p


@dataclass(frozen=True)
class Transcript:
    t: int  # commitment
    c: int  # challenge
    s: int  # response


def generate_keypair(group: SchnorrGroup, rng: random.Random | None = None) -> KeyPair:
    rng = rng or random.Random()
    x = group.random_exponent(rng)
    y = group.pow_g(x)
    return KeyPair(x=x, y=y)


def commit(group: SchnorrGroup, rng: random.Random | None = None) -> tuple[int, int]:
    """Prover's first move. Returns (t, r) — r is the secret nonce kept
    until the response is computed; t is sent to the verifier."""
    rng = rng or random.Random()
    r = group.random_exponent(rng)
    t = group.pow_g(r)
    return t, r


def challenge(group: SchnorrGroup, rng: random.Random | None = None) -> int:
    """Verifier's move: a fresh random challenge in [0, q)."""
    rng = rng or random.Random()
    return rng.randrange(0, group.q)


def respond(group: SchnorrGroup, x: int, r: int, c: int) -> int:
    """Prover's second move."""
    return (r + c * x) % group.q


def verify(group: SchnorrGroup, y: int, t: int, c: int, s: int) -> bool:
    lhs = group.pow_g(s)
    rhs = (t * pow(y, c, group.p)) % group.p
    return lhs == rhs


def run_interactive_proof(
    group: SchnorrGroup, keypair: KeyPair, rng: random.Random | None = None
) -> Transcript:
    """Run a full honest interactive proof end-to-end and return the
    transcript (for demos/visualization); also usable to self-check."""
    rng = rng or random.Random()
    t, r = commit(group, rng)
    c = challenge(group, rng)
    s = respond(group, keypair.x, r, c)
    return Transcript(t=t, c=c, s=s)


def extract_witness(group: SchnorrGroup, t1: Transcript, t2: Transcript) -> int:
    """Special-soundness knowledge extractor.

    Given two ACCEPTING transcripts that share the same commitment `t` but
    have different challenges, recover the discrete-log witness x. This is
    the concrete mechanism behind "soundness": no prover strategy can pass
    verification for two different challenges on the same commitment
    without actually knowing x, because if one *could*, this function
    would extract x from it — which is exactly what it does here.
    """
    if t1.t != t2.t:
        raise ValueError("transcripts must share the same commitment t to extract")
    if t1.c == t2.c:
        raise ValueError("transcripts must have different challenges to extract")
    c_diff = (t1.c - t2.c) % group.q
    s_diff = (t1.s - t2.s) % group.q
    c_diff_inv = pow(c_diff, -1, group.q)
    return (s_diff * c_diff_inv) % group.q
