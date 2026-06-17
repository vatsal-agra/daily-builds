"""Small byte-level helpers shared across codecs."""
from __future__ import annotations

# --- CRC-32 (IEEE 802.3), implemented from scratch ------------------------
_CRC_TABLE: list[int] = []
for _n in range(256):
    _c = _n
    for _k in range(8):
        _c = (0xEDB88320 ^ (_c >> 1)) if (_c & 1) else (_c >> 1)
    _CRC_TABLE.append(_c)


def crc32(data: bytes) -> int:
    crc = 0xFFFFFFFF
    table = _CRC_TABLE
    for b in data:
        crc = table[(crc ^ b) & 0xFF] ^ (crc >> 8)
    return crc ^ 0xFFFFFFFF


def write_uvarint(out: bytearray, value: int) -> None:
    """LEB128 unsigned varint."""
    if value < 0:
        raise ValueError("uvarint must be non-negative")
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return


def read_uvarint(data: bytes, pos: int) -> tuple[int, int]:
    """Return (value, new_pos)."""
    result = 0
    shift = 0
    while True:
        if pos >= len(data):
            raise ValueError("truncated varint")
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            return result, pos
        shift += 7
        if shift > 63:
            raise ValueError("varint too long")
