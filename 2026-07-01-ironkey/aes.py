"""
AES-128/192/256 block cipher implemented from the FIPS 197 specification.

Everything is derived, not hardcoded: the S-box is generated from the
GF(2^8) multiplicative-inverse + affine transform construction (section
5.1.1), MixColumns/InvMixColumns are real GF(2^8) matrix multiplications,
and the key schedule follows section 5.2. No `Crypto`/`cryptography`.
"""

_AES_MOD = 0x11B  # x^8 + x^4 + x^3 + x + 1, the AES reduction polynomial


def gf_mul(a, b):
    """Multiply two bytes as GF(2^8) polynomials, reduced mod the AES
    irreducible polynomial x^8+x^4+x^3+x+1."""
    p = 0
    a &= 0xFF
    b &= 0xFF
    for _ in range(8):
        if b & 1:
            p ^= a
        carry = a & 0x80
        a = (a << 1) & 0xFF
        if carry:
            a ^= 0x1B
        b >>= 1
    return p & 0xFF


def gf_pow(a, n):
    result = 1
    base = a
    while n:
        if n & 1:
            result = gf_mul(result, base)
        base = gf_mul(base, base)
        n >>= 1
    return result


def gf_inv(a):
    """Multiplicative inverse in GF(2^8): every nonzero element has
    order dividing 255, so a**254 == a**-1."""
    return 0 if a == 0 else gf_pow(a, 254)


def _rotl8(x, n):
    return ((x << n) | (x >> (8 - n))) & 0xFF


def _build_sbox():
    sbox = [0] * 256
    for a in range(256):
        inv = gf_inv(a)
        s = inv
        for shift in (1, 2, 3, 4):
            s ^= _rotl8(inv, shift)
        s ^= 0x63
        sbox[a] = s
    return sbox


SBOX = _build_sbox()
INV_SBOX = [0] * 256
for _i, _v in enumerate(SBOX):
    INV_SBOX[_v] = _i

assert SBOX[0x00] == 0x63 and SBOX[0x01] == 0x7C and SBOX[0x53] == 0xED, \
    "generated S-box disagrees with FIPS 197 Figure 7"

RCON = [0x00]  # RCON[0] unused; RCON[i] for i=1.. is x^(i-1) in GF(2^8)
_r = 1
for _i in range(1, 15):
    RCON.append(_r)
    _r = gf_mul(_r, 0x02)


def _sub_word(w):
    return bytes(SBOX[b] for b in w)


def _rot_word(w):
    return w[1:] + w[:1]


def key_expansion(key):
    """FIPS 197 section 5.2. Returns Nb*(Nr+1) 4-byte words."""
    if len(key) not in (16, 24, 32):
        raise ValueError("AES key must be 16, 24, or 32 bytes")
    nk = len(key) // 4
    nr = nk + 6
    nb = 4
    total_words = nb * (nr + 1)

    w = [key[4 * i:4 * i + 4] for i in range(nk)]
    for i in range(nk, total_words):
        temp = w[i - 1]
        if i % nk == 0:
            temp = _sub_word(_rot_word(temp))
            temp = bytes([temp[0] ^ RCON[i // nk]]) + temp[1:]
        elif nk > 6 and i % nk == 4:
            temp = _sub_word(temp)
        w.append(bytes(a ^ b for a, b in zip(w[i - nk], temp)))
    return w, nr


def _add_round_key(state, round_words):
    round_key = b"".join(round_words)
    return bytes(s ^ k for s, k in zip(state, round_key))


def _sub_bytes(state):
    return bytes(SBOX[b] for b in state)


def _inv_sub_bytes(state):
    return bytes(INV_SBOX[b] for b in state)


def _shift_rows(state):
    # state[r + 4c] is row r, column c; row r is shifted left by r.
    out = bytearray(16)
    for r in range(4):
        for c in range(4):
            out[r + 4 * c] = state[r + 4 * ((c + r) % 4)]
    return bytes(out)


def _inv_shift_rows(state):
    out = bytearray(16)
    for r in range(4):
        for c in range(4):
            out[r + 4 * ((c + r) % 4)] = state[r + 4 * c]
    return bytes(out)


def _mix_single_column(col):
    a0, a1, a2, a3 = col
    return bytes([
        gf_mul(a0, 2) ^ gf_mul(a1, 3) ^ a2 ^ a3,
        a0 ^ gf_mul(a1, 2) ^ gf_mul(a2, 3) ^ a3,
        a0 ^ a1 ^ gf_mul(a2, 2) ^ gf_mul(a3, 3),
        gf_mul(a0, 3) ^ a1 ^ a2 ^ gf_mul(a3, 2),
    ])


def _inv_mix_single_column(col):
    a0, a1, a2, a3 = col
    return bytes([
        gf_mul(a0, 14) ^ gf_mul(a1, 11) ^ gf_mul(a2, 13) ^ gf_mul(a3, 9),
        gf_mul(a0, 9) ^ gf_mul(a1, 14) ^ gf_mul(a2, 11) ^ gf_mul(a3, 13),
        gf_mul(a0, 13) ^ gf_mul(a1, 9) ^ gf_mul(a2, 14) ^ gf_mul(a3, 11),
        gf_mul(a0, 11) ^ gf_mul(a1, 13) ^ gf_mul(a2, 9) ^ gf_mul(a3, 14),
    ])


def _mix_columns(state):
    out = bytearray(16)
    for c in range(4):
        out[4 * c:4 * c + 4] = _mix_single_column(state[4 * c:4 * c + 4])
    return bytes(out)


def _inv_mix_columns(state):
    out = bytearray(16)
    for c in range(4):
        out[4 * c:4 * c + 4] = _inv_mix_single_column(state[4 * c:4 * c + 4])
    return bytes(out)


def encrypt_block(plaintext, key):
    if len(plaintext) != 16:
        raise ValueError("AES block must be exactly 16 bytes")
    w, nr = key_expansion(key)
    nb = 4
    state = plaintext
    state = _add_round_key(state, w[0:nb])
    for rnd in range(1, nr):
        state = _sub_bytes(state)
        state = _shift_rows(state)
        state = _mix_columns(state)
        state = _add_round_key(state, w[rnd * nb:(rnd + 1) * nb])
    state = _sub_bytes(state)
    state = _shift_rows(state)
    state = _add_round_key(state, w[nr * nb:(nr + 1) * nb])
    return state


def decrypt_block(ciphertext, key):
    if len(ciphertext) != 16:
        raise ValueError("AES block must be exactly 16 bytes")
    w, nr = key_expansion(key)
    nb = 4
    state = ciphertext
    state = _add_round_key(state, w[nr * nb:(nr + 1) * nb])
    for rnd in range(nr - 1, 0, -1):
        state = _inv_shift_rows(state)
        state = _inv_sub_bytes(state)
        state = _add_round_key(state, w[rnd * nb:(rnd + 1) * nb])
        state = _inv_mix_columns(state)
    state = _inv_shift_rows(state)
    state = _inv_sub_bytes(state)
    state = _add_round_key(state, w[0:nb])
    return state


class AES:
    """A keyed AES instance exposing raw single-block ECB-style
    encrypt/decrypt. Real usage should go through `modes.py` (CBC/GCM) —
    a bare block cipher is not a secure way to encrypt >16 bytes."""

    def __init__(self, key):
        if len(key) not in (16, 24, 32):
            raise ValueError("AES key must be 16, 24, or 32 bytes")
        self.key = key

    def encrypt_block(self, block):
        return encrypt_block(block, self.key)

    def decrypt_block(self, block):
        return decrypt_block(block, self.key)
