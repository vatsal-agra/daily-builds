"""Scenario builders. Every experiment wires real Flow objects into a real
shared Network/Bottleneck and lets the discrete-event simulator run — the
phenomena reported here (fairness convergence, RTT unfairness, bufferbloat,
BBR's shallow queue) are measured outcomes of the simulation, not asserted
inputs.
"""

from __future__ import annotations

import bisect
import random

from .congestion import ALGORITHMS
from .congestion.base import CongestionControl
from .flow import MSS, Flow
from .metrics import jains_fairness_index, throughput_bps
from .network import EventQueue, Network, REDConfig

BULK_PACKETS = 10 ** 7  # effectively-infinite bulk data; never exhausted in-run


def _default_red(capacity, min_frac, max_frac, max_p=0.1):
    """A RED config sized off the buffer capacity, clamped so it stays
    valid (min_th < max_th) even for a tiny capacity where naive
    percentages would collapse to the same integer or invert."""
    min_th = max(1, int(capacity * min_frac))
    max_th = max(min_th + 1, min(capacity, int(capacity * max_frac)))
    return REDConfig(min_th=min_th, max_th=max_th, max_p=max_p)


class _PingCC(CongestionControl):
    """A fixed-window (cwnd=1) 'controller' used only as a latency probe in
    the bufferbloat demo: it never grows its window, so its measured RTT is
    a clean readout of the queueing delay the shared bottleneck imposes on
    a lightweight interactive flow, independent of its own behavior."""

    name = "ping"

    def on_ack(self, now, rtt_sample, acked_packets=1, inflight=None) -> None:
        pass

    def on_loss_event(self, now) -> None:
        pass


def _build_network(bandwidth_bps, capacity_packets, core_prop_delay_s, red=None, seed=1):
    ev = EventQueue()
    rng = random.Random(seed)
    network = Network(ev, bandwidth_bps, capacity_packets, core_prop_delay_s, red=red, rng=rng)
    return ev, network


def _add_flow(ev, network, flow_id, name, algo, access_delay_s,
              total_packets=BULK_PACKETS, start_delay=0.0, cc_override=None):
    cc = cc_override if cc_override is not None else ALGORITHMS[algo]()
    flow = Flow(flow_id, name, ev, network, cc, total_packets, access_delay_s)
    network.add_flow(flow)
    ev.schedule(start_delay, flow.start)
    return flow


def _cumulative_delivered_at(delivery_log, t):
    times = [x[0] for x in delivery_log]
    idx = bisect.bisect_right(times, t) - 1
    return 0 if idx < 0 else delivery_log[idx][1]


def _interval_throughput(flow, t0, t1):
    d0 = _cumulative_delivered_at(flow.receiver.delivery_log, t0)
    d1 = _cumulative_delivered_at(flow.receiver.delivery_log, t1)
    return throughput_bps(d1 - d0, MSS, t1 - t0)


def _fairness_time_series(flows, duration_s, step=0.5):
    series = []
    t = step
    prev = {f.flow_id: 0 for f in flows}
    while t <= duration_s + 1e-9:
        cum = {f.flow_id: _cumulative_delivered_at(f.receiver.delivery_log, t) for f in flows}
        interval_counts = [cum[f.flow_id] - prev[f.flow_id] for f in flows]
        series.append((t, jains_fairness_index(interval_counts)))
        prev = cum
        t += step
    return series


def _flow_result(flow, duration_s):
    delivered = flow.receiver.delivered_count
    return {
        "name": flow.name,
        "algorithm": flow.cc.name,
        "delivered_segments": delivered,
        "throughput_bps": throughput_bps(delivered, MSS, duration_s),
        "cwnd_series": flow.sender.samples,
        "loss_events": flow.sender.loss_events,
        "delivery_log": flow.receiver.delivery_log,
        "base_rtt_s": 2 * flow.base_owd(),
    }


# ---------------------------------------------------------------------------
# Experiment 1: a single flow — sanity-checks slow start / AIMD / cubic in
# isolation before any multi-flow contention is introduced.
# ---------------------------------------------------------------------------

