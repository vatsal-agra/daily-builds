"""
SHA-256 implemented from the FIPS 180-4 specification: message padding,
64-word message schedule expansion, and the 64-round compression
function over eight 32-bit working variables. No `hashlib`.
"""

_MASK32 = 0xFFFFFFFF

# First 32 bits of the fractional parts of the cube roots of the first
# 64 primes (FIPS 180-4 section 4.2.2).
_K = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1,
    0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
    0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786,
    0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147,
    0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
    0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
    0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a,
    0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
    0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
]

# First 32 bits of the fractional parts of the square roots of the first
# 8 primes (initial hash value, FIPS 180-4 section 5.3.3).
_H0 = [
    0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
    0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
]


def _rotr(x, n):
    return ((x >> n) | (x << (32 - n))) & _MASK32


def _pad(message):
    """FIPS 180-4 section 5.1.1 padding: append 0x80, zero-pad, then the
    64-bit big-endian bit length, to a multiple of 512 bits (64 bytes)."""
    ml = len(message) * 8
    msg = bytearray(message)
    msg.append(0x80)
    while len(msg) % 64 != 56:
        msg.append(0)
    msg += ml.to_bytes(8, "big")
    return bytes(msg)


def _compress(h, block):
    w = [0] * 64
    for t in range(16):
        w[t] = int.from_bytes(block[t * 4:t * 4 + 4], "big")
    for t in range(16, 64):
        s0 = _rotr(w[t - 15], 7) ^ _rotr(w[t - 15], 18) ^ (w[t - 15] >> 3)
        s1 = _rotr(w[t - 2], 17) ^ _rotr(w[t - 2], 19) ^ (w[t - 2] >> 10)
        w[t] = (w[t - 16] + s0 + w[t - 7] + s1) & _MASK32

    a, b, c, d, e, f, g, hh = h

    for t in range(64):
        S1 = _rotr(e, 6) ^ _rotr(e, 11) ^ _rotr(e, 25)
        ch = (e & f) ^ ((~e & _MASK32) & g)
        temp1 = (hh + S1 + ch + _K[t] + w[t]) & _MASK32
        S0 = _rotr(a, 2) ^ _rotr(a, 13) ^ _rotr(a, 22)
        maj = (a & b) ^ (a & c) ^ (b & c)
        temp2 = (S0 + maj) & _MASK32

        hh = g
        g = f
        f = e
        e = (d + temp1) & _MASK32
        d = c
        c = b
        b = a
        a = (temp1 + temp2) & _MASK32

    return [
        (h[0] + a) & _MASK32, (h[1] + b) & _MASK32, (h[2] + c) & _MASK32,
        (h[3] + d) & _MASK32, (h[4] + e) & _MASK32, (h[5] + f) & _MASK32,
        (h[6] + g) & _MASK32, (h[7] + hh) & _MASK32,
    ]


def sha256(message):
    """Return the 32-byte SHA-256 digest of `message` (bytes-like)."""
    if isinstance(message, str):
        raise TypeError("sha256() requires bytes, not str — encode first")
    padded = _pad(message)
    h = list(_H0)
    for offset in range(0, len(padded), 64):
        h = _compress(h, padded[offset:offset + 64])
    return b"".join(x.to_bytes(4, "big") for x in h)


def sha256_hex(message):
    return sha256(message).hex()


class SHA256:
    """Incremental/streaming interface mirroring hashlib's, built on the
    same `sha256()` primitive (buffers and hashes on `digest()` — SHA-256's
    Merkle-Damgard state is exposed here only through the top-level
    function to keep the from-scratch compression function the single
    source of truth)."""

    def __init__(self, data=b""):
        self._buf = bytearray(data)

    def update(self, data):
        self._buf += data
        return self

    def digest(self):
        return sha256(bytes(self._buf))

    def hexdigest(self):
        return self.digest().hex()
