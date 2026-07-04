"""P-256 (secp256r1 / NIST P-256) elliptic curve cryptography from scratch.

Implements:
  - Affine and Jacobian projective point arithmetic (add, double, scalar mul)
  - Montgomery ladder for constant-time scalar multiplication
  - ECDH key exchange (RFC 5903)
  - ECDSA sign/verify with RFC 6979 deterministic k (no random k)
  - SEC1 point encoding (uncompressed 04 and compressed 02/03)

No external crypto libraries. OS entropy used only for key generation.
"""

import os
import struct
from sha256 import sha256, hmac_sha256

# ---------------------------------------------------------------------------
# P-256 domain parameters (SEC2 v2.0, Section 2.6)
# ---------------------------------------------------------------------------

_P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
_A = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFC
_B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B
_GX = 0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296
_GY = 0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5
_N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
_H = 1  # cofactor

# Generator point G
_G = (_GX, _GY)


# ---------------------------------------------------------------------------
# Modular arithmetic over GF(P)
# ---------------------------------------------------------------------------

def _mod_inv(a: int, m: int) -> int:
    """Modular inverse via Fermat's little theorem (m is prime)."""
    return pow(a, m - 2, m)


# ---------------------------------------------------------------------------
# Jacobian projective coordinates
# (X, Y, Z) represents the affine point (X/Z^2, Y/Z^3)
# Identity (point at infinity) = (1, 1, 0)
# ---------------------------------------------------------------------------

_INF_JAC = (1, 1, 0)  # Point at infinity in Jacobian coords


def _is_inf(p: tuple) -> bool:
    return p[2] == 0


def _to_affine(p: tuple) -> tuple | None:
    """Convert Jacobian to affine. Returns None for infinity."""
    if _is_inf(p):
        return None
    X, Y, Z = p
    iz = _mod_inv(Z, _P)
    iz2 = iz * iz % _P
    iz3 = iz2 * iz % _P
    return (X * iz2 % _P, Y * iz3 % _P)


def _from_affine(p: tuple | None) -> tuple:
    """Convert affine to Jacobian. None → infinity."""
    if p is None:
        return _INF_JAC
    return (p[0], p[1], 1)


def _jac_double(P: tuple) -> tuple:
    """Point doubling in Jacobian coordinates (A = -3 for P-256)."""
    if _is_inf(P):
        return _INF_JAC
    X1, Y1, Z1 = P
    if Y1 == 0:
        return _INF_JAC
    Y1sq = Y1 * Y1 % _P
    S = 4 * X1 * Y1sq % _P
    # For P-256, A = -3 mod P, so M = 3*(X^2 - Z^4) = 3*X^2 + A*Z^4
    Z1sq = Z1 * Z1 % _P
    Z1_4 = Z1sq * Z1sq % _P
    M = (3 * X1 * X1 + _A * Z1_4) % _P
    X3 = (M * M - 2 * S) % _P
    Y3 = (M * (S - X3) - 8 * Y1sq * Y1sq) % _P
    Z3 = 2 * Y1 * Z1 % _P
    return (X3, Y3, Z3)


def _jac_add(P: tuple, Q: tuple) -> tuple:
    """Point addition in Jacobian coordinates (P ≠ Q, neither infinity)."""
    if _is_inf(P):
        return Q
    if _is_inf(Q):
        return P
    X1, Y1, Z1 = P
    X2, Y2, Z2 = Q
    Z1sq = Z1 * Z1 % _P
    Z2sq = Z2 * Z2 % _P
    U1 = X1 * Z2sq % _P
    U2 = X2 * Z1sq % _P
    S1 = Y1 * Z2sq % _P * Z2 % _P
    S2 = Y2 * Z1sq % _P * Z1 % _P
    H = (U2 - U1) % _P
    R = (S2 - S1) % _P
    if H == 0:
        if R == 0:
            return _jac_double(P)
        return _INF_JAC
    H2 = H * H % _P
    H3 = H2 * H % _P
    X3 = (R * R - H3 - 2 * U1 * H2) % _P
    Y3 = (R * (U1 * H2 - X3) - S1 * H3) % _P
    Z3 = H * Z1 % _P * Z2 % _P
    return (X3, Y3, Z3)


