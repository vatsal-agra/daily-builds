"""LZSS sliding-window dictionary coder with a Huffman backend ("deflate-lite").

Matches are found with a 3-byte hash chain over the window. The token stream is
split into three Huffman-coded streams plus raw "extra" bits, in the spirit of
DEFLATE but with a self-describing gamma-style integer code so lengths and
distances need no fixed table:

* ``litlen``  — symbols 0..255 are literals, 256 marks "a match follows".
* ``lencls``  — Huffman-coded *bit length* of ``(match_len - MIN_MATCH)``;
                the remaining low bits follow raw.
* ``distcls`` — Huffman-coded bit length of ``(distance - 1)``; low bits raw.
"""
from __future__ import annotations

from collections import Counter
from typing import List, Tuple

from .bitio import BitReader, BitWriter
from .huffman import HuffmanCode

WINDOW = 1 << 15        # 32 KiB sliding window
MIN_MATCH = 3
MAX_MATCH = 1 << 13     # cap match length so the finder stays fast
MAX_CHAIN = 96          # hash-chain search depth
MATCH_MARKER = 256

Token = Tuple


def tokenize(data: bytes) -> List[Token]:
    """Greedy LZSS parse into ('l', byte) and ('m', length, distance) tokens."""
    n = len(data)
    tokens: List[Token] = []
    head = {}            # 3-byte key -> most recent position
    prev = [-1] * n      # position -> previous position with same 3-byte key
    i = 0

    def insert(pos: int) -> None:
        if pos + 3 <= n:
            key = data[pos:pos + 3]
            prev[pos] = head.get(key, -1)
            head[key] = pos

    while i < n:
        best_len = 0
        best_dist = 0
        if i + MIN_MATCH <= n:
            j = head.get(data[i:i + 3], -1)
            chain = 0
            maxl = min(MAX_MATCH, n - i)
            while j >= 0 and (i - j) <= WINDOW and chain < MAX_CHAIN:
                if data[j + best_len] == data[i + best_len]:  # quick reject
                    l = 0
                    while l < maxl and data[j + l] == data[i + l]:
                        l += 1
                    if l > best_len:
                        best_len = l
                        best_dist = i - j
                        if l >= maxl:
                            break
                j = prev[j]
                chain += 1

        if best_len >= MIN_MATCH:
            tokens.append(("m", best_len, best_dist))
            end = i + best_len
            while i < end:
                insert(i)
                i += 1
        else:
            tokens.append(("l", data[i]))
            insert(i)
            i += 1
    return tokens


def _encode_int(x: int, code: HuffmanCode, w: BitWriter) -> None:
    nb = x.bit_length()
    c, length = code.enc[nb]
    w.write_bits(c, length)
    if nb > 1:
        w.write_bits(x & ((1 << (nb - 1)) - 1), nb - 1)


def _decode_int(code: HuffmanCode, r: BitReader) -> int:
    nb = code.decode(r, 1)[0]
    if nb == 0:
        return 0
    if nb == 1:
        return 1
    return (1 << (nb - 1)) | r.read_bits(nb - 1)


def compress(data: bytes, w: BitWriter) -> None:
    tokens = tokenize(data)
    litlen_freq: Counter = Counter()
    lencls_freq: Counter = Counter()
    distcls_freq: Counter = Counter()
    for t in tokens:
        if t[0] == "l":
            litlen_freq[t[1]] += 1
        else:
            litlen_freq[MATCH_MARKER] += 1
            lencls_freq[(t[1] - MIN_MATCH).bit_length()] += 1
            distcls_freq[(t[2] - 1).bit_length()] += 1

    litlen = HuffmanCode(_lengths(litlen_freq))
    lencls = HuffmanCode(_lengths(lencls_freq))
    distcls = HuffmanCode(_lengths(distcls_freq))
    litlen.write_table(w)
    lencls.write_table(w)
    distcls.write_table(w)

    for t in tokens:
        if t[0] == "l":
            c, length = litlen.enc[t[1]]
            w.write_bits(c, length)
        else:
            c, length = litlen.enc[MATCH_MARKER]
            w.write_bits(c, length)
            _encode_int(t[1] - MIN_MATCH, lencls, w)
            _encode_int(t[2] - 1, distcls, w)


def _lengths(freq: Counter):
    from .huffman import code_lengths_from_freqs
    return code_lengths_from_freqs(freq)


def decompress(r: BitReader, count: int) -> bytes:
    litlen = HuffmanCode.read_table(r)
    lencls = HuffmanCode.read_table(r)
    distcls = HuffmanCode.read_table(r)
    out = bytearray()
    while len(out) < count:
        sym = litlen.decode(r, 1)[0]
        if sym != MATCH_MARKER:
            out.append(sym)
        else:
            length = _decode_int(lencls, r) + MIN_MATCH
            dist = _decode_int(distcls, r) + 1
            start = len(out) - dist
            if start < 0:
                raise ValueError("corrupt LZ stream: distance before start")
            for k in range(length):
                out.append(out[start + k])
    return bytes(out)
