"""Canonical Huffman coding over an integer-symbol alphabet.

The coder is generic over symbols (plain ints), so it serves both as a byte
entropy coder and as the entropy backend for the LZ77 token stream. Codes are
*canonical*: only the per-symbol bit lengths are stored, and both sides derive
identical codewords from them, which keeps the table small and the decoder
table-free.
"""
from __future__ import annotations

import heapq
from collections import Counter
from typing import Dict, Iterable, List, Tuple

from .bitio import BitReader, BitWriter


def code_lengths_from_freqs(freqs: Dict[int, int]) -> Dict[int, int]:
    """Return optimal per-symbol code lengths via Huffman tree construction.

    A lone symbol is given length 1 (a 0-length code is unrepresentable), and an
    empty frequency map yields an empty table.
    """
    syms = [s for s, f in freqs.items() if f > 0]
    if not syms:
        return {}
    if len(syms) == 1:
        return {syms[0]: 1}

    # Heap of (weight, tie, node). Nodes are either an int leaf-symbol or a
    # (left, right) tuple. The tie counter keeps ordering deterministic.
    heap: List[Tuple[int, int, object]] = []
    tie = 0
    for s in syms:
        heapq.heappush(heap, (freqs[s], tie, s))
        tie += 1
    while len(heap) > 1:
        w1, _, n1 = heapq.heappop(heap)
        w2, _, n2 = heapq.heappop(heap)
        heapq.heappush(heap, (w1 + w2, tie, (n1, n2)))
        tie += 1
    root = heap[0][2]

    lengths: Dict[int, int] = {}

    def walk(node, depth):
        if isinstance(node, tuple):
            walk(node[0], depth + 1)
            walk(node[1], depth + 1)
        else:
            lengths[node] = depth

    walk(root, 0)
    return lengths


def canonical_codes(lengths: Dict[int, int]) -> Dict[int, Tuple[int, int]]:
    """Assign canonical codewords given code lengths.

    Returns ``{symbol: (code, length)}``. Symbols are ordered by (length, symbol);
    codes start at 0 and increment, shifting left when the length increases.
    """
    if not lengths:
        return {}
    items = sorted(lengths.items(), key=lambda kv: (kv[1], kv[0]))
    codes: Dict[int, Tuple[int, int]] = {}
    code = 0
    prev_len = items[0][1]
    for sym, length in items:
        code <<= (length - prev_len)
        codes[sym] = (code, length)
        code += 1
        prev_len = length
    return codes


class HuffmanCode:
    """A built canonical Huffman code with serialize / encode / decode."""

    def __init__(self, lengths: Dict[int, int]) -> None:
        self.lengths = dict(lengths)
        self.enc = canonical_codes(self.lengths)
        self._build_decoder()

    @classmethod
    def from_data(cls, symbols: Iterable[int]) -> "HuffmanCode":
        return cls(code_lengths_from_freqs(Counter(symbols)))

    def _build_decoder(self) -> None:
        # Group symbols by length, sorted, to derive canonical first-codes.
        self._by_len: Dict[int, List[int]] = {}
        for sym, length in self.lengths.items():
            self._by_len.setdefault(length, []).append(sym)
        for length in self._by_len:
            self._by_len[length].sort()
        self._maxlen = max(self.lengths.values()) if self.lengths else 0
        # first_code[L] and the running symbol index offset.
        self._first_code: Dict[int, int] = {}
        code = 0
        for length in range(1, self._maxlen + 1):
            self._first_code[length] = code
            code = (code + len(self._by_len.get(length, []))) << 1

    # -- table serialization -------------------------------------------------
    def write_table(self, w: BitWriter) -> None:
        present = sorted(self.lengths.items())
        w.write_varint(len(present))
        for sym, length in present:
            w.write_varint(sym)
            w.write_varint(length)

    @classmethod
    def read_table(cls, r: BitReader) -> "HuffmanCode":
        n = r.read_varint()
        lengths: Dict[int, int] = {}
        for _ in range(n):
            sym = r.read_varint()
            length = r.read_varint()
            lengths[sym] = length
        return cls(lengths)

    # -- coding --------------------------------------------------------------
    def encode(self, symbols: Iterable[int], w: BitWriter) -> None:
        enc = self.enc
        for s in symbols:
            code, length = enc[s]
            w.write_bits(code, length)

    def decode(self, r: BitReader, count: int) -> List[int]:
        """Decode exactly ``count`` symbols."""
        if count == 0:
            return []
        # Special-case a single-symbol alphabet (code length 1, one symbol).
        out: List[int] = []
        by_len = self._by_len
        first_code = self._first_code
        for _ in range(count):
            code = 0
            length = 0
            while True:
                code = (code << 1) | r.read_bit()
                length += 1
                bucket = by_len.get(length)
                if bucket:
                    offset = code - first_code[length]
                    if 0 <= offset < len(bucket):
                        out.append(bucket[offset])
                        break
                if length > self._maxlen:
                    raise ValueError("corrupt Huffman stream: no code matched")
        return out


# -- convenience byte-level codec (used directly by the `huffman` codec) ------

def compress_bytes(data: bytes, w: BitWriter) -> None:
    code = HuffmanCode.from_data(data)
    code.write_table(w)
    code.encode(data, w)


def decompress_bytes(r: BitReader, count: int) -> bytes:
    code = HuffmanCode.read_table(r)
    return bytes(code.decode(r, count))
