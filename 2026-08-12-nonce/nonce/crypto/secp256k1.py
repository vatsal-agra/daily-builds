"""secp256k1 elliptic-curve arithmetic and ECDSA, implemented from scratch.

This is the exact curve Bitcoin and Ethereum use: y^2 = x^3 + 7 over the
prime field F_p. Point arithmetic is plain affine add/double (no fancy
Jacobian-coordinate speedups — clarity over speed, this is a teaching-grade
implementation) plus double-and-add scalar multiplication.

Signing uses RFC 6979 deterministic-k generation (built on this package's
own hmac_sha256) so the same (privkey, message) pair always produces the
same signature — no reliance on a fresh random nonce every time, which is
exactly the failure mode that leaked the Sony PS3 signing key and, more
than once, real Bitcoin wallets (reused/predictable k lets anyone solve for
the private key from two signatures).

Curve parameters and correctness are checked against the published SEC2
values and round-tripped through thousands of random sign/verify pairs in
tests/test_secp256k1.py.
"""

from .sha256 import hmac_sha256

# --- SEC2 secp256k1 domain parameters ---------------------------------
P = 0xFFFFFFFF_FFFFFFFF_FFFFFFFF_FFFFFFFF_FFFFFFFF_FFFFFFFF_FFFFFFFE_FFFFFC2F
A = 0
B = 7
GX = 0x79BE667E_F9DCBBAC_55A06295_CE870B07_029BFCDB_2DCE28D9_59F2815B_16F81798
GY = 0x483ADA77_26A3C465_5DA4FBFC_0E1108A8_FD17B448_A6855419_9C47D08F_FB10D4B8
N = 0xFFFFFFFF_FFFFFFFF_FFFFFFFF_FFFFFFFE_BAAEDCE6_AF48A03B_BFD25E8C_D0364141

G = (GX, GY)
INFINITY = None  # point at infinity, the additive identity


def _inv_mod(x, m):
    """Modular inverse via the extended Euclidean algorithm."""
    if x == 0:
        raise ZeroDivisionError("inverse of 0")
    old_r, r = x % m, m
    old_s, s = 1, 0
    while r != 0:
        q = old_r // r
        old_r, r = r, old_r - q * r
        old_s, s = s, old_s - q * s
    if old_r != 1:
        raise ZeroDivisionError(f"{x} has no inverse mod {m}")
    return old_s % m


def point_add(p1, p2):
    if p1 is INFINITY:
        return p2
    if p2 is INFINITY:
        return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2 and (y1 + y2) % P == 0:
        return INFINITY
    if p1 == p2:
        if y1 == 0:
            return INFINITY
        lam = (3 * x1 * x1 + A) * _inv_mod(2 * y1, P) % P
    else:
        lam = (y2 - y1) * _inv_mod((x2 - x1) % P, P) % P
    x3 = (lam * lam - x1 - x2) % P
    y3 = (lam * (x1 - x3) - y1) % P
    return (x3, y3)


def scalar_mult(k, point):
    """k * point via double-and-add. k is reduced mod N first."""
    k = k % N
    result = INFINITY
    addend = point
    while k:
        if k & 1:
            result = point_add(result, addend)
        addend = point_add(addend, addend)
        k >>= 1
    return result


def is_on_curve(point):
    if point is INFINITY:
        return True
    x, y = point
    return (y * y - (x * x * x + A * x + B)) % P == 0


def privkey_to_pubkey(privkey: int):
    if not (1 <= privkey < N):
        raise ValueError("private key out of range [1, N-1]")
    return scalar_mult(privkey, G)


def pubkey_to_bytes(point, compressed=True) -> bytes:
    x, y = point
    if compressed:
        prefix = b"\x02" if y % 2 == 0 else b"\x03"
        return prefix + x.to_bytes(32, "big")
    return b"\x04" + x.to_bytes(32, "big") + y.to_bytes(32, "big")


