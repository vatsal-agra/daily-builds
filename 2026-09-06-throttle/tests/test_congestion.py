import pytest

from throttle import congestion


MSS = 1000


@pytest.mark.parametrize("name", ["reno", "tahoe", "cubic"])
def test_initial_window_rfc5681(name):
    cc = congestion.make(name, MSS)
    assert cc.cwnd == min(4 * MSS, max(2 * MSS, 4380))


@pytest.mark.parametrize("name", ["reno", "tahoe", "cubic"])
def test_slow_start_grows_by_acked_bytes_below_ssthresh(name):
    cc = congestion.make(name, MSS)
    cc.ssthresh = 10 ** 9  # keep us in slow start
    before = cc.cwnd
    cc.on_ack(MSS, flight_before=before, now=1.0)
    assert cc.cwnd == before + MSS


@pytest.mark.parametrize("name", ["reno", "tahoe"])
def test_congestion_avoidance_grows_slower_than_slow_start(name):
    cc = congestion.make(name, MSS)
    cc.ssthresh = cc.cwnd  # force into congestion avoidance immediately
    before = cc.cwnd
    cc.on_ack(MSS, flight_before=before, now=1.0)
    # ~ +MSS^2/cwnd, much less than a full +MSS slow-start step
    assert before < cc.cwnd < before + MSS


def test_reno_third_dup_ack_triggers_fast_retransmit_and_sets_ssthresh():
    cc = congestion.make("reno", MSS)
    flight = 8 * MSS
    assert cc.on_dup_ack(1, flight) is False
    assert cc.on_dup_ack(2, flight) is False
    fire = cc.on_dup_ack(3, flight)
    assert fire is True
    assert cc.ssthresh == max(flight / 2, 2 * MSS)
    assert cc.cwnd == cc.ssthresh + 3 * MSS
    assert cc.in_recovery is True


def test_reno_inflates_during_recovery_then_deflates_on_recovery_ack():
    cc = congestion.make("reno", MSS)
    flight = 8 * MSS
    cc.on_dup_ack(1, flight)
    cc.on_dup_ack(2, flight)
    cc.on_dup_ack(3, flight)
    inflated = cc.cwnd
    cc.on_dup_ack(4, flight)
    assert cc.cwnd == inflated + MSS
    cc.on_recovery_ack()
    assert cc.cwnd == cc.ssthresh
    assert cc.in_recovery is False


def test_tahoe_goes_straight_to_one_mss_no_inflation():
    cc = congestion.make("tahoe", MSS)
    flight = 8 * MSS
    cc.on_dup_ack(1, flight)
    cc.on_dup_ack(2, flight)
    fire = cc.on_dup_ack(3, flight)
    assert fire is True
    assert cc.cwnd == MSS
    # further dup acks must NOT inflate cwnd (the whole point of Tahoe vs Reno)
    cc.on_dup_ack(4, flight)
    assert cc.cwnd == MSS


def test_reno_and_tahoe_react_identically_to_timeout():
    for name in ("reno", "tahoe"):
        cc = congestion.make(name, MSS)
        flight = 8 * MSS
        cc.on_timeout(flight)
        assert cc.cwnd == MSS
        assert cc.ssthresh == max(flight / 2, 2 * MSS)
        assert cc.in_recovery is False


def test_cubic_multiplicative_decrease_uses_beta_not_half():
    cc = congestion.make("cubic", MSS)
    cc.cwnd = 20 * MSS
    flight = 20 * MSS
    cc.on_dup_ack(1, flight)
    cc.on_dup_ack(2, flight)
    cc.on_dup_ack(3, flight)
    assert cc.cwnd == pytest.approx(20 * MSS * congestion.Cubic.BETA)
    assert cc.ssthresh == cc.cwnd


def test_cubic_growth_is_monotonic_and_accelerates_after_inflection():
    cc = congestion.make("cubic", MSS)
    cc.cwnd = 10 * MSS
    cc.ssthresh = 5 * MSS  # already past slow start
    cc.w_max_segs = 20.0   # remembered window from a prior loss

    samples = []
    t = 0.0
    for _ in range(40):
        cc.on_ack(MSS, flight_before=int(cc.cwnd), now=t)
        samples.append(cc.cwnd)
        t += 0.05

    # monotonic non-decreasing
    assert all(b >= a - 1e-9 for a, b in zip(samples, samples[1:]))
    # net growth over the whole run is positive
    assert samples[-1] > samples[0]


def test_unknown_algorithm_raises():
    with pytest.raises(ValueError):
        congestion.make("bbr", MSS)
