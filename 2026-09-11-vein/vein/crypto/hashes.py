"""From-scratch SHA-256 and RIPEMD-160.

Both hash functions are implemented directly from their published
specifications (FIPS 180-4 for SHA-256; Dobbertin/Bosselaers/Preneel's
1996 RIPEMD-160 spec) using nothing but Python integers and bytes —
`hashlib` is never imported here. `hashlib.sha256` / `hashlib.new("ripemd160")`
are used only inside the test suite, as a differential oracle to catch
bugs in these implementations, never on the runtime code path.
"""

from __future__ import annotations

_MASK32 = 0xFFFFFFFF


def _rotl32(x: int, n: int) -> int:
    x &= _MASK32
    return ((x << n) | (x >> (32 - n))) & _MASK32


def _rotr32(x: int, n: int) -> int:
    x &= _MASK32
    return ((x >> n) | (x << (32 - n))) & _MASK32


# --------------------------------------------------------------------------
# SHA-256 (FIPS 180-4)
# --------------------------------------------------------------------------

_SHA256_K = (
    0x428A2F98, 0x71374491, 0xB5C0FBCF, 0xE9B5DBA5, 0x3956C25B, 0x59F111F1, 0x923F82A4, 0xAB1C5ED5,
    0xD807AA98, 0x12835B01, 0x243185BE, 0x550C7DC3, 0x72BE5D74, 0x80DEB1FE, 0x9BDC06A7, 0xC19BF174,
    0xE49B69C1, 0xEFBE4786, 0x0FC19DC6, 0x240CA1CC, 0x2DE92C6F, 0x4A7484AA, 0x5CB0A9DC, 0x76F988DA,
    0x983E5152, 0xA831C66D, 0xB00327C8, 0xBF597FC7, 0xC6E00BF3, 0xD5A79147, 0x06CA6351, 0x14292967,
    0x27B70A85, 0x2E1B2138, 0x4D2C6DFC, 0x53380D13, 0x650A7354, 0x766A0ABB, 0x81C2C92E, 0x92722C85,
    0xA2BFE8A1, 0xA81A664B, 0xC24B8B70, 0xC76C51A3, 0xD192E819, 0xD6990624, 0xF40E3585, 0x106AA070,
    0x19A4C116, 0x1E376C08, 0x2748774C, 0x34B0BCB5, 0x391C0CB3, 0x4ED8AA4A, 0x5B9CCA4F, 0x682E6FF3,
    0x748F82EE, 0x78A5636F, 0x84C87814, 0x8CC70208, 0x90BEFFFA, 0xA4506CEB, 0xBEF9A3F7, 0xC67178F2,
)

_SHA256_H0 = (
    0x6A09E667, 0xBB67AE85, 0x3C6EF372, 0xA54FF53A,
    0x510E527F, 0x9B05688C, 0x1F83D9AB, 0x5BE0CD19,
)


def sha256(data: bytes) -> bytes:
    msg = bytearray(data)
    bit_len = len(data) * 8
    msg.append(0x80)
    while len(msg) % 64 != 56:
        msg.append(0)
    msg += bit_len.to_bytes(8, "big")

    h = list(_SHA256_H0)
    for off in range(0, len(msg), 64):
        chunk = msg[off:off + 64]
        w = [0] * 64
        for i in range(16):
            w[i] = int.from_bytes(chunk[i * 4:i * 4 + 4], "big")
        for i in range(16, 64):
            s0 = _rotr32(w[i - 15], 7) ^ _rotr32(w[i - 15], 18) ^ (w[i - 15] >> 3)
            s1 = _rotr32(w[i - 2], 17) ^ _rotr32(w[i - 2], 19) ^ (w[i - 2] >> 10)
            w[i] = (w[i - 16] + s0 + w[i - 7] + s1) & _MASK32

        a, b, c, d, e, f, g, hh = h
        for i in range(64):
            s1 = _rotr32(e, 6) ^ _rotr32(e, 11) ^ _rotr32(e, 25)
            ch = (e & f) ^ ((~e & _MASK32) & g)
            temp1 = (hh + s1 + ch + _SHA256_K[i] + w[i]) & _MASK32
            s0 = _rotr32(a, 2) ^ _rotr32(a, 13) ^ _rotr32(a, 22)
            maj = (a & b) ^ (a & c) ^ (b & c)
            temp2 = (s0 + maj) & _MASK32

            hh, g, f = g, f, e
            e = (d + temp1) & _MASK32
            d, c, b = c, b, a
            a = (temp1 + temp2) & _MASK32

        h = [(x + y) & _MASK32 for x, y in zip(h, (a, b, c, d, e, f, g, hh))]

    return b"".join(x.to_bytes(4, "big") for x in h)


def double_sha256(data: bytes) -> bytes:
    """Bitcoin-style hash256: sha256(sha256(data)). Used throughout Vein."""
    return sha256(sha256(data))


# --------------------------------------------------------------------------
# RIPEMD-160
# --------------------------------------------------------------------------

