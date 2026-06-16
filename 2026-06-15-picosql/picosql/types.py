"""Value model and binary (de)serialization for PicoSQL rows.

A *value* is one of: None (NULL), int (INTEGER), float (REAL), str (TEXT).
A *row* is a tuple of values. Rows are serialized to a type-tagged byte string
so they can be stored as B+tree leaf payloads and read back losslessly.
"""

from __future__ import annotations

import struct
from typing import List, Sequence, Tuple

# Column type names used in schemas / CREATE TABLE.
COLUMN_TYPES = ("INTEGER", "REAL", "TEXT")

# Value tags.
_TAG_NULL = 0
_TAG_INT = 1
_TAG_REAL = 2
_TAG_TEXT = 3

Value = object  # None | int | float | str
Row = Tuple[Value, ...]


class TypeError_(Exception):
    """Raised when a value cannot be coerced/encoded for its declared type."""


def coerce(value: Value, declared_type: str) -> Value:
    """Coerce a Python value to a column's declared type, or raise.

    NULL passes through. INTEGER accepts bool/int and integral floats. REAL
    accepts int/float. TEXT accepts str (and stringifies ints/reals is *not*
    done implicitly — that would hide bugs)."""
    if value is None:
        return None
    t = declared_type.upper()
    if t == "INTEGER":
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        raise TypeError_(f"cannot store {value!r} in INTEGER column")
    if t == "REAL":
        if isinstance(value, bool):
            return float(value)
        if isinstance(value, (int, float)):
            return float(value)
        raise TypeError_(f"cannot store {value!r} in REAL column")
    if t == "TEXT":
        if isinstance(value, str):
            return value
        raise TypeError_(f"cannot store {value!r} in TEXT column")
    raise TypeError_(f"unknown column type {declared_type!r}")


def encode_value(value: Value) -> bytes:
    if value is None:
        return bytes([_TAG_NULL])
    if isinstance(value, bool):  # bool is a subclass of int; store as int
        value = int(value)
    if isinstance(value, int):
        return bytes([_TAG_INT]) + struct.pack("<q", value)
    if isinstance(value, float):
        return bytes([_TAG_REAL]) + struct.pack("<d", value)
    if isinstance(value, str):
        b = value.encode("utf-8")
        return bytes([_TAG_TEXT]) + struct.pack("<I", len(b)) + b
    raise TypeError_(f"cannot encode value of type {type(value).__name__}")


def _decode_value(buf: bytes, off: int) -> Tuple[Value, int]:
    tag = buf[off]
    off += 1
    if tag == _TAG_NULL:
        return None, off
    if tag == _TAG_INT:
        (v,) = struct.unpack_from("<q", buf, off)
        return v, off + 8
    if tag == _TAG_REAL:
        (v,) = struct.unpack_from("<d", buf, off)
        return v, off + 8
    if tag == _TAG_TEXT:
        (n,) = struct.unpack_from("<I", buf, off)
        off += 4
        s = buf[off : off + n].decode("utf-8")
        return s, off + n
    raise ValueError(f"corrupt value tag {tag} at offset {off - 1}")


def encode_row(row: Sequence[Value]) -> bytes:
    out = [struct.pack("<H", len(row))]
    for v in row:
        out.append(encode_value(v))
    return b"".join(out)


def decode_row(buf: bytes) -> Row:
    (n,) = struct.unpack_from("<H", buf, 0)
    off = 2
    vals: List[Value] = []
    for _ in range(n):
        v, off = _decode_value(buf, off)
        vals.append(v)
    return tuple(vals)
