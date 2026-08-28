"""secp256k1 elliptic curve arithmetic and ECDSA, entirely from scratch.

This is the exact curve real Bitcoin/Ethereum wallets use. Everything here
is built on Python's arbitrary-precision integers: finite-field point
addition/doubling, scalar multiplication by double-and-add, modular inverse
via Fermat's little theorem (the field order is prime), RFC 6979
deterministic nonce generation (so signing is reproducible and never leaks
key material through a bad RNG), and minimal DER signature encoding.

No `ecdsa`/`cryptography`/`coincurve` package is used anywhere.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from typing import Optional, Tuple

# --- secp256k1 domain parameters (the curve y^2 = x^3 + 7 mod P) ----------
P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
A = 0
B = 7
GX = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
GY = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8
N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141

Point = Optional[Tuple[int, int]]  # None represents the point at infinity
G: Point = (GX, GY)


def _mod_inv(a: int, m: int) -> int:
    """Modular inverse via Fermat's little theorem (m must be prime)."""
    a = a % m
    if a == 0:
        raise ZeroDivisionError("inverse of 0")
    return pow(a, m - 2, m)


def is_on_curve(pt: Point) -> bool:
    if pt is None:
        return True
    x, y = pt
    return (y * y - (x * x * x + A * x + B)) % P == 0


def point_add(p1: Point, p2: Point) -> Point:
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2 and (y1 + y2) % P == 0:
        return None  # p1 == -p2 -> infinity
    if x1 == x2 and y1 == y2:
        # point doubling
        lam = (3 * x1 * x1 + A) * _mod_inv(2 * y1, P) % P
    else:
        lam = (y2 - y1) * _mod_inv((x2 - x1) % P, P) % P
    x3 = (lam * lam - x1 - x2) % P
    y3 = (lam * (x1 - x3) - y1) % P
    return (x3, y3)


def scalar_mult(k: int, pt: Point) -> Point:
    """Double-and-add scalar multiplication. O(log k) point operations."""
    if k % N == 0 or pt is None:
        return None
    if k < 0:
        return scalar_mult(-k, point_neg(pt))
    result: Point = None
    addend = pt
    while k:
        if k & 1:
            result = point_add(result, addend)
        addend = point_add(addend, addend)
        k >>= 1
    return result


def point_neg(pt: Point) -> Point:
    if pt is None:
        return None
    x, y = pt
    return (x, (-y) % P)


# --- keys -------------------------------------------------------------

def generate_private_key() -> int:
    """A uniformly random scalar in [1, N-1] using a CSPRNG."""
    while True:
        k = secrets.randbelow(N - 1) + 1
        if 1 <= k < N:
            return k


def private_to_public(privkey: int) -> Point:
    pub = scalar_mult(privkey, G)
    assert pub is not None, "private key produced point at infinity"
    return pub


def compress_pubkey(pub: Point) -> bytes:
    x, y = pub
    prefix = b"\x02" if y % 2 == 0 else b"\x03"
    return prefix + x.to_bytes(32, "big")