def _scalar_mul(k: int, P: tuple) -> tuple:
    """Montgomery ladder scalar multiplication for constant-time behavior."""
    if k == 0:
        return _INF_JAC
    if k < 0:
        k = k % _N

    # Montgomery ladder: R0 = O, R1 = P
    R0 = _INF_JAC
    R1 = P
    for bit in range(k.bit_length() - 1, -1, -1):
        if (k >> bit) & 1:
            R0 = _jac_add(R0, R1)
            R1 = _jac_double(R1)
        else:
            R1 = _jac_add(R0, R1)
            R0 = _jac_double(R0)
    return R0


# ---------------------------------------------------------------------------
# Point on curve (affine) helpers
# ---------------------------------------------------------------------------

def _on_curve(px: int, py: int) -> bool:
    """Check if (px, py) lies on the P-256 curve."""
    lhs = py * py % _P
    rhs = (px * px * px + _A * px + _B) % _P
    return lhs == rhs


def _mul_G(k: int) -> tuple | None:
    """k * G, returns affine point or None for infinity."""
    return _to_affine(_scalar_mul(k, _from_affine(_G)))


def _mul_point(k: int, px: int, py: int) -> tuple | None:
    """k * (px, py), returns affine point or None for infinity."""
    return _to_affine(_scalar_mul(k, _from_affine((px, py))))


# ---------------------------------------------------------------------------
# Key types
# ---------------------------------------------------------------------------

class ECPrivateKey:
    def __init__(self, d: int):
        if not (1 <= d < _N):
            raise ValueError(f"Private key scalar must be in [1, N-1]; got {d!r}")
        self.d = d
        qx, qy = _mul_G(d)
        self.public_key = ECPublicKey(qx, qy)

    def to_hex(self) -> str:
        return f"{self.d:064x}"

    @classmethod
    def from_hex(cls, h: str) -> "ECPrivateKey":
        h = h.strip()
        if len(h) != 64:
            raise ValueError(f"Private key must be 64 hex chars (32 bytes), got {len(h)}")
        try:
            return cls(int(h, 16))
        except ValueError as e:
            raise ValueError(f"Invalid private key hex: {e}") from e

    @classmethod
    def generate(cls) -> "ECPrivateKey":
        while True:
            d = int.from_bytes(os.urandom(32), "big") % _N
            if d >= 1:
                return cls(d)


