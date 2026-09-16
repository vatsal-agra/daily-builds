"""Jacobson/Karels RTO estimation (RFC 6298) + Karn's algorithm.

Karn's algorithm: never feed an RTT sample measured from a segment that was
retransmitted — you can't tell whether the ACK you got back is for the
original send or the retransmission, so the "measured" RTT is meaningless
(this is the classic "retransmission ambiguity" problem). Callers signal
that by simply not calling ``sample()`` for retransmitted segments; this
module doesn't need to know which segment an ACK belongs to.
"""

from __future__ import annotations

ALPHA = 1 / 8
BETA = 1 / 4
K = 4
CLOCK_GRANULARITY = 0.01  # seconds; RFC 6298's "G"
MIN_RTO = 0.2
MAX_RTO = 60.0
INITIAL_RTO = 1.0


class RTOEstimator:
    def __init__(self) -> None:
        self.srtt: float | None = None
        self.rttvar: float | None = None
        self.rto: float = INITIAL_RTO
        self.samples_taken = 0

    def sample(self, rtt: float) -> None:
        """Feed one *non-retransmitted* segment's measured RTT (seconds)."""
        if rtt <= 0:
            raise ValueError(f"non-positive RTT sample: {rtt}")
        self.samples_taken += 1
        if self.srtt is None:
            self.srtt = rtt
            self.rttvar = rtt / 2
        else:
            assert self.rttvar is not None
            self.rttvar = (1 - BETA) * self.rttvar + BETA * abs(self.srtt - rtt)
            self.srtt = (1 - ALPHA) * self.srtt + ALPHA * rtt
        self.rto = self.srtt + max(CLOCK_GRANULARITY, K * self.rttvar)
        self.rto = min(MAX_RTO, max(MIN_RTO, self.rto))

    def backoff(self) -> None:
        """Exponential backoff after a retransmission timeout fires again."""
        self.rto = min(MAX_RTO, self.rto * 2)

    def current(self) -> float:
        return self.rto