def run_single_flow(algo="reno", duration_s=20.0, bandwidth_bps=2_000_000,
                     capacity=50, core_prop_delay_s=0.005, access_delay_s=0.005, seed=1):
    ev, network = _build_network(bandwidth_bps, capacity, core_prop_delay_s, seed=seed)
    flow = _add_flow(ev, network, 0, algo, algo, access_delay_s)
    ev.run_until(duration_s)
    return {
        "duration_s": duration_s,
        "flows": [_flow_result(flow, duration_s)],
        "queue_samples": network.bottleneck.queue_samples,
        "drop_count": network.bottleneck.drop_count,
        "_network": network,
    }


# ---------------------------------------------------------------------------
# Experiment 2: AIMD fairness convergence — N identical-RTT flows of the
# same algorithm sharing one bottleneck should converge to a fair split
# (Chiu & Jain, 1989) regardless of arrival order.
# ---------------------------------------------------------------------------

def run_fairness_same_rtt(algo="reno", n_flows=2, duration_s=40.0, bandwidth_bps=2_000_000,
                           capacity=150, core_prop_delay_s=0.005, access_delay_s=0.005, seed=1,
                           red=True):
    # capacity=150 is deliberately larger than the ~64-packet ceiling slow
    # start reaches before any flow has ever lost a packet (cwnd starts
    # unconstrained, by design, exactly like real TCP): a shallow buffer
    # (this repo's bufferbloat demo uses 50-200 on purpose, to study
    # queueing delay) turns that first overshoot into a multi-segment loss
    # burst so large that, without SACK, cumulative-ACK recovery can take
    # many RTOs per lost segment — realistic, but it swamps the fairness
    # signal this experiment is trying to isolate. A buffer sized above the
    # overshoot ceiling keeps the first loss event survivable in one or two
    # recovery rounds, matching how real fairness studies size buffers to
    # the path's bandwidth-delay product rather than deliberately
    # under-provisioning them.
    # RED, not drop-tail, is the default here on purpose: drop-tail is a
    # strictly synchronous, deterministic admission rule, so in a
    # deterministic discrete-event simulator (no jitter, no OS scheduling
    # noise) two competing flows can fall into exact phase-lock, where one
    # flow's retransmission timer always fires at the instant the other
    # flow's burst has the queue full — a lock-out artifact of determinism
    # itself, not of the algorithms under test. This is precisely the
    # failure mode RED was invented to break (Floyd & Jacobson, 1993): its
    # randomized early drops desynchronize competing flows so steady-state
    # fairness reflects the congestion-control algorithm, not simulator
    # determinism. Drop-tail is used deliberately instead in the
    # bufferbloat experiment, where reproducing exactly this kind of
    # queue-dominating behavior is the point.
    red_cfg = _default_red(capacity, 0.3, 0.9) if red else None
    ev, network = _build_network(bandwidth_bps, capacity, core_prop_delay_s, red=red_cfg, seed=seed)
    flows = [
        _add_flow(ev, network, i, f"{algo}-{i}", algo, access_delay_s, start_delay=0.05 * i)
        for i in range(n_flows)
    ]
    ev.run_until(duration_s)
    fairness_series = _fairness_time_series(flows, duration_s)
    return {
        "duration_s": duration_s,
        "flows": [_flow_result(f, duration_s) for f in flows],
        "fairness_series": fairness_series,
        "final_fairness": fairness_series[-1][1] if fairness_series else 0.0,
        "queue_samples": network.bottleneck.queue_samples,
        "drop_count": network.bottleneck.drop_count,
        "_network": network,
    }


# ---------------------------------------------------------------------------
# Experiment 3: RTT unfairness — two flows of the same algorithm, different
# base RTTs, same bottleneck. Reno's per-RTT-clocked additive increase
# should give the short-RTT flow a disproportionate share; CUBIC's
# real-time-clocked growth should narrow that gap on the identical topology.
# ---------------------------------------------------------------------------

