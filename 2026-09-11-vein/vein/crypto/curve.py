"""secp256k1 field and point arithmetic, from scratch.

This is the actual curve Bitcoin/Ethereum use (y^2 = x^3 + 7 over a
256-bit prime field) — a different curve from the P-256/X25519 curves
this repo's earlier crypto builds (Cryptex, Ironkey) implemented.
Everything here is plain Python integer arithmetic: no `ecdsa`, no
`cryptography`, no `gmpy2`.
"""

from __future__ import annotations

from dataclasses import dataclass

# secp256k1 domain parameters (SEC 2, section 2.4.1)
P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
A = 0
B = 7
GX = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
GY = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8
N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141


def _inv_mod(x: int, m: int) -> int:
    """Modular inverse via Fermat's little theorem (m must be prime)."""
    return pow(x, m - 2, m)


@dataclass(frozen=True)
class Point:
    """A point on secp256k1, or the point at infinity when x is None."""

    x: int | None
    y: int | None

    def is_infinity(self) -> bool:
        return self.x is None

    def __add__(self, other: "Point") -> "Point":
        return point_add(self, other)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Point):
            return NotImplemented
        return self.x == other.x and self.y == other.y


INFINITY = Point(None, None)
G = Point(GX, GY)


def is_on_curve(pt: Point) -> bool:
    if pt.is_infinity():
        return True
    return (pt.y * pt.y - (pt.x**3 + A * pt.x + B)) % P == 0


def point_add(p1: Point, p2: Point) -> Point:
    if p1.is_infinity():
        return p2
    if p2.is_infinity():
        return p1
    if p1.x == p2.x and (p1.y + p2.y) % P == 0:
        return INFINITY  # p2 == -p1

    if p1.x == p2.x and p1.y == p2.y:
        # Point doubling: lambda = (3x^2 + a) / (2y)
        lam = (3 * p1.x * p1.x + A) * _inv_mod(2 * p1.y % P, P) % P
    else:
        # Point addition: lambda = (y2 - y1) / (x2 - x1)
        lam = (p2.y - p1.y) * _inv_mod((p2.x - p1.x) % P, P) % P

    x3 = (lam * lam - p1.x - p2.x) % P
    y3 = (lam * (p1.x - x3) - p1.y) % P
    return Point(x3, y3)


def scalar_mult(k: int, pt: Point) -> Point:
    """Double-and-add scalar multiplication, k * pt."""
    if k % N == 0 or pt.is_infinity():
        return INFINITY
    if k < 0:
        return scalar_mult(-k, Point(pt.x, (-pt.y) % P))

    result = INFINITY
    addend = pt
    while k:
        if k & 1:
            result = point_add(result, addend)
        addend = point_add(addend, addend)
        k >>= 1
    return result


def derive_pubkey(privkey: int) -> Point:
    if not (1 <= privkey <= N - 1):
        raise ValueError("private key out of range [1, N-1]")
    return scalar_mult(privkey, G)
