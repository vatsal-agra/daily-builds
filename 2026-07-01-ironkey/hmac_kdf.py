"""
HMAC-SHA256 (RFC 2104) and PBKDF2-HMAC-SHA256 (RFC 8018 section 5.2),
built entirely on our from-scratch `sha256()` — no `hmac`/`hashlib`.
"""
from sha256 import sha256

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


def pbkdf2_hmac_sha256(password, salt, iterations, dklen):
    """RFC 8018 section 5.2 PBKDF2 with PRF = HMAC-SHA256."""
    if iterations < 1:
        raise ValueError("iterations must be >= 1")
    if dklen <= 0:
        raise ValueError("dklen must be > 0")

    num_blocks = -(-dklen // _DIGEST_SIZE)  # ceil division
    if num_blocks > (2 ** 32 - 1):
        raise ValueError("derived key too long")

    dk = bytearray()
    for block_index in range(1, num_blocks + 1):
        u = hmac_sha256(password, salt + block_index.to_bytes(4, "big"))
        t = bytearray(u)
        for _ in range(iterations - 1):
            u = hmac_sha256(password, u)
            t = bytearray(_xor_bytes(t, u))
        dk += t
    return bytes(dk[:dklen])
