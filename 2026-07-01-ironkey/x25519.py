"""
X25519 (RFC 7748) Diffie-Hellman key exchange on Curve25519, implemented
directly from the RFC's Montgomery-ladder pseudocode. Modular inversion
uses our own `bigint.modinv` (Fermat's little theorem via modexp), not a
borrowed big-number library.
"""
import os

import bigint

_P = 2 ** 255 - 19
_A24 = 121665  # (486662 - 2) // 4
_BASEPOINT_U = 9


def _clamp_scalar(k):
    k = bytearray(k)
    k[0] &= 248
    k[31] &= 127
    k[31] |= 64
    return int.from_bytes(bytes(k), "little")


def _decode_u(u_bytes):
    u = bytearray(u_bytes)
    u[31] &= 0x7F  # RFC 7748 sec 5: mask the unused top bit on decode
    return int.from_bytes(bytes(u), "little")


def _encode_u(u_int):
    return (u_int % _P).to_bytes(32, "little")


def _cswap(swap, a, b):
    return (b, a) if swap else (a, b)


def x25519(scalar_bytes, u_bytes):
    """The RFC 7748 X25519 function: scalar-multiply the point with
    u-coordinate `u_bytes` by the clamped scalar `scalar_bytes`."""
    if len(scalar_bytes) != 32 or len(u_bytes) != 32:
        raise ValueError("X25519 scalar and u-coordinate must each be 32 bytes")

    k = _clamp_scalar(scalar_bytes)
    u = _decode_u(u_bytes)

    x1 = u
    x2, z2 = 1, 0
    x3, z3 = u, 1
    swap = 0

    for t in reversed(range(255)):
        k_t = (k >> t) & 1
        swap ^= k_t
        x2, x3 = _cswap(swap, x2, x3)
        z2, z3 = _cswap(swap, z2, z3)
        swap = k_t

        A = (x2 + z2) % _P
        AA = (A * A) % _P
        B = (x2 - z2) % _P
        BB = (B * B) % _P
        E = (AA - BB) % _P
        C = (x3 + z3) % _P
        D = (x3 - z3) % _P
        DA = (D * A) % _P
        CB = (C * B) % _P
        x3 = ((DA + CB) * (DA + CB)) % _P
        z3 = (x1 * ((DA - CB) * (DA - CB))) % _P
        x2 = (AA * BB) % _P
        z2 = (E * (AA + _A24 * E)) % _P

    x2, x3 = _cswap(swap, x2, x3)
    z2, z3 = _cswap(swap, z2, z3)

    if z2 % _P == 0:
        # Degenerate/low-order input (e.g. all-zero public key). RFC 7748
        # sec 6.1 notes the result is undefined; return the all-zero
        # string rather than raising, but callers MUST reject an
        # all-zero shared secret before using it (see session.py).
        return b"\x00" * 32

    inv_z2 = bigint.modinv(z2, _P)
    return _encode_u((x2 * inv_z2) % _P)


def generate_private_key():
    return os.urandom(32)


def derive_public_key(private_key):
    return x25519(private_key, _BASEPOINT_U.to_bytes(32, "little"))


def compute_shared_secret(private_key, peer_public_key):
    secret = x25519(private_key, peer_public_key)
    if secret == b"\x00" * 32:
        raise ValueError(
            "shared secret is all-zero — peer public key is a degenerate/"
            "low-order point; refusing to use it as a key"
        )
    return secret
