"""secp256k1 elliptic-curve arithmetic and ECDSA, built from scratch.

No `cryptography` / `ecdsa` / `secp256k1` package and no OpenSSL EC
bindings are used anywhere in this module — only Python's arbitrary
precision integers and `hashlib.sha256` for hashing. The curve is
y^2 = x^3 + 7 over F_p, the exact curve Bitcoin and Ethereum use.
"""

import hashlib
import secrets

# --- secp256k1 domain parameters -------------------------------------------

P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
A = 0
B = 7
GX = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
GY = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8
N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141

INFINITY = None  # point at infinity, the group identity


def _mod_inv(a, m):
    """Modular inverse via Fermat's little theorem (m is prime)."""
    return pow(a % m, m - 2, m)


def is_on_curve(point):
    if point is INFINITY:
        return True
    x, y = point
    return (y * y - (x * x * x + A * x + B)) % P == 0


def point_add(p1, p2):
    if p1 is INFINITY:
        return p2
    if p2 is INFINITY:
        return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2 and (y1 + y2) % P == 0:
        return INFINITY
    if x1 == x2 and y1 == y2:
        # point doubling
        s = (3 * x1 * x1 + A) * _mod_inv(2 * y1, P) % P
    else:
        s = (y2 - y1) * _mod_inv((x2 - x1) % P, P) % P
    x3 = (s * s - x1 - x2) % P
    y3 = (s * (x1 - x3) - y1) % P
    return (x3, y3)


def scalar_mult(k, point):
    """Double-and-add scalar multiplication, k * point."""
    k = k % N
    result = INFINITY
    addend = point
    while k:
        if k & 1:
            result = point_add(result, addend)
        addend = point_add(addend, addend)
        k >>= 1
    return result


G = (GX, GY)
assert is_on_curve(G), "generator must be on the curve"


# --- keys and serialization -------------------------------------------------

def generate_private_key():
    """A cryptographically random integer in [1, N-1]."""
    while True:
        d = secrets.randbelow(N - 1) + 1
        if 1 <= d < N:
            return d


def private_to_public(d):
    return scalar_mult(d, G)


def compress_pubkey(point):
    x, y = point
    prefix = 0x02 if y % 2 == 0 else 0x03
    return bytes([prefix]) + x.to_bytes(32, "big")


def decompress_pubkey(data):
    if len(data) != 33 or data[0] not in (0x02, 0x03):
        raise ValueError("invalid compressed pubkey encoding")
    x = int.from_bytes(data[1:], "big")
    if x >= P:
        raise ValueError("x-coordinate is not a valid field element (>= P)")
    y_sq = (x * x * x + A * x + B) % P
    y = pow(y_sq, (P + 1) // 4, P)  # valid sqrt exponent since P % 4 == 3
    if (y * y) % P != y_sq:
        raise ValueError("point is not on the curve")
    if (y % 2 == 0) != (data[0] == 0x02):
        y = P - y
    point = (x, y)
    if not is_on_curve(point):
        raise ValueError("decompressed point is not on the curve")
    return point


# --- base58check -------------------------------------------------------------

_B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def base58_encode(data):
    n = int.from_bytes(data, "big")
    out = ""
    while n > 0:
        n, rem = divmod(n, 58)
        out = _B58_ALPHABET[rem] + out
    n_leading_zero_bytes = len(data) - len(data.lstrip(b"\x00"))
    return "1" * n_leading_zero_bytes + out


def base58_decode(s):
    n = 0
    for ch in s:
        n = n * 58 + _B58_ALPHABET.index(ch)
    n_leading_ones = len(s) - len(s.lstrip("1"))
    body = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    return b"\x00" * n_leading_ones + body


def base58check_encode(version: bytes, payload: bytes):
    data = version + payload
    checksum = hashlib.sha256(hashlib.sha256(data).digest()).digest()[:4]
    return base58_encode(data + checksum)


def base58check_decode(s):
    raw = base58_decode(s)
    if len(raw) < 5:
        raise ValueError("base58check string too short")
    data, checksum = raw[:-4], raw[-4:]
    expected = hashlib.sha256(hashlib.sha256(data).digest()).digest()[:4]
    if checksum != expected:
        raise ValueError("base58check checksum mismatch")
    return data[:1], data[1:]


ADDRESS_VERSION = b"\x1c"  # arbitrary single-byte version for Concord addresses


def pubkey_to_address(point):
    """base58check(SHA256(SHA256(compressed pubkey)))[:20].

    Real Bitcoin uses RIPEMD160(SHA256(pubkey)); Python's hashlib does not
    guarantee RIPEMD-160 is available (OpenSSL 3.x disables legacy digests
    on many distros), so this uses a second SHA-256 round instead. Same
    base58check envelope, same from-scratch encoder, documented simplification.
    """
    pub_hash = hashlib.sha256(hashlib.sha256(compress_pubkey(point)).digest()).digest()[:20]
    return base58check_encode(ADDRESS_VERSION, pub_hash)


def is_valid_address(address):
    try:
        version, payload = base58check_decode(address)
    except (ValueError, IndexError):
        return False
    return version == ADDRESS_VERSION and len(payload) == 20


# --- ECDSA -------------------------------------------------------------------

def _hash_to_int(message: bytes):
    h = hashlib.sha256(message).digest()
    return int.from_bytes(h, "big") % N


def sign(private_key: int, message: bytes):
    z = _hash_to_int(message)
    while True:
        k = secrets.randbelow(N - 1) + 1
        r, _ = scalar_mult(k, G)
        r %= N
        if r == 0:
            continue
        s = (_mod_inv(k, N) * (z + r * private_key)) % N
        if s == 0:
            continue
        # canonical low-s form, standard malleability guard
        if s > N // 2:
            s = N - s
        return (r, s)


def verify(public_key_point, message: bytes, signature):
    r, s = signature
    if not (1 <= r < N and 1 <= s < N):
        return False
    if s > N // 2:
        # reject non-canonical high-s signatures. ECDSA's verification
        # equation is symmetric under s -> N-s: anyone (not just the
        # holder of the private key) can flip a valid low-s signature into
        # an equally-valid high-s one for the exact same message, without
        # ever touching the private key. Since a transaction's txid hashes
        # its own signature bytes, that flip mints a second, different
        # txid for what is semantically the identical, already-signed
        # transaction — classic ECDSA signature malleability. sign() above
        # only ever emits low-s, so this rejects nothing legitimate; it
        # only closes the malleability path for anyone verifying elsewhere.
        return False
    z = _hash_to_int(message)
    w = _mod_inv(s, N)
    u1 = (z * w) % N
    u2 = (r * w) % N
    point = point_add(scalar_mult(u1, G), scalar_mult(u2, public_key_point))
    if point is INFINITY:
        return False
    x, _ = point
    return (x % N) == r


def sig_to_bytes(sig):
    r, s = sig
    return r.to_bytes(32, "big") + s.to_bytes(32, "big")


def sig_from_bytes(data):
    if len(data) != 64:
        raise ValueError("invalid signature length")
    return (int.from_bytes(data[:32], "big"), int.from_bytes(data[32:], "big"))
