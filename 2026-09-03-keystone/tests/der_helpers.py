"""Minimal hand-rolled ASN.1 DER encoding — just enough to hand secp256k1
keys and ECDSA signatures to/from the real `openssl` binary as an
independent verification oracle for keystone/crypto.py. Test-support code
only, deliberately not part of the shipped `keystone` package: no
`cryptography`/`pyasn1` package is used to build these bytes, on the same
principle as the rest of Keystone's crypto layer.
"""
from __future__ import annotations

import base64

OID_EC_PUBLIC_KEY = bytes.fromhex("06072a8648ce3d0201")  # 1.2.840.10045.2.1
OID_SECP256K1 = bytes.fromhex("06052b8104000a")  # 1.3.132.0.10


def der_len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    body = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(body)]) + body


def der_tlv(tag: int, content: bytes) -> bytes:
    return bytes([tag]) + der_len(len(content)) + content


def der_integer(n: int) -> bytes:
    if n == 0:
        body = b"\x00"
    else:
        body = n.to_bytes((n.bit_length() + 7) // 8 + 1, "big")  # extra byte covers sign
        body = body.lstrip(b"\x00") or b"\x00"
        if body[0] & 0x80:
            body = b"\x00" + body
    return der_tlv(0x02, body)


def der_sequence(*parts: bytes) -> bytes:
    return der_tlv(0x30, b"".join(parts))


def der_bitstring(data: bytes, unused_bits: int = 0) -> bytes:
    return der_tlv(0x03, bytes([unused_bits]) + data)


def der_octetstring(data: bytes) -> bytes:
    return der_tlv(0x04, data)


def der_explicit(tag_number: int, content: bytes) -> bytes:
    return der_tlv(0xA0 | tag_number, content)


def to_pem(der: bytes, label: str) -> str:
    b64 = base64.b64encode(der).decode("ascii")
    lines = [b64[i:i + 64] for i in range(0, len(b64), 64)]
    return f"-----BEGIN {label}-----\n" + "\n".join(lines) + f"\n-----END {label}-----\n"


def public_key_pem(x: int, y: int) -> str:
    point = b"\x04" + x.to_bytes(32, "big") + y.to_bytes(32, "big")
    spki = der_sequence(
        der_sequence(OID_EC_PUBLIC_KEY, OID_SECP256K1),
        der_bitstring(point),
    )
    return to_pem(spki, "PUBLIC KEY")


def private_key_pem(privkey: int, x: int, y: int) -> str:
    point = b"\x04" + x.to_bytes(32, "big") + y.to_bytes(32, "big")
    sec1 = der_sequence(
        der_integer(1),
        der_octetstring(privkey.to_bytes(32, "big")),
        der_explicit(0, OID_SECP256K1),
        der_explicit(1, der_bitstring(point)),
    )
    return to_pem(sec1, "EC PRIVATE KEY")


def signature_der(r: int, s: int) -> bytes:
    return der_sequence(der_integer(r), der_integer(s))


def parse_der_integer(data: bytes, offset: int):
    assert data[offset] == 0x02
    offset += 1
    length = data[offset]
    offset += 1
    value = int.from_bytes(data[offset:offset + length], "big")
    return value, offset + length


def parse_signature_der(data: bytes):
    assert data[0] == 0x30
    offset = 2 if data[1] < 0x80 else 2 + (data[1] & 0x7F)
    r, offset = parse_der_integer(data, offset)
    s, offset = parse_der_integer(data, offset)
    return r, s
