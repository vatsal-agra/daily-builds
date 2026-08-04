"""secp256k1 elliptic-curve arithmetic, ECDSA, and Bedrock address derivation
— every operation hand-implemented from the field/group axioms up. Nothing
here calls into `hashlib.sha256` beyond it being the hash function used as a
building block; the curve math, modular inverse, ECDSA sign/verify, base58
encoding, and address scheme are all written from scratch.

Only stdlib `secrets` is used, and only to draw a nonce/private key from the
OS CSPRNG — random bytes, not the algorithm itself.
"""

import hashlib
import secrets

# --- secp256k1 domain parameters (the curve Bitcoin uses; a well-known,
# publicly specified set of constants, not something to "derive") ---
P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
A = 0
B = 7
GX = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
GY = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8
N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
G = (GX, GY)


class CurveError(ValueError):
    pass


def sha256d(data: bytes) -> bytes:
    """Double SHA-256, the same hash used throughout Bedrock's block/tx layer."""
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


# ---------------------------------------------------------------------------
# Field arithmetic
# ---------------------------------------------------------------------------

def inv_mod(x: int, m: int) -> int:
    """Modular inverse via Fermat's little theorem (m must be prime)."""
    x %= m
    if x == 0:
        raise CurveError("cannot invert zero")
    return pow(x, m - 2, m)


# ---------------------------------------------------------------------------
# Elliptic curve point arithmetic (affine coordinates). Point at infinity is
# represented as None.
# ---------------------------------------------------------------------------

def is_on_curve(point):
    if point is None:
        return True
    x, y = point
    return (y * y - (x * x * x + A * x + B)) % P == 0


def point_add(p1, p2):
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2 and (y1 + y2) % P == 0:
        return None  # P + (-P) = infinity
    if x1 == x2 and y1 == y2:
        m = (3 * x1 * x1 + A) * inv_mod(2 * y1, P) % P
    else:
        m = (y2 - y1) * inv_mod((x2 - x1) % P, P) % P
    x3 = (m * m - x1 - x2) % P
    y3 = (m * (x1 - x3) - y1) % P
    return (x3, y3)


def scalar_mult(k: int, point):
    """Double-and-add scalar multiplication: k * point."""
    if k % N == 0 or point is None:
        return None
    if k < 0:
        return scalar_mult(-k, point_neg(point))
    result = None
    addend = point
    while k:
        if k & 1:
            result = point_add(result, addend)
        addend = point_add(addend, addend)
        k >>= 1
    return result


def point_neg(point):
    if point is None:
        return None
    x, y = point
    return (x, (-y) % P)


# ---------------------------------------------------------------------------
# Keys
# ---------------------------------------------------------------------------

def generate_private_key() -> int:
    """A uniformly random integer in [1, N-1] drawn from the OS CSPRNG."""
    while True:
        candidate = secrets.randbelow(N - 1) + 1
        if 0 < candidate < N:
            return candidate


def derive_public_key(private_key: int):
    if not (0 < private_key < N):
        raise CurveError("private key out of range")
    return scalar_mult(private_key, G)


def compress_pubkey(pubkey) -> bytes:
    x, y = pubkey
    prefix = b"\x02" if y % 2 == 0 else b"\x03"
    return prefix + x.to_bytes(32, "big")


