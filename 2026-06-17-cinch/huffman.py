"""Canonical Huffman entropy coding over a byte alphabet.

Pipeline:
  symbol frequencies
    -> length-limited code lengths via the package-merge algorithm
    -> canonical codes assigned by (length, symbol) order
    -> bit-packed stream, with a compact RLE code-length header.

A canonical code is fully determined by each symbol's *code length*, so a tree
is transmitted as just a list of lengths (most of them zero), run-length
encoded. This is the same idea gzip uses to ship its Huffman trees. The
reusable pieces (`build_codes`, `CanonicalDecoder`, code-length table I/O) are
shared with deflate.py.
"""
from __future__ import annotations

from bitio import BitReader, BitWriter
from util import read_uvarint, write_uvarint

MAX_BITS = 15  # length limit; lengths fit in 4 bits and keep codes sane


def length_limited_lengths(freqs: dict[int, int], limit: int = MAX_BITS) -> dict[int, int]:
    """Optimal code lengths with every length <= limit (package-merge).

    `freqs` maps present symbols (count > 0) to their counts.
    """
    syms = sorted(freqs, key=lambda s: (freqs[s], s))
    m = len(syms)
    if m == 0:
        return {}
    if m == 1:
        return {syms[0]: 1}
    if (1 << limit) < m:
        raise ValueError(f"limit {limit} too small for {m} symbols")

    # leaves carry (weight, [positions]) where positions index into `syms`.
    leaves = [(freqs[syms[i]], [i]) for i in range(m)]
    prev: list[tuple[int, list[int]]] = []
    for _ in range(limit):
        merged = sorted(leaves + prev, key=lambda t: t[0])
        prev = [
            (merged[k][0] + merged[k + 1][0], merged[k][1] + merged[k + 1][1])
            for k in range(0, len(merged) - 1, 2)
        ]
    lengths_pos = [0] * m
    for _weight, members in prev[: m - 1]:
        for p in members:
            lengths_pos[p] += 1
    return {syms[p]: lengths_pos[p] for p in range(m)}


def canonical_codes(lengths: dict[int, int]) -> dict[int, tuple[int, int]]:
    """Map symbol -> (code, length) using the canonical assignment."""
    if not lengths:
        return {}
    max_len = max(lengths.values())
    bl_count = [0] * (max_len + 1)
    for ln in lengths.values():
        bl_count[ln] += 1
    bl_count[0] = 0
    next_code = [0] * (max_len + 2)
    code = 0
    for bits in range(1, max_len + 1):
        code = (code + bl_count[bits - 1]) << 1
        next_code[bits] = code
    codes: dict[int, tuple[int, int]] = {}
    for sym in sorted(lengths):  # symbol order within each length
        ln = lengths[sym]
        codes[sym] = (next_code[ln], ln)
        next_code[ln] += 1
    return codes


def build_codes(freqs: dict[int, int], limit: int = MAX_BITS):
    """freqs -> (codes, lengths) for canonical Huffman."""
    lengths = length_limited_lengths(freqs, limit)
    return canonical_codes(lengths), lengths


class CanonicalDecoder:
    """Decodes one canonical-Huffman symbol at a time from a BitReader."""

    def __init__(self, lengths: dict[int, int]):
        # Note: a single-symbol tree gets a real 1-bit code (canonical length 1),
        # so we must still *consume* that bit during decode to stay in sync with
        # the encoder — the normal path below does exactly that. No shortcut.
        self.lengths = lengths
        self.max_len = max(lengths.values()) if lengths else 0
        self.syms_by_len: list[list[int]] = [[] for _ in range(self.max_len + 1)]
        for sym in sorted(lengths):
            self.syms_by_len[lengths[sym]].append(sym)
        codes = canonical_codes(lengths)
        self.first_code = [0] * (self.max_len + 1)
        for ln in range(1, self.max_len + 1):
            if self.syms_by_len[ln]:
                self.first_code[ln] = codes[self.syms_by_len[ln][0]][0]

    def decode_symbol(self, br: BitReader) -> int:
        code = 0
        length = 0
        while True:
            code = (code << 1) | br.read_bit()
            length += 1
            if length > self.max_len:
                raise ValueError("invalid Huffman code (overran max length)")
            bucket = self.syms_by_len[length]
            if bucket:
                offset = code - self.first_code[length]
                if 0 <= offset < len(bucket):
                    return bucket[offset]


def encode_code_lengths(lengths_arr: list[int]) -> bytes:
    """RLE a code-length array (values 0..15) of any alphabet size.

    Emits varint(npairs) then (value_byte, varint run) pairs.
    """
    out = bytearray()
    n = len(lengths_arr)
    pairs: list[tuple[int, int]] = []
    i = 0
    while i < n:
        v = lengths_arr[i]
        j = i
        while j < n and lengths_arr[j] == v:
            j += 1
        pairs.append((v, j - i))
        i = j
    write_uvarint(out, len(pairs))
    for v, run in pairs:
        out.append(v)
        write_uvarint(out, run)
    return bytes(out)


def decode_code_lengths(data: bytes, pos: int, n: int) -> tuple[list[int], int]:
    npairs, pos = read_uvarint(data, pos)
    lengths_arr = [0] * n
    idx = 0
    for _ in range(npairs):
        v = data[pos]
        pos += 1
        run, pos = read_uvarint(data, pos)
        for _k in range(run):
            if idx >= n:
                raise ValueError("length table overflow")
            lengths_arr[idx] = v
            idx += 1
    if idx != n:
        raise ValueError("length table did not cover the alphabet")
    return lengths_arr, pos


def encode(data: bytes) -> bytes:
    """Self-contained Huffman blob for arbitrary bytes."""
    out = bytearray()
    write_uvarint(out, len(data))
    if not data:
        return bytes(out)

    freqs: dict[int, int] = {}
    for b in data:
        freqs[b] = freqs.get(b, 0) + 1

    codes, lengths = build_codes(freqs)
    lengths_arr = [lengths.get(s, 0) for s in range(256)]
    out += encode_code_lengths(lengths_arr)

    bw = BitWriter()
    for b in data:
        code, ln = codes[b]
        bw.write_bits(code, ln)
    payload = bw.getvalue()
    write_uvarint(out, len(payload))
    out += payload
    return bytes(out)


def decode(blob: bytes) -> bytes:
    n, pos = read_uvarint(blob, 0)
    if n == 0:
        return b""
    lengths_arr, pos = decode_code_lengths(blob, pos, 256)
    lengths = {s: lengths_arr[s] for s in range(256) if lengths_arr[s] > 0}

    payload_len, pos = read_uvarint(blob, pos)
    payload = blob[pos:pos + payload_len]

    decoder = CanonicalDecoder(lengths)
    br = BitReader(payload)
    out = bytearray()
    for _ in range(n):
        out.append(decoder.decode_symbol(br))
    return bytes(out)