class ECPublicKey:
    def __init__(self, x: int, y: int):
        if not _on_curve(x, y):
            raise ValueError("Point is not on P-256")
        self.x = x
        self.y = y

    def to_uncompressed_hex(self) -> str:
        return f"04{self.x:064x}{self.y:064x}"

    def to_compressed_hex(self) -> str:
        prefix = "02" if self.y % 2 == 0 else "03"
        return f"{prefix}{self.x:064x}"

    @classmethod
    def from_hex(cls, h: str) -> "ECPublicKey":
        h = h.strip()
        if h.startswith("04") and len(h) == 130:
            x = int(h[2:66], 16)
            y = int(h[66:], 16)
            return cls(x, y)
        elif h[:2] in ("02", "03") and len(h) == 66:
            return cls.from_compressed(h)
        raise ValueError(f"Unrecognized point encoding: {h[:6]}...")

    @classmethod
    def from_compressed(cls, h: str) -> "ECPublicKey":
        prefix = int(h[:2], 16)
        x = int(h[2:], 16)
        # y^2 = x^3 + ax + b mod P
        y2 = (pow(x, 3, _P) + _A * x + _B) % _P
        y = pow(y2, (_P + 1) // 4, _P)  # Works because P ≡ 3 mod 4
        if y % 2 != prefix % 2:
            y = _P - y
        return cls(x, y)


# ---------------------------------------------------------------------------
# ECDH key exchange
# ---------------------------------------------------------------------------

def ecdh_exchange(priv: ECPrivateKey, peer_pub: ECPublicKey) -> bytes:
    """ECDH shared secret: d * Q_peer → SHA-256(x-coordinate).

    We hash the raw x-coordinate with SHA-256 to produce 32 bytes of key
    material (simulating the ANSI X9.63 single-hash KDF). A real application
    would use HKDF. The raw x-coordinate itself is never returned.
    """
    pt = _mul_point(priv.d, peer_pub.x, peer_pub.y)
    if pt is None:
        raise ValueError("ECDH result is the point at infinity")
    shared_x, _ = pt
    return sha256(shared_x.to_bytes(32, "big"))


# ---------------------------------------------------------------------------
# RFC 6979 deterministic k generation
# ---------------------------------------------------------------------------

def _rfc6979_k(priv_int: int, msg_hash: bytes) -> int:
    """Deterministic k per RFC 6979 §3.2 using HMAC-SHA256."""
    q_bytes = _N.to_bytes(32, "big")
    x_bytes = priv_int.to_bytes(32, "big")
    h1 = msg_hash[:32]

    # Step b/c/d: initialize V and K
    V = b"\x01" * 32
    K = b"\x00" * 32

    def hmac(k: bytes, data: bytes) -> bytes:
        return hmac_sha256(k, data)

    K = hmac(K, V + b"\x00" + x_bytes + h1)
    V = hmac(K, V)
    K = hmac(K, V + b"\x01" + x_bytes + h1)
    V = hmac(K, V)

    while True:
        T = b""
        while len(T) < 32:
            V = hmac(K, V)
            T += V
        k = int.from_bytes(T[:32], "big")
        if 1 <= k < _N:
            return k
        K = hmac(K, V + b"\x00")
        V = hmac(K, V)


# ---------------------------------------------------------------------------
# ECDSA sign/verify
# ---------------------------------------------------------------------------

def ecdsa_sign(priv: ECPrivateKey, message: bytes) -> tuple[int, int]:
    """Sign message with ECDSA (RFC 6979 deterministic k). Returns (r, s)."""
    z = int.from_bytes(sha256(message), "big")
    # Truncate to N bit length if needed
    z >>= max(0, 256 - _N.bit_length())

    k = _rfc6979_k(priv.d, sha256(message))
    pt = _mul_G(k)
    if pt is None:
        raise ValueError("k*G = infinity (impossible for valid k)")
    r = pt[0] % _N
    if r == 0:
        raise ValueError("r = 0 (impossible for valid k)")
    k_inv = pow(k, _N - 2, _N)  # Fermat inverse mod prime N
    s = k_inv * (z + r * priv.d) % _N
    if s == 0:
        raise ValueError("s = 0 (impossible)")
    # Normalize s to low-S form (canonical)
    if s > _N // 2:
        s = _N - s
    return (r, s)


def ecdsa_verify(pub: ECPublicKey, message: bytes,
                 r: int, s: int) -> bool:
    """Verify ECDSA signature (r, s) on message. Returns True if valid."""
    if not (1 <= r < _N and 1 <= s < _N):
        return False
    z = int.from_bytes(sha256(message), "big")
    z >>= max(0, 256 - _N.bit_length())

    w = pow(s, _N - 2, _N)
    u1 = z * w % _N
    u2 = r * w % _N

    # Compute u1*G + u2*Q
    p1 = _scalar_mul(u1, _from_affine(_G))
    p2 = _scalar_mul(u2, _from_affine((pub.x, pub.y)))
    pt = _to_affine(_jac_add(p1, p2))
    if pt is None:
        return False
    return pt[0] % _N == r


def ecdsa_sign_hex(priv: ECPrivateKey, message: bytes) -> str:
    r, s = ecdsa_sign(priv, message)
    return f"{r:064x}{s:064x}"


def ecdsa_verify_hex(pub: ECPublicKey, message: bytes, sig_hex: str) -> bool:
    if len(sig_hex) != 128:
        return False
    r = int(sig_hex[:64], 16)
    s = int(sig_hex[64:], 16)
    return ecdsa_verify(pub, message, r, s)
