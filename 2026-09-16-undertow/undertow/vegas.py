"""VegasCongestionController — a simplified TCP Vegas: delay-based, not
loss-based.

Reno (and every loss-based controller) only ever learns it went too fast
*after* a packet is already lost — it treats the network as either "fine"
or "full", with no signal in between. Vegas instead watches RTT: it knows
`base_rtt` (the smallest RTT it's ever measured on this connection, taken
as an estimate of the network with an empty queue) and compares it to the
RTT it's actually seeing right now. The gap between "how much data *should*
be in flight at this cwnd if the path were empty" and "how much *actually*
is" (both computed in units of segments) is a direct estimate of how many
packets are sitting in a queue *before* any of them are dropped — so Vegas
can back off from a growing queue pre-emptively, while Reno is still
happily doubling cwnd on the way to the loss that would have told it to
stop.
"""

from __future__ import annotations

from .congestion import CongestionController, DUP_ACK_THRESHOLD, INITIAL_SSTHRESH
from .packet import MSS


class VegasCongestionController(CongestionController):
    name = "vegas"

    def __init__(self, mss: int = MSS, alpha: float = 2.0, beta: float = 4.0, gamma: float = 1.0) -> None:
        self.mss = mss
        self._cwnd = mss
        self.ssthresh = INITIAL_SSTHRESH
        self.state = "slow_start"
        self.alpha = alpha  # segments of "queueing" below which we speed up
        self.beta = beta  # segments of "queueing" above which we slow down
        self.gamma = gamma  # slow-start exit threshold, in segments
        self.base_rtt: float | None = None
        self._last_rtt: float | None = None
        self.dup_ack_count = 0

    @property
    def cwnd(self) -> int:
        return self._cwnd

    def on_rtt_sample(self, rtt: float) -> None:
        if rtt <= 0:
            return
        self._last_rtt = rtt
        if self.base_rtt is None or rtt < self.base_rtt:
            self.base_rtt = rtt

    def _queued_segments(self) -> float:
        """How many segments' worth of data is sitting in a queue right
        now, estimated the classic Vegas way: cwnd*(1 - base_rtt/rtt)."""
        if not self.base_rtt or not self._last_rtt or self._last_rtt <= 0:
            return 0.0
        return max(0.0, (self._cwnd / self.mss) * (1 - self.base_rtt / self._last_rtt))

    def on_new_ack(self, newly_acked_bytes: int) -> None:
        if newly_acked_bytes <= 0:
            return
        if self.state == "fast_recovery":
            self._cwnd = self.ssthresh
            self.state = "congestion_avoidance"
            self.dup_ack_count = 0
            return

        if self.base_rtt is None:
            # no RTT sample yet at all: behave like plain slow start until
            # we have one to compute a delay signal from
            self._cwnd += min(newly_acked_bytes, self.mss)
            self.dup_ack_count = 0
            return

        queued = self._queued_segments()

        if self.state == "slow_start":
            if queued > self.gamma:
                # a real queue is already forming -- stop doubling now,
                # well before a loss-based controller would ever find out
                self.state = "congestion_avoidance"
            else:
                self._cwnd += min(newly_acked_bytes, self.mss)
        else:
            if queued < self.alpha:
                self._cwnd += max(1, (self.mss * self.mss) // self._cwnd)
            elif queued > self.beta:
                self._cwnd = max(self.mss, self._cwnd - self.mss)
            # else: in the target range, leave cwnd alone
        self.dup_ack_count = 0

    def on_dup_ack(self) -> bool:
        if self.state == "fast_recovery":
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