def _run_rtt_unfairness_trial(algo, duration_s, bandwidth_bps, capacity,
                               core_prop_delay_s, short_access_delay_s, long_access_delay_s,
                               seed, red_cfg):
    ev, network = _build_network(bandwidth_bps, capacity, core_prop_delay_s, red=red_cfg, seed=seed)
    fast = _add_flow(ev, network, 0, f"{algo}-shortRTT", algo, short_access_delay_s)
    slow = _add_flow(ev, network, 1, f"{algo}-longRTT", algo, long_access_delay_s, start_delay=0.05)
    ev.run_until(duration_s)

    steady_from = duration_s * 0.5  # ignore slow-start transient, measure steady state
    fast_thr = _interval_throughput(fast, steady_from, duration_s)
    slow_thr = _interval_throughput(slow, steady_from, duration_s)
    ratio = (fast_thr / slow_thr) if slow_thr > 0 else float("inf")
    return {
        "seed": seed,
        "duration_s": duration_s,
        "flows": [_flow_result(fast, duration_s), _flow_result(slow, duration_s)],
        "steady_throughput_bps": {"short_rtt": fast_thr, "long_rtt": slow_thr},
        "throughput_ratio_short_over_long": ratio,
        "rtt_ratio_long_over_short": (2 * slow.base_owd()) / (2 * fast.base_owd()),
        "queue_samples": network.bottleneck.queue_samples,
        "_network": network,
    }


def run_rtt_unfairness(algo="reno", duration_s=60.0, bandwidth_bps=2_000_000, capacity=150,
                        core_prop_delay_s=0.005, short_access_delay_s=0.005,
                        long_access_delay_s=0.035, seed=1, red=True, n_trials=15):
    # A single 60-second trial covers only a handful of loss/recovery
    # epochs per flow, so which flow happens to eat a rare, unlucky,
    # multi-RTO stall (an inherent, realistic possibility for
    # non-SACK cumulative-ACK recovery — see REVIEW.md) dominates a
    # single run's throughput ratio and can even flip its sign. Real
    # fairness studies address exactly this by averaging many independent
    # trials rather than trusting one; n_trials=15 (distinct RNG seeds)
    # does the same here, and is what the textbook RTT-unfairness claim
    # (throughput_ratio_short_over_long) and the CUBIC-vs-Reno fairness
    # comparison are measured against. See run_fairness_same_rtt for why
    # RED, not drop-tail, is the admission policy for a fairness
    # measurement in a fully deterministic simulator.
    red_cfg_factory = (lambda: _default_red(capacity, 0.3, 0.9)) if red else (lambda: None)
    trials = [
        _run_rtt_unfairness_trial(algo, duration_s, bandwidth_bps, capacity, core_prop_delay_s,
                                   short_access_delay_s, long_access_delay_s, seed + i, red_cfg_factory())
        for i in range(n_trials)
    ]
    ratios = [t["throughput_ratio_short_over_long"] for t in trials]
    # Pool total delivered bytes across trials before taking the ratio,
    # rather than averaging the N per-trial ratios directly: a trial where
    # the long-RTT flow is (rarely, but realistically — see the n_trials
    # docstring above) almost entirely starved has a near-zero denominator,
    # so its ratio can be a wild outlier (seen empirically: single values
    # >70x) that would dominate a plain arithmetic mean of ratios even
    # though that trial delivered almost no data either way. Pooling bytes
    # first weights every trial by how much it actually transferred.
    total_fast = sum(t["steady_throughput_bps"]["short_rtt"] for t in trials)
    total_slow = sum(t["steady_throughput_bps"]["long_rtt"] for t in trials)
    pooled_ratio = (total_fast / total_slow) if total_slow > 0 else float("inf")
    representative = trials[0]
    return {
        "duration_s": duration_s,
        "n_trials": n_trials,
        "flows": representative["flows"],
        "steady_throughput_bps": representative["steady_throughput_bps"],
        "throughput_ratio_short_over_long": representative["throughput_ratio_short_over_long"],
        "pooled_throughput_ratio_short_over_long": pooled_ratio,
        "per_trial_ratios": ratios,
        "rtt_ratio_long_over_short": representative["rtt_ratio_long_over_short"],
        "queue_samples": representative["queue_samples"],
        "_network": representative["_network"],
    }


