"""Interface every congestion-control algorithm implements.

Loss-recovery mechanics that are *not* algorithm-specific — the triple-dup-ACK
fast-retransmit/fast-recovery window inflation (RFC 5681 section 3.2), and the
retransmission-timeout backoff — live in ``Sender`` (flow.py) and are shared
by every algorithm. What differs per algorithm is exactly two things: how
cwnd grows on a new ACK (``on_ack``), and how cwnd/ssthresh are set the
moment a loss is detected (``on_loss_event``).
"""

from __future__ import annotations

MIN_CWND = 1.0


class CongestionControl:
    name = "base"

    def __init__(self, init_cwnd: float = 1.0, init_ssthresh: float = 64.0):
        self.cwnd = init_cwnd
        self.ssthresh = init_ssthresh

    def on_ack(self, now: float, rtt_sample, acked_packets: int = 1, inflight: float | None = None) -> None:
        """Called once per new cumulative ACK (never for a duplicate ACK).
        ``inflight`` (packets currently unacknowledged, after this ACK is
        applied) is only consumed by BBR; loss-based algorithms ignore it."""
        raise NotImplementedError

    def on_loss_event(self, now: float) -> None:
        """Called exactly once when a loss is first detected (3rd dup ACK
        or an RTO). Must set self.ssthresh and self.cwnd to the algorithm's
        multiplicative-decrease baseline; the caller (Sender) applies the
        generic +3 fast-recovery inflation on top for dup-ACK losses."""
        raise NotImplementedError

    def on_timeout(self, now: float) -> None:
        """A full RTO fired: universally, every TCP variant restarts from
        slow start with cwnd=1 and halves ssthresh — there is nothing
        algorithm-specific about a timeout response."""
        self.ssthresh = max(self.cwnd / 2, 2.0)
        self.cwnd = MIN_CWND

    def enter_fast_recovery_inflate(self) -> None:
        self.cwnd += 3

    def dup_ack_inflate(self) -> None:
        self.cwnd += 1

    def exit_fast_recovery(self) -> None:
        self.cwnd = max(self.ssthresh, MIN_CWND)
