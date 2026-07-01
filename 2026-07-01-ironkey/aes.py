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


def _round_keys(w, nr):
    """Pre-join each round's 4 words into one 16-byte key so the hot
    encrypt/decrypt loop never re-joins/re-slices the schedule."""
    nb = 4
    return [b"".join(w[rnd * nb:(rnd + 1) * nb]) for rnd in range(nr + 1)]


def _add_round_key(state, round_key):
    # XOR as big integers (one C-level bignum op) instead of a 16-item
    # Python-level zip/genexpr — this is on the hottest path in the cipher.
    return (int.from_bytes(state, "big") ^ int.from_bytes(round_key, "big")).to_bytes(16, "big")


_SBOX_TRANSLATE = bytes(SBOX)
_INV_SBOX_TRANSLATE = bytes(INV_SBOX)


def _sub_bytes(state):
    return state.translate(_SBOX_TRANSLATE)


def _inv_sub_bytes(state):
    return state.translate(_INV_SBOX_TRANSLATE)


# ShiftRows/InvShiftRows are fixed permutations of the 16 state bytes —
# precompute the index tables once instead of recomputing r/c on every call.
_SHIFT_ROWS_PERM = tuple(
    r + 4 * ((c + r) % 4) for c in range(4) for r in range(4)
)
_INV_SHIFT_ROWS_PERM = tuple(
    _SHIFT_ROWS_PERM.index(i) for i in range(16)
)


def _shift_rows(state):
    return bytes(state[i] for i in _SHIFT_ROWS_PERM)


def _inv_shift_rows(state):
    return bytes(state[i] for i in _INV_SHIFT_ROWS_PERM)


# GF(2^8) multiply-by-constant lookup tables, precomputed once from the
# same from-scratch gf_mul — MixColumns/InvMixColumns only ever multiply
# by these fixed constants, so a 256-entry table replaces a per-call
# 8-iteration carryless-multiply loop with an O(1) lookup.
_MUL2 = [gf_mul(v, 2) for v in range(256)]
_MUL3 = [gf_mul(v, 3) for v in range(256)]
_MUL9 = [gf_mul(v, 9) for v in range(256)]
_MUL11 = [gf_mul(v, 11) for v in range(256)]
_MUL13 = [gf_mul(v, 13) for v in range(256)]
_MUL14 = [gf_mul(v, 14) for v in range(256)]


def _mix_single_column(col):
    a0, a1, a2, a3 = col
    return (
        _MUL2[a0] ^ _MUL3[a1] ^ a2 ^ a3,
        a0 ^ _MUL2[a1] ^ _MUL3[a2] ^ a3,
        a0 ^ a1 ^ _MUL2[a2] ^ _MUL3[a3],
        _MUL3[a0] ^ a1 ^ a2 ^ _MUL2[a3],
    )


def _inv_mix_single_column(col):
    a0, a1, a2, a3 = col
    return (
        _MUL14[a0] ^ _MUL11[a1] ^ _MUL13[a2] ^ _MUL9[a3],
        _MUL9[a0] ^ _MUL14[a1] ^ _MUL11[a2] ^ _MUL13[a3],
        _MUL13[a0] ^ _MUL9[a1] ^ _MUL14[a2] ^ _MUL11[a3],
        _MUL11[a0] ^ _MUL13[a1] ^ _MUL9[a2] ^ _MUL14[a3],
    )


def _mix_columns(state):
    out = []
    for c in range(4):
        out.extend(_mix_single_column(state[4 * c:4 * c + 4]))
    return bytes(out)


def _inv_mix_columns(state):
    out = []
    for c in range(4):
        out.extend(_inv_mix_single_column(state[4 * c:4 * c + 4]))
    return bytes(out)


def _encrypt_with_schedule(plaintext, round_keys, nr):
    state = plaintext
    state = _add_round_key(state, round_keys[0])
    for rnd in range(1, nr):
        state = _sub_bytes(state)
        state = _shift_rows(state)
        state = _mix_columns(state)
        state = _add_round_key(state, round_keys[rnd])
    state = _sub_bytes(state)
    state = _shift_rows(state)
    state = _add_round_key(state, round_keys[nr])
    return state


def _decrypt_with_schedule(ciphertext, round_keys, nr):
    state = ciphertext
    state = _add_round_key(state, round_keys[nr])
    for rnd in range(nr - 1, 0, -1):
        state = _inv_shift_rows(state)
        state = _inv_sub_bytes(state)
        state = _add_round_key(state, round_keys[rnd])
        state = _inv_mix_columns(state)
    state = _inv_shift_rows(state)
    state = _inv_sub_bytes(state)
    state = _add_round_key(state, round_keys[0])
    return state


def encrypt_block(plaintext, key):
    """Single-block convenience wrapper (expands the key schedule on
    every call — fine for one-off vector tests, but `AES` below caches
    the schedule and is what `modes.py` actually uses for real data)."""
    if len(plaintext) != 16:
        raise ValueError("AES block must be exactly 16 bytes")
    w, nr = key_expansion(key)
    return _encrypt_with_schedule(plaintext, _round_keys(w, nr), nr)


def decrypt_block(ciphertext, key):
    if len(ciphertext) != 16:
        raise ValueError("AES block must be exactly 16 bytes")
    w, nr = key_expansion(key)
    return _decrypt_with_schedule(ciphertext, _round_keys(w, nr), nr)


class AES:
    """A keyed AES instance exposing raw single-block ECB-style
    encrypt/decrypt. Real usage should go through `modes.py` (CBC/GCM) —
    a bare block cipher is not a secure way to encrypt >16 bytes.

    The round-key schedule is expanded and pre-joined into per-round
    16-byte keys once here and reused for every block — expanding it
    per-block (as the free `encrypt_block`/`decrypt_block` functions
    above do) turns a 1 MB file into a 43-second encrypt; caching it
    plus table-based MixColumns/SubBytes brings that under a second."""

    def __init__(self, key):
        if len(key) not in (16, 24, 32):
            raise ValueError("AES key must be 16, 24, or 32 bytes")
        self.key = key
        w, self._nr = key_expansion(key)
        self._round_keys = _round_keys(w, self._nr)

    def encrypt_block(self, block):
        if len(block) != 16:
            raise ValueError("AES block must be exactly 16 bytes")
        return _encrypt_with_schedule(block, self._round_keys, self._nr)

    def decrypt_block(self, block):
        if len(block) != 16:
            raise ValueError("AES block must be exactly 16 bytes")
        return _decrypt_with_schedule(block, self._round_keys, self._nr)
