"""Wire format for MiniTCP segments.

Header layout (network byte order, 16 bytes):

    seq        4 bytes  unsigned int   sequence number of first payload byte
    ack        4 bytes  unsigned int   next expected sequence number
    flags      1 byte   bit flags      SYN/ACK/FIN/PSH/RST
    window     2 bytes  unsigned short receiver's advertised window (bytes)
    sack_count 1 byte   unsigned int   number of SACK blocks that follow
    checksum   4 bytes  unsigned int   CRC32 over header(checksum=0)+SACK+payload

Followed by 0-MAX_SACK_BLOCKS SACK blocks (8 bytes each: start, end as
unsigned ints), followed by the payload.
"""
import struct
import zlib

FLAG_SYN = 0x01
FLAG_ACK = 0x02
FLAG_FIN = 0x04
FLAG_PSH = 0x08
FLAG_RST = 0x10

_HEADER_FMT = "!IIBHBI"
HEADER_SIZE = struct.calcsize(_HEADER_FMT)
assert HEADER_SIZE == 16

_SACK_BLOCK_FMT = "!II"
SACK_BLOCK_SIZE = struct.calcsize(_SACK_BLOCK_FMT)
MAX_SACK_BLOCKS = 3

MSS = 512  # max payload bytes per segment


class ChecksumError(ValueError):
    pass


class Segment:
    __slots__ = ("seq", "ack", "flags", "window", "sack_blocks", "payload")

    def __init__(self, seq=0, ack=0, flags=0, window=0, sack_blocks=None, payload=b""):
        self.seq = seq
        self.ack = ack
        self.flags = flags
        self.window = window
        self.sack_blocks = sack_blocks or []
        self.payload = payload

    def __repr__(self):
        fl = "".join(
            c if self.flags & f else "-"
            for c, f in (("S", FLAG_SYN), ("A", FLAG_ACK), ("F", FLAG_FIN), ("P", FLAG_PSH), ("R", FLAG_RST))
        )
        return (
            f"Segment(seq={self.seq} ack={self.ack} flags={fl} win={self.window} "
            f"sack={self.sack_blocks} len={len(self.payload)})"
        )

    def is_syn(self):
        return bool(self.flags & FLAG_SYN)

    def is_ack(self):
        return bool(self.flags & FLAG_ACK)

    def is_fin(self):
        return bool(self.flags & FLAG_FIN)

    def is_rst(self):
        return bool(self.flags & FLAG_RST)

    def seq_len(self):
        """Number of sequence numbers this segment consumes."""
        n = len(self.payload)
        if self.flags & (FLAG_SYN | FLAG_FIN):
            n += 1
        return n

    def encode(self):
        if len(self.sack_blocks) > MAX_SACK_BLOCKS:
            raise ValueError("too many SACK blocks")
        header = struct.pack(
            _HEADER_FMT,
            self.seq & 0xFFFFFFFF,
            self.ack & 0xFFFFFFFF,
            self.flags & 0xFF,
            self.window & 0xFFFF,
            len(self.sack_blocks),
            0,
        )
        body = b"".join(struct.pack(_SACK_BLOCK_FMT, s, e) for s, e in self.sack_blocks) + self.payload
        checksum = zlib.crc32(header + body) & 0xFFFFFFFF
        header = struct.pack(
            _HEADER_FMT,
            self.seq & 0xFFFFFFFF,
            self.ack & 0xFFFFFFFF,
            self.flags & 0xFF,
            self.window & 0xFFFF,
            len(self.sack_blocks),
            checksum,
        )
        return header + body

    @classmethod
    def decode(cls, data):
        if len(data) < HEADER_SIZE:
            raise ChecksumError("segment shorter than header")
        seq, ack, flags, window, sack_count, checksum = struct.unpack(_HEADER_FMT, data[:HEADER_SIZE])
        rest = data[HEADER_SIZE:]
        needed = sack_count * SACK_BLOCK_SIZE
        if len(rest) < needed:
            raise ChecksumError("segment shorter than declared SACK blocks")
        sack_blocks = []
        off = 0
        for _ in range(sack_count):
            s, e = struct.unpack(_SACK_BLOCK_FMT, rest[off:off + SACK_BLOCK_SIZE])
            sack_blocks.append((s, e))
            off += SACK_BLOCK_SIZE
        payload = rest[off:]

        zero_header = struct.pack(_HEADER_FMT, seq, ack, flags, window, sack_count, 0)
        expected = zlib.crc32(zero_header + rest) & 0xFFFFFFFF
        if expected != checksum:
            raise ChecksumError(f"checksum mismatch: got {checksum:#x} expected {expected:#x}")

        return cls(seq=seq, ack=ack, flags=flags, window=window, sack_blocks=sack_blocks, payload=payload)
