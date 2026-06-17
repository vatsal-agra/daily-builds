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
    orig_len, pos = _read_varint(blob, 6)
    crc = int.from_bytes(blob[pos:pos + 4], "little")
    pos += 4
    payload = blob[pos:]
    data = codecs.decode_by_id(method_id, payload, orig_len)
    if len(data) != orig_len:
        raise ValueError("length mismatch after decompression (corrupt stream)")
    if zlib.crc32(data) != crc:
        raise ValueError("CRC mismatch after decompression (corrupt stream)")
    return data


def method_name(blob: bytes) -> str:
    if len(blob) < 6 or blob[:4] != MAGIC:
        raise ValueError("not a Shannon .shz stream")
    return codecs.ID_TO_NAME.get(blob[5], f"<unknown {blob[5]}>")
