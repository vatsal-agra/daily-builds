"""The two headline, textbook-verifiable phenomena this build exists to
reproduce: AIMD fairness convergence (Chiu & Jain, 1989) and Reno's RTT
unfairness, with CUBIC's documented fairness improvement over Reno on the
identical topology."""

from src import experiments as exp
from src.metrics import jains_fairness_index


def test_two_identical_rtt_reno_flows_converge_to_fair_split():
    r = exp.run_fairness_same_rtt(algo="reno", n_flows=2, duration_s=40)
    delivered = [f["delivered_segments"] for f in r["flows"]]
    # Whole-run cumulative delivery is a far less noisy fairness signal
    # than any single 0.5s interval snapshot (fairness_series is kept
    # around for the visualizer's convergence-over-time chart, where that
    # noise is exactly the interesting AIMD-sawtooth signal — see
    # REVIEW.md) — over the *whole* run it should land close to 1.0.
    assert jains_fairness_index(delivered) > 0.9
    ratio = max(delivered) / min(delivered)
    assert ratio < 1.5, f"expected a roughly even split, got {delivered}"


def test_reno_rtt_unfairness_short_rtt_flow_wins():
    r = exp.run_rtt_unfairness(algo="reno", duration_s=60)
    assert r["rtt_ratio_long_over_short"] > 3.5  # sanity: topology is as configured
    assert r["pooled_throughput_ratio_short_over_long"] > 1.1, (
        "expected the short-RTT flow to get a meaningfully larger share "
        f"(pooled ratio was {r['pooled_throughput_ratio_short_over_long']:.3f})"
    )


def test_cubic_is_more_rtt_fair_than_reno_on_identical_topology():
    reno = exp.run_rtt_unfairness(algo="reno", duration_s=60)
    cubic = exp.run_rtt_unfairness(algo="cubic", duration_s=60)
    reno_unfairness = abs(reno["pooled_throughput_ratio_short_over_long"] - 1.0)
    cubic_unfairness = abs(cubic["pooled_throughput_ratio_short_over_long"] - 1.0)
    assert cubic_unfairness < reno_unfairness, (
        f"expected CUBIC (deviation {cubic_unfairness:.3f}) to be more RTT-fair "
        f"than Reno (deviation {reno_unfairness:.3f}) on the same topology"
    )
