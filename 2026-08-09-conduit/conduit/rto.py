"""RTT estimation and retransmission-timeout calculation.

The Jacobson/Karels algorithm (Van Jacobson, 1988; formalized in RFC 6298),
the same estimator real TCP stacks use: smoothed RTT (SRTT) and RTT
variance (RTTVAR) are tracked with exponentially-weighted moving averages,
and RTO = SRTT + 4*RTTVAR.

Karn's algorithm is applied: only RTT samples from segments that were
*not* retransmitted feed the estimator, since a retransmitted segment's ACK
is ambiguous (was it for the original send or the retransmit?).
"""

ALPHA = 1 / 8  # SRTT gain
BETA = 1 / 4  # RTTVAR gain
K = 4

MIN_RTO = 0.2  # seconds — floor, so we don't spin on sub-millisecond loopback RTTs
MAX_RTO = 30.0  # seconds — ceiling, matching RFC 6298's guidance
INITIAL_RTO = 1.0


class RTOEstimator:
    def __init__(self):
        self.srtt = None
        self.rttvar = None
        self.rto = INITIAL_RTO
        self.samples = 0

    def sample(self, measured_rtt: float) -> None:
        """Feed one *unambiguous* RTT sample (Karn's algorithm: caller must
        not call this for a segment that was retransmitted)."""
        measured_rtt = max(measured_rtt, 1e-6)
        if self.srtt is None:
            self.srtt = measured_rtt
            self.rttvar = measured_rtt / 2
        else:
            self.rttvar = (1 - BETA) * self.rttvar + BETA * abs(self.srtt - measured_rtt)
            self.srtt = (1 - ALPHA) * self.srtt + ALPHA * measured_rtt
        self.samples += 1
        self.rto = self._clamp(self.srtt + K * self.rttvar)

    def backoff(self) -> float:
        """Exponential backoff after a retransmission timeout (Karn's
        algorithm: this does NOT touch SRTT/RTTVAR, only the working RTO)."""
        self.rto = self._clamp(self.rto * 2)
        return self.rto

    @staticmethod
    def _clamp(value: float) -> float:
        return max(MIN_RTO, min(MAX_RTO, value))
