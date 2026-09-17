"""BBR-lite: Bottleneck Bandwidth and RTT (Cardwell et al., 2016).

Reno and CUBIC are both *loss-based*: they keep growing the window until
something drops, so on a deep queue they will happily fill it before ever
backing off (bufferbloat). BBR instead builds an explicit model of the
path — the highest delivery rate it has recently observed (``bw_max``,
a windowed max, since delivery rate estimates *at* the bottleneck are
accurate but delivery rate *below* it under-estimates capacity) and the
lowest RTT it has recently observed (``min_rtt``, a windowed min, taken as
a proxy for the propagation delay with no queueing) — and paces its window
to the resulting bandwidth-delay product (BDP), so it converges to a
*shallow* queue instead of a full one.

This is a "lite" implementation: it controls cwnd directly (this
simulator's senders are window-clocked, not independently rate-paced, so
there is no separate pacing-rate actuator to drive), it shortens BBR's real
eight-phase PROBE_BW gain cycle to four phases, and it approximates BBR's
packet-conservation "round trip" counting with a simulated-time proxy based
on the current min_rtt estimate rather than tracking delivery sequence
markers. The four state-machine phases (STARTUP, DRAIN, PROBE_BW,
PROBE_RTT) and the windowed bandwidth/RTT filters are otherwise real.
"""

from __future__ import annotations

from .base import MIN_CWND, CongestionControl

STARTUP_GAIN = 2.0 / 0.6931471805599453  # 2/ln(2), real BBR's exponential-growth gain
DRAIN_GAIN = 1.0 / STARTUP_GAIN
PROBE_BW_CYCLE = [1.25, 0.75, 1.0, 1.0]  # shortened from real BBR's 8-phase cycle
CWND_GAIN = 2.0
PROBE_RTT_CWND = 4.0
RTPROP_WINDOW_S = 10.0
BW_WINDOW_ROUNDS = 6
PROBE_RTT_MIN_DURATION_S = 0.2


class BBR(CongestionControl):
    name = "bbr"

    def __init__(self, init_cwnd: float = 1.0, init_ssthresh: float = 1e9):
        super().__init__(init_cwnd, init_ssthresh)
        self.mode = "STARTUP"
        self.bw_samples: list[tuple[float, float]] = []  # (time, packets/sec)
        self.bw_max = 0.0
        self.min_rtt: float | None = None
        self.min_rtt_time = 0.0
        self._last_ack_time: float | None = None
        self._full_bw = 0.0
        self._full_bw_rounds = 0
        self._round_start = 0.0
        self._round_len = 0.2  # seconds; refined to min_rtt once known
        self._cycle_idx = 0
        self._probe_rtt_deadline: float | None = None
        self._pre_probe_mode = "PROBE_BW"

    # -- windowed filters -------------------------------------------------
    def _update_bw(self, now: float, acked_packets: int) -> None:
        if self._last_ack_time is not None:
            dt = now - self._last_ack_time
            if dt > 1e-9:
                self.bw_samples.append((now, acked_packets / dt))
        self._last_ack_time = now
        window_start = now - self._round_len * BW_WINDOW_ROUNDS
        self.bw_samples = [(t, b) for (t, b) in self.bw_samples if t >= window_start]
        self.bw_max = max((b for _, b in self.bw_samples), default=self.bw_max)

    def _update_min_rtt(self, now: float, rtt_sample) -> None:
        if rtt_sample is None:
            return
        if self.min_rtt is None or rtt_sample <= self.min_rtt:
            self.min_rtt = rtt_sample
            self.min_rtt_time = now
            self._round_len = max(rtt_sample, 0.01)

    def _bdp(self) -> float:
        if self.min_rtt is None or self.bw_max <= 0:
            return self.cwnd
        return self.bw_max * self.min_rtt

    # -- state machine ------------------------------------------------------
    def on_ack(self, now: float, rtt_sample, acked_packets: int = 1, inflight: float | None = None) -> None:
        self._update_bw(now, acked_packets)
        self._update_min_rtt(now, rtt_sample)

        if self.mode == "PROBE_RTT":
            if self._probe_rtt_deadline is None:
                self._probe_rtt_deadline = now + max(PROBE_RTT_MIN_DURATION_S, self._round_len)
            self.cwnd = PROBE_RTT_CWND
            if now >= self._probe_rtt_deadline:
                self.mode = self._pre_probe_mode
                self._probe_rtt_deadline = None
                self.min_rtt_time = now
            return

        # Any mode other than PROBE_RTT: check whether RTProp is stale
        # enough to warrant re-measuring it with a shallow window.
        if self.min_rtt is not None and now - self.min_rtt_time > RTPROP_WINDOW_S:
            self._pre_probe_mode = self.mode
            self.mode = "PROBE_RTT"
            self._probe_rtt_deadline = None
            return

        if now - self._round_start >= self._round_len:
            self._round_start = now
            self._advance_round(inflight)

        bdp = self._bdp()
        if self.mode == "STARTUP":
            self.cwnd = max(STARTUP_GAIN * bdp, self.cwnd + acked_packets)
        elif self.mode == "DRAIN":
            self.cwnd = max(DRAIN_GAIN * bdp, MIN_CWND)
        else:  # PROBE_BW
            gain = PROBE_BW_CYCLE[self._cycle_idx % len(PROBE_BW_CYCLE)]
            self.cwnd = max(gain * CWND_GAIN * bdp, MIN_CWND)
        self.cwnd = max(self.cwnd, MIN_CWND)

    def _advance_round(self, inflight: float | None) -> None:
        if self.mode == "STARTUP":
            if self.bw_max > self._full_bw * 1.25:
                self._full_bw = self.bw_max
                self._full_bw_rounds = 0
            else:
                self._full_bw_rounds += 1
                if self._full_bw_rounds >= 3:
                    self.mode = "DRAIN"
        elif self.mode == "DRAIN":
            bdp = self._bdp()
            if inflight is None or inflight <= max(bdp, MIN_CWND):
                self.mode = "PROBE_BW"
                self._cycle_idx = 0
        else:  # PROBE_BW
            self._cycle_idx += 1

    def on_loss_event(self, now: float) -> None:
        # BBR does not treat loss as the primary congestion signal; it
        # still must not let cwnd run away under sustained heavy loss, so
        # apply a mild multiplicative backoff without touching the
        # bandwidth/RTT model or leaving PROBE_BW/STARTUP.
        self.ssthresh = max(self.cwnd * 0.7, 2.0)
        self.cwnd = max(self.cwnd * 0.85, MIN_CWND)
