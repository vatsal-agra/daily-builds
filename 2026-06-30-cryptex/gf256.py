"""GF(2^8) arithmetic over the AES irreducible polynomial x^8+x^4+x^3+x+1 (0x11b).

All operations work on integers in [0, 255]. No tables are imported; the S-box
is constructed here by computing multiplicative inverses in the field.
"""

_POLY = 0x11B  # x^8 + x^4 + x^3 + x + 1


def add(a: int, b: int) -> int:
    """GF(2^8) addition is XOR."""
    return a ^ b


def mul(a: int, b: int) -> int:
    """GF(2^8) multiplication via Russian-peasant (shift-and-XOR) method."""
    result = 0
    a &= 0xFF
    b &= 0xFF
    while b:
        if b & 1:
            result ^= a
        b >>= 1
        a <<= 1
        if a & 0x100:
            a ^= _POLY
    return result & 0xFF


def pow2(n: int) -> int:
    """Compute 2^n in GF(2^8) (generator g=2 repeated multiplication)."""
    result = 1
    for _ in range(n):
        result = mul(result, 2)
    return result


def inv(a: int) -> int:
    """Multiplicative inverse in GF(2^8); inv(0) = 0 by convention."""
    if a == 0:
        return 0
    # a^254 = a^(-1) in GF(2^8) since the group order is 255.
    result = 1
    base = a
    exp = 254
    while exp:
        if exp & 1:
            result = mul(result, base)
        base = mul(base, base)
        exp >>= 1
    return result


# ---------------------------------------------------------------------------
# AES S-box: S(a) = affine_transform(inv(a))
# The affine transform is a GF(2) linear map + addition of 0x63.
# ---------------------------------------------------------------------------

def _affine(b: int) -> int:
    """Apply the AES affine transform to byte b."""
    x = b
    # Multiply by the circulant matrix [1,1,1,1,1,0,0,0] in GF(2)
    # which is equivalent to: x XOR rol(x,1) XOR rol(x,2) XOR rol(x,3) XOR rol(x,4)
    # then add 0x63 (constant in GF(2)).
    def rol(v: int, n: int) -> int:
        return ((v << n) | (v >> (8 - n))) & 0xFF
    return x ^ rol(x, 1) ^ rol(x, 2) ^ rol(x, 3) ^ rol(x, 4) ^ 0x63


# Build the forward and inverse S-box at import time.
SBOX: list[int] = [_affine(inv(i)) for i in range(256)]

# Inverse S-box: undoes affine then takes inv (same as undoing the affine).
# inv_aff(b) = rol(b,1) XOR rol(b,3) XOR rol(b,6) XOR 0x05
def _inv_affine(b: int) -> int:
    def rol(v: int, n: int) -> int:
        return ((v << n) | (v >> (8 - n))) & 0xFF
    return rol(b, 1) ^ rol(b, 3) ^ rol(b, 6) ^ 0x05

INV_SBOX: list[int] = [inv(_inv_affine(i)) for i in range(256)]

# Rcon: round constants used in the AES key schedule.
# Rcon[i] = (2^i, 0, 0, 0) in GF(2^8).
RCON: list[int] = [pow2(i) for i in range(11)]
