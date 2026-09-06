from throttle.rtt import RttEstimator


def test_first_sample_seeds_srtt_and_half_rttvar():
    e = RttEstimator(min_rto_s=0.0)
    e.sample(0.2)
    assert e.srtt == 0.2
    assert e.rttvar == 0.1


def test_rto_grows_with_variance():
    e = RttEstimator(min_rto_s=0.0)
    e.sample(0.1)
    stable_rto = e.rto
    e2 = RttEstimator(min_rto_s=0.0)
    e2.sample(0.1)
    e2.sample(0.5)  # big jump -> big RTTVAR -> bigger RTO
    assert e2.rto > stable_rto


def test_backoff_doubles_and_caps():
    e = RttEstimator(min_rto_s=1.0, initial_rto_s=1.0)
    base = e.rto
    e.backoff()
    assert e.rto == base * 2
    e.backoff()
    assert e.rto == base * 4
    for _ in range(20):
        e.backoff()
    assert e.rto <= 60.0


def test_sample_resets_backoff_karns_algorithm():
    e = RttEstimator(min_rto_s=0.0, initial_rto_s=1.0)
    e.sample(0.1)
    e.backoff()
    e.backoff()
    assert e.backoff_multiplier == 4
    e.sample(0.1)  # unambiguous round trip -> Karn's algorithm resets backoff
    assert e.backoff_multiplier == 1


def test_min_rto_floor_enforced():
    e = RttEstimator(min_rto_s=1.0)
    e.sample(0.001)  # a tiny measured RTT should still floor at min_rto_s
    assert e.rto >= 1.0


def test_rto_converges_toward_stable_rtt():
    e = RttEstimator(min_rto_s=0.0)
    for _ in range(50):
        e.sample(0.1)
    # once variance has settled, RTO should be close to SRTT (small RTTVAR term)
    assert abs(e.srtt - 0.1) < 1e-6
    assert e.rto < 0.15
