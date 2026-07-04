"""
Block-cipher modes of operation built on the raw AES block cipher:
CBC with PKCS#7 padding, and GCM (Galois/Counter Mode) — CTR-mode
encryption plus GHASH authentication over GF(2^128), per NIST SP 800-38A
(CBC) and SP 800-38D (GCM).
"""
import os

from aes import AES

_BLOCK = 16


# ----------------------------------------------------------------------
# CBC (confidentiality only — no integrity/authentication; see GCM below
# and padding_oracle.py for exactly why that matters)
# ----------------------------------------------------------------------

def pkcs7_pad(data, block_size=_BLOCK):
    pad_len = block_size - (len(data) % block_size)
    return data + bytes([pad_len]) * pad_len


def pkcs7_unpad(data, block_size=_BLOCK):
    if not data or len(data) % block_size != 0:
        raise ValueError("invalid PKCS#7 padded data: bad length")
    pad_len = data[-1]
    if pad_len == 0 or pad_len > block_size:
        raise ValueError("invalid PKCS#7 padding: bad pad length byte")
    if data[-pad_len:] != bytes([pad_len]) * pad_len:
        raise ValueError("invalid PKCS#7 padding: bytes mismatch")
    return data[:-pad_len]


def _xor(a, b):
    return bytes(x ^ y for x, y in zip(a, b))


def cbc_encrypt(key, iv, plaintext):
    if len(iv) != _BLOCK:
        raise ValueError("IV must be 16 bytes")
    cipher = AES(key)
    padded = pkcs7_pad(plaintext)
    out = bytearray()
    prev = iv
    for i in range(0, len(padded), _BLOCK):
        block = padded[i:i + _BLOCK]
        enc_in = _xor(block, prev)
        enc_out = cipher.encrypt_block(enc_in)
        out += enc_out
        prev = enc_out
    return bytes(out)


def cbc_decrypt(key, iv, ciphertext, unpad=True):
    if len(iv) != _BLOCK:
        raise ValueError("IV must be 16 bytes")
    if len(ciphertext) == 0 or len(ciphertext) % _BLOCK != 0:
        raise ValueError("ciphertext must be a nonzero multiple of the block size")
    cipher = AES(key)
    out = bytearray()
    prev = iv
    for i in range(0, len(ciphertext), _BLOCK):
        block = ciphertext[i:i + _BLOCK]
        dec_out = cipher.decrypt_block(block)
        out += _xor(dec_out, prev)
        prev = block
    return pkcs7_unpad(bytes(out)) if unpad else bytes(out)


# ----------------------------------------------------------------------
# GCM (Galois/Counter Mode) — authenticated encryption. This is what
# vault.py and session.py actually use.
# ----------------------------------------------------------------------

_R = 0xE1000000000000000000000000000000  # GCM reduction constant (bit 128 reversed poly)


def _gf128_mul(x, y):
    """Multiplication in GF(2^128) with the GCM reduction polynomial,
    operating on the bit-reflected representation used by SP 800-38D
    (the MSB of the 128-bit integer is the leftmost bit of the field
    element)."""
    z = 0
    v = y
    for i in range(128):
        if (x >> (127 - i)) & 1:
            z ^= v
        if v & 1:
            v = (v >> 1) ^ _R
        else:
            v >>= 1
    return z


def _ghash(h, aad, ciphertext):
    def pad_to_block(b):
        rem = len(b) % 16
        return b if rem == 0 else b + b"\x00" * (16 - rem)

    data = pad_to_block(aad) + pad_to_block(ciphertext)
    y = 0
    for i in range(0, len(data), 16):
        block = int.from_bytes(data[i:i + 16], "big")
        y = _gf128_mul(y ^ block, h)

    lengths = (len(aad) * 8).to_bytes(8, "big") + (len(ciphertext) * 8).to_bytes(8, "big")
    y = _gf128_mul(y ^ int.from_bytes(lengths, "big"), h)
    return y.to_bytes(16, "big")


def _inc32(counter_block):
    prefix, ctr = counter_block[:12], int.from_bytes(counter_block[12:], "big")
    ctr = (ctr + 1) & 0xFFFFFFFF
    return prefix + ctr.to_bytes(4, "big")


def _gctr(cipher, icb, data):
    if not data:
        return b""
    out = bytearray()
    counter = icb
    for i in range(0, len(data), 16):
        keystream = cipher.encrypt_block(counter)
        chunk = data[i:i + 16]
        out += _xor(chunk, keystream[:len(chunk)])
        counter = _inc32(counter)
    return bytes(out)


def gcm_encrypt(key, iv, plaintext, aad=b"", tag_len=16):
    """AES-GCM encryption per SP 800-38D. iv should normally be 12 bytes
    (the standard/fast case implemented here). Returns (ciphertext, tag)."""
    if len(iv) != 12:
        raise ValueError("this implementation requires a 96-bit (12-byte) IV")
    cipher = AES(key)
    h = int.from_bytes(cipher.encrypt_block(b"\x00" * 16), "big")

    j0 = iv + b"\x00\x00\x00\x01"
    ciphertext = _gctr(cipher, _inc32(j0), plaintext)
    s = _ghash(h, aad, ciphertext)
    tag_full = _xor(cipher.encrypt_block(j0), s)
    return ciphertext, tag_full[:tag_len]


def gcm_decrypt(key, iv, ciphertext, tag, aad=b"", tag_len=16):
    """AES-GCM decryption + authentication. Raises ValueError (does NOT
    return partial plaintext) if the tag doesn't match — this is what
    makes GCM immune to the padding-oracle-style attack in
    padding_oracle.py."""
    if len(iv) != 12:
        raise ValueError("this implementation requires a 96-bit (12-byte) IV")
    if len(tag) != tag_len:
        raise ValueError("tag length mismatch")
    cipher = AES(key)
    h = int.from_bytes(cipher.encrypt_block(b"\x00" * 16), "big")

    j0 = iv + b"\x00\x00\x00\x01"
    s = _ghash(h, aad, ciphertext)
    expected_tag_full = _xor(cipher.encrypt_block(j0), s)
    expected_tag = expected_tag_full[:tag_len]

    if not _consttime_eq(expected_tag, tag):
        raise ValueError("GCM authentication failed: ciphertext or tag has been tampered with")

    return _gctr(cipher, _inc32(j0), ciphertext)


def _consttime_eq(a, b):
    if len(a) != len(b):
        return False
    diff = 0
    for x, y in zip(a, b):
        diff |= x ^ y
    return diff == 0


def random_bytes(n):
    return os.urandom(n)
