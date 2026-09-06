import random

import pytest

from throttle.network import AccessLink, Link, Simulator
from throttle.packet import Segment


def _pkt(payload_len=1000):
    return Segment(seq=0, ack=0, payload=b"x" * payload_len)


def test_simulator_runs_events_in_time_order():
    sim = Simulator()
    order = []
    sim.schedule_after(0.5, lambda: order.append("b"))
    sim.schedule_after(0.1, lambda: order.append("a"))
    sim.schedule_after(1.0, lambda: order.append("c"))
    sim.run()
    assert order == ["a", "b", "c"]
    assert sim.now == 1.0


def test_simulator_ties_broken_by_insertion_order():
    sim = Simulator()
    order = []
    sim.schedule_at(1.0, lambda: order.append(1))
    sim.schedule_at(1.0, lambda: order.append(2))
    sim.schedule_at(1.0, lambda: order.append(3))
    sim.run()
    assert order == [1, 2, 3]


def test_simulator_run_until_stops_early_and_can_resume():
    sim = Simulator()
    hits = []
    sim.schedule_after(1.0, lambda: hits.append(1.0))
    sim.schedule_after(5.0, lambda: hits.append(5.0))
    sim.run(until=2.0)
    assert hits == [1.0]
    assert sim.now == 2.0  # advanced to the horizon even with no event exactly there
    sim.run()
    assert hits == [1.0, 5.0]


def test_simulator_rejects_scheduling_in_the_past():
    sim = Simulator()
    sim.now = 10.0
    try:
        sim.schedule_at(5.0, lambda: None)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_link_serializes_bandwidth_across_packets():
    sim = Simulator()
    # 1000 bytes/sec bandwidth -> a 1000-byte-payload packet (+40 header)
    # takes just over one second to serialize.
    link = Link(sim, bandwidth_Bps=1000, buffer_bytes=1_000_000, prop_delay_s=0.0)
    deliveries = []
    link.send(_pkt(1000), lambda pkt, t: deliveries.append(t))
    link.send(_pkt(1000), lambda pkt, t: deliveries.append(t))
    sim.run()
    assert len(deliveries) == 2
    # second packet cannot arrive before the first has finished serializing
    assert deliveries[1] > deliveries[0]
    assert deliveries[0] == 1040 / 1000  # (1000 payload + 40 header) / bandwidth


def test_link_applies_propagation_delay():
    sim = Simulator()
    link = Link(sim, bandwidth_Bps=10**9, buffer_bytes=10**6, prop_delay_s=0.25)
    got = []
    link.send(_pkt(10), lambda pkt, t: got.append(t))
    sim.run()
    # arrival = propagation delay + (tiny but nonzero) serialization delay
    assert got[0] == pytest.approx(0.25, abs=1e-4)


def test_link_drop_tail_on_overflow():
    sim = Simulator()
    link = Link(sim, bandwidth_Bps=1, buffer_bytes=100, prop_delay_s=0.0)
    delivered = []
    # first packet fits (40-byte header only, no payload -> 40 bytes)
    link.send(_pkt(0), lambda pkt, t: delivered.append(pkt))
    # second packet would push total past the 100-byte buffer -> dropped
    link.send(_pkt(0), lambda pkt, t: delivered.append(pkt))
    link.send(_pkt(0), lambda pkt, t: delivered.append(pkt))
    assert link.stats.dropped_overflow == 1
    assert link.queue_bytes == 80


def test_link_random_loss_is_deterministic_with_seeded_rng():
    sim = Simulator()
    rng = random.Random(0)
    link = Link(sim, bandwidth_Bps=10**9, buffer_bytes=10**6, prop_delay_s=0.0,
                loss_prob=1.0, rng=rng)
    delivered = []
    for _ in range(5):
        link.send(_pkt(10), lambda pkt, t: delivered.append(pkt))
    sim.run()
    assert delivered == []
    assert link.stats.dropped_random == 5


def test_link_no_loss_when_prob_zero():
    sim = Simulator()
    link = Link(sim, bandwidth_Bps=10**9, buffer_bytes=10**6, prop_delay_s=0.0, loss_prob=0.0)
    delivered = []
    for _ in range(20):
        link.send(_pkt(10), lambda pkt, t: delivered.append(pkt))
    sim.run()
    assert len(delivered) == 20
    assert link.stats.dropped_random == 0


def test_access_link_applies_fixed_delay_only():
    sim = Simulator()
    access = AccessLink(sim, delay_s=0.05)
    got = []
    access.send(_pkt(100000), lambda pkt, t: got.append(t))  # size shouldn't matter
    sim.run()
    assert got == [0.05]


def test_access_link_loss_prob_can_drop_packets():
    sim = Simulator()
    rng = random.Random(0)
    access = AccessLink(sim, delay_s=0.01, loss_prob=1.0, rng=rng)
    got = []
    access.send(_pkt(10), lambda pkt, t: got.append(t))
    sim.run()
    assert got == []


def test_link_rejects_invalid_parameters_with_clean_valueerror():
    sim = Simulator()
    for kwargs in [
        dict(bandwidth_Bps=0, buffer_bytes=100, prop_delay_s=0.0),
        dict(bandwidth_Bps=-5, buffer_bytes=100, prop_delay_s=0.0),
        dict(bandwidth_Bps=100, buffer_bytes=-1, prop_delay_s=0.0),
        dict(bandwidth_Bps=100, buffer_bytes=100, prop_delay_s=-0.1),
        dict(bandwidth_Bps=100, buffer_bytes=100, prop_delay_s=0.0, loss_prob=1.5),
        dict(bandwidth_Bps=100, buffer_bytes=100, prop_delay_s=0.0, reorder_prob=-0.1),
    ]:
        try:
            Link(sim, **kwargs)
            assert False, f"expected ValueError for {kwargs}"
        except ValueError:
            pass


def test_access_link_rejects_invalid_parameters():
    sim = Simulator()
    try:
        AccessLink(sim, delay_s=-1.0)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_queue_bytes_returns_to_zero_after_drain():
    sim = Simulator()
    link = Link(sim, bandwidth_Bps=10_000, buffer_bytes=10_000, prop_delay_s=0.0)
    for _ in range(3):
        link.send(_pkt(100), lambda pkt, t: None)
    assert link.queue_bytes > 0
    sim.run()
    assert link.queue_bytes == 0
