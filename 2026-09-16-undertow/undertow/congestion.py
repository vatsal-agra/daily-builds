"""Pluggable congestion controllers.

``RenoCongestionController`` is TCP Reno's textbook state machine: slow
start (exponential cwnd growth until ssthresh), congestion avoidance
(additive-increase, one MSS per RTT), fast retransmit on the 3rd duplicate
ACK, and fast recovery (window inflation while the fast-retransmitted
segment is outstanding, then a clean drop to congestion avoidance once it's
ACKed). Every method mutates and returns just enough state for a caller
(``connection.py``) to drive real segment sends/retransmits off of it — the
controller itself never touches a socket or a clock beyond the RTT samples
handed to it.
"""

from __future__ import annotations

from .packet import MSS

INITIAL_SSTHRESH = 64 * 1024
DUP_ACK_THRESHOLD = 3


class CongestionController:
    """Interface every congestion controller implements."""

    name = "base"

    def on_new_ack(self, newly_acked_bytes: int) -> None:
        raise NotImplementedError

    def on_dup_ack(self) -> bool:
        """Returns True if this call should trigger a fast retransmit."""
        raise NotImplementedError

    def on_timeout(self) -> None:
        raise NotImplementedError

    @property
    def cwnd(self) -> int:
        raise NotImplementedError


class RenoCongestionController(CongestionController):
    name = "reno"

    def __init__(self, mss: int = MSS) -> None:
        self.mss = mss
        self._cwnd = mss
        self.ssthresh = INITIAL_SSTHRESH
        self.state = "slow_start"
        self.dup_ack_count = 0

    @property
    def cwnd(self) -> int:
        return self._cwnd

    def in_slow_start(self) -> bool:
        return self.state == "slow_start"

    def on_new_ack(self, newly_acked_bytes: int) -> None:
        if newly_acked_bytes <= 0:
            return
        if self.state == "fast_recovery":
            # The retransmitted segment (and everything before it) is now
            # covered by a fresh cumulative ACK: recovery is over.
            self._cwnd = self.ssthresh
            self.state = "congestion_avoidance"
            self.dup_ack_count = 0
            return

        if self.state == "slow_start":
            self._cwnd += min(newly_acked_bytes, self.mss)
            if self._cwnd >= self.ssthresh:
                self.state = "congestion_avoidance"
        else:  # congestion_avoidance
            self._cwnd += max(1, (self.mss * self.mss) // self._cwnd)
        self.dup_ack_count = 0

    def on_dup_ack(self) -> bool:
        if self.state == "fast_recovery":
            # Window inflation: each further dup ACK means one more segment
            # left the network, so we can afford to send one more.
            self._cwnd += self.mss
            return False

        self.dup_ack_count += 1
        if self.dup_ack_count >= DUP_ACK_THRESHOLD:
            self.ssthresh = max(self._cwnd // 2, 2 * self.mss)
            self._cwnd = self.ssthresh + DUP_ACK_THRESHOLD * self.mss
            self.state = "fast_recovery"
            return True
        return False

    def on_timeout(self) -> None:
        self.ssthresh = max(self._cwnd // 2, 2 * self.mss)
        self._cwnd = self.mss
        self.state = "slow_start"
        self.dup_ack_count = 0
