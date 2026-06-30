"""AES-256 implementation (Rijndael) from scratch.

Covers:
  - 14-round AES-256 cipher (encrypt + decrypt)
  - ECB mode (raw block, for testing)
  - CBC mode with PKCS#7 padding
  - CTR mode (nonce + 64-bit counter)

Only gf256.py (our own) is imported for field arithmetic.
No hashlib/hmac/Crypto/ssl imports.
"""

import os
import struct
from gf256 import SBOX, INV_SBOX, RCON, mul

_BLOCK = 16  # bytes
_NROUNDS = 14  # AES-256
_NK = 8  # 32-byte key = 8 words


# ---------------------------------------------------------------------------
# Low-level state helpers
# ---------------------------------------------------------------------------

def _bytes_to_state(block: bytes) -> list[list[int]]:
    """Convert 16 bytes to a 4×4 column-major state matrix."""
    state = [[0] * 4 for _ in range(4)]
    for r in range(4):
        for c in range(4):
            state[r][c] = block[r + 4 * c]
    return state


def _state_to_bytes(state: list[list[int]]) -> bytes:
    return bytes(state[r][c] for c in range(4) for r in range(4))


# ---------------------------------------------------------------------------
# Key schedule
# ---------------------------------------------------------------------------

def _sub_word(word: list[int]) -> list[int]:
    return [SBOX[b] for b in word]


def _rot_word(word: list[int]) -> list[int]:
    return word[1:] + word[:1]


