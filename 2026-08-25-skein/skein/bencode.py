"""A from-scratch bencode codec.

Bencode ("Bee-encode") is the serialization format defined by the
original BitTorrent spec (BEP 3). It has exactly four types:

    integers     i<base-10 digits>e      e.g. i42e, i-3e, i0e
    byte strings <len>:<bytes>           e.g. 4:spam
    lists        l<bencoded values>e     e.g. l4:spam4:eggse
    dictionaries d<bencoded k/v pairs>e  e.g. d3:cow3:moo4:spam4:eggse

Dictionary keys must be byte strings and MUST be encoded in sorted
(raw byte, lexicographic) order — this is what makes bencode
deterministic, which matters because a torrent's info-hash is a SHA-1
of a specific dict's bencoded bytes: two encoders that disagree on key
order would produce different info-hashes for the same torrent.

This module deliberately does not depend on any third-party bencode
library — every byte of the encoder/decoder is hand-written and
validated against the worked examples from BEP 3 in tests/test_bencode.py.
"""

from __future__ import annotations


class BencodeError(ValueError):
    """Raised on malformed bencode input or an unencodable Python value."""


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------

def encode(value) -> bytes:
    """Encode a Python value (int, bytes/str, list/tuple, dict) to bencode."""
    out = bytearray()
    _encode_into(value, out)
    return bytes(out)


def _encode_into(value, out: bytearray) -> None:
    if isinstance(value, bool):
        # bool is a subclass of int in Python; bencode has no boolean type
        # and silently encoding True/False as 1/0 would hide bugs, so reject.
        raise BencodeError("bencode has no boolean type; encode an int instead")
    if isinstance(value, int):
        out += b"i" + str(value).encode("ascii") + b"e"
    elif isinstance(value, (bytes, bytearray)):
        out += str(len(value)).encode("ascii") + b":" + bytes(value)
    elif isinstance(value, str):
        b = value.encode("utf-8")
        out += str(len(b)).encode("ascii") + b":" + b
    elif isinstance(value, (list, tuple)):
        out += b"l"
        for item in value:
            _encode_into(item, out)
        out += b"e"
    elif isinstance(value, dict):
        out += b"d"
        # Keys must sort by their *encoded* raw bytes, not by Python str
        # comparison, since a dict key like "\xff" and a mixed str/bytes
        # key set could otherwise disagree with what a real client does.
        items = []
        for k, v in value.items():
            if isinstance(k, str):
                kb = k.encode("utf-8")
            elif isinstance(k, (bytes, bytearray)):
                kb = bytes(k)
            else:
                raise BencodeError(f"dict keys must be str or bytes, got {type(k)!r}")
            items.append((kb, v))
        items.sort(key=lambda kv: kv[0])
        for kb, v in items:
            out += str(len(kb)).encode("ascii") + b":" + kb
            _encode_into(v, out)
        out += b"e"
    else:
        raise BencodeError(f"cannot bencode value of type {type(value)!r}")


# ---------------------------------------------------------------------------
# Decoding
# ---------------------------------------------------------------------------

def decode(data: bytes):
    """Decode a single bencoded value. Raises if trailing bytes remain."""
    value, pos = _decode_at(data, 0)
    if pos != len(data):
        raise BencodeError(f"trailing garbage after bencoded value at offset {pos}")
    return value


def decode_prefix(data: bytes, start: int = 0):
    """Decode one bencoded value starting at `start`; return (value, end_pos).

    Used by callers (e.g. the tracker's compact-peer scanner and streaming
    parsers) that need to decode one value out of a larger buffer without
    requiring the whole buffer to be a single bencoded value.
    """
    return _decode_at(data, start)


def _decode_at(data: bytes, pos: int):
    if pos >= len(data):
        raise BencodeError("unexpected end of data")
    marker = data[pos:pos + 1]
    if marker == b"i":
        return _decode_int(data, pos)
    if marker == b"l":
        return _decode_list(data, pos)
    if marker == b"d":
        return _decode_dict(data, pos)
    if marker.isdigit():
        return _decode_bytestring(data, pos)
    raise BencodeError(f"invalid bencode marker {marker!r} at offset {pos}")


def _decode_int(data: bytes, pos: int):
    assert data[pos:pos + 1] == b"i"
    end = data.find(b"e", pos + 1)
    if end == -1:
        raise BencodeError(f"unterminated integer starting at offset {pos}")
    raw = data[pos + 1:end]
    if raw == b"" or raw == b"-":
        raise BencodeError(f"empty integer at offset {pos}")
    # Reject leading zeros ("i03e") and negative zero ("i-0e") — real
    # encoders never produce these, and accepting them would let two
    # different byte strings decode to the same int (ambiguous encoding).
    sign = ""
    digits = raw
    if raw[:1] == b"-":
        sign = "-"
        digits = raw[1:]
    if digits == b"" or not digits.isdigit():
        raise BencodeError(f"malformed integer {raw!r} at offset {pos}")
    if digits == b"0" and sign == "-":
        raise BencodeError(f"negative zero is not valid bencode at offset {pos}")
    if len(digits) > 1 and digits[0:1] == b"0":
        raise BencodeError(f"leading zero in integer {raw!r} at offset {pos}")
    return int(sign + digits.decode("ascii")), end + 1


def _decode_bytestring(data: bytes, pos: int):
    colon = data.find(b":", pos)
    if colon == -1:
        raise BencodeError(f"unterminated byte string length at offset {pos}")
    len_raw = data[pos:colon]
    if not len_raw.isdigit():
        raise BencodeError(f"malformed byte string length {len_raw!r} at offset {pos}")
    if len(len_raw) > 1 and len_raw[0:1] == b"0":
        raise BencodeError(f"leading zero in byte string length at offset {pos}")
    length = int(len_raw)
    start = colon + 1
    end = start + length
    if end > len(data):
        raise BencodeError(f"byte string of length {length} runs past end of data")
    return data[start:end], end


def _decode_list(data: bytes, pos: int):
    assert data[pos:pos + 1] == b"l"
    items = []
    pos += 1
    while True:
        if pos >= len(data):
            raise BencodeError("unterminated list")
        if data[pos:pos + 1] == b"e":
            return items, pos + 1
        value, pos = _decode_at(data, pos)
        items.append(value)


def _decode_dict(data: bytes, pos: int):
    assert data[pos:pos + 1] == b"d"
    result = {}
    pos += 1
    prev_key = None
    while True:
        if pos >= len(data):
            raise BencodeError("unterminated dict")
        if data[pos:pos + 1] == b"e":
            return result, pos + 1
        key, pos = _decode_at(data, pos)
        if not isinstance(key, (bytes, bytearray)):
            raise BencodeError("dict keys must be byte strings")
        key = bytes(key)
        if prev_key is not None and key <= prev_key:
            raise BencodeError(
                f"dict keys not in strict sorted order: {prev_key!r} before {key!r}"
            )
        prev_key = key
        value, pos = _decode_at(data, pos)
        result[key] = value
