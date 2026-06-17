"""End-to-end named codecs composed from the primitive coders and transforms.

Each codec maps ``bytes -> payload bytes`` and back. The :mod:`container` module
wraps a payload with a magic header, the method id, the original length, and a
CRC of the original data so decompression is self-verifying.
"""
from __future__ import annotations

from typing import Callable, Dict, Tuple

from . import arith, huffman, lz77
from . import transforms as T
from .bitio import BitReader, BitWriter

BWT_BLOCK = 1 << 15  # 32 KiB BWT blocks (bounds suffix-array cost)


# -- store (no compression) ---------------------------------------------------

def _store_encode(data: bytes) -> bytes:
    return data


def _store_decode(payload: bytes, orig_len: int) -> bytes:
    return payload


# -- huffman ------------------------------------------------------------------

def _huffman_encode(data: bytes) -> bytes:
    w = BitWriter()
    huffman.compress_bytes(data, w)
    return w.getvalue()


def _huffman_decode(payload: bytes, orig_len: int) -> bytes:
    return huffman.decompress_bytes(BitReader(payload), orig_len)


# -- arithmetic ---------------------------------------------------------------

def _arith0_encode(data: bytes) -> bytes:
    w = BitWriter()
    arith.encode(data, w, arith.Order0Model())
    return w.getvalue()


def _arith0_decode(payload: bytes, orig_len: int) -> bytes:
    return arith.decode(BitReader(payload), orig_len, arith.Order0Model())


def _arith1_encode(data: bytes) -> bytes:
    w = BitWriter()
    arith.encode(data, w, arith.Order1Model())
    return w.getvalue()


def _arith1_decode(payload: bytes, orig_len: int) -> bytes:
    return arith.decode(BitReader(payload), orig_len, arith.Order1Model())


# -- lz77 (deflate-lite) ------------------------------------------------------

def _lz_encode(data: bytes) -> bytes:
    w = BitWriter()
    lz77.compress(data, w)
    return w.getvalue()


def _lz_decode(payload: bytes, orig_len: int) -> bytes:
    return lz77.decompress(BitReader(payload), orig_len)


# -- bwt (bzip-lite): BWT -> MTF (per block) -> RLE -> Huffman ----------------

def _bwt_encode(data: bytes) -> bytes:
    n = len(data)
    w = BitWriter()
    if n == 0:
        w.write_varint(0)   # nblocks
        w.write_varint(0)   # huff symbol count
        huffman.HuffmanCode({}).write_table(w)
        return w.getvalue()

    nblocks = (n + BWT_BLOCK - 1) // BWT_BLOCK
    sent_positions = []
    transformed = bytearray()
    for b in range(nblocks):
        block = data[b * BWT_BLOCK:(b + 1) * BWT_BLOCK]
        bw, sent = T.bwt_encode(block)
        sent_positions.append(sent)
        transformed.extend(T.mtf_encode(bw))

    rle = T.rle_encode(bytes(transformed))

    w.write_varint(nblocks)
    for sp in sent_positions:
        w.write_varint(sp)
    w.write_varint(len(rle))
    huffman.compress_bytes(rle, w)
    return w.getvalue()


def _bwt_decode(payload: bytes, orig_len: int) -> bytes:
    r = BitReader(payload)
    nblocks = r.read_varint()
    sent_positions = [r.read_varint() for _ in range(nblocks)]
    huff_count = r.read_varint()
    rle = huffman.decompress_bytes(r, huff_count)
    transformed = T.rle_decode(rle)

    out = bytearray()
    pos = 0
    for b in range(nblocks):
        block_len = min(BWT_BLOCK, orig_len - b * BWT_BLOCK)
        chunk = transformed[pos:pos + block_len]
        pos += block_len
        bw = T.mtf_decode(chunk)
        out.extend(T.bwt_decode(bw, sent_positions[b]))
    return bytes(out)


# -- registry -----------------------------------------------------------------

EncodeFn = Callable[[bytes], bytes]
DecodeFn = Callable[[bytes, int], bytes]

# name -> (method_id, encode, decode)
CODECS: Dict[str, Tuple[int, EncodeFn, DecodeFn]] = {
    "store": (0, _store_encode, _store_decode),
    "huffman": (1, _huffman_encode, _huffman_decode),
    "arith0": (2, _arith0_encode, _arith0_decode),
    "arith1": (3, _arith1_encode, _arith1_decode),
    "lz77": (4, _lz_encode, _lz_decode),
    "bwt": (5, _bwt_encode, _bwt_decode),
}

ID_TO_NAME = {mid: name for name, (mid, _, _) in CODECS.items()}

# Codecs offered when auto-selecting the best (store is the safety net).
ALL_NAMES = ["store", "huffman", "arith0", "arith1", "lz77", "bwt"]


def encode(name: str, data: bytes) -> bytes:
    if name not in CODECS:
        raise KeyError(f"unknown codec {name!r}")
    return CODECS[name][1](data)


def decode_by_id(method_id: int, payload: bytes, orig_len: int) -> bytes:
    if method_id not in ID_TO_NAME:
        raise ValueError(f"unknown method id {method_id}")
    return CODECS[ID_TO_NAME[method_id]][2](payload, orig_len)
