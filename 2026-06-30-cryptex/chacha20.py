"""ChaCha20 stream cipher and Poly1305 MAC from scratch (RFC 8439).

Implements:
  - ChaCha20 quarter round and block function (20 rounds)
  - ChaCha20 stream cipher (keystream XOR)
  - Poly1305 one-time MAC (130-bit integer arithmetic)
  - ChaCha20-Poly1305 AEAD (Authenticated Encryption with Associated Data)

No external crypto libraries.
"""

import struct


# ---------------------------------------------------------------------------
# ChaCha20
# ---------------------------------------------------------------------------

def _u32(x: int) -> int:
    return x & 0xFFFFFFFF


def _rotl32(x: int, n: int) -> int:
    return _u32((x << n) | (x >> (32 - n)))


def _quarter_round(state: list[int], a: int, b: int, c: int, d: int) -> None:
    """ChaCha20 quarter round in-place."""
    state[a] = _u32(state[a] + state[b]); state[d] = _rotl32(state[d] ^ state[a], 16)
    state[c] = _u32(state[c] + state[d]); state[b] = _rotl32(state[b] ^ state[c], 12)
    state[a] = _u32(state[a] + state[b]); state[d] = _rotl32(state[d] ^ state[a],  8)
    state[c] = _u32(state[c] + state[d]); state[b] = _rotl32(state[b] ^ state[c],  7)


def _chacha20_block(key: bytes, counter: int, nonce: bytes) -> bytes:
    """Produce one 64-byte ChaCha20 block (RFC 8439 §2.1.1)."""
    assert len(key) == 32
    assert len(nonce) == 12
    k = struct.unpack("<8I", key)
    n = struct.unpack("<3I", nonce)
    state = [
        0x61707865, 0x3320646E, 0x79622D32, 0x6B206574,  # "expa", "nd 3", "2-by", "te k"
        k[0], k[1], k[2], k[3],
        k[4], k[5], k[6], k[7],
        counter & 0xFFFFFFFF, n[0], n[1], n[2],
    ]
    working = list(state)
    for _ in range(10):  # 20 rounds = 10 double rounds
        _quarter_round(working, 0, 4,  8, 12)
        _quarter_round(working, 1, 5,  9, 13)
        _quarter_round(working, 2, 6, 10, 14)
        _quarter_round(working, 3, 7, 11, 15)
        _quarter_round(working, 0, 5, 10, 15)
        _quarter_round(working, 1, 6, 11, 12)
        _quarter_round(working, 2, 7,  8, 13)
        _quarter_round(working, 3, 4,  9, 14)
    out = [_u32(working[i] + state[i]) for i in range(16)]
    return struct.pack("<16I", *out)


def chacha20_keystream(key: bytes, nonce: bytes, counter: int, length: int) -> bytes:
    """Generate `length` bytes of ChaCha20 keystream."""
    blocks = bytearray()
    block_counter = counter
    while len(blocks) < length:
        blocks.extend(_chacha20_block(key, block_counter, nonce))
        block_counter += 1
    return bytes(blocks[:length])


def chacha20_encrypt(key: bytes, nonce: bytes, plaintext: bytes,
                     counter: int = 0) -> bytes:
    """Encrypt (or decrypt — XOR cipher) with ChaCha20."""
    ks = chacha20_keystream(key, nonce, counter, len(plaintext))
    return bytes(p ^ k for p, k in zip(plaintext, ks))


chacha20_decrypt = chacha20_encrypt


# ---------------------------------------------------------------------------
# Poly1305 MAC (RFC 8439 §2.5)
# ---------------------------------------------------------------------------

def poly1305_mac(message: bytes, one_time_key: bytes) -> bytes:
    """Compute Poly1305 MAC. one_time_key must be 32 bytes."""
    assert len(one_time_key) == 32

    # Clamp r (first 16 bytes)
    r_bytes = bytearray(one_time_key[:16])
    # Clamping: clear specific bits per RFC 8439 §2.5
    r_bytes[3] &= 0x0F
    r_bytes[7] &= 0x0F
    r_bytes[11] &= 0x0F
    r_bytes[15] &= 0x0F
    r_bytes[4] &= 0xFC
    r_bytes[8] &= 0xFC
    r_bytes[12] &= 0xFC
    r = int.from_bytes(r_bytes, "little")

    s = int.from_bytes(one_time_key[16:32], "little")
    _P = (1 << 130) - 5  # Poly1305 prime

    accumulator = 0
    for i in range(0, len(message), 16):
        block = message[i:i + 16]
        # Append 1-bit after the block
        n = int.from_bytes(block, "little") | (1 << (8 * len(block)))
        accumulator = (r * (accumulator + n)) % _P

    # Final tag
    tag = (accumulator + s) & 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF  # mod 2^128
    return tag.to_bytes(16, "little")


def poly1305_verify(message: bytes, key: bytes, expected_tag: bytes) -> bool:
    """Constant-time MAC verification."""
    tag = poly1305_mac(message, key)
    # XOR all bytes to check equality (constant-time-ish in Python)
    diff = 0
    for a, b in zip(tag, expected_tag):
        diff |= a ^ b
    return diff == 0 and len(tag) == len(expected_tag)


# ---------------------------------------------------------------------------
# ChaCha20-Poly1305 AEAD (RFC 8439 §2.8)
# ---------------------------------------------------------------------------

def _pad16(data: bytes) -> bytes:
    pad = (16 - len(data) % 16) % 16
    return data + b"\x00" * pad


def _poly1305_key_gen(key: bytes, nonce: bytes) -> bytes:
    """Generate one-time Poly1305 key using ChaCha20 block 0."""
    block = _chacha20_block(key, 0, nonce)
    return block[:32]


def chacha20_poly1305_encrypt(key: bytes, nonce: bytes, plaintext: bytes,
                               aad: bytes = b"") -> tuple[bytes, bytes]:
    """Encrypt and authenticate. Returns (ciphertext, tag)."""
    assert len(key) == 32
    assert len(nonce) == 12
    ciphertext = chacha20_encrypt(key, nonce, plaintext, counter=1)
    otk = _poly1305_key_gen(key, nonce)
    mac_data = (
        _pad16(aad) + _pad16(ciphertext)
        + struct.pack("<QQ", len(aad), len(ciphertext))
    )
    tag = poly1305_mac(mac_data, otk)
    return ciphertext, tag


def chacha20_poly1305_decrypt(key: bytes, nonce: bytes, ciphertext: bytes,
                               tag: bytes, aad: bytes = b"") -> bytes:
    """Verify MAC and decrypt. Raises ValueError if authentication fails."""
    assert len(key) == 32
    assert len(nonce) == 12
    otk = _poly1305_key_gen(key, nonce)
    mac_data = (
        _pad16(aad) + _pad16(ciphertext)
        + struct.pack("<QQ", len(aad), len(ciphertext))
    )
    if not poly1305_verify(mac_data, otk, tag):
        raise ValueError("Authentication tag mismatch — ciphertext tampered or wrong key")
    return chacha20_decrypt(key, nonce, ciphertext, counter=1)
