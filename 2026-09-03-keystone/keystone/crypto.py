"""
From-scratch secp256k1 elliptic-curve cryptography + supporting primitives.

No `ecdsa`, `cryptography`, `secp256k1`, or `Crypto` packages anywhere in this
module. `hashlib.sha256` is used as a building block (Ironkey, an earlier
build in this repo, already implemented and NIST-vector-verified SHA-256
from scratch; redoing that here would be a repeat, not new work — see
PLAN.md). RIPEMD-160 *is* implemented from scratch below: OpenSSL 3 dropped
it from its default provider, so `hashlib.new('ripemd160')` isn't reliably
available on this box in the first place, and Bitcoin-style addresses need
it, so it has to exist here or not at all.

Curve: secp256k1 (the curve Bitcoin/Ethereum use), y^2 = x^3 + 7 over F_p.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# secp256k1 domain parameters (SEC 2, section 2.4.1)
# ---------------------------------------------------------------------------
P = 0xFFFFFFFF_FFFFFFFF_FFFFFFFF_FFFFFFFF_FFFFFFFF_FFFFFFFF_FFFFFFFE_FFFFFC2F
A = 0
B = 7
N = 0xFFFFFFFF_FFFFFFFF_FFFFFFFF_FFFFFFFE_BAAEDCE6_AF48A03B_BFD25E8C_D0364141
GX = 0x79BE667E_F9DCBBAC_55A06295_CE870B07_029BFCDB_2DCE28D9_59F2815B_16F81798
GY = 0x483ADA77_26A3C465_5DA4FBFC_0E1108A8_FD17B448_A6855419_9C47D08F_FB10D4B8

Point = tuple  # (x, y) or None for the point at infinity


def _inv_mod(a: int, m: int) -> int:
    """Modular inverse via the extended Euclidean algorithm."""
    if a == 0:
        raise ZeroDivisionError("inverse of 0")
    return pow(a, -1, m)


def point_add(p1, p2):
    """Elliptic-curve point addition over F_P, short-Weierstrass form."""
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2 and (y1 + y2) % P == 0:
        return None  # p2 == -p1
    if p1 == p2:
        if y1 == 0:
            return None
        lam = (3 * x1 * x1 + A) * _inv_mod(2 * y1, P) % P
    else:
        lam = (y2 - y1) * _inv_mod((x2 - x1) % P, P) % P
    x3 = (lam * lam - x1 - x2) % P
    y3 = (lam * (x1 - x3) - y1) % P
    return (x3, y3)


def scalar_mult(k: int, point):
    """Double-and-add scalar multiplication. k must be reduced mod N by caller."""
    if k % N == 0 or point is None:
        return None
    if k < 0:
        return scalar_mult(-k, point_neg(point))
    result = None
    addend = point
    while k:
        if k & 1:
            result = point_add(result, addend)
        addend = point_add(addend, addend)
        k >>= 1
    return result


def point_neg(point):
    if point is None:
        return None
    x, y = point
    return (x, (-y) % P)


G = (GX, GY)
assert (GY * GY - (GX**3 + A * GX + B)) % P == 0, "generator not on curve"


def is_on_curve(point) -> bool:
    if point is None:
        return True
    x, y = point
    return (y * y - (x**3 + A * x + B)) % P == 0


# ---------------------------------------------------------------------------
# Keys
# ---------------------------------------------------------------------------

def generate_private_key() -> int:
    """A uniformly random scalar in [1, N-1] using a CSPRNG."""
    while True:
        k = secrets.randbelow(N - 1) + 1
        if 1 <= k < N:
            return k


def private_to_public(privkey: int):
    if not (1 <= privkey < N):
        raise ValueError("private key out of range")
    return scalar_mult(privkey, G)


def compress_pubkey(pub) -> bytes:
    x, y = pub
    prefix = b"\x02" if y % 2 == 0 else b"\x03"
    return prefix + x.to_bytes(32, "big")


def decompress_pubkey(data: bytes):
    if len(data) != 33 or data[0] not in (2, 3):
        raise ValueError("bad compressed pubkey")
    x = int.from_bytes(data[1:], "big")
    y_sq = (x**3 + A * x + B) % P
    y = pow(y_sq, (P + 1) // 4, P)  # P % 4 == 3 for secp256k1, so this is valid sqrt
    if (y * y) % P != y_sq:
        raise ValueError("point not on curve")
    if (y % 2 == 0) != (data[0] == 2):
        y = P - y
    return (x, y)


# ---------------------------------------------------------------------------
# ECDSA, RFC 6979 deterministic nonce (no randomness needed to sign, and no
# risk of the classic "reused-k leaks the private key" disaster)
# ---------------------------------------------------------------------------

def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def double_sha256(data: bytes) -> bytes:
    return sha256(sha256(data))


def _bits2int(b: bytes) -> int:
    x = int.from_bytes(b, "big")
    excess = len(b) * 8 - N.bit_length()
    if excess > 0:
        x >>= excess
    return x


def _int2octets(x: int) -> bytes:
    return x.to_bytes(32, "big")


def _bits2octets(b: bytes) -> bytes:
    z1 = _bits2int(b)
    z2 = z1 % N
    return _int2octets(z2)


def rfc6979_k(privkey: int, msg_hash: bytes):
    """RFC 6979 deterministic-k generator, HMAC-SHA256 variant. Yields
    successive candidate nonces (near-always just the first is used)."""
    x = _int2octets(privkey)
    h1 = msg_hash
    v = b"\x01" * 32
    k = b"\x00" * 32
    k = hmac.new(k, v + b"\x00" + x + _bits2octets(h1), hashlib.sha256).digest()
    v = hmac.new(k, v, hashlib.sha256).digest()
    k = hmac.new(k, v + b"\x01" + x + _bits2octets(h1), hashlib.sha256).digest()
    v = hmac.new(k, v, hashlib.sha256).digest()
    while True:
        v = hmac.new(k, v, hashlib.sha256).digest()
        candidate = _bits2int(v)
        yield candidate
        k = hmac.new(k, v + b"\x00", hashlib.sha256).digest()
        v = hmac.new(k, v, hashlib.sha256).digest()


def sign(privkey: int, msg_hash: bytes) -> tuple:
    """Sign a 32-byte digest, return low-s-normalized (r, s)."""
    if len(msg_hash) != 32:
        raise ValueError("msg_hash must be 32 bytes")
    z = int.from_bytes(msg_hash, "big")
    for k in rfc6979_k(privkey, msg_hash):
        if not (0 < k < N):
            continue
        R = scalar_mult(k, G)
        if R is None:
            continue
        r = R[0] % N
        if r == 0:
            continue
        s = (_inv_mod(k, N) * (z + r * privkey)) % N
        if s == 0:
            continue
        if s > N // 2:  # low-S normalization (BIP-62 style), canonical form
            s = N - s
        return (r, s)


def verify(pub, msg_hash: bytes, sig: tuple) -> bool:
    r, s = sig
    if not (0 < r < N and 0 < s < N):
        return False
    if not is_on_curve(pub) or pub is None:
        return False
    z = int.from_bytes(msg_hash, "big")
    w = _inv_mod(s, N)
    u1 = (z * w) % N
    u2 = (r * w) % N
    point = point_add(scalar_mult(u1, G), scalar_mult(u2, pub))
    if point is None:
        return False
    return point[0] % N == r


# ---------------------------------------------------------------------------
# RIPEMD-160, implemented from scratch (ISO/IEC 10118-3), for addresses.
# ---------------------------------------------------------------------------

def _rol(x: int, n: int) -> int:
    x &= 0xFFFFFFFF
    return ((x << n) | (x >> (32 - n))) & 0xFFFFFFFF


_R1 = [
    0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15,
    7, 4, 13, 1, 10, 6, 15, 3, 12, 0, 9, 5, 2, 14, 11, 8,
    3, 10, 14, 4, 9, 15, 8, 1, 2, 7, 0, 6, 13, 11, 5, 12,
    1, 9, 11, 10, 0, 8, 12, 4, 13, 3, 7, 15, 14, 5, 6, 2,
    4, 0, 5, 9, 7, 12, 2, 10, 14, 1, 3, 8, 11, 6, 15, 13,
]
_R2 = [
    5, 14, 7, 0, 9, 2, 11, 4, 13, 6, 15, 8, 1, 10, 3, 12,
    6, 11, 3, 7, 0, 13, 5, 10, 14, 15, 8, 12, 4, 9, 1, 2,
    15, 5, 1, 3, 7, 14, 6, 9, 11, 8, 12, 2, 10, 0, 4, 13,
    8, 6, 4, 1, 3, 11, 15, 0, 5, 12, 2, 13, 9, 7, 10, 14,
    12, 15, 10, 4, 1, 5, 8, 7, 6, 2, 13, 14, 0, 3, 9, 11,
]
_S1 = [
    11, 14, 15, 12, 5, 8, 7, 9, 11, 13, 14, 15, 6, 7, 9, 8,
    7, 6, 8, 13, 11, 9, 7, 15, 7, 12, 15, 9, 11, 7, 13, 12,
    11, 13, 6, 7, 14, 9, 13, 15, 14, 8, 13, 6, 5, 12, 7, 5,
    11, 12, 14, 15, 14, 15, 9, 8, 9, 14, 5, 6, 8, 6, 5, 12,
    9, 15, 5, 11, 6, 8, 13, 12, 5, 12, 13, 14, 11, 8, 5, 6,
]
_S2 = [
    8, 9, 9, 11, 13, 15, 15, 5, 7, 7, 8, 11, 14, 14, 12, 6,
    9, 13, 15, 7, 12, 8, 9, 11, 7, 7, 12, 7, 6, 15, 13, 11,
    9, 7, 15, 11, 8, 6, 6, 14, 12, 13, 5, 14, 13, 13, 7, 5,
    15, 5, 8, 11, 14, 14, 6, 14, 6, 9, 12, 9, 12, 5, 15, 8,
    8, 5, 12, 9, 12, 5, 14, 6, 8, 13, 6, 5, 15, 13, 11, 11,
]


def _f(j, x, y, z):
    if j < 16:
        return x ^ y ^ z
    if j < 32:
        return (x & y) | (~x & 0xFFFFFFFF & z)
    if j < 48:
        return (x | (~y & 0xFFFFFFFF)) ^ z
    if j < 64:
        return (x & z) | (y & ~z & 0xFFFFFFFF)
    return x ^ (y | (~z & 0xFFFFFFFF))


_K1 = [0x00000000, 0x5A827999, 0x6ED9EBA1, 0x8F1BBCDC, 0xA953FD4E]
_K2 = [0x50A28BE6, 0x5C4DD124, 0x6D703EF3, 0x7A6D76E9, 0x00000000]


def ripemd160(message: bytes) -> bytes:
    h0, h1, h2, h3, h4 = 0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476, 0xC3D2E1F0

    msg_len_bits = (len(message) * 8) & 0xFFFFFFFFFFFFFFFF
    padded = bytearray(message)
    padded.append(0x80)
    while len(padded) % 64 != 56:
        padded.append(0)
    padded += msg_len_bits.to_bytes(8, "little")

    for block_start in range(0, len(padded), 64):
        block = padded[block_start:block_start + 64]
        X = [int.from_bytes(block[i:i + 4], "little") for i in range(0, 64, 4)]

        al, bl, cl, dl, el = h0, h1, h2, h3, h4
        ar, br, cr, dr, er = h0, h1, h2, h3, h4

        for j in range(80):
            round_ = j // 16
            # left line
            t = (al + _f(j, bl, cl, dl) + X[_R1[j]] + _K1[round_]) & 0xFFFFFFFF
            t = (_rol(t, _S1[j]) + el) & 0xFFFFFFFF
            al, bl, cl, dl, el = el, t, bl, _rol(cl, 10), dl
            # right line (mirrored: f(79-j, ...), independent message
            # schedule/rotations/constants — this is what makes RIPEMD-160
            # resistant to attacks that broke plain MD4/MD5-family hashes)
            t = (ar + _f(79 - j, br, cr, dr) + X[_R2[j]] + _K2[round_]) & 0xFFFFFFFF
            t = (_rol(t, _S2[j]) + er) & 0xFFFFFFFF
            ar, br, cr, dr, er = er, t, br, _rol(cr, 10), dr

        t = (h1 + cl + dr) & 0xFFFFFFFF
        h1 = (h2 + dl + er) & 0xFFFFFFFF
        h2 = (h3 + el + ar) & 0xFFFFFFFF
        h3 = (h4 + al + br) & 0xFFFFFFFF
        h4 = (h0 + bl + cr) & 0xFFFFFFFF
        h0 = t

    return b"".join(h.to_bytes(4, "little") for h in (h0, h1, h2, h3, h4))


def hash160(data: bytes) -> bytes:
    """Bitcoin-style RIPEMD160(SHA256(data)), used to derive addresses."""
    return ripemd160(sha256(data))


# ---------------------------------------------------------------------------
# Base58Check encoding (Bitcoin's alphabet — no 0/O/I/l — with a 4-byte
# double-SHA256 checksum so a mistyped address is caught, not silently
# accepted).
# ---------------------------------------------------------------------------

_B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58encode(data: bytes) -> str:
    n = int.from_bytes(data, "big")
    out = ""
    while n > 0:
        n, rem = divmod(n, 58)
        out = _B58_ALPHABET[rem] + out
    # preserve leading zero bytes as leading '1's
    n_leading_zeros = len(data) - len(data.lstrip(b"\x00"))
    return "1" * n_leading_zeros + out


def b58decode(s: str) -> bytes:
    n = 0
    for ch in s:
        if ch not in _B58_ALPHABET:
            raise ValueError(f"invalid base58 character {ch!r}")
        n = n * 58 + _B58_ALPHABET.index(ch)
    n_leading_ones = len(s) - len(s.lstrip("1"))
    body = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    return b"\x00" * n_leading_ones + body


def b58check_encode(payload: bytes, version: int = 0x00) -> str:
    versioned = bytes([version]) + payload
    checksum = double_sha256(versioned)[:4]
    return b58encode(versioned + checksum)


def b58check_decode(s: str) -> tuple:
    raw = b58decode(s)
    if len(raw) < 5:
        raise ValueError("base58check string too short")
    versioned, checksum = raw[:-4], raw[-4:]
    if double_sha256(versioned)[:4] != checksum:
        raise ValueError("bad base58check checksum")
    return versioned[0], versioned[1:]
