"""Compressed pubkey (de)serialization and Base58Check addresses."""

from __future__ import annotations

from .curve import P, Point, is_on_curve
from .hashes import hash160
from .base58 import b58check_encode, b58check_decode

VERSION_BYTE = 0x24  # arbitrary network version byte for Vein addresses


def serialize_pubkey(pt: Point) -> bytes:
    """SEC1 compressed point encoding: 1-byte parity prefix + 32-byte x."""
    if pt.is_infinity():
        raise ValueError("cannot serialize the point at infinity")
    prefix = 0x02 if pt.y % 2 == 0 else 0x03
    return bytes([prefix]) + pt.x.to_bytes(32, "big")


def parse_pubkey(data: bytes) -> Point:
    if len(data) != 33 or data[0] not in (0x02, 0x03):
        raise ValueError("expected a 33-byte compressed pubkey")
    x = int.from_bytes(data[1:], "big")
    rhs = (pow(x, 3, P) + 7) % P
    y = pow(rhs, (P + 1) // 4, P)  # valid sqrt since P % 4 == 3
    if (y * y - rhs) % P != 0:
        raise ValueError("x is not on the curve")
    want_odd = data[0] == 0x03
    if (y % 2 == 1) != want_odd:
        y = P - y
    pt = Point(x, y)
    if not is_on_curve(pt):
        raise ValueError("decoded point is not on the curve")
    return pt


def address_from_pubkey(pubkey_bytes: bytes) -> str:
    payload = bytes([VERSION_BYTE]) + hash160(pubkey_bytes)
    return b58check_encode(payload)


def pubkey_hash_from_address(addr: str) -> bytes:
    payload = b58check_decode(addr)
    if len(payload) != 21 or payload[0] != VERSION_BYTE:
        raise ValueError("not a valid Vein address")
    return payload[1:]


def is_valid_address(addr: str) -> bool:
    try:
        pubkey_hash_from_address(addr)
        return True
    except ValueError:
        return False
