"""
HMAC-SHA256 (RFC 2104) and PBKDF2-HMAC-SHA256 (RFC 8018 section 5.2),
built entirely on our from-scratch `sha256()` — no `hmac`/`hashlib`.
"""
from sha256 import sha256, _H0, _compress, _compress_tail

_BLOCK_SIZE = 64  # SHA-256 block size in bytes
_DIGEST_SIZE = 32


def hmac_sha256(key, message):
    """RFC 2104 HMAC over SHA-256."""
    if len(key) > _BLOCK_SIZE:
        key = sha256(key)
    key = key + b"\x00" * (_BLOCK_SIZE - len(key))

    o_key_pad = bytes(b ^ 0x5C for b in key)
    i_key_pad = bytes(b ^ 0x36 for b in key)

    inner = sha256(i_key_pad + message)
    return sha256(o_key_pad + inner)


def hmac_sha256_hex(key, message):
    return hmac_sha256(key, message).hex()


def _xor_bytes(a, b):
    return bytes(x ^ y for x, y in zip(a, b))


class _CachedKeyHMAC:
    """Same HMAC-SHA256 as `hmac_sha256`, but for repeated calls with the
    SAME key (PBKDF2's inner loop calls HMAC thousands of times with an
    unchanging password): the ipad/opad key block is exactly one 64-byte
    SHA-256 block, so the compression state right after absorbing it is
    identical on every call and can be computed once instead of
    thousands of times. Verified byte-for-byte identical to
    `hmac_sha256` for the same (key, message) below."""

    def __init__(self, key):
        if len(key) > _BLOCK_SIZE:
            key = sha256(key)
        key = key + b"\x00" * (_BLOCK_SIZE - len(key))
        i_key_pad = bytes(b ^ 0x36 for b in key)
        o_key_pad = bytes(b ^ 0x5C for b in key)
        self._inner_state = _compress(list(_H0), i_key_pad)
        self._outer_state = _compress(list(_H0), o_key_pad)

    def compute(self, message):
        inner_digest = _compress_tail(self._inner_state, _BLOCK_SIZE, message)
        return _compress_tail(self._outer_state, _BLOCK_SIZE, inner_digest)


def pbkdf2_hmac_sha256(password, salt, iterations, dklen):
    """RFC 8018 section 5.2 PBKDF2 with PRF = HMAC-SHA256."""
    if iterations < 1:
        raise ValueError("iterations must be >= 1")
    if dklen <= 0:
        raise ValueError("dklen must be > 0")

    num_blocks = -(-dklen // _DIGEST_SIZE)  # ceil division
    if num_blocks > (2 ** 32 - 1):
        raise ValueError("derived key too long")

    prf = _CachedKeyHMAC(password)
    dk = bytearray()
    for block_index in range(1, num_blocks + 1):
        u = prf.compute(salt + block_index.to_bytes(4, "big"))
        t = bytearray(u)
        for _ in range(iterations - 1):
            u = prf.compute(u)
            t = bytearray(_xor_bytes(t, u))
        dk += t
    return bytes(dk[:dklen])