_RMD_R_LEFT = (
    0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15,
    7, 4, 13, 1, 10, 6, 15, 3, 12, 0, 9, 5, 2, 14, 11, 8,
    3, 10, 14, 4, 9, 15, 8, 1, 2, 7, 0, 6, 13, 11, 5, 12,
    1, 9, 11, 10, 0, 8, 12, 4, 13, 3, 7, 15, 14, 5, 6, 2,
    4, 0, 5, 9, 7, 12, 2, 10, 14, 1, 3, 8, 11, 6, 15, 13,
)
_RMD_R_RIGHT = (
    5, 14, 7, 0, 9, 2, 11, 4, 13, 6, 15, 8, 1, 10, 3, 12,
    6, 11, 3, 7, 0, 13, 5, 10, 14, 15, 8, 12, 4, 9, 1, 2,
    15, 5, 1, 3, 7, 14, 6, 9, 11, 8, 12, 2, 10, 0, 4, 13,
    8, 6, 4, 1, 3, 11, 15, 0, 5, 12, 2, 13, 9, 7, 10, 14,
    12, 15, 10, 4, 1, 5, 8, 7, 6, 2, 13, 14, 0, 3, 9, 11,
)
_RMD_S_LEFT = (
    11, 14, 15, 12, 5, 8, 7, 9, 11, 13, 14, 15, 6, 7, 9, 8,
    7, 6, 8, 13, 11, 9, 7, 15, 7, 12, 15, 9, 11, 7, 13, 12,
    11, 13, 6, 7, 14, 9, 13, 15, 14, 8, 13, 6, 5, 12, 7, 5,
    11, 12, 14, 15, 14, 15, 9, 8, 9, 14, 5, 6, 8, 6, 5, 12,
    9, 15, 5, 11, 6, 8, 13, 12, 5, 12, 13, 14, 11, 8, 5, 6,
)
_RMD_S_RIGHT = (
    8, 9, 9, 11, 13, 15, 15, 5, 7, 7, 8, 11, 14, 14, 12, 6,
    9, 13, 15, 7, 12, 8, 9, 11, 7, 7, 12, 7, 6, 15, 13, 11,
    9, 7, 15, 11, 8, 6, 6, 14, 12, 13, 5, 14, 13, 13, 7, 5,
    15, 5, 8, 11, 14, 14, 6, 14, 6, 9, 12, 9, 12, 5, 15, 8,
    8, 5, 12, 9, 12, 5, 14, 6, 8, 13, 6, 5, 15, 13, 11, 11,
)
_RMD_K_LEFT = (0x00000000, 0x5A827999, 0x6ED9EBA1, 0x8F1BBCDC, 0xA953FD4E)
_RMD_K_RIGHT = (0x50A28BE6, 0x5C4DD124, 0x6D703EF3, 0x7A6D76E9, 0x00000000)


def _rmd_f(j: int, x: int, y: int, z: int) -> int:
    if j < 16:
        return x ^ y ^ z
    if j < 32:
        return (x & y) | ((~x & _MASK32) & z)
    if j < 48:
        return (x | (~y & _MASK32)) ^ z
    if j < 64:
        return (x & z) | (y & (~z & _MASK32))
    return x ^ (y | (~z & _MASK32))


def ripemd160(data: bytes) -> bytes:
    msg = bytearray(data)
    bit_len = len(data) * 8
    msg.append(0x80)
    while len(msg) % 64 != 56:
        msg.append(0)
    msg += bit_len.to_bytes(8, "little")

    h0, h1, h2, h3, h4 = 0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476, 0xC3D2E1F0

    for off in range(0, len(msg), 64):
        chunk = msg[off:off + 64]
        x = [int.from_bytes(chunk[i * 4:i * 4 + 4], "little") for i in range(16)]

        al, bl, cl, dl, el = h0, h1, h2, h3, h4
        ar, br, cr, dr, er = h0, h1, h2, h3, h4

        for j in range(80):
            round_idx = j // 16
            t = (al + _rmd_f(j, bl, cl, dl) + x[_RMD_R_LEFT[j]] + _RMD_K_LEFT[round_idx]) & _MASK32
            t = _rotl32(t, _RMD_S_LEFT[j])
            t = (t + el) & _MASK32
            al, el, dl, cl, bl = el, dl, _rotl32(cl, 10), bl, t

            round_idx_r = j // 16
            t = (ar + _rmd_f(79 - j, br, cr, dr) + x[_RMD_R_RIGHT[j]] + _RMD_K_RIGHT[round_idx_r]) & _MASK32
            t = _rotl32(t, _RMD_S_RIGHT[j])
            t = (t + er) & _MASK32
            ar, er, dr, cr, br = er, dr, _rotl32(cr, 10), br, t

        t = (h1 + cl + dr) & _MASK32
        h1 = (h2 + dl + er) & _MASK32
        h2 = (h3 + el + ar) & _MASK32
        h3 = (h4 + al + br) & _MASK32
        h4 = (h0 + bl + cr) & _MASK32
        h0 = t

    return b"".join(x.to_bytes(4, "little") for x in (h0, h1, h2, h3, h4))


def hash160(data: bytes) -> bytes:
    """Bitcoin-style hash160: ripemd160(sha256(data)). Used for addresses."""
    return ripemd160(sha256(data))


# --------------------------------------------------------------------------
# HMAC-SHA256 (RFC 2104), built on the from-scratch sha256 above.
# Needed for RFC 6979 deterministic ECDSA nonce generation.
# --------------------------------------------------------------------------

_HMAC_BLOCK_SIZE = 64


def hmac_sha256(key: bytes, message: bytes) -> bytes:
    if len(key) > _HMAC_BLOCK_SIZE:
        key = sha256(key)
    key = key + b"\x00" * (_HMAC_BLOCK_SIZE - len(key))
    o_key_pad = bytes(b ^ 0x5C for b in key)
    i_key_pad = bytes(b ^ 0x36 for b in key)
    return sha256(o_key_pad + sha256(i_key_pad + message))
