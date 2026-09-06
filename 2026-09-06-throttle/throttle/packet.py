"""TCP segment representation.

A `Segment` carries exactly the header fields a real TCP segment carries
(sequence number, acknowledgment number, SYN/ACK/FIN flags, advertised
receive window, payload) plus a couple of simulation-bookkeeping fields
(`send_time`, `retransmit_count`) that a real NIC doesn't need but our RTT
estimator (which must implement Karn's algorithm — never sample RTT from a
retransmitted segment) does.

Sequence numbers here are plain unbounded Python ints, not real TCP's
32-bit wrapping space. A real stack must handle sequence-number wraparound
(and the same-parity ISN randomization defense it enables); a simulated
transfer here never gets remotely close to 2**32 bytes, so wraparound
is a deliberately out-of-scope simplification, called out again in the
README rather than silently assumed.

IP+TCP header overhead is modeled as a flat `HEADER_BYTES` added to every
segment's on-wire size, so the bottleneck link's bandwidth accounting
includes header cost the way a real link's does (a stream of tiny ACKs
still consumes real bytes on the wire).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Tuple

HEADER_BYTES = 40  # 20 bytes IPv4 + 20 bytes TCP, no options
SACK_BLOCK_BYTES = 8  # 2 x 32-bit sequence numbers, real RFC 2018 SACK option cost


@dataclass
class Segment:
    seq: int                    # sequence number of the first payload byte
                                 # (or of the SYN/FIN itself, which consumes
                                 # one sequence number per RFC 793)
    ack: int                    # cumulative ACK: next expected byte
    syn: bool = False
    ack_flag: bool = False      # the ACK *flag* (distinct from the `ack` field
                                 # being meaningful — a pure SYN has ack_flag=False)
    fin: bool = False
    window: int = 0             # advertised receive window, in bytes
    payload: bytes = b""
    flow_id: int = 0
    sack_blocks: Tuple[Tuple[int, int], ...] = ()  # RFC 2018: (start, end) ranges
                                                     # of extra bytes the receiver
                                                     # already holds beyond `ack`

    # simulation-only bookkeeping (never inspected by the "protocol logic"
    # itself, only by the RTT estimator / stats collector)
    send_time: float = 0.0
    is_retransmit: bool = False
    retransmit_count: int = 0

    @property
    def payload_len(self) -> int:
        return len(self.payload)

    @property
    def seq_len(self) -> int:
        """Number of sequence-space slots this segment consumes.

        SYN and FIN each consume exactly one sequence number, in addition
        to however many payload bytes are carried (real TCP allows a SYN
        or FIN to piggyback data; we never do that here, so it's always
        payload_len + (1 if syn or fin else 0))."""
        return self.payload_len + (1 if (self.syn or self.fin) else 0)

    @property
    def size_bytes(self) -> int:
        return HEADER_BYTES + self.payload_len + SACK_BLOCK_BYTES * len(self.sack_blocks)

    def clone_for_retransmit(self) -> "Segment":
        return Segment(
            seq=self.seq, ack=self.ack, syn=self.syn, ack_flag=self.ack_flag,
            fin=self.fin, window=self.window, payload=self.payload,
            flow_id=self.flow_id, send_time=self.send_time,
            is_retransmit=True, retransmit_count=self.retransmit_count + 1,
            sack_blocks=self.sack_blocks,
        )
