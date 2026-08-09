"""Reno-style congestion control (RFC 5681): slow start, congestion
avoidance (AIMD), fast retransmit on triple duplicate ACK, fast recovery.

All windows are tracked in bytes (not segments), consistent with
Conduit's byte-stream sequence numbers. `mss` is the maximum segment
size used to scale the additive-increase terms.
"""

SLOW_START = "slow_start"
CONGESTION_AVOIDANCE = "congestion_avoidance"
FAST_RECOVERY = "fast_recovery"

DUP_ACK_THRESHOLD = 3


class RenoCongestionControl:
    def __init__(self, mss: int, init_cwnd_segments: int = 2, init_ssthresh_bytes: int = 64 * 1024):
        self.mss = mss
        self.cwnd = mss * init_cwnd_segments
        self.ssthresh = init_ssthresh_bytes
        self.state = SLOW_START
        self.dup_ack_count = 0
        self._recovery_point = 0  # highest seq sent at the moment we entered fast recovery

    def on_new_ack(self, acked_bytes: int, send_una_after: int) -> None:
        """A cumulative ACK advanced send_una by `acked_bytes` (> 0)."""
        self.dup_ack_count = 0

        if self.state == FAST_RECOVERY:
            if send_una_after >= self._recovery_point:
                # The retransmission was ack'd — deflate and resume normal operation.
                self.cwnd = self.ssthresh
                self.state = CONGESTION_AVOIDANCE
            else:
                # Partial ACK within fast recovery: inflate window for the newly-freed room.
                self.cwnd += acked_bytes
            return

        if self.state == SLOW_START:
            self.cwnd += min(acked_bytes, self.mss)
            if self.cwnd >= self.ssthresh:
                self.state = CONGESTION_AVOIDANCE
        else:  # CONGESTION_AVOIDANCE
            self.cwnd += max(1, (self.mss * self.mss) // self.cwnd)

    def on_duplicate_ack(self, send_next: int) -> bool:
        """A duplicate ACK arrived. Returns True exactly when this call is
        the one that should trigger a fast retransmit (the 3rd dup ACK)."""
        if self.state == FAST_RECOVERY:
            self.cwnd += self.mss  # further inflation while recovering
            return False

        self.dup_ack_count += 1
        if self.dup_ack_count >= DUP_ACK_THRESHOLD:
            self.ssthresh = max(self.cwnd // 2, 2 * self.mss)
            self.cwnd = self.ssthresh + DUP_ACK_THRESHOLD * self.mss
            self.state = FAST_RECOVERY
            self._recovery_point = send_next
            self.dup_ack_count = 0
            return True
        return False

    def on_timeout(self) -> None:
        self.ssthresh = max(self.cwnd // 2, 2 * self.mss)
        self.cwnd = self.mss
        self.state = SLOW_START
        self.dup_ack_count = 0

    def snapshot(self) -> dict:
        return {
            "cwnd": self.cwnd,
            "ssthresh": self.ssthresh,
            "state": self.state,
        }
