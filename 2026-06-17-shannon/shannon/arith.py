"""Arithmetic coding (Witten-Neal-Cleary) with adaptive frequency models.

This is the entropy-coding centerpiece: unlike Huffman it is not limited to an
integer number of bits per symbol, so with a good model it approaches the true
entropy. The exact symbol count is carried by the container (``orig_len``), so we
need no end-of-stream symbol — the decoder simply asks for N symbols.

Two models are provided:
* :class:`Order0Model` — a single adaptive frequency table.
* :class:`Order1Model` — one table per previous byte (context = last symbol).

Both use a Fenwick (binary-indexed) tree so cumulative-frequency lookup and the
inverse "find symbol owning this cumulative count" both run in O(log alphabet).
"""
from __future__ import annotations

from typing import List, Tuple

from .bitio import BitReader, BitWriter

PRECISION = 32
TOP = (1 << PRECISION) - 1
HALF = 1 << (PRECISION - 1)
QUARTER = 1 << (PRECISION - 2)
THREE_QUARTER = 3 * QUARTER

MAX_TOTAL = 1 << 16   # keep well under 2**(PRECISION-2) for exact arithmetic
INCREMENT = 24        # how much a symbol's count grows after it is seen


class _Fenwick:
    """Adaptive frequency table over symbols 0..size-1 with O(log n) ops."""

    __slots__ = ("size", "freq", "tree", "total")

    def __init__(self, size: int) -> None:
        self.size = size
        self.freq = [1] * size           # raw counts (1 = Laplace smoothing)
        self.tree = [0] * (size + 1)
        self.total = 0
        for i in range(size):
            self._add(i, 1)
        self.total = size

    def _add(self, idx: int, delta: int) -> None:
        i = idx + 1
        while i <= self.size:
            self.tree[i] += delta
            i += i & (-i)

    def prefix(self, idx: int) -> int:
        """Sum of freq[0..idx-1]."""
        s = 0
        i = idx
        while i > 0:
            s += self.tree[i]
            i -= i & (-i)
        return s

    def cum_range(self, sym: int) -> Tuple[int, int]:
        low = self.prefix(sym)
        return low, low + self.freq[sym]

    def find(self, cum: int) -> int:
        """Smallest symbol whose cumulative range contains ``cum``."""
        idx = 0
        bit_mask = 1 << (self.size.bit_length())
        remaining = cum
        while bit_mask:
            next_idx = idx + bit_mask
            if next_idx <= self.size and self.tree[next_idx] <= remaining:
                idx = next_idx
                remaining -= self.tree[next_idx]
            bit_mask >>= 1
        return idx  # idx is the symbol (0-based)

    def update(self, sym: int) -> None:
        self._add(sym, INCREMENT)
        self.freq[sym] += INCREMENT
        self.total += INCREMENT
        if self.total >= MAX_TOTAL:
            self._rescale()

    def _rescale(self) -> None:
        self.tree = [0] * (self.size + 1)
        self.total = 0
        for i in range(self.size):
            self.freq[i] = (self.freq[i] + 1) >> 1   # halve, keep >= 1
            self._add(i, self.freq[i])
            self.total += self.freq[i]


class Order0Model:
    def __init__(self, alphabet: int = 256) -> None:
        self.t = _Fenwick(alphabet)

    def cum(self, sym: int):
        low, high = self.t.cum_range(sym)
        return low, high, self.t.total

    def total(self) -> int:
        return self.t.total

    def find(self, value: int):
        sym = self.t.find(value)
        low, high = self.t.cum_range(sym)
        return sym, low, high, self.t.total

    def update(self, sym: int) -> None:
        self.t.update(sym)


class Order1Model:
    """Context model keyed on the previous symbol (order-1)."""

    def __init__(self, alphabet: int = 256) -> None:
        self.alphabet = alphabet
        self.ctx: List[_Fenwick] = [None] * alphabet  # lazy
        self.prev = 0

    def _table(self, context: int) -> _Fenwick:
        t = self.ctx[context]
        if t is None:
            t = _Fenwick(self.alphabet)
            self.ctx[context] = t
        return t

    def cum(self, sym: int):
        t = self._table(self.prev)
        low, high = t.cum_range(sym)
        return low, high, t.total

    def total(self) -> int:
        return self._table(self.prev).total

    def find(self, value: int):
        t = self._table(self.prev)
        sym = t.find(value)
        low, high = t.cum_range(sym)
        return sym, low, high, t.total

    def update(self, sym: int) -> None:
        self._table(self.prev).update(sym)
        self.prev = sym


def encode(data: bytes, w: BitWriter, model) -> None:
    low = 0
    high = TOP
    pending = 0

    def emit(bit: int) -> None:
        nonlocal pending
        w.write_bit(bit)
        while pending:
            w.write_bit(bit ^ 1)
            pending -= 1

    for sym in data:
        cum_low, cum_high, total = model.cum(sym)
        rng = high - low + 1
        high = low + (rng * cum_high) // total - 1
        low = low + (rng * cum_low) // total
        model.update(sym)
        while True:
            if high < HALF:
                emit(0)
            elif low >= HALF:
                emit(1)
                low -= HALF
                high -= HALF
            elif low >= QUARTER and high < THREE_QUARTER:
                pending += 1
                low -= QUARTER
                high -= QUARTER
            else:
                break
            low <<= 1
            high = (high << 1) + 1

    # flush: one more bit (plus pending) disambiguates the final interval.
    pending += 1
    if low < QUARTER:
        emit(0)
    else:
        emit(1)


def decode(r: BitReader, count: int, model) -> bytes:
    if count == 0:
        return b""
    low = 0
    high = TOP
    value = r.read_bits(PRECISION)
    out = bytearray()
    for _ in range(count):
        rng = high - low + 1
        total = model.total()
        cum = ((value - low + 1) * total - 1) // rng
        sym, cum_low, cum_high, total = model.find(cum)
        high = low + (rng * cum_high) // total - 1
        low = low + (rng * cum_low) // total
        model.update(sym)
        out.append(sym)
        while True:
            if high < HALF:
                pass
            elif low >= HALF:
                value -= HALF
                low -= HALF
                high -= HALF
            elif low >= QUARTER and high < THREE_QUARTER:
                value -= QUARTER
                low -= QUARTER
                high -= QUARTER
            else:
                break
            low <<= 1
            high = (high << 1) + 1
            value = (value << 1) + r.read_bit()
    return bytes(out)