# ---------------------------------------------------------------------------
# Experiment 4: bufferbloat — a bulk loss-based flow sharing a deep
# drop-tail queue with a latency-sensitive "ping" flow; optionally replay
# the identical scenario with RED active queue management.
# ---------------------------------------------------------------------------

def run_bufferbloat(algo="reno", use_red=False, duration_s=30.0, bandwidth_bps=2_000_000,
                     capacity=200, core_prop_delay_s=0.005, access_delay_s=0.005, seed=1):
    red = _default_red(capacity, 0.2, 0.8) if use_red else None
    ev, network = _build_network(bandwidth_bps, capacity, core_prop_delay_s, red=red, seed=seed)
    bulk = _add_flow(ev, network, 0, f"bulk-{algo}", algo, access_delay_s)
    ping = _add_flow(ev, network, 1, "ping", None, access_delay_s, cc_override=_PingCC())
    ev.run_until(duration_s)

    base_rtt = 2 * ping.base_owd()
    steady_samples = [(t, srtt) for (t, cwnd, srtt) in ping.sender.samples if srtt is not None and t > duration_s * 0.3]
    mean_ping_rtt = sum(s for _, s in steady_samples) / len(steady_samples) if steady_samples else base_rtt
    max_ping_rtt = max((s for _, s in steady_samples), default=base_rtt)
    utilization = _interval_throughput(bulk, duration_s * 0.3, duration_s) / bandwidth_bps
    return {
        "duration_s": duration_s,
        "use_red": use_red,
        "flows": [_flow_result(bulk, duration_s), _flow_result(ping, duration_s)],
        "base_rtt_s": base_rtt,
        "mean_ping_rtt_s": mean_ping_rtt,
        "max_ping_rtt_s": max_ping_rtt,
        "bloat_ratio": mean_ping_rtt / base_rtt if base_rtt > 0 else float("inf"),
        "bottleneck_utilization": utilization,
        "queue_samples": network.bottleneck.queue_samples,
        "drop_count": network.bottleneck.drop_count,
        "_network": network,
    }


# ---------------------------------------------------------------------------
# Experiment 5 (stretch): BBR-lite vs a loss-based algorithm on an identical,
# generously-buffered bottleneck — BBR's whole premise is holding a shallow
# queue at full utilization instead of filling whatever buffer it's given.
# ---------------------------------------------------------------------------

def run_bbr_vs_loss_based(loss_algo="cubic", duration_s=30.0, bandwidth_bps=2_000_000,
                           capacity=150, core_prop_delay_s=0.005, access_delay_s=0.005, seed=1):
    # capacity=150: see run_fairness_same_rtt for why a deep (e.g. 300+)
    # buffer is deliberately avoided outside the bufferbloat experiment —
    # without SACK, a loss-based flow whose window overshoots a deep
    # buffer can drop so many segments in one burst that cumulative-ACK
    # recovery (one segment repaired per round trip, see flow.py) takes
    # far longer than is useful for isolating this experiment's actual
    # question, which is queue depth at steady state, not recovery speed.
    results = {}
    for algo in (loss_algo, "bbr"):
        ev, network = _build_network(bandwidth_bps, capacity, core_prop_delay_s, seed=seed)
        flow = _add_flow(ev, network, 0, algo, algo, access_delay_s)
        ev.run_until(duration_s)
        steady_from = duration_s * 0.4
        thr = _interval_throughput(flow, steady_from, duration_s)
        samples = [q for (t, q) in network.bottleneck.queue_samples if t > steady_from]
        mean_queue = sum(samples) / len(samples) if samples else 0.0
        results[algo] = {
            "throughput_bps": thr,
            "utilization": thr / bandwidth_bps,
            "mean_queue_packets": mean_queue,
            "queue_samples": network.bottleneck.queue_samples,
            "flows": [_flow_result(flow, duration_s)],
            "_network": network,
        }
    return {"duration_s": duration_s, "capacity": capacity, "results": results}
