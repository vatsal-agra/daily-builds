"""Canonical Huffman coding for JPEG: consuming a (bits, huffval) table pair
into an encode/decode map (ITU-T T.81 Annex C "Generate_codes"), building a
fresh optimal canonical table from symbol frequencies (for the optimal
per-image-table stretch feature), and a bit-level writer/reader implementing
JPEG's entropy-coded segment framing (MSB-first bit packing, 0xFF00 byte
stuffing, 1-padding at the end of a scan)."""

import heapq

MAX_CODE_LENGTH = 16


class HuffTable:
    """A JPEG Huffman table: canonical codes derived from (bits, huffval)."""

    def __init__(self, bits, huffval):
        if sum(bits) != len(huffval):
            raise ValueError("bits counts must sum to len(huffval)")
        if len(bits) != MAX_CODE_LENGTH:
            raise ValueError("bits must have 16 entries (lengths 1..16)")
        self.bits = list(bits)
        self.huffval = list(huffval)

        sizes = []
        for length_index, count in enumerate(self.bits):
            sizes.extend([length_index + 1] * count)

        codes = []
        code = 0
        li = 0
        for length_index, count in enumerate(self.bits):
            for _ in range(count):
                codes.append(code)
                code += 1
            code <<= 1

        self.encode_map = {}  # symbol -> (code, length)
        self.decode_map = {}  # (length, code) -> symbol
        for sym, c, l in zip(self.huffval, codes, sizes):
            self.encode_map[sym] = (c, l)
            self.decode_map[(l, c)] = sym
        self.max_code_length = max(sizes) if sizes else 0

    def encode(self, symbol):
        return self.encode_map[symbol]

    def decode_one(self, bitreader):
        """Read bits one at a time from `bitreader` until they match a
        valid code; return the decoded symbol."""
        code = 0
        for length in range(1, MAX_CODE_LENGTH + 1):
            code = (code << 1) | bitreader.read_bit()
            sym = self.decode_map.get((length, code))
            if sym is not None:
                return sym
        raise ValueError("no valid Huffman code found in bitstream")


def build_optimal_table(freqs, max_length=16):
    """Build a spec-legal canonical Huffman table (bits, huffval) from a
    symbol->frequency dict, via a standard priority-queue Huffman tree.
    Falls back to signalling failure (returns None) if any resulting code
    would exceed `max_length` bits, so the caller can fall back to a
    standard table instead of producing an illegal DHT segment."""
    symbols = [s for s, f in freqs.items() if f > 0]
    if not symbols:
        return None
    if len(symbols) == 1:
        # A single-symbol alphabet still needs a real 1-bit code.
        return [1] + [0] * 15, symbols

    # heap entries: (frequency, insertion_order, node)
    # node is either a leaf (symbol) or an internal (left, right) tuple
    counter = 0
    heap = []
    for s in symbols:
        heapq.heappush(heap, (freqs[s], counter, ("leaf", s)))
        counter += 1
    while len(heap) > 1:
        f1, _, n1 = heapq.heappop(heap)
        f2, _, n2 = heapq.heappop(heap)
        heapq.heappush(heap, (f1 + f2, counter, ("node", n1, n2)))
        counter += 1
    _, _, root = heap[0]

    lengths = {}

    def walk(node, depth):
        if node[0] == "leaf":
            lengths[node[1]] = max(depth, 1)
        else:
            walk(node[1], depth + 1)
            walk(node[2], depth + 1)

    walk(root, 0)

    if max(lengths.values()) > max_length:
        return None

    # Reserve one code point: JPEG forbids the all-1-bits code of the
    # longest length (it's reserved). With a proper Huffman tree over >=2
    # symbols this is already guaranteed structurally, so no adjustment
    # needed here.

    bits = [0] * max_length
    for l in lengths.values():
        bits[l - 1] += 1
    huffval = sorted(lengths.keys(), key=lambda s: (lengths[s], s))
    return bits, huffval


class BitWriter:
    """MSB-first bit packer implementing JPEG entropy-segment byte stuffing
    (an emitted 0xFF byte is immediately followed by a stuffing 0x00)."""

    def __init__(self):
        self._bytes = bytearray()
        self._cur = 0
        self._nbits = 0

    def write_bits(self, value, length):
        if length == 0:
            return
        for i in range(length - 1, -1, -1):
            bit = (value >> i) & 1
            self._cur = (self._cur << 1) | bit
            self._nbits += 1
            if self._nbits == 8:
                self._flush_byte()

    def _flush_byte(self):
        b = self._cur & 0xFF
        self._bytes.append(b)
        if b == 0xFF:
            self._bytes.append(0x00)
        self._cur = 0
        self._nbits = 0

    def pad_and_get_bytes(self):
        if self._nbits > 0:
            pad = 8 - self._nbits
            self._cur = (self._cur << pad) | ((1 << pad) - 1)
            self._nbits = 8
            self._flush_byte()
        return bytes(self._bytes)


class BitReader:
    """Reads bits MSB-first from a byte string that uses JPEG's 0xFF00
    stuffing; stops (raises StopIteration-safe EOFError) at a real marker
    (0xFF followed by a non-zero byte)."""

    def __init__(self, data, start=0):
        self._data = data
        self._pos = start
        self._cur = 0
        self._nbits = 0
        self.hit_marker = None

    def read_bit(self):
        if self._nbits == 0:
            if self._pos >= len(self._data):
                raise EOFError("entropy stream exhausted")
            b = self._data[self._pos]
            self._pos += 1
            if b == 0xFF:
                nxt = self._data[self._pos] if self._pos < len(self._data) else 0
                if nxt == 0x00:
                    self._pos += 1  # stuffed byte, real data is 0xFF
                else:
                    # Real marker: back up so the caller can see it, and
                    # feed 1-bits (matches padding at end of scan).
                    self._pos -= 1
                    self.hit_marker = (0xFF, nxt)
                    return 1
            self._cur = b
            self._nbits = 8
        self._nbits -= 1
        return (self._cur >> self._nbits) & 1
