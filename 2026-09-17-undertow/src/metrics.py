"""Ground-truth measurements used both by the experiments and by the tests
that hold this simulator to a real, checkable standard rather than a
plausible-looking chart."""

from __future__ import annotations


def jains_fairness_index(values: list[float]) -> float:
    """Chiu & Jain's fairness index: 1.0 = perfectly fair, 1/n = maximally
    unfair (one flow gets everything). Defined for nonnegative throughputs."""
    n = len(values)
    if n == 0:
        return 0.0
    total = sum(values)
    if total <= 0:
        return 0.0
    return (total ** 2) / (n * sum(v * v for v in values))


def throughput_bps(delivered_segments: int, mss_bytes: int, duration_s: float) -> float:
    if duration_s <= 0:
        return 0.0
    return delivered_segments * mss_bytes * 8 / duration_s


def queueing_delay_series(queue_samples: list[tuple[float, int]], bandwidth_bps: float, mss_bytes: int):
    """Convert (time, queue_length_in_packets) samples into (time,
    queueing_delay_seconds) — how long a packet arriving right now would
    wait behind the packets already queued ahead of it."""
    serialization = mss_bytes * 8 / bandwidth_bps
    return [(t, q * serialization) for t, q in queue_samples]
