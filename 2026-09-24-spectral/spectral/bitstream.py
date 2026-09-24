"""MSB-first bit I/O with JPEG entropy-coded-segment byte stuffing.

JPEG packs Huffman codes MSB-first into bytes. Because the byte value
0xFF is reserved to introduce markers, any literal 0xFF byte that appears
*inside* entropy-coded data must be immediately followed by a stuffed
0x00 byte on the wire; the decoder removes that 0x00 back out. This
module implements both directions of that rule so nothing above it has
to think about it.
"""


class BitWriter:
    def __init__(self):
        self._bytes = bytearray()
        self._acc = 0
        self._nbits = 0

    def write_bits(self, value, nbits):
        """Write the low `nbits` bits of `value`, MSB first."""
        if nbits == 0:
            return
        self._acc = (self._acc << nbits) | (value & ((1 << nbits) - 1))
        self._nbits += nbits
        while self._nbits >= 8:
            self._nbits -= 8
            byte = (self._acc >> self._nbits) & 0xFF
            self._emit_byte(byte)
        self._acc &= (1 << self._nbits) - 1 if self._nbits else 0

    def _emit_byte(self, byte):
        self._bytes.append(byte)
        if byte == 0xFF:
            self._bytes.append(0x00)  # byte stuffing

    def align_byte(self, fill_bit=1):
        """Pad the current partial byte out with `fill_bit`s (JPEG uses 1s)."""
        if self._nbits:
            pad = 8 - self._nbits
            self.write_bits((1 << pad) - 1 if fill_bit else 0, pad)

    def getvalue(self):
        return bytes(self._bytes)


class BitReader:
    """Reads bits MSB-first from entropy-coded data, undoing byte stuffing.

    A 0xFF byte followed by 0x00 is destuffed to a literal 0xFF data byte.
    A 0xFF byte followed by anything else is a marker: the reader stops
    there (leaves the stream positioned at the 0xFF) so the caller (the
    scan decoder) can hand control back to the marker parser.
    """

    def __init__(self, data, start=0):
        self._data = data
        self._pos = start
        self._acc = 0
        self._nbits = 0
        self.hit_marker = None  # set to the marker byte if one was found

    def _fill(self):
        if self.hit_marker is not None:
            return False
        if self._pos >= len(self._data):
            return False
        byte = self._data[self._pos]
        if byte == 0xFF:
            if self._pos + 1 >= len(self._data):
                return False
            nxt = self._data[self._pos + 1]
            if nxt == 0x00:
                self._pos += 2
                self._acc = (self._acc << 8) | 0xFF
                self._nbits += 8
                return True
            else:
                # A real marker (e.g. 0xFFD9 EOI, or a restart marker).
                self.hit_marker = nxt
                return False
        else:
            self._pos += 1
            self._acc = (self._acc << 8) | byte
            self._nbits += 8
            return True

    def read_bit(self):
        if self._nbits == 0:
            if not self._fill():
                return None
        self._nbits -= 1
        bit = (self._acc >> self._nbits) & 1
        self._acc &= (1 << self._nbits) - 1 if self._nbits else 0
        return bit

    def read_bits(self, n):
        """Read n bits MSB-first as an unsigned int, or None on EOF/marker."""
        if n == 0:
            return 0
        v = 0
        for _ in range(n):
            b = self.read_bit()
            if b is None:
                return None
            v = (v << 1) | b
        return v

    def byte_pos(self):
        return self._pos

    def reset_for_restart(self, new_pos):
        """After consuming a restart marker, resync the bit reader."""
        self._pos = new_pos
        self._acc = 0
        self._nbits = 0
        self.hit_marker = None


def extend_receive(value, nbits):
    """JPEG's EXTEND(V, T): map an nbits-bit magnitude+sign-coded value
    back to a signed integer. If the top bit is 0, the value is negative
    and coded as (value - (2**nbits - 1)); otherwise it's the value as-is.
    nbits == 0 always means the coefficient is exactly 0.
    """
    if nbits == 0:
        return 0
    vt = 1 << (nbits - 1)
    if value < vt:
        return value - (1 << nbits) + 1
    return value


def bits_for_value(value):
    """The number of bits needed to represent |value| (JPEG's SSSS), and
    the magnitude-coded bit pattern to send for `value` (its own EXTEND
    inverse: negative values are bit-complemented within their category).
    """
    if value == 0:
        return 0, 0
    av = abs(value)
    nbits = av.bit_length()
    if value < 0:
        coded = value + (1 << nbits) - 1
    else:
        coded = value
    return nbits, coded
