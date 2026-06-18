"""MSB-first bit-level I/O over byte buffers.

A compressor lives or dies on getting bit packing exactly right, so this is the
foundation every other module builds on. Bits are packed most-significant-first
within each byte, which matches how Huffman/arithmetic code tables are usually
written and read.
"""
from __future__ import annotations


class BitWriter:
    """Accumulates bits MSB-first into a bytearray.

    The final byte is zero-padded; callers that need to know the exact bit count
    should store it out-of-band (the container does this via ``orig_len``).
    """

    __slots__ = ("_buf", "_cur", "_nbits", "_total")

    def __init__(self) -> None:
        self._buf = bytearray()
        self._cur = 0          # partially filled current byte
        self._nbits = 0        # bits currently in _cur (0..7)
        self._total = 0        # total bits written

    def write_bit(self, bit: int) -> None:
        self._cur = (self._cur << 1) | (bit & 1)
        self._nbits += 1
        self._total += 1
        if self._nbits == 8:
            self._buf.append(self._cur)
            self._cur = 0
            self._nbits = 0

    def write_bits(self, value: int, count: int) -> None:
        """Write the low ``count`` bits of ``value``, MSB-first."""
        if count < 0:
            raise ValueError("count must be non-negative")
        for i in range(count - 1, -1, -1):
            self.write_bit((value >> i) & 1)

    def write_byte(self, b: int) -> None:
        self.write_bits(b & 0xFF, 8)

    def write_varint(self, value: int) -> None:
        """LEB128 unsigned varint: 7 payload bits per byte, MSB = continuation."""
        if value < 0:
            raise ValueError("varint must be non-negative")
        while True:
            byte = value & 0x7F
            value >>= 7
            if value:
                self.write_byte(byte | 0x80)
            else:
                self.write_byte(byte)
                break

    @property
    def bit_length(self) -> int:
        return self._total

    def getvalue(self) -> bytes:
        """Flush any partial byte (zero-padded) and return the buffer."""
        if self._nbits:
            out = bytearray(self._buf)
            out.append(self._cur << (8 - self._nbits))
            return bytes(out)
        return bytes(self._buf)


class BitReader:
    """Reads bits MSB-first from a bytes object.

    Reading past the end yields ``0`` bits rather than raising; this lets entropy
    decoders that consume a fixed symbol count tolerate the zero padding the
    writer added. Use :meth:`bits_remaining` when exactness matters.
    """

    __slots__ = ("_data", "_pos", "_bitpos", "_len")

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._len = len(data)
        self._pos = 0      # byte index
        self._bitpos = 0   # bit index within current byte (0 = MSB)

    def read_bit(self) -> int:
        if self._pos >= self._len:
            return 0
        bit = (self._data[self._pos] >> (7 - self._bitpos)) & 1
        self._bitpos += 1
        if self._bitpos == 8:
            self._bitpos = 0
            self._pos += 1
        return bit

    def read_bits(self, count: int) -> int:
        value = 0
        for _ in range(count):
            value = (value << 1) | self.read_bit()
        return value

    def read_byte(self) -> int:
        return self.read_bits(8)

    def read_varint(self) -> int:
        value = 0
        shift = 0
        while True:
            byte = self.read_byte()
            value |= (byte & 0x7F) << shift
            if not (byte & 0x80):
                return value
            shift += 7

    def bits_remaining(self) -> int:
        return (self._len - self._pos) * 8 - self._bitpos
