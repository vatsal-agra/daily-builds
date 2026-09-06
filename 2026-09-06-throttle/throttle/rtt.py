"""Jacobson/Karels RTT estimation (RFC 6298) + Karn's algorithm.

RFC 6298's smoothing:

    SRTT   <- (1 - alpha) * SRTT   + alpha * R      (alpha = 1/8)
    RTTVAR <- (1 - beta)  * RTTVAR + beta  * |SRTT - R|   (beta = 1/4)
    RTO    = SRTT + max(G, 4 * RTTVAR)

seeded on the very first sample by SRTT = R, RTTVAR = R / 2. RFC 6298 also
mandates a *minimum* RTO of 1 second — a rule that looks strange next to a
simulated network whose real RTTs are tens of milliseconds, but it's a
genuine, deliberate part of the spec (to avoid spurious retransmits from
transient variance) and reproduced faithfully here rather than "fixed" to
make demo output look more dramatic. Its real consequence, also visible in
this simulator's own experiments: most loss recovery happens via fast
retransmit (3 duplicate ACKs), not RTO expiry — RTO is a slow safety net,
not the primary loss-detection path.

Karn's algorithm has two parts, both implemented here:

1. Never feed a retransmitted segment's ACK into the SRTT/RTTVAR sample —
   there's no way to tell whether the ACK acknowledges the original
   transmission or the retransmission, so the RTT sample would be
   ambiguous ("retransmission ambiguity").
2. Use an exponentially backed-off RTO for any segment currently being
   retransmitted, and only fall back to the SRTT/RTTVAR-computed RTO once
   an *unambiguous* (non-retransmitted) round trip completes.
"""
from __future__ import annotations

ALPHA = 1.0 / 8.0
BETA = 1.0 / 4.0
CLOCK_GRANULARITY_S = 0.001
MAX_BACKOFF = 64
MAX_RTO_S = 60.0


class RttEstimator:
    def __init__(self, min_rto_s: float = 1.0, initial_rto_s: float = 1.0) -> None:
        self.min_rto_s = min_rto_s
        self.srtt: float | None = None
        self.rttvar: float | None = None
        self.base_rto = initial_rto_s
        self.backoff_multiplier = 1
        self.samples_taken = 0

    def sample(self, r: float) -> None:
        """Feed in one unambiguous (non-retransmitted) RTT measurement."""
        if r < 0:
            return
        if self.srtt is None:
            self.srtt = r
            self.rttvar = r / 2.0
        else:
            assert self.rttvar is not None
            self.rttvar = (1 - BETA) * self.rttvar + BETA * abs(self.srtt - r)
            self.srtt = (1 - ALPHA) * self.srtt + ALPHA * r
        self.base_rto = max(self.min_rto_s, self.srtt + max(CLOCK_GRANULARITY_S, 4 * self.rttvar))
        self.samples_taken += 1
        # Karn's algorithm, part 2: an unambiguous round trip completed,
        # so drop back to the base (non-backed-off) RTO.
        self.backoff_multiplier = 1

    def backoff(self) -> None:
        """Called on every retransmission timeout for the *same* segment —
        exponential backoff, per Karn's algorithm part 2 and RFC 6298 §5.5."""
        self.backoff_multiplier = min(self.backoff_multiplier * 2, MAX_BACKOFF)

    @property
    def rto(self) -> float:
        return min(self.base_rto * self.backoff_multiplier, MAX_RTO_S)
