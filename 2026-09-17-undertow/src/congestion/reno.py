"""TCP Reno / RFC 5681 congestion avoidance.

Slow start: cwnd grows by one packet per ACKed packet (exponential — doubles
roughly once per RTT). Congestion avoidance: cwnd grows by 1/cwnd per ACKed
packet (additive — +1 packet per RTT, regardless of how large cwnd already
is). On loss: multiplicative decrease, halve cwnd.
"""

from __future__ import annotations

from .base import MIN_CWND, CongestionControl


class Reno(CongestionControl):
    name = "reno"

    def on_ack(self, now: float, rtt_sample, acked_packets: int = 1, inflight: float | None = None) -> None:
        if self.cwnd < self.ssthresh:
            self.cwnd += acked_packets
        else:
            self.cwnd += acked_packets / self.cwnd

    def on_loss_event(self, now: float) -> None:
        self.ssthresh = max(self.cwnd / 2, 2.0)
        self.cwnd = max(self.ssthresh, MIN_CWND)
