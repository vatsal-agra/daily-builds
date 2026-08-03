"""TCP Reno congestion control (RFC 5681-style AIMD).

States:
  SLOW_START        cwnd grows by 1 MSS per ACK (exponential per RTT)
                     until cwnd >= ssthresh
  CONGESTION_AVOID   cwnd grows by ~1 MSS per RTT (1/cwnd per ACK), linear
  FAST_RECOVERY      entered on triple-duplicate-ACK; cwnd inflates by 1 MSS
                     per further duplicate ACK; on a fresh ACK, cwnd deflates
                     to ssthresh and we drop back to CONGESTION_AVOID

Units: cwnd/ssthresh are tracked in bytes, MSS-quantized where the RFC calls
for it, matching how Reno is actually specified.
"""

SLOW_START = "slow_start"
CONGESTION_AVOID = "congestion_avoidance"
FAST_RECOVERY = "fast_recovery"


class RenoCongestionControl:
    def __init__(self, mss, init_cwnd_segments=1, init_ssthresh_segments=64):
        self.mss = mss
        self.cwnd = mss * init_cwnd_segments
        self.ssthresh = mss * init_ssthresh_segments
        self.state = SLOW_START
        self.dup_ack_count = 0
        self.history = []  # list of (event, cwnd, ssthresh, state)

    def _record(self, event):
        self.history.append((event, self.cwnd, self.ssthresh, self.state))

    def on_new_ack(self, newly_acked_bytes):
        """A fresh (non-duplicate) ACK advanced send_una."""
        self.dup_ack_count = 0
        if self.state == FAST_RECOVERY:
            # Full recovery: deflate to ssthresh and resume congestion avoidance.
            self.cwnd = self.ssthresh
            self.state = CONGESTION_AVOID
            self._record("recovery_exit")
            return
        if self.state == SLOW_START:
            self.cwnd += min(newly_acked_bytes, self.mss)
            if self.cwnd >= self.ssthresh:
                self.state = CONGESTION_AVOID
            self._record("ack_slow_start")
        else:  # CONGESTION_AVOID
            self.cwnd += max(1, (self.mss * self.mss) // max(self.cwnd, 1))
            self._record("ack_cong_avoid")

    def on_duplicate_ack(self):
        """A duplicate ACK arrived (same ack number as the last one)."""
        if self.state == FAST_RECOVERY:
            self.cwnd += self.mss  # window inflation
            self._record("dup_ack_inflate")
            return None
        self.dup_ack_count += 1
        if self.dup_ack_count == 3:
            self.ssthresh = max(self.cwnd // 2, 2 * self.mss)
            self.cwnd = self.ssthresh + 3 * self.mss
            self.state = FAST_RECOVERY
            self._record("fast_retransmit")
            return "fast_retransmit"
        return None

    def on_timeout(self):
        """A retransmission timeout fired: this is a much stronger signal
        of congestion than dup-ACKs, so we go back to slow start."""
        self.ssthresh = max(self.cwnd // 2, 2 * self.mss)
        self.cwnd = self.mss
        self.state = SLOW_START
        self.dup_ack_count = 0
        self._record("timeout")

    def usable_window_segments(self):
        return max(1, self.cwnd // self.mss)
