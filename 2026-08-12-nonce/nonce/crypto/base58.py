"""Base58Check encoding, from scratch (the Bitcoin-address alphabet: no
0/O/I/l, so addresses can't be visually confused character-for-character).
"""

from .sha256 import sha256d

_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_BASE = len(_ALPHABET)


def b58encode(data: bytes) -> str:
    n = int.from_bytes(data, "big")
    out = ""
    while n > 0:
        n, rem = divmod(n, _BASE)
        out = _ALPHABET[rem] + out
    # preserve leading zero bytes as leading '1's (base58 convention)
    n_leading_zeros = len(data) - len(data.lstrip(b"\x00"))
    return "1" * n_leading_zeros + out


def b58decode(s: str) -> bytes:
    n = 0
    for ch in s:
        n = n * _BASE + _ALPHABET.index(ch)
    n_leading_ones = len(s) - len(s.lstrip("1"))
    body = n.to_bytes((n.bit_length() + 7) // 8, "big") if n > 0 else b""
    return b"\x00" * n_leading_ones + body


def b58check_encode(version: bytes, payload: bytes) -> str:
    body = version + payload
    checksum = sha256d(body)[:4]
    return b58encode(body + checksum)


def b58check_decode(s: str):
    """Returns (version, payload). Raises ValueError on bad checksum."""
    raw = b58decode(s)
    body, checksum = raw[:-4], raw[-4:]
    if sha256d(body)[:4] != checksum:
        raise ValueError("bad base58check checksum")
    return body[:1], body[1:]
