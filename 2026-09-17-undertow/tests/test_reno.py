from src import experiments as exp


def test_slow_start_doubles_roughly_each_rtt_before_any_loss():
    # a huge buffer so no loss occurs during the observation window;
    # isolates pure slow-start behaviour.
    r = exp.run_single_flow(algo="reno", duration_s=1.0, capacity=100_000)
    samples = r["flows"][0]["cwnd_series"]
    assert len(samples) > 10
    # cwnd must be monotonically non-decreasing during slow start.
    cwnds = [c for (_, c, _) in samples]
    for a, b in zip(cwnds, cwnds[1:]):
        assert b >= a - 1e-9
    # it should reach a healthy multiple of the initial window quickly
    # (exponential growth): starting at 1, several RTTs in it should be
    # well past 16.
    assert cwnds[-1] > 16


def test_loss_triggers_multiplicative_decrease_to_about_half():
    r = exp.run_single_flow(algo="reno", duration_s=20, capacity=50)
    samples = r["flows"][0]["cwnd_series"]
    loss_events = r["flows"][0]["loss_events"]
    assert loss_events, "expected at least one loss with a 50-packet buffer"
    fast_retransmits = [t for (t, kind) in loss_events if kind == "fast_retransmit"]
    assert fast_retransmits, "expected at least one fast retransmit (not just timeouts)"
    t_loss = fast_retransmits[0]
    before = max((c for (t, c, _) in samples if t < t_loss), default=None)
    after = min((c for (t, c, _) in samples if t >= t_loss), default=None)
    assert before is not None and after is not None
    # RFC 5681: ssthresh = cwnd/2, so cwnd right after loss should be close
    # to half of its pre-loss peak (fast-recovery inflation adds a little
    # on top, so allow generous headroom rather than an exact 0.5).
    assert after < before * 0.85


def test_single_flow_reno_achieves_high_utilization():
    r = exp.run_single_flow(algo="reno", duration_s=20, bandwidth_bps=2_000_000)
    utilization = r["flows"][0]["throughput_bps"] / 2_000_000
    assert utilization > 0.85, f"expected Reno to saturate the link, got {utilization:.2%}"
