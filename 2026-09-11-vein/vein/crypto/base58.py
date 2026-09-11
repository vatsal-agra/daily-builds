"""Base58Check encoding, from scratch (the encoding Bitcoin addresses use).

Base58 drops characters that are easy to confuse in print or by eye
(0/O, I/l) and avoids '+' and '/' so addresses copy-paste cleanly.
Base58Check appends a 4-byte double-SHA256 checksum so a single typo'd
character is detected rather than silently sending funds to a mistyped,
unowned address.
"""

from __future__ import annotations

from .hashes import double_sha256

_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_BASE = len(_ALPHABET)


def b58encode(data: bytes) -> str:
    n = int.from_bytes(data, "big")
    chars = []
    while n > 0:
        n, rem = divmod(n, _BASE)
        chars.append(_ALPHABET[rem])
    chars.reverse()
    encoded = "".join(chars)

    # Preserve leading zero bytes as leading '1's (Bitcoin convention).
    n_leading_zeros = len(data) - len(data.lstrip(b"\x00"))
    return "1" * n_leading_zeros + (encoded or "")


def b58decode(s: str) -> bytes:
    n = 0
    for ch in s:
        if ch not in _ALPHABET:
            raise ValueError(f"invalid base58 character: {ch!r}")
        n = n * _BASE + _ALPHABET.index(ch)

    n_leading_ones = len(s) - len(s.lstrip("1"))
    body = n.to_bytes((n.bit_length() + 7) // 8, "big") if n > 0 else b""
    return b"\x00" * n_leading_ones + body


def b58check_encode(payload: bytes) -> str:
    checksum = double_sha256(payload)[:4]
    return b58encode(payload + checksum)


def b58check_decode(s: str) -> bytes:
    raw = b58decode(s)
    if len(raw) < 4:
        raise ValueError("base58check string too short")
    payload, checksum = raw[:-4], raw[-4:]
    if double_sha256(payload)[:4] != checksum:
        raise ValueError("base58check checksum mismatch")
    return payload