def bytes_to_pubkey(data: bytes):
    if data[0] == 0x04:
        x = int.from_bytes(data[1:33], "big")
        y = int.from_bytes(data[33:65], "big")
        point = (x, y)
    elif data[0] in (0x02, 0x03):
        x = int.from_bytes(data[1:33], "big")
        if x >= P:
            # x must be canonically reduced mod P. Without this check, x
            # and x-P behave identically in every downstream curve
            # computation (everything is mod P anyway) — not a security
            # hole — but it lets a single point be encoded two different
            # ways, which a correct decoder should reject as malformed.
            raise ValueError("x-coordinate is not a valid field element (>= P)")
        y_sq = (x * x * x + A * x + B) % P
        y = pow(y_sq, (P + 1) // 4, P)  # P % 4 == 3, so this recovers a sqrt
        if (y % 2 == 0) != (data[0] == 0x02):
            y = P - y
        point = (x, y)
    else:
        raise ValueError("unrecognized pubkey encoding")
    if not is_on_curve(point):
        raise ValueError("decoded point is not on secp256k1")
    return point


# --- RFC 6979 deterministic nonce generation ---------------------------

def _int_to_bytes32(x: int) -> bytes:
    return x.to_bytes(32, "big")


def _bits_to_int(b: bytes) -> int:
    x = int.from_bytes(b, "big")
    excess = len(b) * 8 - N.bit_length()
    if excess > 0:
        x >>= excess
    return x


def _rfc6979_k(privkey: int, msg_hash: bytes):
    """Deterministic k per RFC 6979 §3.2, specialized to SHA-256 / secp256k1."""
    x = _int_to_bytes32(privkey)
    h1 = msg_hash
    v = b"\x01" * 32
    k = b"\x00" * 32
    k = hmac_sha256(k, v + b"\x00" + x + h1)
    v = hmac_sha256(k, v)
    k = hmac_sha256(k, v + b"\x01" + x + h1)
    v = hmac_sha256(k, v)
    while True:
        v = hmac_sha256(k, v)
        candidate = _bits_to_int(v)
        if 1 <= candidate < N:
            return candidate
        k = hmac_sha256(k, v + b"\x00")
        v = hmac_sha256(k, v)


def sign(privkey: int, msg_hash: bytes):
    """ECDSA sign a 32-byte message hash. Returns (r, s) with s
    low-normalized (s <= N/2) to avoid signature malleability, matching
    Bitcoin's BIP-62 convention."""
    if len(msg_hash) != 32:
        raise ValueError("msg_hash must be 32 bytes (already hashed)")
    z = int.from_bytes(msg_hash, "big")
    while True:
        k = _rfc6979_k(privkey, msg_hash)
        point = scalar_mult(k, G)
        if point is INFINITY:
            continue
        r = point[0] % N
        if r == 0:
            continue
        s = (_inv_mod(k, N) * (z + r * privkey)) % N
        if s == 0:
            continue
        if s > N // 2:
            s = N - s
        return (r, s)


def verify(pubkey, msg_hash: bytes, signature) -> bool:
    r, s = signature
    if not (1 <= r < N and 1 <= s < N):
        return False
    if s > N // 2:
        # ECDSA is symmetric in s (both s and N-s validate for the same r,
        # z, pubkey), so accepting high-s signatures lets a third party
        # take any valid signature and flip it to a different, still-valid
        # encoding — changing the transaction's id without invalidating
        # any signature ("transaction malleability", the exact class of
        # bug that motivated Bitcoin's BIP-62). sign() only ever produces
        # low-s, so rejecting high-s here makes low-s the one canonical
        # encoding a valid signature can have.
        return False
    if not is_on_curve(pubkey):
        return False
    z = int.from_bytes(msg_hash, "big")
    w = _inv_mod(s, N)
    u1 = (z * w) % N
    u2 = (r * w) % N
    point = point_add(scalar_mult(u1, G), scalar_mult(u2, pubkey))
    if point is INFINITY:
        return False
    return point[0] % N == r