def decompress_pubkey(data: bytes):
    if len(data) != 33 or data[0] not in (2, 3):
        raise CurveError("bad compressed pubkey encoding")
    x = int.from_bytes(data[1:], "big")
    y_sq = (x * x * x + A * x + B) % P
    y = pow(y_sq, (P + 1) // 4, P)  # P % 4 == 3, so this is a valid sqrt formula
    if (y * y) % P != y_sq:
        raise CurveError("point is not on the curve")
    if (y % 2 == 0) != (data[0] == 2):
        y = P - y
    point = (x, y)
    if not is_on_curve(point):
        raise CurveError("decompressed point is not on the curve")
    return point


# ---------------------------------------------------------------------------
# ECDSA
# ---------------------------------------------------------------------------

def _hash_to_int(message: bytes) -> int:
    return int.from_bytes(hashlib.sha256(message).digest(), "big") % N


def sign(private_key: int, message: bytes) -> tuple:
    """Returns (r, s). Retries with a fresh nonce on the (astronomically
    unlikely) r == 0 or s == 0 case, exactly as the algorithm requires."""
    e = _hash_to_int(message)
    while True:
        k = secrets.randbelow(N - 1) + 1
        point = scalar_mult(k, G)
        if point is None:
            continue
        r = point[0] % N
        if r == 0:
            continue
        s = (inv_mod(k, N) * (e + r * private_key)) % N
        if s == 0:
            continue
        # Canonical low-S form (as Bitcoin does) so a signature has one
        # unambiguous encoding, which matters once signatures are gossiped
        # across a P2P network and re-serialized by other nodes.
        if s > N // 2:
            s = N - s
        return (r, s)


def verify(pubkey, message: bytes, signature: tuple) -> bool:
    r, s = signature
    if not (0 < r < N and 0 < s < N):
        return False
    if s > N // 2:
        # Reject the non-canonical high-S form. Both s and N-s satisfy the
        # verification equation for the same (r, message, pubkey) — without
        # this check, anyone who observes a valid signature could flip it to
        # a second, still-valid encoding with a different byte representation
        # (and thus a different txid), a classic transaction-malleability bug.
        # sign() only ever produces the canonical low-S form, so this never
        # rejects an honestly-produced signature.
        return False
    if pubkey is None or not is_on_curve(pubkey):
        return False
    e = _hash_to_int(message)
    w = inv_mod(s, N)
    u1 = (e * w) % N
    u2 = (r * w) % N
    point = point_add(scalar_mult(u1, G), scalar_mult(u2, pubkey))
    if point is None:
        return False
    return (point[0] % N) == r


def encode_signature(signature: tuple) -> bytes:
    r, s = signature
    return r.to_bytes(32, "big") + s.to_bytes(32, "big")


def decode_signature(data: bytes) -> tuple:
    if len(data) != 64:
        raise CurveError("bad signature encoding")
    return (int.from_bytes(data[:32], "big"), int.from_bytes(data[32:], "big"))


# ---------------------------------------------------------------------------
# Base58check (Bitcoin's alphabet — avoids the visually-ambiguous 0/O/I/l)
# ---------------------------------------------------------------------------

_B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def base58_encode(data: bytes) -> str:
    n = int.from_bytes(data, "big")
    out = []
    while n > 0:
        n, rem = divmod(n, 58)
        out.append(_B58_ALPHABET[rem])
    leading_zeros = len(data) - len(data.lstrip(b"\x00"))
    return (_B58_ALPHABET[0] * leading_zeros) + "".join(reversed(out))


def base58_decode(s: str) -> bytes:
    n = 0
    for ch in s:
        if ch not in _B58_ALPHABET:
            raise ValueError(f"invalid base58 character: {ch!r}")
        n = n * 58 + _B58_ALPHABET.index(ch)
    body = n.to_bytes((n.bit_length() + 7) // 8, "big") if n > 0 else b""
    leading_zeros = len(s) - len(s.lstrip(_B58_ALPHABET[0]))
    return b"\x00" * leading_zeros + body


# ---------------------------------------------------------------------------
# Bedrock addresses: version byte || sha256d(compressed pubkey)[:20] || 4-byte
# checksum, base58-encoded. Deliberately not Bitcoin-wire-compatible (no
# RIPEMD-160 dependency — this OS's OpenSSL disables legacy hashes), but the
# same "hash-then-checksum-then-base58" shape.
# ---------------------------------------------------------------------------

ADDRESS_VERSION = 0x1B  # arbitrary, gives Bedrock addresses a distinct prefix


def pubkey_to_address(pubkey) -> str:
    pubkey_bytes = compress_pubkey(pubkey)
    payload = sha256d(pubkey_bytes)[:20]
    versioned = bytes([ADDRESS_VERSION]) + payload
    checksum = sha256d(versioned)[:4]
    return base58_encode(versioned + checksum)


def is_valid_address(address: str) -> bool:
    try:
        raw = base58_decode(address)
    except ValueError:
        return False
    if len(raw) != 25:
        return False
    versioned, checksum = raw[:21], raw[21:]
    if versioned[0] != ADDRESS_VERSION:
        return False
    return sha256d(versioned)[:4] == checksum
