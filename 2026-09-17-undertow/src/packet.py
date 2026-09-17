"""The unit of data the simulator moves. Two identifiers matter for very
different reasons: ``seq`` is the TCP-level sequence number (a logical unit
of data — a retransmission of seq 7 is still "seq 7"), used by the
congestion-control/ACK machinery. ``phys_id`` is assigned once per physical
transmission onto the wire (a retransmission gets a *new* phys_id), used
only by the network-layer packet-conservation invariant test: every physical
transmission must end up exactly once in {delivered, dropped, still in
flight when the run ends}.
"""

from dataclasses import dataclass


@dataclass
class Packet:
    flow_id: int
    seq: int
    phys_id: int
    size_bytes: int
    send_time: float
    is_retransmit: bool = False
    is_ack: bool = False
    ack_num: int = 0
