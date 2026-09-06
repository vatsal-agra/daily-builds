from throttle.experiment import (
    exp_fairness_equal_rtt,
    exp_reno_vs_tahoe,
    exp_rtt_unfairness,
    exp_single_flow_lossy,
    jains_fairness_index,
    run_all_named,
)


def test_jains_index_perfect_fairness():
    assert jains_fairness_index([10.0, 10.0, 10.0]) == 1.0


def test_jains_index_unfair_case_below_one():
    assert jains_fairness_index([100.0, 1.0]) < 1.0


def test_jains_index_empty_is_none():
    assert jains_fairness_index([]) is None
    assert jains_fairness_index([0.0, 0.0]) is None


def test_single_flow_lossy_completes_with_verified_reassembly():
    result = exp_single_flow_lossy(seed=1)
    assert len(result.flows) == 1
    f = result.flows[0]
    assert f.completed
    assert f.verified_correct
    assert result.dropped_random > 0  # loss was actually injected
    assert (f.timeouts + f.fast_retransmits) > 0  # and recovered from


def test_fairness_equal_rtt_converges_near_one():
    result = exp_fairness_equal_rtt(seed=2)
    assert len(result.flows) == 3
    assert all(f.completed and f.verified_correct for f in result.flows)
    assert result.fairness_index > 0.9


def test_rtt_unfairness_short_rtt_flow_wins():
    result = exp_rtt_unfairness(seed=3)
    short, long_ = result.flows
    assert short.access_delay_s < long_.access_delay_s
    assert all(f.completed and f.verified_correct for f in result.flows)
    assert short.throughput_Bps > long_.throughput_Bps
    assert result.fairness_index < 1.0


def test_reno_beats_tahoe_under_identical_loss():
    result = exp_reno_vs_tahoe(seed=4)
    reno, tahoe = result.flows
    assert reno.cc_name == "reno" and tahoe.cc_name == "tahoe"
    assert all(f.completed and f.verified_correct for f in result.flows)
    assert reno.completion_time < tahoe.completion_time


def test_run_all_named_covers_every_experiment_and_all_verify():
    results = run_all_named()
    labels = [label for label, _ in results]
    assert len(labels) == len(set(labels))  # no duplicate labels
    assert {"single-flow-lossy", "fairness-equal-rtt", "rtt-unfairness",
            "reno-vs-tahoe", "high-bdp-reno", "high-bdp-cubic"} <= set(labels)
    for label, result in results:
        for f in result.flows:
            assert f.completed, f"{label}/{f.name} did not complete within its time cap"
            assert f.verified_correct, f"{label}/{f.name} reassembled incorrectly"
