"""Minimal deterministic binary encoding helpers (LEB128 varints and
length-prefixed byte strings) shared by transaction.py and block.py.
Deterministic byte-for-byte encoding matters here: block/transaction hashes
are computed over these bytes, so two nodes must produce identical bytes for
identical logical content.
"""


def write_varint(n: int) -> bytes:
    if n < 0:
        raise ValueError("varint must be non-negative")
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def read_varint(buf: bytes, offset: int):
    shift = 0
    result = 0
    while True:
        b = buf[offset]
        offset += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, offset
        shift += 7


def write_bytes(data: bytes) -> bytes:
    return write_varint(len(data)) + data


def read_bytes(buf: bytes, offset: int):
    length, offset = read_varint(buf, offset)
    data = buf[offset:offset + length]
    if len(data) != length:
        raise ValueError("truncated buffer while reading length-prefixed bytes")
    return data, offset + length


def write_str(s: str) -> bytes:
    return write_bytes(s.encode("utf-8"))


def read_str(buf: bytes, offset: int):
    data, offset = read_bytes(buf, offset)
    return data.decode("utf-8"), offset
