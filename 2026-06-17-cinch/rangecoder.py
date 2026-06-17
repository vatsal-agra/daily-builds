"""Adaptive arithmetic (range) coding.

A byte-oriented carryless range coder (the Subbotin construction) driven by an
adaptive frequency model. Unlike Huffman, which must spend a whole number of
bits per symbol, a range coder can spend fractional bits, so it tracks the true
entropy of the source far more closely — it routinely beats Huffman on text.

Two models are provided:
  * order-0: one adaptive frequency table over all bytes.
  * order-1: a separate adaptive table per *previous* byte (context), which
    captures local correlations (e.g. "u" usually follows "q").

A dedicated EOF symbol (256) terminates the stream, so no length field is
needed inside the payload.
"""
from __future__ import annotations

TOP = 1 << 24
BOT = 1 << 16
MASK = 0xFFFFFFFF
EOF = 256
NSYM = 257


class _Encoder:
    def __init__(self) -> None:
        self.low = 0
        self.range = MASK
        self.out = bytearray()

    def _renorm(self) -> None:
        while True:
            if ((self.low ^ ((self.low + self.range) & MASK)) & MASK) < TOP:
                pass
            elif self.range < BOT:
                self.range = (-self.low) & (BOT - 1)
            else:
                break
            self.out.append((self.low >> 24) & 0xFF)
            self.low = (self.low << 8) & MASK
            self.range = (self.range << 8) & MASK

    def encode(self, cum: int, freq: int, tot: int) -> None:
        self.range //= tot
        self.low = (self.low + cum * self.range) & MASK
        self.range = (self.range * freq) & MASK
        self._renorm()

    def finish(self) -> bytes:
        for _ in range(4):
            self.out.append((self.low >> 24) & 0xFF)
            self.low = (self.low << 8) & MASK
        return bytes(self.out)


class _Decoder:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0
        self.low = 0
        self.range = MASK
        self.code = 0
        for _ in range(4):
            self.code = ((self.code << 8) | self._byte()) & MASK

    def _byte(self) -> int:
        b = self.data[self.pos] if self.pos < len(self.data) else 0
        self.pos += 1
        return b

    def get_freq(self, tot: int) -> int:
        self.range //= tot
        value = ((self.code - self.low) & MASK) // self.range
        return tot - 1 if value >= tot else value

    def decode(self, cum: int, freq: int, _tot: int) -> None:
        self.low = (self.low + cum * self.range) & MASK
        self.range = (self.range * freq) & MASK
        while True:
            if ((self.low ^ ((self.low + self.range) & MASK)) & MASK) < TOP:
                pass
            elif self.range < BOT:
                self.range = (-self.low) & (BOT - 1)
            else:
                break
            self.code = ((self.code << 8) | self._byte()) & MASK
            self.low = (self.low << 8) & MASK
            self.range = (self.range << 8) & MASK


class _Model:
    """Adaptive order-0 frequency table with periodic rescaling."""

    __slots__ = ("freq", "tot")
    INC = 24
    LIMIT = BOT - 64  # keep total strictly below BOT for the range coder

    def __init__(self) -> None:
        self.freq = [1] * NSYM
        self.tot = NSYM

    def cum_of(self, sym: int) -> tuple[int, int, int]:
        f = self.freq
        cum = 0
        for s in range(sym):
            cum += f[s]
        return cum, f[sym], self.tot

    def find(self, value: int) -> tuple[int, int, int]:
        f = self.freq
        cum = 0
        for s in range(NSYM):
            fs = f[s]
            if cum + fs > value:
                return s, cum, fs
            cum += fs
        # Should not happen; guard against rounding at the tail.
        return NSYM - 1, self.tot - f[NSYM - 1], f[NSYM - 1]

    def update(self, sym: int) -> None:
        self.freq[sym] += self.INC
        self.tot += self.INC
        if self.tot >= self.LIMIT:
            self.tot = 0
            for s in range(NSYM):
                self.freq[s] = (self.freq[s] + 1) >> 1
                self.tot += self.freq[s]


def encode_order0(data: bytes) -> bytes:
    enc = _Encoder()
    model = _Model()
    for b in data:
        cum, freq, tot = model.cum_of(b)
        enc.encode(cum, freq, tot)
        model.update(b)
    cum, freq, tot = model.cum_of(EOF)
    enc.encode(cum, freq, tot)
    return enc.finish()


def decode_order0(blob: bytes, limit: int | None = None) -> bytes:
    dec = _Decoder(blob)
    model = _Model()
    out = bytearray()
    while True:
        value = dec.get_freq(model.tot)
        sym, cum, freq = model.find(value)
        dec.decode(cum, freq, model.tot)
        if sym == EOF:
            break
        out.append(sym)
        # Corrupt data may never emit EOF; bound the output so we fail instead
        # of looping forever over the decoder's infinite zero padding.
        if limit is not None and len(out) > limit:
            raise ValueError("range stream exceeded expected length")
        model.update(sym)
    return bytes(out)


def encode_order1(data: bytes) -> bytes:
    enc = _Encoder()
    models: dict[int, _Model] = {}
    ctx = 256  # start-of-stream context
    for b in data:
        model = models.get(ctx)
        if model is None:
            model = models[ctx] = _Model()
        cum, freq, tot = model.cum_of(b)
        enc.encode(cum, freq, tot)
        model.update(b)
        ctx = b
    model = models.get(ctx) or _Model()
    models.setdefault(ctx, model)
    cum, freq, tot = model.cum_of(EOF)
    enc.encode(cum, freq, tot)
    return enc.finish()


def decode_order1(blob: bytes, limit: int | None = None) -> bytes:
    dec = _Decoder(blob)
    models: dict[int, _Model] = {}
    out = bytearray()
    ctx = 256
    while True:
        model = models.get(ctx)
        if model is None:
            model = models[ctx] = _Model()
        value = dec.get_freq(model.tot)
        sym, cum, freq = model.find(value)
        dec.decode(cum, freq, model.tot)
        if sym == EOF:
            break
        out.append(sym)
        if limit is not None and len(out) > limit:
            raise ValueError("range stream exceeded expected length")
        model.update(sym)
        ctx = sym
    return bytes(out)
