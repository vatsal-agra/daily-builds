"""Multi-flow experiment harness: build a topology + N TCP flows, run the
simulator to completion (or a time cap), and record everything a real
network-measurement tool would — per-flow throughput/completion time/loss
counts and time series, plus link-level occupancy and drop stats — so the
canned experiments below can be checked against textbook TCP predictions
instead of eyeballed.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .network import Simulator
from .tcp import Topology, TcpConnection

MSS = 1460


@dataclass
class FlowSpec:
    name: str
    cc_name: str
    data_bytes: int
    access_delay_s: float
    recv_window: int = 65536
    min_rto_s: float = 1.0


@dataclass
class FlowResult:
    name: str
    cc_name: str
    data_bytes: int
    access_delay_s: float
    completed: bool
    completion_time: Optional[float]
    bytes_delivered: int
    throughput_Bps: float
    timeouts: int
    fast_retransmits: int
    segments_sent: int
    verified_correct: bool
    cwnd_series: List[Tuple[float, float]]
    rtt_series: List[Tuple[float, float]]
    inflight_series: List[Tuple[float, int]]


@dataclass
class ExperimentResult:
    name: str
    description: str
    duration_s: float
    bandwidth_Bps: float
    buffer_bytes: int
    dropped_overflow: int
    dropped_random: int
    max_queue_bytes: int
    queue_samples: List[Tuple[float, int]]
    flows: List[FlowResult]
    fairness_index: Optional[float]


def jains_fairness_index(values: List[float]) -> Optional[float]:
    values = [v for v in values if v > 0]
    if not values:
        return None
    n = len(values)
    return (sum(values) ** 2) / (n * sum(v * v for v in values))


def run_experiment(
    name: str,
    description: str,
    flow_specs: List[FlowSpec],
    bandwidth_Bps: float,
    buffer_bytes: int,
    core_prop_delay_s: float,
    fwd_loss_prob: float = 0.0,
    fwd_reorder_prob: float = 0.0,
    sim_duration_cap: float = 120.0,
    seed: int = 1234,
    mss: int = MSS,
) -> ExperimentResult:
    rng = random.Random(seed)
    sim = Simulator()
    topo = Topology(
        sim, bandwidth_Bps, buffer_bytes, core_prop_delay_s,
        fwd_loss_prob=fwd_loss_prob, fwd_reorder_prob=fwd_reorder_prob, rng=rng,
    )

    connections: List[Tuple[FlowSpec, TcpConnection, bytes]] = []
    for i, spec in enumerate(flow_specs):
        data = bytes(rng.getrandbits(8) for _ in range(spec.data_bytes))
        conn = TcpConnection(
            sim, i, topo, data, spec.access_delay_s, mss=mss, cc_name=spec.cc_name,
            recv_window=spec.recv_window, rng=rng, min_rto_s=spec.min_rto_s,
        )
        connections.append((spec, conn, data))

    for _, conn, _ in connections:
        conn.start()

    sim.run(until=sim_duration_cap)
    duration = sim.now

    flow_results: List[FlowResult] = []
    throughputs: List[float] = []
    for spec, conn, data in connections:
        completed = conn.sender.done and conn.receiver.done
        t = conn.sender.done_time if completed else None
        delivered = len(conn.receiver.assembled)
        elapsed = t if (completed and t) else duration
        thpt = delivered / elapsed if elapsed > 0 else 0.0
        throughputs.append(thpt)
        flow_results.append(FlowResult(
            name=spec.name, cc_name=spec.cc_name, data_bytes=spec.data_bytes,
            access_delay_s=spec.access_delay_s, completed=bool(completed),
            completion_time=t, bytes_delivered=delivered, throughput_Bps=thpt,
            timeouts=conn.sender.timeouts, fast_retransmits=conn.sender.fast_retransmits,
            segments_sent=conn.sender.segments_sent,
            verified_correct=bytes(conn.receiver.assembled) == data[:delivered],
            cwnd_series=conn.sender.cwnd_series, rtt_series=conn.sender.rtt_series,
            inflight_series=conn.sender.inflight_series,
        ))

    return ExperimentResult(
        name=name, description=description, duration_s=duration,
        bandwidth_Bps=bandwidth_Bps, buffer_bytes=buffer_bytes,
        dropped_overflow=topo.fwd_link.stats.dropped_overflow,
        dropped_random=topo.fwd_link.stats.dropped_random,
        max_queue_bytes=topo.fwd_link.stats.max_queue_bytes,
        queue_samples=topo.fwd_link.stats.queue_samples,
        flows=flow_results,
        fairness_index=jains_fairness_index(throughputs) if len(throughputs) > 1 else None,
    )


# ---------------------------------------------------------------------------
# Canned experiments. Parameters were chosen (and verified while building
# this) to land in the *interesting* regime for each claim — enough load to
# see real loss/recovery, not so much that the link collapses into
# multi-minute go-back-1 stalls (a real TCP phenomenon under severe/bursty
# loss without SACK, but not a useful demo of the point being made).
# ---------------------------------------------------------------------------

def exp_single_flow_lossy(seed: int = 1) -> ExperimentResult:
    return run_experiment(
        name="single-flow-lossy",
        description=(
            "One Reno flow over a lossy, reordering link (1% independent loss, "
            "2% reordering). Demonstrates real loss recovery (fast retransmit "
            "and/or RTO) and — the actual correctness claim — byte-for-byte "
            "correct reassembly of the whole transferred payload despite it."
        ),
        flow_specs=[FlowSpec("reno", "reno", 1_500_000, access_delay_s=0.02)],
        bandwidth_Bps=1_000_000, buffer_bytes=100_000, core_prop_delay_s=0.01,
        fwd_loss_prob=0.01, fwd_reorder_prob=0.02, sim_duration_cap=120.0, seed=seed,
    )


def exp_fairness_equal_rtt(seed: int = 2) -> ExperimentResult:
    specs = [FlowSpec(f"reno-{i+1}", "reno", 2_000_000, access_delay_s=0.02) for i in range(3)]
    return run_experiment(
        name="fairness-equal-rtt",
        description=(
            "Three Reno flows with identical RTT sharing one bottleneck link. "
            "AIMD's classic fairness result predicts their throughputs converge "
            "to roughly equal shares — checked here via Jain's fairness index "
            "(1.0 = perfectly fair)."
        ),
        flow_specs=specs, bandwidth_Bps=1_000_000, buffer_bytes=150_000,
        core_prop_delay_s=0.01, sim_duration_cap=120.0, seed=seed,
    )


def exp_rtt_unfairness(seed: int = 3) -> ExperimentResult:
    specs = [
        FlowSpec("reno-short-rtt", "reno", 3_000_000, access_delay_s=0.01),
        FlowSpec("reno-long-rtt", "reno", 3_000_000, access_delay_s=0.08),
    ]
    return run_experiment(
        name="rtt-unfairness",
        description=(
            "Two Reno flows, same algorithm, different RTT (short-RTT flow's "
            "access delay is 8x the long-RTT flow's). Congestion avoidance "
            "grows cwnd ~1 MSS per RTT, so more RTTs/sec means faster growth: "
            "the short-RTT flow should win a majority of the bottleneck's "
            "throughput — well-known real TCP RTT bias, not scripted here."
        ),
        flow_specs=specs, bandwidth_Bps=1_000_000, buffer_bytes=150_000,
        core_prop_delay_s=0.01, sim_duration_cap=120.0, seed=seed,
    )


def exp_reno_vs_tahoe(seed: int = 4) -> ExperimentResult:
    specs = [
        FlowSpec("reno", "reno", 3_000_000, access_delay_s=0.02),
        FlowSpec("tahoe", "tahoe", 3_000_000, access_delay_s=0.02),
    ]
    return run_experiment(
        name="reno-vs-tahoe",
        description=(
            "A Reno flow and a Tahoe flow, identical RTT, sharing one link "
            "with 0.5% independent loss. Tahoe collapses to slow start "
            "(cwnd -> 1 MSS) on every loss signal; Reno fast-recovers "
            "(cwnd -> ssthresh). Reno should finish noticeably faster."
        ),
        flow_specs=specs, bandwidth_Bps=1_000_000, buffer_bytes=100_000,
        core_prop_delay_s=0.01, fwd_loss_prob=0.005, sim_duration_cap=120.0, seed=seed,
    )


def exp_reno_vs_cubic_high_bdp(seed: int = 5) -> ExperimentResult:
    return {
        "reno": run_experiment(
            name="high-bdp-reno",
            description="A single Reno flow alone on a high bandwidth-delay-product "
                        "path (10 Mbit/s x ~110ms RTT) with light independent loss.",
            flow_specs=[FlowSpec("reno", "reno", 20_000_000, access_delay_s=0.045)],
            bandwidth_Bps=10_000_000, buffer_bytes=1_000_000, core_prop_delay_s=0.01,
            fwd_loss_prob=0.0005, sim_duration_cap=300.0, seed=seed,
        ),
        "cubic": run_experiment(
            name="high-bdp-cubic",
            description="The same transfer, same path, same loss — CUBIC instead of "
                        "Reno. CUBIC's cubic (not linear) window growth should reach "
                        "a higher steady-state window, and finish faster, on a path "
                        "this large.",
            flow_specs=[FlowSpec("cubic", "cubic", 20_000_000, access_delay_s=0.045)],
            bandwidth_Bps=10_000_000, buffer_bytes=1_000_000, core_prop_delay_s=0.01,
            fwd_loss_prob=0.0005, sim_duration_cap=300.0, seed=seed,
        ),
    }


CANNED_EXPERIMENTS = {
    "single-flow-lossy": exp_single_flow_lossy,
    "fairness-equal-rtt": exp_fairness_equal_rtt,
    "rtt-unfairness": exp_rtt_unfairness,
    "reno-vs-tahoe": exp_reno_vs_tahoe,
}


def run_all_named() -> List[Tuple[str, ExperimentResult]]:
    """Every canned experiment, flattened to (label, ExperimentResult) pairs
    — used by both `throttle viz` (one report covering everything) and
    `demo.sh` (one thing to iterate over and assert against)."""
    out: List[Tuple[str, ExperimentResult]] = []
    for key, fn in CANNED_EXPERIMENTS.items():
        out.append((key, fn()))
    hb = exp_reno_vs_cubic_high_bdp()
    out.append(("high-bdp-reno", hb["reno"]))
    out.append(("high-bdp-cubic", hb["cubic"]))
    return out
