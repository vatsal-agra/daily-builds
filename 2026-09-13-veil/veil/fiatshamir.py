"""The Fiat-Shamir transform: interactive Schnorr -> non-interactive proof
-> a real signature scheme.

The interactive Schnorr protocol needs a live verifier to hand back a
random challenge `c`. Fiat-Shamir (1986) replaces that verifier with a hash
function acting as a "random oracle": the prover computes their own
challenge as

    c = H(t, context)

where `context` binds the proof to whatever it should be tied to. With no
context, this is a non-interactive zero-knowledge proof-of-knowledge (NIZK)
of the discrete log. Bind `context` to a message and this becomes exactly
the **Schnorr signature scheme** — one of the two signature schemes
actually used in production cryptography (the other being ECDSA, which
Cryptex and Vein already built) and the direct ancestor of EdDSA/Ed25519.

Security-relevant properties demonstrated here, all runnable:

- **Message-binding**: flipping a single bit of the signed message changes
  `H(t, message)` and invalidates the signature (`test_tamper_detected`).
- **Non-malleability of the *signature* under a fixed message**: you cannot
  take a valid (t, s) and message m and derive a different valid (t', s')
  for the same m without knowing x (same soundness argument as Schnorr
  itself — the extractor in schnorr.py applies unchanged if a forger could
  ever answer two different self-chosen challenges for the same t).
- **Replay is NOT prevented by the signature alone** (a signature does not
  expire or bind to a nonce/session) — `sign` documents this and the
  membership.py flagship demo shows what real replay protection this
  enables looks like: a used one-time nonce log.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass

from veil.group import SchnorrGroup, default_rng, is_valid_group_element
from veil.schnorr import KeyPair, generate_keypair  # re-exported for convenience

__all__ = ["KeyPair", "generate_keypair", "Signature", "sign", "verify", "prove", "verify_proof"]


def _hash_challenge(group: SchnorrGroup, t: int, context: bytes) -> int:
    h = hashlib.sha256(str(t).encode() + b"|" + context).digest()
    return int.from_bytes(h, "big") % group.q


@dataclass(frozen=True)
class Signature:
    t: int
    s: int


def sign(
    group: SchnorrGroup, keypair: KeyPair, message: bytes, rng: random.Random | None = None
) -> Signature:
    """Produce a Schnorr signature over `message`. NOTE: this binds the
    signature to the message content, not to freshness — signing the same
    message twice is fine (each signing draws a fresh random nonce r, so
    two signatures of the same message look different) but a *verifier*
    who wants replay protection must track which (message, signature)
    pairs it has already accepted, exactly like membership.py does.
    """
    rng = rng or default_rng()
    r = group.random_exponent(rng)
    t = group.pow_g(r)
    c = _hash_challenge(group, t, message)
    s = (r + c * keypair.x) % group.q
    return Signature(t=t, s=s)


def verify(group: SchnorrGroup, y: int, message: bytes, sig: Signature) -> bool:
    if not is_valid_group_element(group, y):
        # See REVIEW.md Finding 1 — same degenerate-key rejection Schnorr
        # verification needs, since this is the same equation under Fiat-
        # Shamir.
        return False
    c = _hash_challenge(group, sig.t, message)
    lhs = group.pow_g(sig.s)
    rhs = (sig.t * pow(y, c, group.p)) % group.p
    return lhs == rhs


# Non-interactive proof-of-knowledge with no message context (context=b"")
# is the same construction under the hood; kept as separate names because
# "prove I know x" and "sign this message as x" are different use cases
# even though the math is identical.


def prove(group: SchnorrGroup, keypair: KeyPair, rng: random.Random | None = None) -> Signature:
    return sign(group, keypair, b"", rng)


def verify_proof(group: SchnorrGroup, y: int, proof: Signature) -> bool:
    return verify(group, y, b"", proof)
