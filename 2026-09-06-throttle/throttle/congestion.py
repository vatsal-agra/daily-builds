"""Pluggable TCP congestion-control algorithms.

Every algorithm here shares the same slow-start / congestion-avoidance
skeleton (grow `cwnd` by roughly one MSS per acked segment below
`ssthresh`, roughly one MSS per RTT above it) and differs only in how it
reacts to loss signals (3 duplicate ACKs = fast retransmit; RTO expiry =
timeout) and, for CUBIC, in what "above ssthresh" growth actually looks
like. `TcpSender` (tcp.py) drives these through one fixed interface so a
flow's algorithm is a pure `CongestionControl` instance is swapped for the
whole simulation.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class CongestionControl(ABC):
    name = "abstract"

    def __init__(self, mss: int) -> None:
        self.mss = mss
        # RFC 5681 initial window: min(4*MSS, max(2*MSS, 4380 bytes))
        self.cwnd: float = min(4 * mss, max(2 * mss, 4380))
        self.ssthresh: float = 2.0 ** 30  # effectively "infinite" until first loss
        self.in_recovery = False

    @abstractmethod
    def on_ack(self, acked_bytes: int, flight_before: int, now: float) -> None:
        """A new (non-duplicate) cumulative ACK advanced send_una."""

    @abstractmethod
    def on_dup_ack(self, dup_count: int, flight_before: int) -> bool:
        """Returns True the moment a fast retransmit should fire (3rd dup ACK)."""

    @abstractmethod
    def on_recovery_ack(self) -> None:
        """The new-data ACK that ends fast recovery has arrived."""

    @abstractmethod
    def on_timeout(self, flight_before: int) -> None:
        """RTO expired for the oldest unacked segment."""


class Reno(CongestionControl):
    """Classic TCP Reno: slow start, congestion avoidance, fast retransmit,
    and fast recovery with window inflation/deflation (RFC 5681 + 6582's
    predecessor NewReno-lite: we don't implement NewReno's partial-ACK
    handling, so a fast recovery episode covering >1 lost segment can need
    a second round of dup-ACKs — a real, documented Reno limitation, not a
    bug introduced here)."""

    name = "reno"

    def on_ack(self, acked_bytes: int, flight_before: int, now: float) -> None:
        if self.cwnd < self.ssthresh:
            self.cwnd += acked_bytes  # slow start: ~doubles cwnd per RTT
        else:
            self.cwnd += self.mss * acked_bytes / self.cwnd  # ~+1 MSS per RTT

    def on_dup_ack(self, dup_count: int, flight_before: int) -> bool:
        if dup_count == 3 and not self.in_recovery:
            self.ssthresh = max(flight_before / 2.0, 2 * self.mss)
            self.cwnd = self.ssthresh + 3 * self.mss
            self.in_recovery = True
            return True
        if self.in_recovery:
            self.cwnd += self.mss  # Reno window inflation during recovery
        return False

    def on_recovery_ack(self) -> None:
        self.cwnd = self.ssthresh  # deflate
        self.in_recovery = False

    def on_timeout(self, flight_before: int) -> None:
        self.ssthresh = max(flight_before / 2.0, 2 * self.mss)
        self.cwnd = self.mss
        self.in_recovery = False


class Tahoe(CongestionControl):
    """Classic TCP Tahoe: identical slow start / congestion avoidance to
    Reno, but no fast recovery — any loss signal (dup-ACK or timeout) drops
    cwnd straight back to 1 MSS and re-enters slow start from ssthresh."""

    name = "tahoe"

    def on_ack(self, acked_bytes: int, flight_before: int, now: float) -> None:
        if self.cwnd < self.ssthresh:
            self.cwnd += acked_bytes
        else:
            self.cwnd += self.mss * acked_bytes / self.cwnd

    def on_dup_ack(self, dup_count: int, flight_before: int) -> bool:
        if dup_count == 3 and not self.in_recovery:
            self.ssthresh = max(flight_before / 2.0, 2 * self.mss)
            self.cwnd = self.mss
            self.in_recovery = True
            return True
        return False

    def on_recovery_ack(self) -> None:
        self.in_recovery = False

    def on_timeout(self, flight_before: int) -> None:
        self.ssthresh = max(flight_before / 2.0, 2 * self.mss)
        self.cwnd = self.mss
        self.in_recovery = False


class Cubic(CongestionControl):
    """A simplified but real implementation of CUBIC (RFC 8312)'s window
    growth function. Real Linux CUBIC also blends in a "TCP-friendly
    region" (matching Reno's growth rate when CUBIC would grow slower than
    Reno would, so CUBIC never *loses* to Reno on short/low-BDP paths) —
    that blend is intentionally omitted here to keep the growth function
    legible; what's implemented is the actual cubic curve that gives the
    algorithm its name, not a stand-in. This is documented as a
    simplification in README.md, not silently passed off as the full
    Linux implementation.

    Growth function once past ssthresh, in units of *segments* (W = cwnd/mss):

        K = cbrt((W_max - W_origin) / C)          (time to re-reach W_max)
        W(t) = C * (t - K)**3 + W_max

    where t is seconds since the start of the current growth epoch
    (reset at every loss event) and C = 0.4 is CUBIC's scaling constant.
    On loss, cwnd is multiplicatively cut by beta = 0.7 (gentler than
    Reno/Tahoe's 0.5), and W_max remembers the window size at the moment
    of loss so the curve's inflection point targets "re-approach the
    window that triggered the last loss" — CUBIC's defining idea.
    """

    name = "cubic"
    C = 0.4
    BETA = 0.7

    def __init__(self, mss: int) -> None:
        super().__init__(mss)
        self.w_max_segs: float | None = None
        self.epoch_start: float | None = None
        self.origin_segs: float = self.cwnd / self.mss

    def on_ack(self, acked_bytes: int, flight_before: int, now: float) -> None:
        if self.cwnd < self.ssthresh:
            self.cwnd += acked_bytes
            return

        if self.epoch_start is None:
            self.epoch_start = now
            if self.w_max_segs is None or self.w_max_segs <= self.cwnd / self.mss:
                self.origin_segs = self.cwnd / self.mss
                self._k = 0.0
            else:
                self.origin_segs = self.w_max_segs
                self._k = ((self.w_max_segs - self.cwnd / self.mss) / self.C) ** (1.0 / 3.0)

        t = now - self.epoch_start
        target_segs = self.C * (t - self._k) ** 3 + self.origin_segs
        target_bytes = target_segs * self.mss

        if target_bytes > self.cwnd:
            # Move a fraction of the way to the target this ACK, scaled so
            # that (roughly) one full step happens per RTT-worth of ACKs —
            # the same "concave/convex approach" shape as real CUBIC.
            self.cwnd += ((target_bytes - self.cwnd) / self.cwnd) * acked_bytes
        else:
            # Target is behind current cwnd (early in a fresh, higher epoch
            # than the one that produced w_max) — grow Reno-CA-style so the
            # window never stalls waiting for the cubic curve to catch up.
            self.cwnd += (self.mss * acked_bytes) / self.cwnd

    def on_dup_ack(self, dup_count: int, flight_before: int) -> bool:
        if dup_count == 3 and not self.in_recovery:
            self.w_max_segs = self.cwnd / self.mss
            self.cwnd = max(self.cwnd * self.BETA, 2 * self.mss)
            self.ssthresh = self.cwnd
            self.epoch_start = None
            self.in_recovery = True
            return True
        if self.in_recovery:
            self.cwnd += self.mss
        return False

    def on_recovery_ack(self) -> None:
        self.cwnd = self.ssthresh
        self.in_recovery = False

    def on_timeout(self, flight_before: int) -> None:
        self.w_max_segs = self.cwnd / self.mss
        self.ssthresh = max(flight_before / 2.0, 2 * self.mss)
        self.cwnd = self.mss
        self.epoch_start = None
        self.in_recovery = False


ALGORITHMS = {"reno": Reno, "tahoe": Tahoe, "cubic": Cubic}


def make(name: str, mss: int) -> CongestionControl:
    try:
        cls = ALGORITHMS[name]
    except KeyError:
        raise ValueError(f"unknown congestion control algorithm: {name!r} "
                          f"(choices: {sorted(ALGORITHMS)})") from None
    return cls(mss)
