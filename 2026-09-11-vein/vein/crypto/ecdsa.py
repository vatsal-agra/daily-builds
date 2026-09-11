"""Deterministic ECDSA (RFC 6979) over secp256k1, from scratch.

Uses RFC 6979 to derive the per-signature nonce `k` from the private key
and message hash via HMAC-SHA256, instead of a fresh random nonce. This
makes signing byte-for-byte reproducible (same key + same message always
produces the same signature — good for testing) and, more importantly,
closes the real-world nonce-reuse vulnerability that leaks a private key
outright if two signatures ever share a `k` (the exact bug that let
attackers recover a Sony PS3 signing key, and that has bitten several
real Bitcoin wallets).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .curve import G, N, Point, scalar_mult, point_add, is_on_curve
from .hashes import hmac_sha256, sha256

_QLEN = N.bit_length()  # 256
_RLEN = (_QLEN + 7) // 8  # 32 bytes


def _bits2int(data: bytes) -> int:
    x = int.from_bytes(data, "big")
    excess = len(data) * 8 - _QLEN
    if excess > 0:
        x >>= excess
    return x


def _int2octets(x: int) -> bytes:
    return x.to_bytes(_RLEN, "big")


def _bits2octets(data: bytes) -> bytes:
    z = _bits2int(data) % N
    return _int2octets(z)


def generate_privkey() -> int:
    """A fresh random private key in [1, N-1], from os.urandom (a real CSPRNG)."""
    while True:
        k = int.from_bytes(os.urandom(32), "big")
        if 1 <= k <= N - 1:
            return k


def _deterministic_k(privkey: int, msg_hash: bytes) -> int:
    """RFC 6979 section 3.2: derive a deterministic per-message nonce."""
    x_octets = _int2octets(privkey % N)
    h1_octets = _bits2octets(msg_hash)

    v = b"\x01" * 32
    k = b"\x00" * 32
    k = hmac_sha256(k, v + b"\x00" + x_octets + h1_octets)
    v = hmac_sha256(k, v)
    k = hmac_sha256(k, v + b"\x01" + x_octets + h1_octets)
    v = hmac_sha256(k, v)

    while True:
        t = b""
        while len(t) < _RLEN:
            v = hmac_sha256(k, v)
            t += v
        candidate = _bits2int(t)
        if 1 <= candidate <= N - 1:
            return candidate
        k = hmac_sha256(k, v + b"\x00")
        v = hmac_sha256(k, v)


@dataclass(frozen=True)
class Signature:
    r: int
    s: int

    def der_encode(self) -> bytes:
        def enc_int(x: int) -> bytes:
            b = x.to_bytes((x.bit_length() + 7) // 8 or 1, "big")
            if b[0] & 0x80:
                b = b"\x00" + b
            return b"\x02" + len(b).to_bytes(1, "big") + b

        body = enc_int(self.r) + enc_int(self.s)
        return b"\x30" + len(body).to_bytes(1, "big") + body

    @staticmethod
    def der_decode(data: bytes) -> "Signature":
        if data[0] != 0x30:
            raise ValueError("not a DER sequence")
        pos = 2
        assert data[pos] == 0x02
        rlen = data[pos + 1]
        r = int.from_bytes(data[pos + 2:pos + 2 + rlen], "big")
        pos += 2 + rlen
        assert data[pos] == 0x02
        slen = data[pos + 1]
        s = int.from_bytes(data[pos + 2:pos + 2 + slen], "big")
        return Signature(r, s)


def sign(privkey: int, msg_hash: bytes) -> Signature:
    """Sign a 32-byte message hash (e.g. double_sha256(tx)) with a private key."""
    if len(msg_hash) != 32:
        raise ValueError("msg_hash must be 32 bytes")
    z = _bits2int(msg_hash) % N

    while True:
        k = _deterministic_k(privkey, msg_hash)
        r_point = scalar_mult(k, G)
        r = r_point.x % N
        if r == 0:
            continue
        k_inv = pow(k, N - 2, N)
        s = (k_inv * (z + r * privkey)) % N
        if s == 0:
            continue
        # Low-S normalization: canonical form used by Bitcoin to remove
        # the trivial (r, s) / (r, N-s) signature-malleability ambiguity.
        if s > N // 2:
            s = N - s
        return Signature(r, s)


def verify(pubkey: Point, msg_hash: bytes, sig: Signature) -> bool:
    if len(msg_hash) != 32:
        raise ValueError("msg_hash must be 32 bytes")
    if not is_on_curve(pubkey) or pubkey.is_infinity():
        return False
    r, s = sig.r, sig.s
    if not (1 <= r <= N - 1 and 1 <= s <= N - 1):
        return False

    z = _bits2int(msg_hash) % N
    w = pow(s, N - 2, N)
    u1 = (z * w) % N
    u2 = (r * w) % N
    point = point_add(scalar_mult(u1, G), scalar_mult(u2, pubkey))
    if point.is_infinity():
        return False
    return point.x % N == r
