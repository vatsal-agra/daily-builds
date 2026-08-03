"""Jacobson/Karels retransmission-timeout estimator (RFC 6298 / the
algorithm real BSD TCP has used since 1988).

    SRTT   <- smoothed round-trip time
    RTTVAR <- smoothed mean deviation of RTT
    RTO    <- SRTT + 4 * RTTVAR

On the first sample:
    SRTT   = R
    RTTVAR = R / 2

On subsequent samples (alpha = 1/8, beta = 1/4):
    RTTVAR = (1 - beta) * RTTVAR + beta * |SRTT - R|
    SRTT   = (1 - alpha) * SRTT + alpha * R

Karn's algorithm: never take an RTT sample from a retransmitted segment,
since an ACK for it is ambiguous (can't tell if it acks the original or the
retransmit). On timeout, RTO is doubled (exponential backoff) rather than
recomputed from a sample.
"""

ALPHA = 1.0 / 8
BETA = 1.0 / 4
K = 4
MIN_RTO = 0.2   # seconds
MAX_RTO = 10.0  # seconds
CLOCK_GRANULARITY = 0.01  # seconds


class RTOEstimator:
    def __init__(self):
        self.srtt = None
        self.rttvar = None
        self.rto = 1.0  # RFC 6298: initial RTO before any sample

    def sample(self, rtt_seconds):
        """Feed a *non-retransmitted* segment's measured RTT."""
        r = max(rtt_seconds, 1e-6)
        if self.srtt is None:
            self.srtt = r
            self.rttvar = r / 2.0
        else:
            self.rttvar = (1 - BETA) * self.rttvar + BETA * abs(self.srtt - r)
            self.srtt = (1 - ALPHA) * self.srtt + ALPHA * r
        self.rto = self.srtt + max(CLOCK_GRANULARITY, K * self.rttvar)
        self.rto = min(MAX_RTO, max(MIN_RTO, self.rto))
        return self.rto

    def backoff(self):
        """Exponential backoff after a retransmission timeout fires again
        before any new sample arrives (Karn's algorithm)."""
        self.rto = min(MAX_RTO, self.rto * 2)
        return self.rto

    def current(self):
        return self.rto
