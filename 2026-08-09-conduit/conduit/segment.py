"""Conduit wire segment: header framing, flags, (en/de)coding.

Header layout (network byte order, 15 bytes, no implicit padding):

    0        4        8   9    11   13   15
    +--------+--------+---+----+----+----+
    |  seq   |  ack   |flg| win| len| sum|
    +--------+--------+---+----+----+----+

- seq / ack : 4 bytes each, byte-stream sequence numbers (like real TCP —
  they count bytes of payload sent/acknowledged, not segments).
- flags     : 1 byte, bit flags (SYN/ACK/FIN/RST — see below).
- window    : 2 bytes, the sender's advertised receive window, in bytes.
- length    : 2 bytes, payload length in bytes (payload follows the
  header immediately; max 65535, comfortably above our MSS).
- checksum  : 2 bytes, the RFC 1071 Internet checksum of the header
  (with this field zeroed during computation) plus the payload.

Payload immediately follows the 15-byte header.
"""

import struct

from conduit.checksum import checksum16

FLAG_SYN = 0x01
FLAG_ACK = 0x02
FLAG_FIN = 0x04
FLAG_RST = 0x08

_HEADER_FMT = "!IIBHHH"
HEADER_SIZE = struct.calcsize(_HEADER_FMT)
assert HEADER_SIZE == 15

MAX_PAYLOAD = 65535 - HEADER_SIZE


class SegmentError(ValueError):
    """Raised when a received datagram is not a well-formed Conduit segment."""


class Segment:
    __slots__ = ("seq", "ack", "flags", "window", "payload")

    def __init__(self, seq=0, ack=0, flags=0, window=0, payload=b""):
        self.seq = seq & 0xFFFFFFFF
        self.ack = ack & 0xFFFFFFFF
        self.flags = flags & 0xFF
        self.window = window & 0xFFFF
        self.payload = payload

    def has(self, flag: int) -> bool:
        return bool(self.flags & flag)

    def flag_str(self) -> str:
        names = []
        if self.has(FLAG_SYN):
            names.append("SYN")
        if self.has(FLAG_ACK):
            names.append("ACK")
        if self.has(FLAG_FIN):
            names.append("FIN")
        if self.has(FLAG_RST):
            names.append("RST")
        return "|".join(names) or "-"

    def __repr__(self):
        return (
            f"Segment(seq={self.seq}, ack={self.ack}, flags={self.flag_str()}, "
            f"window={self.window}, len={len(self.payload)})"
        )

    def encode(self) -> bytes:
        if len(self.payload) > MAX_PAYLOAD:
            raise SegmentError(f"payload too large: {len(self.payload)} > {MAX_PAYLOAD}")
        header_zero_sum = struct.pack(
            _HEADER_FMT, self.seq, self.ack, self.flags, self.window, len(self.payload), 0
        )
        body = header_zero_sum + self.payload
        chk = checksum16(body)
        header = struct.pack(
            _HEADER_FMT, self.seq, self.ack, self.flags, self.window, len(self.payload), chk
        )
        return header + self.payload

    @classmethod
    def decode(cls, raw: bytes) -> "Segment":
        if len(raw) < HEADER_SIZE:
            raise SegmentError(f"datagram too short for a header: {len(raw)} bytes")
        seq, ack, flags, window, length, chk = struct.unpack(_HEADER_FMT, raw[:HEADER_SIZE])
        payload = raw[HEADER_SIZE:]
        if len(payload) != length:
            raise SegmentError(
                f"declared length {length} does not match actual payload {len(payload)}"
            )
        # Recompute the checksum with the checksum field zeroed, exactly as encode() did.
        header_zero_sum = struct.pack(_HEADER_FMT, seq, ack, flags, window, length, 0)
        expected = checksum16(header_zero_sum + payload)
        if expected != chk:
            raise SegmentError(f"checksum mismatch: header says {chk:#06x}, computed {expected:#06x}")
        return cls(seq=seq, ack=ack, flags=flags, window=window, payload=payload)
