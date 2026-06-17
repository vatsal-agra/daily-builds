"""DEFLATE-lite: LZ77 dictionary matching composed with Huffman entropy coding.

This is the heart of the toolkit and mirrors how real DEFLATE (RFC 1951) works:

  * LZ77 produces literal / (length, distance) tokens.
  * Lengths 3..258 are mapped to the 29 DEFLATE *length codes* (symbols
    257..285) plus a few "extra bits"; literals stay as symbols 0..255 and
    symbol 256 is end-of-block. Together that is one alphabet (the
    "litlen" alphabet) coded by one canonical Huffman tree.
  * Distances 1..32768 map to the 30 DEFLATE *distance codes* plus extra bits,
    coded by a second Huffman tree.

We compute optimal (per-file "dynamic") Huffman trees for both alphabets,
serialize them as code-length tables, then emit the bitstream. Extra bits are
written LSB-first, matching the DEFLATE convention.
"""
from __future__ import annotations

import lz77
from bitio import BitReader, BitWriter
from huffman import (CanonicalDecoder, build_codes, decode_code_lengths,
                     encode_code_lengths)
from util import read_uvarint, write_uvarint

# --- DEFLATE length code tables (symbols 257..285) ------------------------
_LENGTH_BASE = [3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35,
                43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258]
_LENGTH_EXTRA = [0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3,
                 4, 4, 4, 4, 5, 5, 5, 5, 0]

# --- DEFLATE distance code tables (symbols 0..29) -------------------------
_DIST_BASE = [1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257,
              385, 513, 769, 1025, 1537, 2049, 3073, 4097, 6145, 8193, 12289,
              16385, 24577]
_DIST_EXTRA = [0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8,
               9, 9, 10, 10, 11, 11, 12, 12, 13, 13]

EOB = 256                      # end-of-block symbol
LITLEN_ALPHABET = 286          # 0..255 literals, 256 EOB, 257..285 lengths
DIST_ALPHABET = 30

# Reverse lookups built once.
_LEN_TO_CODE: list[int] = [0] * (lz77.MAX_MATCH + 1)   # length -> index 0..28
for _ci in range(len(_LENGTH_BASE)):
    _hi = _LENGTH_BASE[_ci + 1] - 1 if _ci + 1 < len(_LENGTH_BASE) else lz77.MAX_MATCH
    for _l in range(_LENGTH_BASE[_ci], _hi + 1):
        _LEN_TO_CODE[_l] = _ci

_DIST_TO_CODE: list[int] = [0] * (lz77.WINDOW + 1)     # distance -> index 0..29
for _ci in range(len(_DIST_BASE)):
    _hi = _DIST_BASE[_ci + 1] - 1 if _ci + 1 < len(_DIST_BASE) else lz77.WINDOW
    for _d in range(_DIST_BASE[_ci], _hi + 1):
        _DIST_TO_CODE[_d] = _ci


def _len_code(length: int) -> int:
    return 257 + _LEN_TO_CODE[length]


def _dist_code(dist: int) -> int:
    return _DIST_TO_CODE[dist]


def encode(data: bytes, max_chain: int = 128) -> bytes:
    out = bytearray()
    write_uvarint(out, len(data))
    if not data:
        return bytes(out)

    tokens = lz77.tokenize(data, max_chain=max_chain)

    litlen_freq: dict[int, int] = {EOB: 1}
    dist_freq: dict[int, int] = {}
    for tok in tokens:
        if isinstance(tok, int):
            litlen_freq[tok] = litlen_freq.get(tok, 0) + 1
        else:
            length, dist = tok
            sym = _len_code(length)
            litlen_freq[sym] = litlen_freq.get(sym, 0) + 1
            dsym = _dist_code(dist)
            dist_freq[dsym] = dist_freq.get(dsym, 0) + 1
    if not dist_freq:
        dist_freq[0] = 1  # phantom symbol so the tree is well-formed (never used)

    litlen_codes, litlen_lengths = build_codes(litlen_freq)
    dist_codes, dist_lengths = build_codes(dist_freq)

    out += encode_code_lengths([litlen_lengths.get(s, 0) for s in range(LITLEN_ALPHABET)])
    out += encode_code_lengths([dist_lengths.get(s, 0) for s in range(DIST_ALPHABET)])

    bw = BitWriter()
    for tok in tokens:
        if isinstance(tok, int):
            code, ln = litlen_codes[tok]
            bw.write_bits(code, ln)
        else:
            length, dist = tok
            lsym = _len_code(length)
            code, ln = litlen_codes[lsym]
            bw.write_bits(code, ln)
            lci = lsym - 257
            if _LENGTH_EXTRA[lci]:
                bw.write_bits_lsb(length - _LENGTH_BASE[lci], _LENGTH_EXTRA[lci])
            dsym = _dist_code(dist)
            dcode, dln = dist_codes[dsym]
            bw.write_bits(dcode, dln)
            if _DIST_EXTRA[dsym]:
                bw.write_bits_lsb(dist - _DIST_BASE[dsym], _DIST_EXTRA[dsym])
    eob_code, eob_ln = litlen_codes[EOB]
    bw.write_bits(eob_code, eob_ln)

    payload = bw.getvalue()
    write_uvarint(out, len(payload))
    out += payload
    return bytes(out)


def decode(blob: bytes) -> bytes:
    n, pos = read_uvarint(blob, 0)
    if n == 0:
        return b""
    litlen_arr, pos = decode_code_lengths(blob, pos, LITLEN_ALPHABET)
    dist_arr, pos = decode_code_lengths(blob, pos, DIST_ALPHABET)
    litlen_lengths = {s: litlen_arr[s] for s in range(LITLEN_ALPHABET) if litlen_arr[s] > 0}
    dist_lengths = {s: dist_arr[s] for s in range(DIST_ALPHABET) if dist_arr[s] > 0}

    payload_len, pos = read_uvarint(blob, pos)
    payload = blob[pos:pos + payload_len]

    litlen_dec = CanonicalDecoder(litlen_lengths)
    dist_dec = CanonicalDecoder(dist_lengths)
    br = BitReader(payload)
    out = bytearray()
    while True:
        sym = litlen_dec.decode_symbol(br)
        if sym == EOB:
            break
        if sym < 256:
            out.append(sym)
            continue
        lci = sym - 257
        length = _LENGTH_BASE[lci]
        if _LENGTH_EXTRA[lci]:
            length += br.read_bits_lsb(_LENGTH_EXTRA[lci])
        dsym = dist_dec.decode_symbol(br)
        dist = _DIST_BASE[dsym]
        if _DIST_EXTRA[dsym]:
            dist += br.read_bits_lsb(_DIST_EXTRA[dsym])
        start = len(out) - dist
        if start < 0:
            raise ValueError("corrupt stream: distance before start")
        for k in range(length):
            out.append(out[start + k])
    if len(out) != n:
        raise ValueError(f"decoded length {len(out)} != expected {n}")
    return bytes(out)
