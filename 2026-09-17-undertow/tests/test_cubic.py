from src import experiments as exp
from src.congestion.cubic import BETA_CUBIC, Cubic


def test_cubic_loss_response_matches_rfc8312_beta():
    cc = Cubic(init_cwnd=100.0, init_ssthresh=10.0)  # already past slow start
    cc.on_loss_event(now=5.0)
    assert cc.w_max == 100.0
    assert abs(cc.ssthresh - 100.0 * BETA_CUBIC) < 1e-9
    assert abs(cc.cwnd - 100.0 * BETA_CUBIC) < 1e-9
    assert cc.epoch_start is None  # fresh epoch starts on the next ACK


def test_cubic_growth_is_continuous_at_epoch_start():
    # W_cubic(0) must equal the post-decrease cwnd exactly (that's the
    # entire point of solving for K the way RFC 8312 does) — otherwise the
    # curve would jump discontinuously the instant congestion avoidance
    # resumes.
    cc = Cubic(init_cwnd=100.0, init_ssthresh=10.0)
    cc.on_loss_event(now=5.0)
    post_decrease_cwnd = cc.cwnd
    cc.on_ack(now=5.0, rtt_sample=0.05, acked_packets=1)  # t=0 in the new epoch
    assert abs(cc.cwnd - post_decrease_cwnd) < 1e-6


def test_cubic_grows_monotonically_after_a_loss_absent_new_losses():
    cc = Cubic(init_cwnd=100.0, init_ssthresh=10.0)
    cc.on_loss_event(now=0.0)
    cwnds = []
    t = 0.0
    for _ in range(200):
        t += 0.02
        cc.on_ack(now=t, rtt_sample=0.02, acked_packets=1)
        cwnds.append(cc.cwnd)
    for a, b in zip(cwnds, cwnds[1:]):
        assert b >= a - 1e-9
    assert cwnds[-1] > cwnds[0]  # it did grow


def test_single_flow_cubic_achieves_high_utilization_with_few_drops():
    r = exp.run_single_flow(algo="cubic", duration_s=20, bandwidth_bps=2_000_000)
    utilization = r["flows"][0]["throughput_bps"] / 2_000_000
    assert utilization > 0.85, f"expected CUBIC to saturate the link, got {utilization:.2%}"


def test_cubic_survives_a_deep_buffer_without_stalling():
    # regression test for the head-of-line-blocking runaway found in
    # REVIEW.md: an unbounded number of duplicate-ACK window inflations
    # during one stuck recovery episode could keep a flow's cumulative ACK
    # pinned near zero progress for the entire run.
    r = exp.run_single_flow(algo="cubic", duration_s=60, capacity=300)
    utilization = r["flows"][0]["throughput_bps"] / 2_000_000
    assert utilization > 0.8
