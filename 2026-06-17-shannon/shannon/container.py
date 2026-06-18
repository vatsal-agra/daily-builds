"""The ``.shz`` container: a self-verifying wrapper around a codec payload.

Layout (all integers little-endian where fixed-width)::

    magic   : 4 bytes  b"SHZ1"
    version : 1 byte    (currently 1)
    method  : 1 byte    codec id (see codecs.CODECS)
    orig_len: varint    original uncompressed length
    crc32   : 4 bytes   CRC-32 of the *original* data
    payload : bytes      the codec output

CRC lets decompression detect corruption (and lets the test suite trust the
round-trip).  varint here is a standalone LEB128 helper so the header can be
parsed without a bit reader.
"""
from __future__ import annotations

import zlib
from typing import Tuple

from . import codecs

MAGIC = b"SHZ1"
VERSION = 1

# Hard ceiling on decompressed size. A few corrupted header bytes can otherwise
# encode a multi-gigabyte length/count and turn decompression into an OOM bomb;
# refusing absurd sizes up front keeps a corrupt stream cheap to reject.
MAX_DECOMPRESSED = 1 << 30  # 1 GiB


def _write_varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _read_varint(data: bytes, pos: int) -> Tuple[int, int]:
    value = 0
    shift = 0
    while True:
        byte = data[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            return value, pos
        shift += 7


def pack(method: str, data: bytes) -> bytes:
    if method not in codecs.CODECS:
        raise KeyError(f"unknown codec {method!r}")
    method_id = codecs.CODECS[method][0]
    payload = codecs.encode(method, data)
    header = bytearray()
    header += MAGIC
    header.append(VERSION)
    header.append(method_id)
    header += _write_varint(len(data))
    header += zlib.crc32(data).to_bytes(4, "little")
    return bytes(header) + payload


def unpack(blob: bytes) -> bytes:
    if len(blob) < 6 or blob[:4] != MAGIC:
        raise ValueError("not a Shannon .shz stream (bad magic)")
    version = blob[4]
    if version != VERSION:
        raise ValueError(f"unsupported .shz version {version}")
    method_id = blob[5]
    try:
        orig_len, pos = _read_varint(blob, 6)
    except IndexError:
        raise ValueError("truncated .shz header")
    if orig_len > MAX_DECOMPRESSED:
        raise ValueError(f"declared size {orig_len} exceeds the {MAX_DECOMPRESSED}-byte limit")
    crc = int.from_bytes(blob[pos:pos + 4], "little")
    pos += 4
    payload = blob[pos:]
    # Any structural damage in the payload surfaces here as one of a handful of
    # low-level errors; normalize them all to a single ValueError.
    try:
        data = codecs.decode_by_id(method_id, payload, orig_len)
    except (IndexError, KeyError, OverflowError, MemoryError, RecursionError) as e:
        raise ValueError(f"corrupt .shz payload ({type(e).__name__})")
    if len(data) != orig_len:
        raise ValueError("length mismatch after decompression (corrupt stream)")
    if zlib.crc32(data) != crc:
        raise ValueError("CRC mismatch after decompression (corrupt stream)")
    return data


def method_name(blob: bytes) -> str:
    if len(blob) < 6 or blob[:4] != MAGIC:
        raise ValueError("not a Shannon .shz stream")
    return codecs.ID_TO_NAME.get(blob[5], f"<unknown {blob[5]}>")
