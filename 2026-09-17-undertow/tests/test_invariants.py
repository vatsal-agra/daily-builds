"""Invariants that must hold regardless of which congestion-control
algorithm or scenario is running — these test the network engine itself,
independent of TCP semantics."""

from src import experiments as exp
from src.congestion.base import MIN_CWND
from src.metrics import jains_fairness_index


def _check_packet_conservation(network):
    sent = network.sent_ids
    delivered = network.delivered_ids
    dropped = network.dropped_ids
    assert delivered & dropped == set(), "a physical packet cannot be both delivered and dropped"
    assert delivered <= sent, "delivered a packet that was never sent"
    assert dropped <= sent, "dropped a packet that was never sent"
    in_flight = sent - delivered - dropped
    # every sent packet ends the run in exactly one of the three buckets
    assert sent == delivered | dropped | in_flight


def test_packet_conservation_single_flow():
    for algo in ("reno", "cubic", "bbr"):
        r = exp.run_single_flow(algo=algo, duration_s=15)
        _check_packet_conservation(r["_network"])


def test_packet_conservation_multi_flow():
    r = exp.run_fairness_same_rtt(algo="reno", n_flows=3, duration_s=15)
    _check_packet_conservation(r["_network"])
    r = exp.run_bufferbloat(algo="reno", use_red=False, duration_s=15)
    _check_packet_conservation(r["_network"])
    r = exp.run_bufferbloat(algo="reno", use_red=True, duration_s=15)
    _check_packet_conservation(r["_network"])


def test_cwnd_never_below_minimum():
    for algo in ("reno", "cubic", "bbr"):
        r = exp.run_single_flow(algo=algo, duration_s=20, capacity=50)
        for (_, cwnd, _) in r["flows"][0]["cwnd_series"]:
            assert cwnd >= MIN_CWND - 1e-9, f"{algo} cwnd went below {MIN_CWND}: {cwnd}"


def test_queue_never_exceeds_capacity_or_goes_negative():
    capacity = 50
    r = exp.run_single_flow(algo="reno", duration_s=20, capacity=capacity)
    for (_, qlen) in r["queue_samples"]:
        assert 0 <= qlen <= capacity


def test_jains_fairness_index_known_values():
    assert jains_fairness_index([1, 1]) == 1.0
    assert jains_fairness_index([1, 1, 1, 1]) == 1.0
    assert jains_fairness_index([1, 0]) == 0.5
    assert jains_fairness_index([]) == 0.0
    assert jains_fairness_index([0, 0]) == 0.0
    # maximally unfair for n flows -> 1/n
    assert abs(jains_fairness_index([1, 0, 0, 0]) - 0.25) < 1e-9


def test_jains_fairness_index_bounds():
    import random
    rng = random.Random(0)
    for _ in range(200):
        n = rng.randint(1, 8)
        values = [rng.uniform(0, 100) for _ in range(n)]
        idx = jains_fairness_index(values)
        assert 1.0 / n - 1e-9 <= idx <= 1.0 + 1e-9


def test_receiver_delivers_exactly_once_under_reordering():
    from src.flow import Receiver

    r = Receiver()
    # deliver out of order: 1, 0, 2 -> should end up with delivered_count=3
    # and never double count seq 0/1 even though seq 1 arrived before seq 0.
    r.on_packet(1, 0.1)
    assert r.delivered_count == 0  # gap at seq 0, buffered
    r.on_packet(0, 0.2)
    assert r.delivered_count == 2  # 0 and the buffered 1 both flush
    r.on_packet(2, 0.3)
    assert r.delivered_count == 3
    # a duplicate/late arrival of an already-delivered segment must not
    # double count.
    r.on_packet(0, 0.4)
    assert r.delivered_count == 3
