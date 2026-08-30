"""From-scratch secp256k1 elliptic-curve cryptography.

Implements the exact curve Bitcoin uses (secp256k1): finite-field and
elliptic-curve point arithmetic, keypair generation, ECDSA sign/verify,
and base58check address encoding. No `ecdsa`/`cryptography`/`secp256k1`
package is used anywhere in this module — every operation below is plain
Python big-integer arithmetic.

Hashing (SHA-256) uses the stdlib `hashlib` — this project's from-scratch
subject is the *consensus protocol and its cryptographic authorization*,
not SHA-256's internal bit-diffusion (already built from scratch in this
repo's Cryptex/Ironkey), so we lean on the standard library for that one
primitive.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# secp256k1 domain parameters (the exact curve: y^2 = x^3 + 7 over F_p)
# ---------------------------------------------------------------------------
P = 0xFFFFFFFF_FFFFFFFF_FFFFFFFF_FFFFFFFF_FFFFFFFF_FFFFFFFF_FFFFFFFE_FFFFFC2F
A = 0
B = 7
N = 0xFFFFFFFF_FFFFFFFF_FFFFFFFF_FFFFFFFE_BAAEDCE6_AF48A03B_BFD25E8C_D0364141
GX = 0x79BE667E_F9DCBBAC_55A06295_CE870B07_029BFCDB_2DCE28D9_59F2815B_16F81798
GY = 0x483ADA77_26A3C465_5DA4FBFC_0E1108A8_FD17B448_A6855419_9C47D08F_FB10D4B8
G = (GX, GY)  # generator point


def _inv_mod(a: int, m: int) -> int:
    """Modular inverse via the extended Euclidean algorithm."""
    if a == 0:
        raise ZeroDivisionError("inverse of 0")
    a %= m
    old_r, r = a, m
    old_s, s = 1, 0
    while r != 0:
        q = old_r // r
        old_r, r = r, old_r - q * r
        old_s, s = s, old_s - q * s
    # old_r is gcd(a, m); must be 1 for an inverse to exist
    if old_r != 1:
        raise ValueError("no inverse exists")
    return old_s % m


def point_add(p1, p2):
    """Add two points on the curve over F_P. `None` is the point at infinity."""
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2 and (y1 + y2) % P == 0:
        return None  # P + (-P) = infinity
    if x1 == x2 and y1 == y2:
        # point doubling: slope = (3x1^2 + a) / (2y1)
        m = (3 * x1 * x1 + A) * _inv_mod(2 * y1, P) % P
    else:
        m = (y2 - y1) * _inv_mod(x2 - x1, P) % P
    x3 = (m * m - x1 - x2) % P
    y3 = (m * (x1 - x3) - y1) % P
    return (x3, y3)


def point_mul(k: int, point=G):
    """Scalar multiplication via double-and-add."""
    if k % N == 0 or point is None:
        return None
    if k < 0:
        return point_mul(-k, (point[0], (-point[1]) % P))
    result = None
    addend = point
    while k:
        if k & 1:
            result = point_add(result, addend)
        addend = point_add(addend, addend)
        k >>= 1
    return result


def is_on_curve(point) -> bool:
    if point is None:
        return True
    x, y = point
    return (y * y - (x * x * x + A * x + B)) % P == 0


# ---------------------------------------------------------------------------
# Hashing helpers
# ---------------------------------------------------------------------------

def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def hash256(data: bytes) -> bytes:
    """Double SHA-256, exactly as Bitcoin uses for block/tx hashing."""
    return sha256(sha256(data))


def hash160(data: bytes) -> bytes:
    """RIPEMD-160(SHA-256(data)) — the standard pubkey-hash used for addresses.

    hashlib provides ripemd160 via OpenSSL's legacy provider on most builds;
    if unavailable in this environment we fall back to a compact from-scratch
    RIPEMD-160 implementation so address derivation never silently breaks.
    """
    h = sha256(data)
    try:
        r = hashlib.new("ripemd160")
        r.update(h)
        return r.digest()
    except (ValueError, TypeError):
        return _ripemd160(h)


# --- from-scratch RIPEMD-160 fallback (used only if hashlib lacks it) ------
def _ripemd160(message: bytes) -> bytes:
    def rol(x, n):
        return ((x << n) | (x >> (32 - n))) & 0xFFFFFFFF

    r1 = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15,
          7, 4, 13, 1, 10, 6, 15, 3, 12, 0, 9, 5, 2, 14, 11, 8,
          3, 10, 14, 4, 9, 15, 8, 1, 2, 7, 0, 6, 13, 11, 5, 12,
          1, 9, 11, 10, 0, 8, 12, 4, 13, 3, 7, 15, 14, 5, 6, 2,
          4, 0, 5, 9, 7, 12, 2, 10, 14, 1, 3, 8, 11, 6, 15, 13]
    r2 = [5, 14, 7, 0, 9, 2, 11, 4, 13, 6, 15, 8, 1, 10, 3, 12,
          6, 11, 3, 7, 0, 13, 5, 10, 14, 15, 8, 12, 4, 9, 1, 2,
          15, 5, 1, 3, 7, 14, 6, 9, 11, 8, 12, 2, 10, 0, 4, 13,
          8, 6, 4, 1, 3, 11, 15, 0, 5, 12, 2, 13, 9, 7, 10, 14,
          12, 15, 10, 4, 1, 5, 8, 7, 6, 2, 13, 14, 0, 3, 9, 11]
    s1 = [11, 14, 15, 12, 5, 8, 7, 9, 11, 13, 14, 15, 6, 7, 9, 8,
          7, 6, 8, 13, 11, 9, 7, 15, 7, 12, 15, 9, 11, 7, 13, 12,
          11, 13, 6, 7, 14, 9, 13, 15, 14, 8, 13, 6, 5, 12, 7, 5,
          11, 12, 14, 15, 14, 15, 9, 8, 9, 14, 5, 6, 8, 6, 5, 12,
          9, 15, 5, 11, 6, 8, 13, 12, 5, 12, 13, 14, 11, 8, 5, 6]
    s2 = [8, 9, 9, 11, 13, 15, 15, 5, 7, 7, 8, 11, 14, 14, 12, 6,
          9, 13, 15, 7, 12, 8, 9, 11, 7, 7, 12, 7, 6, 15, 13, 11,
          9, 7, 15, 11, 8, 6, 6, 14, 12, 13, 5, 14, 13, 13, 7, 5,
          15, 5, 8, 11, 14, 14, 6, 14, 6, 9, 12, 9, 12, 5, 15, 8,
          8, 5, 12, 9, 12, 5, 14, 6, 8, 13, 6, 5, 15, 13, 11, 11]

    def f(j, x, y, z):
        if j < 16:
            return x ^ y ^ z
        if j < 32:
            return (x & y) | (~x & 0xFFFFFFFF & z)
        if j < 48:
            return (x | (~y & 0xFFFFFFFF)) ^ z
        if j < 64:
            return (x & z) | (y & ~z & 0xFFFFFFFF)
        return x ^ (y | (~z & 0xFFFFFFFF))

    K1 = [0x00000000, 0x5A827999, 0x6ED9EBA1, 0x8F1BBCDC, 0xA953FD4E]
    K2 = [0x50A28BE6, 0x5C4DD124, 0x6D703EF3, 0x7A6D76E9, 0x00000000]

    msg = bytearray(message)
    orig_len_bits = (len(message) * 8) & 0xFFFFFFFFFFFFFFFF
    msg.append(0x80)
    while len(msg) % 64 != 56:
        msg.append(0)
    msg += orig_len_bits.to_bytes(8, "little")

    h0, h1, h2, h3, h4 = 0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476, 0xC3D2E1F0
    for chunk_start in range(0, len(msg), 64):
        chunk = msg[chunk_start:chunk_start + 64]
        X = [int.from_bytes(chunk[i:i + 4], "little") for i in range(0, 64, 4)]
        A1 = B1 = C1 = D1 = E1 = h0, h1, h2, h3, h4
        al, bl, cl, dl, el = h0, h1, h2, h3, h4
        ar, br, cr, dr, er = h0, h1, h2, h3, h4
        for j in range(80):
            t = (al + f(j, bl, cl, dl) + X[r1[j]] + K1[j // 16]) & 0xFFFFFFFF
            t = rol(t, s1[j])
            t = (t + el) & 0xFFFFFFFF
            al, el, dl, cl, bl = el, dl, rol(cl, 10), bl, t

            t = (ar + f(79 - j, br, cr, dr) + X[r2[j]] + K2[j // 16]) & 0xFFFFFFFF
            t = rol(t, s2[j])
            t = (t + er) & 0xFFFFFFFF
            ar, er, dr, cr, br = er, dr, rol(cr, 10), br, t
        t = (h1 + cl + dr) & 0xFFFFFFFF
        h1 = (h2 + dl + er) & 0xFFFFFFFF
        h2 = (h3 + el + ar) & 0xFFFFFFFF
        h3 = (h4 + al + br) & 0xFFFFFFFF
        h4 = (h0 + bl + cr) & 0xFFFFFFFF
        h0 = t
    out = b"".join(x.to_bytes(4, "little") for x in (h0, h1, h2, h3, h4))
    return out


# ---------------------------------------------------------------------------
# Keypairs
# ---------------------------------------------------------------------------

@dataclass
class KeyPair:
    private_key: int
    public_key: tuple  # (x, y) point on the curve

    @staticmethod
    def generate(rng: os.urandom = None) -> "KeyPair":
        priv = int.from_bytes(os.urandom(32), "big") % (N - 1) + 1
        pub = point_mul(priv, G)
        return KeyPair(priv, pub)

    @staticmethod
    def from_private(priv: int) -> "KeyPair":
        priv %= N
        if priv == 0:
            raise ValueError("private key must be nonzero")
        return KeyPair(priv, point_mul(priv, G))

    def pubkey_bytes(self) -> bytes:
        """Compressed SEC format: 0x02/0x03 prefix + 32-byte x coordinate."""
        x, y = self.public_key
        prefix = b"\x02" if y % 2 == 0 else b"\x03"
        return prefix + x.to_bytes(32, "big")

    def address(self) -> str:
        return pubkey_to_address(self.pubkey_bytes())


def decompress_pubkey(data: bytes) -> tuple:
    if len(data) != 33 or data[0] not in (2, 3):
        raise ValueError("expected 33-byte compressed pubkey")
    x = int.from_bytes(data[1:], "big")
    rhs = (x * x * x + A * x + B) % P
    y = pow(rhs, (P + 1) // 4, P)  # valid sqrt exponent since P % 4 == 3
    if (y * y - rhs) % P != 0:
        raise ValueError("point not on curve")
    if (y % 2 == 0) != (data[0] == 2):
        y = P - y
    return (x, y)


# ---------------------------------------------------------------------------
# ECDSA
# ---------------------------------------------------------------------------

def sign(message_hash: bytes, private_key: int, k: int = None) -> tuple:
    """Sign a 32-byte hash. Returns (r, s), low-s normalized (BIP-62 style)."""
    z = int.from_bytes(message_hash, "big")
    if k is None:
        # Deterministic-ish nonce: derived from message + key + fresh entropy,
        # so it is never reused across signatures (a reused k leaks the key).
        k_material = private_key.to_bytes(32, "big") + message_hash + os.urandom(16)
        k = int.from_bytes(hashlib.sha256(k_material).digest(), "big") % N
    if k == 0:
        k = 1
    r = point_mul(k, G)[0] % N
    if r == 0:
        return sign(message_hash, private_key)  # retry with fresh k (astronomically rare)
    s = (_inv_mod(k, N) * (z + r * private_key)) % N
    if s == 0:
        return sign(message_hash, private_key)
    if s > N // 2:
        s = N - s  # low-s normalization: prevents trivial signature malleability
    return (r, s)


def verify(message_hash: bytes, signature: tuple, public_key: tuple) -> bool:
    r, s = signature
    if not (1 <= r < N and 1 <= s < N):
        return False
    if not is_on_curve(public_key):
        return False
    z = int.from_bytes(message_hash, "big")
    try:
        s_inv = _inv_mod(s, N)
    except (ZeroDivisionError, ValueError):
        return False
    u1 = (z * s_inv) % N
    u2 = (r * s_inv) % N
    point = point_add(point_mul(u1, G), point_mul(u2, public_key))
    if point is None:
        return False
    return point[0] % N == r


# ---------------------------------------------------------------------------
# Base58Check addresses
# ---------------------------------------------------------------------------
_B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
VERSION_BYTE = b"\x00"  # single network in this project; kept for realism


def b58encode(data: bytes) -> str:
    n = int.from_bytes(data, "big")
    out = ""
    while n > 0:
        n, rem = divmod(n, 58)
        out = _B58_ALPHABET[rem] + out
    # preserve leading zero bytes as leading '1's (Bitcoin convention)
    n_leading_zeros = len(data) - len(data.lstrip(b"\x00"))
    return "1" * n_leading_zeros + out


def b58decode(s: str) -> bytes:
    n = 0
    for ch in s:
        if ch not in _B58_ALPHABET:
            raise ValueError(f"invalid base58 character: {ch!r}")
        n = n * 58 + _B58_ALPHABET.index(ch)
    n_leading_ones = len(s) - len(s.lstrip("1"))
    body = n.to_bytes((n.bit_length() + 7) // 8, "big") if n > 0 else b""
    return b"\x00" * n_leading_ones + body


def pubkey_to_address(pubkey_bytes: bytes) -> str:
    payload = VERSION_BYTE + hash160(pubkey_bytes)
    checksum = hash256(payload)[:4]
    return b58encode(payload + checksum)


def address_to_pubkey_hash(address: str) -> bytes:
    raw = b58decode(address)
    if len(raw) != 25:
        raise ValueError("invalid address length")
    payload, checksum = raw[:21], raw[21:]
    if hash256(payload)[:4] != checksum:
        raise ValueError("invalid address checksum")
    if payload[:1] != VERSION_BYTE:
        raise ValueError("invalid address version byte")
    return payload[1:]
