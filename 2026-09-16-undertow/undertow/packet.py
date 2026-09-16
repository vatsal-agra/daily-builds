"""Undertow wire format: a real header, a real RFC 1071 checksum.

Header (network byte order, no padding — all fields explicit width):

    seq        4 bytes   sequence number of the first payload byte
    ack        4 bytes   next byte the sender of this packet expects
    flags      1 byte    bit 0 SYN, bit 1 ACK, bit 2 FIN, bit 3 RST
    sack_count 1 byte    number of (start,end) SACK blocks that follow
    window     2 bytes   receiver's advertised window, in bytes
    checksum   2 bytes   RFC 1071 one's-complement checksum

Then ``sack_count`` * 8 bytes of SACK blocks (start:4, end:4 each), then
the payload.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

HEADER_FMT = "!IIBBHH"
HEADER_LEN = struct.calcsize(HEADER_FMT)
SACK_BLOCK_FMT = "!II"
SACK_BLOCK_LEN = struct.calcsize(SACK_BLOCK_FMT)
MAX_SACK_BLOCKS = 3

FLAG_SYN = 0x01
FLAG_ACK = 0x02
FLAG_FIN = 0x04
FLAG_RST = 0x08

MSS = 1400  # max payload bytes per segment


class PacketError(ValueError):
    pass


def checksum16(data: bytes) -> int:
    """RFC 1071 16-bit one's-complement checksum over `data`."""
    if len(data) % 2:
        data = data + b"\x00"
    total = 0
    for i in range(0, len(data), 2):
        total += (data[i] << 8) | data[i + 1]
        total = (total & 0xFFFF) + (total >> 16)
    return (~total) & 0xFFFF


@dataclass
class Packet:
    seq: int
    ack: int
    flags: int = 0
    window: int = 0
    sack_blocks: list[tuple[int, int]] = field(default_factory=list)
    payload: bytes = b""

    @property
    def is_syn(self) -> bool:
        return bool(self.flags & FLAG_SYN)

    @property
    def is_ack(self) -> bool:
        return bool(self.flags & FLAG_ACK)

    @property
    def is_fin(self) -> bool:
        return bool(self.flags & FLAG_FIN)

    @property
    def is_rst(self) -> bool:
        return bool(self.flags & FLAG_RST)

    def encode(self) -> bytes:
        if len(self.sack_blocks) > MAX_SACK_BLOCKS:
            raise PacketError(
                f"too many SACK blocks: {len(self.sack_blocks)} > {MAX_SACK_BLOCKS}"
            )
        header = struct.pack(
            HEADER_FMT,
            self.seq & 0xFFFFFFFF,
            self.ack & 0xFFFFFFFF,
            self.flags & 0xFF,
            len(self.sack_blocks),
            self.window & 0xFFFF,
            0,  # checksum placeholder
        )
        sacks = b"".join(struct.pack(SACK_BLOCK_FMT, s, e) for s, e in self.sack_blocks)
        body = header + sacks + self.payload
        cksum = checksum16(body)
        header = struct.pack(
            HEADER_FMT,
            self.seq & 0xFFFFFFFF,
            self.ack & 0xFFFFFFFF,
            self.flags & 0xFF,
            len(self.sack_blocks),
            self.window & 0xFFFF,
            cksum,
        )
        return header + sacks + self.payload

    @classmethod
    def decode(cls, raw: bytes) -> "Packet":
        if len(raw) < HEADER_LEN:
            raise PacketError(f"packet too short: {len(raw)} < {HEADER_LEN}")
        seq, ack, flags, sack_count, window, cksum = struct.unpack(
            HEADER_FMT, raw[:HEADER_LEN]
        )
        if sack_count > MAX_SACK_BLOCKS:
            raise PacketError(f"bogus sack_count {sack_count}")
        sacks_end = HEADER_LEN + sack_count * SACK_BLOCK_LEN
        if len(raw) < sacks_end:
            raise PacketError("packet truncated before declared SACK blocks")

        zeroed = raw[:12] + b"\x00\x00" + raw[14:]
        computed = checksum16(zeroed)
        if computed != cksum:
            raise PacketError(f"checksum mismatch: got {cksum:#06x} want {computed:#06x}")

        sack_blocks = [
            struct.unpack(
                SACK_BLOCK_FMT,
                raw[HEADER_LEN + i * SACK_BLOCK_LEN : HEADER_LEN + (i + 1) * SACK_BLOCK_LEN],
            )
            for i in range(sack_count)
        ]
        payload = raw[sacks_end:]
        return cls(seq=seq, ack=ack, flags=flags, window=window, sack_blocks=sack_blocks, payload=payload)
