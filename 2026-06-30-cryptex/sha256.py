"""SHA-256 and HMAC-SHA256 from scratch (FIPS 180-4).

No hashlib, no hmac module used in the implementation — only stdlib `struct`
for packing integers. The round constants and initial hash values are computed
from prime square/cube roots as specified in the standard.
"""

import struct


# ---------------------------------------------------------------------------
# Round constants K[0..63]: first 32 bits of the fractional parts of the
# cube roots of the first 64 primes (2, 3, 5, 7, ...).
# ---------------------------------------------------------------------------

def _is_prime(n: int) -> bool:
    if n < 2:
        return False
    if n < 4:
        return True
    if n % 2 == 0 or n % 3 == 0:
        return False
    i = 5
    while i * i <= n:
        if n % i == 0 or n % (i + 2) == 0:
            return False
        i += 6
    return True


def _nth_primes(count: int) -> list[int]:
    primes, n = [], 2
    while len(primes) < count:
        if _is_prime(n):
            primes.append(n)
        n += 1
    return primes


def _frac32(x: float) -> int:
    """First 32 bits of the fractional part of x."""
    frac = x - int(x)
    return int(frac * (2 ** 32)) & 0xFFFFFFFF


_PRIMES64 = _nth_primes(64)
_PRIMES8 = _PRIMES64[:8]

K: tuple[int, ...] = tuple(_frac32(p ** (1 / 3)) for p in _PRIMES64)
H0: tuple[int, ...] = tuple(_frac32(p ** 0.5) for p in _PRIMES8)


# ---------------------------------------------------------------------------
# Bit operations
# ---------------------------------------------------------------------------

def _ror(x: int, n: int) -> int:
    return ((x >> n) | (x << (32 - n))) & 0xFFFFFFFF


def _add(*args: int) -> int:
    result = 0
    for a in args:
        result = (result + a) & 0xFFFFFFFF
    return result


# ---------------------------------------------------------------------------
# SHA-256 compression
# ---------------------------------------------------------------------------

def _compress(H: list[int], block: bytes) -> list[int]:
    """Process one 64-byte block and return updated hash state."""
    assert len(block) == 64
    W = list(struct.unpack(">16I", block))
    for i in range(16, 64):
        s0 = _ror(W[i - 15], 7) ^ _ror(W[i - 15], 18) ^ (W[i - 15] >> 3)
        s1 = _ror(W[i - 2], 17) ^ _ror(W[i - 2], 19) ^ (W[i - 2] >> 10)
        W.append(_add(W[i - 16], s0, W[i - 7], s1))

    a, b, c, d, e, f, g, h = H

    for i in range(64):
        S1 = _ror(e, 6) ^ _ror(e, 11) ^ _ror(e, 25)
        ch = (e & f) ^ (~e & g) & 0xFFFFFFFF
        temp1 = _add(h, S1, ch, K[i], W[i])
        S0 = _ror(a, 2) ^ _ror(a, 13) ^ _ror(a, 22)
        maj = (a & b) ^ (a & c) ^ (b & c)
        temp2 = _add(S0, maj)
        h, g, f, e, d, c, b, a = g, f, e, _add(d, temp1), c, b, a, _add(temp1, temp2)

    return [_add(H[i], v) for i, v in enumerate([a, b, c, d, e, f, g, h])]


# ---------------------------------------------------------------------------
# Public SHA-256
# ---------------------------------------------------------------------------

def sha256(message: bytes) -> bytes:
    """Compute SHA-256 of message. Returns 32 bytes."""
    # Padding: append 1-bit, then zeros, then 64-bit big-endian length.
    bit_len = len(message) * 8
    message = bytearray(message)
    message.append(0x80)
    while len(message) % 64 != 56:
        message.append(0x00)
    message += struct.pack(">Q", bit_len)

    H = list(H0)
    for i in range(0, len(message), 64):
        H = _compress(H, bytes(message[i:i + 64]))

    return struct.pack(">8I", *H)


def sha256_hex(message: bytes) -> str:
    return sha256(message).hex()


# ---------------------------------------------------------------------------
# HMAC-SHA256
# ---------------------------------------------------------------------------

_BLOCK_SIZE = 64


def hmac_sha256(key: bytes, message: bytes) -> bytes:
    """HMAC-SHA256 per RFC 2104."""
    # Normalize key to block size
    if len(key) > _BLOCK_SIZE:
        key = sha256(key)
    key = key.ljust(_BLOCK_SIZE, b"\x00")

    ipad = bytes(k ^ 0x36 for k in key)
    opad = bytes(k ^ 0x5C for k in key)

    inner = sha256(ipad + message)
    return sha256(opad + inner)


def hmac_sha256_hex(key: bytes, message: bytes) -> str:
    return hmac_sha256(key, message).hex()