def key_schedule(key: bytes) -> list[list[int]]:
    """Expand a 32-byte key into 15 round keys (each 4×4 state = 16 bytes).

    Returns a flat list of 60 32-bit words (as 4-byte lists).
    """
    assert len(key) == 32, "AES-256 requires a 32-byte key"
    W: list[list[int]] = []
    for i in range(_NK):
        W.append(list(key[4 * i: 4 * i + 4]))

    for i in range(_NK, 4 * (_NROUNDS + 1)):
        temp = list(W[i - 1])
        if i % _NK == 0:
            temp = _sub_word(_rot_word(temp))
            # FIPS 197: Rcon[i/Nk] where Rcon[1]=0x01, Rcon[2]=0x02, ...
            # Our RCON array is 0-indexed (RCON[0]=1), so offset by 1.
            temp[0] ^= RCON[i // _NK - 1]
        elif i % _NK == 4:
            temp = _sub_word(temp)
        W.append([W[i - _NK][j] ^ temp[j] for j in range(4)])
    return W


def _get_round_key(W: list[list[int]], rnd: int) -> list[list[int]]:
    """Extract round key r as a 4×4 state matrix."""
    state = [[0] * 4 for _ in range(4)]
    for c in range(4):
        word = W[rnd * 4 + c]
        for r in range(4):
            state[r][c] = word[r]
    return state


# ---------------------------------------------------------------------------
# AES round transformations
# ---------------------------------------------------------------------------

def _add_round_key(state: list[list[int]], rk: list[list[int]]) -> None:
    for r in range(4):
        for c in range(4):
            state[r][c] ^= rk[r][c]


def _sub_bytes(state: list[list[int]]) -> None:
    for r in range(4):
        for c in range(4):
            state[r][c] = SBOX[state[r][c]]


def _inv_sub_bytes(state: list[list[int]]) -> None:
    for r in range(4):
        for c in range(4):
            state[r][c] = INV_SBOX[state[r][c]]


def _shift_rows(state: list[list[int]]) -> None:
    for r in range(1, 4):
        state[r] = state[r][r:] + state[r][:r]


def _inv_shift_rows(state: list[list[int]]) -> None:
    for r in range(1, 4):
        state[r] = state[r][4 - r:] + state[r][:4 - r]


def _mix_columns(state: list[list[int]]) -> None:
    for c in range(4):
        s0, s1, s2, s3 = state[0][c], state[1][c], state[2][c], state[3][c]
        state[0][c] = mul(0x02, s0) ^ mul(0x03, s1) ^ s2 ^ s3
        state[1][c] = s0 ^ mul(0x02, s1) ^ mul(0x03, s2) ^ s3
        state[2][c] = s0 ^ s1 ^ mul(0x02, s2) ^ mul(0x03, s3)
        state[3][c] = mul(0x03, s0) ^ s1 ^ s2 ^ mul(0x02, s3)


def _inv_mix_columns(state: list[list[int]]) -> None:
    for c in range(4):
        s0, s1, s2, s3 = state[0][c], state[1][c], state[2][c], state[3][c]
        state[0][c] = mul(0x0e, s0) ^ mul(0x0b, s1) ^ mul(0x0d, s2) ^ mul(0x09, s3)
        state[1][c] = mul(0x09, s0) ^ mul(0x0e, s1) ^ mul(0x0b, s2) ^ mul(0x0d, s3)
        state[2][c] = mul(0x0d, s0) ^ mul(0x09, s1) ^ mul(0x0e, s2) ^ mul(0x0b, s3)
        state[3][c] = mul(0x0b, s0) ^ mul(0x0d, s1) ^ mul(0x09, s2) ^ mul(0x0e, s3)


# ---------------------------------------------------------------------------
# Core block cipher
# ---------------------------------------------------------------------------

def aes256_encrypt_block(block: bytes, W: list[list[int]]) -> bytes:
    """Encrypt a single 16-byte block with the expanded key schedule W."""
    assert len(block) == _BLOCK
    state = _bytes_to_state(block)
    _add_round_key(state, _get_round_key(W, 0))
    for rnd in range(1, _NROUNDS):
        _sub_bytes(state)
        _shift_rows(state)
        _mix_columns(state)
        _add_round_key(state, _get_round_key(W, rnd))
    _sub_bytes(state)
    _shift_rows(state)
    _add_round_key(state, _get_round_key(W, _NROUNDS))
    return _state_to_bytes(state)


def aes256_decrypt_block(block: bytes, W: list[list[int]]) -> bytes:
    """Decrypt a single 16-byte block with the expanded key schedule W."""
    assert len(block) == _BLOCK
    state = _bytes_to_state(block)
    _add_round_key(state, _get_round_key(W, _NROUNDS))
    for rnd in range(_NROUNDS - 1, 0, -1):
        _inv_shift_rows(state)
        _inv_sub_bytes(state)
        _add_round_key(state, _get_round_key(W, rnd))
        _inv_mix_columns(state)
    _inv_shift_rows(state)
    _inv_sub_bytes(state)
    _add_round_key(state, _get_round_key(W, 0))
    return _state_to_bytes(state)


# ---------------------------------------------------------------------------
# PKCS#7 padding
# ---------------------------------------------------------------------------

def pkcs7_pad(data: bytes, block_size: int = _BLOCK) -> bytes:
    pad_len = block_size - (len(data) % block_size)
    return data + bytes([pad_len] * pad_len)


def pkcs7_unpad(data: bytes) -> bytes:
    if not data:
        raise ValueError("Empty data cannot be unpadded")
    pad_len = data[-1]
    if pad_len == 0 or pad_len > _BLOCK:
        raise ValueError(f"Invalid PKCS#7 pad byte: {pad_len}")
    if data[-pad_len:] != bytes([pad_len] * pad_len):
        raise ValueError("PKCS#7 padding verification failed")
    return data[:-pad_len]


# ---------------------------------------------------------------------------
# Mode wrappers
# ---------------------------------------------------------------------------

class AES256:
    """AES-256 cipher with CBC and CTR modes."""

    def __init__(self, key: bytes):
        if len(key) != 32:
            raise ValueError("AES-256 requires a 32-byte (256-bit) key")
        self._key = key
        self._W = key_schedule(key)

    # ECB (raw, for test vectors only)
    def encrypt_block(self, block: bytes) -> bytes:
        return aes256_encrypt_block(block, self._W)

    def decrypt_block(self, block: bytes) -> bytes:
        return aes256_decrypt_block(block, self._W)

    # CBC
    def encrypt_cbc(self, plaintext: bytes, iv: bytes) -> bytes:
        if len(iv) != _BLOCK:
            raise ValueError("IV must be 16 bytes")
        padded = pkcs7_pad(plaintext)
        ct = bytearray()
        prev = iv
        for i in range(0, len(padded), _BLOCK):
            chunk = bytes(p ^ c for p, c in zip(padded[i:i + _BLOCK], prev))
            block = aes256_encrypt_block(chunk, self._W)
            ct.extend(block)
            prev = block
        return bytes(ct)

    def decrypt_cbc(self, ciphertext: bytes, iv: bytes) -> bytes:
        if len(iv) != _BLOCK:
            raise ValueError("IV must be 16 bytes")
        if len(ciphertext) % _BLOCK != 0:
            raise ValueError("Ciphertext length must be a multiple of 16")
        pt = bytearray()
        prev = iv
        for i in range(0, len(ciphertext), _BLOCK):
            block = ciphertext[i:i + _BLOCK]
            dec = aes256_decrypt_block(block, self._W)
            pt.extend(p ^ c for p, c in zip(dec, prev))
            prev = block
        return pkcs7_unpad(bytes(pt))

    # CTR
    def _ctr_keystream(self, nonce: bytes, counter: int, length: int) -> bytes:
        """Generate `length` bytes of CTR keystream."""
        if len(nonce) != 8:
            raise ValueError("CTR nonce must be 8 bytes")
        ks = bytearray()
        while len(ks) < length:
            # Counter block: nonce (8 bytes) || counter (8 bytes big-endian)
            cb = nonce + struct.pack(">Q", counter)
            ks.extend(aes256_encrypt_block(cb, self._W))
            counter = (counter + 1) & 0xFFFFFFFFFFFFFFFF
        return bytes(ks[:length])

    def encrypt_ctr(self, plaintext: bytes, nonce: bytes, counter: int = 0) -> bytes:
        ks = self._ctr_keystream(nonce, counter, len(plaintext))
        return bytes(p ^ k for p, k in zip(plaintext, ks))

    def decrypt_ctr(self, ciphertext: bytes, nonce: bytes, counter: int = 0) -> bytes:
        # CTR encryption = decryption
        return self.encrypt_ctr(ciphertext, nonce, counter)


# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------

def encrypt_file(in_path: str, out_path: str, key: bytes) -> bytes:
    """Encrypt a file with AES-256-CTR. Returns the 8-byte nonce prepended."""
    nonce = os.urandom(8)
    cipher = AES256(key)
    with open(in_path, "rb") as f:
        plaintext = f.read()
    ciphertext = cipher.encrypt_ctr(plaintext, nonce)
    with open(out_path, "wb") as f:
        f.write(nonce + ciphertext)
    return nonce


def decrypt_file(in_path: str, out_path: str, key: bytes) -> None:
    """Decrypt a file produced by encrypt_file."""
    with open(in_path, "rb") as f:
        data = f.read()
    if len(data) < 8:
        raise ValueError("File too short — missing nonce")
    nonce, ct = data[:8], data[8:]
    cipher = AES256(key)
    plaintext = cipher.decrypt_ctr(ct, nonce)
    with open(out_path, "wb") as f:
        f.write(plaintext)