def decompress_pubkey(data: bytes) -> Point:
    if len(data) != 33 or data[0] not in (2, 3):
        raise ValueError("bad compressed pubkey encoding")
    x = int.from_bytes(data[1:], "big")
    y_sq = (x * x * x + A * x + B) % P
    y = pow(y_sq, (P + 1) // 4, P)  # P % 4 == 3 for secp256k1 -> fast sqrt
    if (y * y) % P != y_sq:
        raise ValueError("point is not on curve")
    if (y % 2 == 0) != (data[0] == 2):
        y = P - y
    pt = (x, y)
    if not is_on_curve(pt):
        raise ValueError("decompressed point is not on curve")
    return pt


# --- RFC 6979 deterministic nonce ---------------------------------------

def _bits2int(b: bytes, qlen_bits: int) -> int:
    x = int.from_bytes(b, "big")
    excess = len(b) * 8 - qlen_bits
    if excess > 0:
        x >>= excess
    return x


def _int2octets(x: int, rolen: int) -> bytes:
    return x.to_bytes(rolen, "big")


def _bits2octets(b: bytes, rolen: int) -> bytes:
    z1 = _bits2int(b, rolen * 8)
    z2 = z1 % N
    if z2 < 0:
        z2 += N
    return _int2octets(z2, rolen)


def _rfc6979_k(msg_hash: bytes, privkey: int) -> int:
    """Deterministic nonce per RFC 6979 using HMAC-SHA256."""
    rolen = 32
    hash_len = 32
    x = _int2octets(privkey, rolen)
    h1 = msg_hash
    v = b"\x01" * hash_len
    k = b"\x00" * hash_len
    k = hmac.new(k, v + b"\x00" + x + _bits2octets(h1, rolen), hashlib.sha256).digest()
    v = hmac.new(k, v, hashlib.sha256).digest()
    k = hmac.new(k, v + b"\x01" + x + _bits2octets(h1, rolen), hashlib.sha256).digest()
    v = hmac.new(k, v, hashlib.sha256).digest()
    while True:
        v = hmac.new(k, v, hashlib.sha256).digest()
        t = _bits2int(v, rolen * 8)
        if 1 <= t < N:
            return t
        k = hmac.new(k, v + b"\x00", hashlib.sha256).digest()
        v = hmac.new(k, v, hashlib.sha256).digest()


@dataclass(frozen=True)
class Signature:
    r: int
    s: int

    def to_der(self) -> bytes:
        def enc_int(x: int) -> bytes:
            b = x.to_bytes((x.bit_length() + 7) // 8 or 1, "big")
            if b[0] & 0x80:
                b = b"\x00" + b
            return b"\x02" + bytes([len(b)]) + b

        body = enc_int(self.r) + enc_int(self.s)
        return b"\x30" + bytes([len(body)]) + body

    @staticmethod
    def from_der(data: bytes) -> "Signature":
        if data[0] != 0x30:
            raise ValueError("bad DER signature")
        pos = 2
        if data[1] & 0x80:  # long-form length, not needed at our sizes
            raise ValueError("unsupported DER length")

        def read_int(buf: bytes, i: int) -> Tuple[int, int]:
            if buf[i] != 0x02:
                raise ValueError("bad DER integer tag")
            ln = buf[i + 1]
            val = int.from_bytes(buf[i + 2 : i + 2 + ln], "big")
            return val, i + 2 + ln

        r, pos = read_int(data, pos)
        s, pos = read_int(data, pos)
        return Signature(r, s)


def sign(msg_hash: bytes, privkey: int) -> Signature:
    """Sign a 32-byte digest with RFC 6979 deterministic k."""
    if len(msg_hash) != 32:
        raise ValueError("msg_hash must be 32 bytes")
    z = int.from_bytes(msg_hash, "big")
    while True:
        k = _rfc6979_k(msg_hash, privkey)
        R = scalar_mult(k, G)
        if R is None:
            continue
        r = R[0] % N
        if r == 0:
            continue
        k_inv = _mod_inv(k, N)
        s = (k_inv * (z + r * privkey)) % N
        if s == 0:
            continue
        if s > N // 2:  # low-S normalization (canonical, matches real wallets)
            s = N - s
        return Signature(r, s)


def verify(msg_hash: bytes, sig: Signature, pub: Point) -> bool:
    if len(msg_hash) != 32:
        return False
    r, s = sig.r, sig.s
    if not (1 <= r < N and 1 <= s < N):
        return False
    z = int.from_bytes(msg_hash, "big")
    w = _mod_inv(s, N)
    u1 = (z * w) % N
    u2 = (r * w) % N
    pt = point_add(scalar_mult(u1, G), scalar_mult(u2, pub))
    if pt is None:
        return False
    return pt[0] % N == r
