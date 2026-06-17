"""MSB-first bit I/O over a bytearray.

The bit order matters: we write the most-significant bit of a code first, which
is the convention canonical Huffman codes are designed around (so that reading
bits one at a time and walking down the code-length groups works).
"""
from __future__ import annotations


class BitWriter:
    """Accumulates bits MSB-first into an internal bytearray."""

    __slots__ = ("_buf", "_cur", "_nbits")

    def __init__(self) -> None:
        self._buf = bytearray()
        self._cur = 0       # partially filled current byte
        self._nbits = 0     # bits currently in _cur (0..7)

    def write_bit(self, bit: int) -> None:
        self._cur = (self._cur << 1) | (bit & 1)
        self._nbits += 1
        if self._nbits == 8:
            self._buf.append(self._cur)
            self._cur = 0
            self._nbits = 0

    def write_bits(self, value: int, count: int) -> None:
        """Write the low `count` bits of `value`, MSB first."""
        if count < 0:
            raise ValueError("count must be non-negative")
        for i in range(count - 1, -1, -1):
            self.write_bit((value >> i) & 1)

    def write_bits_lsb(self, value: int, count: int) -> None:
        """Write the low `count` bits of `value`, LSB first.

        Used for DEFLATE-style "extra bits", which are stored low-bit-first.
        """
        if count < 0:
            raise ValueError("count must be non-negative")
        for i in range(count):
            self.write_bit((value >> i) & 1)

    def bit_length(self) -> int:
        return len(self._buf) * 8 + self._nbits

    def getvalue(self) -> bytes:
        """Flush any partial byte (zero-padded on the low side) and return."""
        if self._nbits:
            pad = self._cur << (8 - self._nbits)
            return bytes(self._buf) + bytes([pad & 0xFF])
        return bytes(self._buf)


class BitReader:
    """Reads bits MSB-first from a bytes object."""

    __slots__ = ("_data", "_pos", "_cur", "_nbits")

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0       # next byte index
        self._cur = 0
        self._nbits = 0     # bits remaining in _cur

    def read_bit(self) -> int:
        if self._nbits == 0:
            if self._pos >= len(self._data):
                raise EOFError("ran out of bits")
            self._cur = self._data[self._pos]
            self._pos += 1
            self._nbits = 8
        self._nbits -= 1
        return (self._cur >> self._nbits) & 1

    def read_bits(self, count: int) -> int:
        value = 0
        for _ in range(count):
            value = (value << 1) | self.read_bit()
        return value

    def read_bits_lsb(self, count: int) -> int:
        value = 0
        for i in range(count):
            value |= self.read_bit() << i
        return value
