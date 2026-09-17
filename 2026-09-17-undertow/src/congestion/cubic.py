"""TCP CUBIC (RFC 8312), the Linux default since 2.6.19.

Reno grows its window once per *ACK*, which means once per RTT for a fixed
window — so a flow with half the RTT of a competitor gets roughly twice as
many growth opportunities per second (RTT unfairness). CUBIC's window is
instead a cubic function of *wall-clock time* since the last congestion
event:

    W_cubic(t) = C * (t - K)**3 + W_max

where W_max is the window size at the last loss, C is a scaling constant
(0.4), and K = cbrt((W_max - cwnd_after_decrease) / C) is chosen so the
curve is continuous with the post-decrease window at t=0. The curve is
concave (decelerating growth) approaching W_max — "remembering" where the
network last complained — then convex (accelerating growth) past it,
probing for new capacity. Because t is real elapsed time rather than
RTT-count, two CUBIC flows with different RTTs see approximately the same
growth curve, which is what makes CUBIC materially fairer across
mixed-RTT paths than Reno.

RFC 8312 also defines a "TCP-friendly region": below convergence points
where Reno would grow faster than the raw cubic function, CUBIC's window
tracks an estimate of what a competing Reno flow would achieve instead, so
CUBIC never falls meaningfully behind Reno on the same path. Both regions
are implemented below (Sec. 4.2 and 4.3 of RFC 8312, September 2021, in
their non-HyStart form — HyStart's slow-start exit heuristic is out of
scope for this build).
"""

from __future__ import annotations

from .base import MIN_CWND, CongestionControl

C = 0.4
BETA_CUBIC = 0.7


class Cubic(CongestionControl):
    name = "cubic"

    def __init__(self, init_cwnd: float = 1.0, init_ssthresh: float = 64.0):
        super().__init__(init_cwnd, init_ssthresh)
        self.w_max: float | None = None
        self.epoch_start: float | None = None
        self.origin_point = 0.0
        self.k = 0.0
        self.last_rtt = 0.1  # seconds; refined by real RTT samples as they arrive

    def on_ack(self, now: float, rtt_sample, acked_packets: int = 1, inflight: float | None = None) -> None:
        if rtt_sample is not None:
            self.last_rtt = rtt_sample

        if self.cwnd < self.ssthresh:
            # Slow start is identical across every loss-based algorithm.
            self.cwnd += acked_packets
            return

        if self.epoch_start is None:
            self.epoch_start = now
            if self.w_max is None or self.w_max <= self.cwnd:
                self.k = 0.0
                self.origin_point = self.cwnd
            else:
                self.k = ((self.w_max - self.cwnd) / C) ** (1.0 / 3.0)
                self.origin_point = self.w_max

        t = now - self.epoch_start
        w_cubic = C * (t - self.k) ** 3 + self.origin_point

        # TCP-friendly region (RFC 8312 sec. 4.2): what plain Reno AIMD
        # would have reached by elapsed time t, at ~1 packet/RTT growth
        # scaled by the post-decrease window.
        w_est = self.origin_point * BETA_CUBIC + (
            3 * (1 - BETA_CUBIC) / (1 + BETA_CUBIC)
        ) * (t / max(self.last_rtt, 1e-6))

        # cwnd is a pure function of elapsed time since the epoch started,
        # so each ACK simply re-evaluates that function at the current
        # time rather than accumulating a per-ACK increment.
        target = max(w_cubic, w_est, MIN_CWND)
        self.cwnd = max(target, MIN_CWND)

    def on_loss_event(self, now: float) -> None:
        self.w_max = self.cwnd
        self.ssthresh = max(self.cwnd * BETA_CUBIC, 2.0)
        self.cwnd = max(self.ssthresh, MIN_CWND)
        self.epoch_start = None
