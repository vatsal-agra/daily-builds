"""Wire format for a Causeway segment, and the RFC 1071 checksum it uses.

Header layout (network byte order, 13 bytes, followed by the payload)::

    0               1               2               3
    0 1 2 3 4 5 6 7 0 1 2 3 4 5 6 7 0 1 2 3 4 5 6 7 0 1 2 3 4 5 6 7
   +---------------------------------------------------------------+
   |                        sequence number                        |
   +---------------------------------------------------------------+
   |                     acknowledgment number                     |
   +---------------------------------------------------------------+
   |         window          |     flags     |         checksum    |
   +---------------------------------------------------------------+
   |          (checksum, continued)          |
   +-------------------------------------------

This is deliberately close to TCP's own segment header (minus the fields
Causeway doesn't need, like a source/dest port or the data-offset field
required only because TCP options have variable length). ``seq``/``ack``
count *bytes* of the application stream, exactly like TCP: SYN and FIN each
consume one sequence number, a pure-ACK with no payload consumes none.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

# Flag bits.
SYN = 0x1
ACK = 0x2
FIN = 0x4

_HEADER_FMT = "!IIHBH"  # seq, ack, window, flags, checksum
HEADER_SIZE = struct.calcsize(_HEADER_FMT)
assert HEADER_SIZE == 13


def checksum16(data: bytes) -> int:
    """The RFC 1071 Internet checksum: one's-complement sum of 16-bit words.

    This is the exact algorithm IP/TCP/UDP all use, hand-implemented (no
    zlib.crc32 shortcut): pad to an even length, sum every 16-bit big-endian
    word with end-around carry, then take the one's complement of the
    16-bit result.
    """
    if len(data) % 2:
        data = data + b"\x00"
    total = 0
    for i in range(0, len(data), 2):
        word = (data[i] << 8) + data[i + 1]
        total += word
        # End-around carry: fold any overflow past 16 bits back in.
        total = (total & 0xFFFF) + (total >> 16)
    return (~total) & 0xFFFF


@dataclass
class Segment:
    seq: int
    ack: int
    window: int
    flags: int
    payload: bytes = b""
    # Set on decode only, for diagnostics; never trusted for correctness
    # (encode() always recomputes it).
    _decoded_checksum_ok: bool = field(default=True, repr=False, compare=False)

    @property
    def is_syn(self) -> bool:
        return bool(self.flags & SYN)

    @property
    def is_ack(self) -> bool:
        return bool(self.flags & ACK)

    @property
    def is_fin(self) -> bool:
        return bool(self.flags & FIN)

    def seq_len(self) -> int:
        """Sequence-number space this segment consumes (SYN/FIN cost 1 each)."""
        n = len(self.payload)
        if self.is_syn:
            n += 1
        if self.is_fin:
            n += 1
        return n

    def encode(self) -> bytes:
        header = struct.pack(
            _HEADER_FMT, self.seq & 0xFFFFFFFF, self.ack & 0xFFFFFFFF,
            self.window & 0xFFFF, self.flags & 0xFF, 0,
        )
        chk = checksum16(header + self.payload)
        header = struct.pack(
            _HEADER_FMT, self.seq & 0xFFFFFFFF, self.ack & 0xFFFFFFFF,
            self.window & 0xFFFF, self.flags & 0xFF, chk,
        )
        return header + self.payload

    @classmethod
    def decode(cls, raw: bytes) -> "Segment":
        if len(raw) < HEADER_SIZE:
            raise ValueError(f"segment too short: {len(raw)} bytes")
        seq, ack, window, flags, chk = struct.unpack(_HEADER_FMT, raw[:HEADER_SIZE])
        payload = raw[HEADER_SIZE:]
        zeroed = struct.pack(_HEADER_FMT, seq, ack, window, flags, 0)
        ok = checksum16(zeroed + payload) == chk
        return cls(seq=seq, ack=ack, window=window, flags=flags, payload=payload,
                    _decoded_checksum_ok=ok)
