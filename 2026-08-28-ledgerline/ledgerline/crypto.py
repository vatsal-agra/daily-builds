"""Hashing and address-encoding helpers shared across the protocol.

Block/transaction hashing uses double-SHA256 ("SHA-256d"), exactly like
real Bitcoin, to avoid length-extension issues from a single SHA-256 pass.
See PLAN.md for why this project uses `hashlib.sha256` rather than
re-deriving SHA-256 from scratch (it's been done twice already in this
repo's history) and instead spends its "from scratch" budget on secp256k1
ECDSA in `ecdsa.py`.

Addresses use Base58Check over `sha256d(pubkey)[:20]` — deliberately
RIPEMD-160-free (real Bitcoin hashes RIPEMD160(SHA256(pubkey))) so address
derivation has zero dependency on RIPEMD160's spotty availability across
OpenSSL builds.
"""
from __future__ import annotations

import hashlib

ADDRESS_VERSION = 0x30  # arbitrary version byte, makes addresses start with "L" (for LedgerLine)
_B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def sha256d(data: bytes) -> bytes:
    """Double SHA-256, as used for block and transaction IDs."""
    return sha256(sha256(data))


def hash160(data: bytes) -> bytes:
    """20-byte digest used for addresses (see module docstring)."""
    return sha256d(data)[:20]


def b58encode(data: bytes) -> str:
    n = int.from_bytes(data, "big")
    out = ""
    while n > 0:
        n, rem = divmod(n, 58)
        out = _B58_ALPHABET[rem] + out
    # preserve leading zero bytes as leading '1's, like real Base58Check
    n_leading_zeros = len(data) - len(data.lstrip(b"\x00"))
    return "1" * n_leading_zeros + out


def b58decode(s: str) -> bytes:
    n = 0
    for ch in s:
        if ch not in _B58_ALPHABET:
            raise ValueError(f"invalid base58 character: {ch!r}")
        n = n * 58 + _B58_ALPHABET.index(ch)
    n_leading_ones = len(s) - len(s.lstrip("1"))
    body = n.to_bytes((n.bit_length() + 7) // 8, "big") if n > 0 else b""
    return b"\x00" * n_leading_ones + body


def b58check_encode(payload: bytes, version: int = ADDRESS_VERSION) -> str:
    versioned = bytes([version]) + payload
    checksum = sha256d(versioned)[:4]
    return b58encode(versioned + checksum)


def b58check_decode(s: str, expected_version: int = ADDRESS_VERSION) -> bytes:
    raw = b58decode(s)
    if len(raw) < 5:
        raise ValueError("base58check payload too short")
    versioned, checksum = raw[:-4], raw[-4:]
    if sha256d(versioned)[:4] != checksum:
        raise ValueError("base58check checksum mismatch (corrupt address)")
    if versioned[0] != expected_version:
        raise ValueError("unexpected address version byte")
    return versioned[1:]


def pubkey_to_address(compressed_pubkey: bytes) -> str:
    return b58check_encode(hash160(compressed_pubkey))
