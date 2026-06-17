"""The Cinch container format and method dispatch.

A `.cinch` file is fully self-describing:

    magic  : 5 bytes  b"CINCH"
    version: 1 byte    (currently 1)
    method : 1 byte    (see METHODS)
    crc32  : 4 bytes   big-endian CRC-32 of the *original* data
    origlen: uvarint   original length in bytes
    payload: the codec blob

Decompression verifies the CRC and the recovered length, so corrupt or
truncated files are rejected rather than silently mis-decoded.
"""
from __future__ import annotations

import deflate
import huffman
import lz77
import rangecoder
from util import crc32, read_uvarint, write_uvarint

MAGIC = b"CINCH"
VERSION = 1

# method id -> (name, encode, decode)
METHODS = {
    0: ("store", lambda d: d, lambda b: b),
    1: ("huffman", huffman.encode, huffman.decode),
    2: ("lz77", lz77.encode, lz77.decode),
    3: ("deflate", deflate.encode, deflate.decode),
    4: ("range0", rangecoder.encode_order0, rangecoder.decode_order0),
    5: ("range1", rangecoder.encode_order1, rangecoder.decode_order1),
}
NAME_TO_ID = {name: mid for mid, (name, _e, _d) in METHODS.items()}


class CinchError(Exception):
    pass


def compress(data: bytes, method: str = "deflate") -> bytes:
    if method == "auto":
        return _compress_auto(data)
    if method not in NAME_TO_ID:
        raise CinchError(f"unknown method {method!r}")
    mid = NAME_TO_ID[method]
    _name, enc, _dec = METHODS[mid]
    payload = enc(data)
    out = bytearray()
    out += MAGIC
    out.append(VERSION)
    out.append(mid)
    out += crc32(data).to_bytes(4, "big")
    write_uvarint(out, len(data))
    out += payload
    return bytes(out)


def _compress_auto(data: bytes) -> bytes:
    """Try every real method and keep the smallest container."""
    best = None
    for name in ("store", "huffman", "lz77", "deflate", "range0", "range1"):
        cand = compress(data, name)
        if best is None or len(cand) < len(best):
            best = cand
    return best


def decompress(blob: bytes) -> bytes:
    if len(blob) < 11 or blob[:5] != MAGIC:
        raise CinchError("not a Cinch container (bad magic)")
    version = blob[5]
    if version != VERSION:
        raise CinchError(f"unsupported version {version}")
    mid = blob[6]
    if mid not in METHODS:
        raise CinchError(f"unknown method id {mid}")
    want_crc = int.from_bytes(blob[7:11], "big")
    origlen, pos = read_uvarint(blob, 11)
    payload = blob[pos:]
    _name, _enc, dec = METHODS[mid]
    try:
        data = dec(payload)
    except (EOFError, ValueError, IndexError) as exc:
        raise CinchError(f"corrupt payload: {exc}") from exc
    if len(data) != origlen:
        raise CinchError(f"length mismatch: got {len(data)}, header says {origlen}")
    if crc32(data) != want_crc:
        raise CinchError("CRC mismatch: data is corrupt")
    return data


def inspect(blob: bytes) -> dict:
    """Decode just the header (no full decompression) for `inspect`."""
    if len(blob) < 11 or blob[:5] != MAGIC:
        raise CinchError("not a Cinch container (bad magic)")
    mid = blob[6]
    name = METHODS[mid][0] if mid in METHODS else f"?{mid}"
    crc = int.from_bytes(blob[7:11], "big")
    origlen, pos = read_uvarint(blob, 11)
    comp_len = len(blob)
    ratio = comp_len / origlen if origlen else float("nan")
    return {
        "version": blob[5],
        "method": name,
        "method_id": mid,
        "crc32": crc,
        "original_size": origlen,
        "compressed_size": comp_len,
        "header_size": pos,
        "payload_size": comp_len - pos,
        "ratio": ratio,
        "saving": (1 - ratio) if origlen else float("nan"),
    }
