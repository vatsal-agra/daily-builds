import random

import pytest

from throttle.network import Simulator
from throttle.tcp import Topology, TcpConnection


def _run_transfer(data_len, cc_name="reno", access_delay=0.01, core_delay=0.005,
                   bandwidth=200_000, buffer=64 * 1024, loss=0.0, reorder=0.0,
                   seed=1, cap=60.0, min_rto_s=1.0):
    rng = random.Random(seed)
    sim = Simulator()
    topo = Topology(sim, bandwidth, buffer, core_delay, fwd_loss_prob=loss,
                     fwd_reorder_prob=reorder, rng=rng)
    data = bytes(rng.getrandbits(8) for _ in range(data_len))
    conn = TcpConnection(sim, 0, topo, data, access_delay, cc_name=cc_name, rng=rng,
                          min_rto_s=min_rto_s)
    conn.start()
    sim.run(until=cap)
    return sim, topo, conn, data


def test_handshake_completes_before_data_flows():
    sim, topo, conn, data = _run_transfer(1000)
    assert conn.sender.state in ("ESTABLISHED", "CLOSED")
    assert conn.receiver.state == "ESTABLISHED"
    assert conn.sender.segments_sent >= 1


def test_clean_link_transfer_completes_and_reassembles_exactly():
    sim, topo, conn, data = _run_transfer(200_000)
    assert conn.sender.done and conn.receiver.done
    assert bytes(conn.receiver.assembled) == data
    assert conn.sender.timeouts == 0
    assert topo.fwd_link.stats.dropped_overflow == 0
    assert topo.fwd_link.stats.dropped_random == 0


def test_transfer_survives_loss_and_reordering_with_exact_reassembly():
    # Note: buffer is sized generously relative to the bandwidth-delay
    # product on purpose. TCP Reno without SACK recovers from multiple
    # losses within one window one segment per RTO (go-back-1), and a
    # too-small buffer combined with real loss can compound into that
    # legitimate but very slow recovery path (see REVIEW.md) -- this test
    # wants to exercise ordinary loss recovery, not that pathology.
    sim, topo, conn, data = _run_transfer(
        150_000, loss=0.02, reorder=0.03, bandwidth=1_000_000, buffer=100_000,
        core_delay=0.01, access_delay=0.02, seed=7, min_rto_s=0.5, cap=60.0,
    )
    assert conn.sender.done and conn.receiver.done
    assert bytes(conn.receiver.assembled) == data
    assert topo.fwd_link.stats.dropped_random > 0  # loss actually happened
    assert (conn.sender.fast_retransmits + conn.sender.timeouts) > 0  # and was recovered from


def test_flow_control_never_exceeds_advertised_receive_window():
    # A tiny receive window should cap in-flight bytes even though cwnd
    # would otherwise allow much more.
    rng = random.Random(3)
    sim = Simulator()
    topo = Topology(sim, 10_000_000, 1_000_000, 0.001, rng=rng)
    data = bytes(rng.getrandbits(8) for _ in range(500_000))
    from throttle.tcp import TcpConnection as TC
    conn = TC(sim, 0, topo, data, access_delay_s=0.001, cc_name="reno",
              recv_window=3000, rng=rng)
    conn.start()

    max_flight_seen = 0

    orig = conn.sender._maybe_send_more

    def spy(now):
        orig(now)
        nonlocal max_flight_seen
        max_flight_seen = max(max_flight_seen, conn.sender._flight_bytes())

    conn.sender._maybe_send_more = spy
    sim.run(until=30.0)
    assert conn.sender.done
    assert bytes(conn.receiver.assembled) == data
    # generous slack for one extra in-flight MSS-sized segment
    assert max_flight_seen <= 3000 + 1460


def test_out_of_order_segments_are_buffered_and_drained_in_order():
    sim = Simulator()
    from throttle.tcp import TcpReceiver
    sent = []
    recv = TcpReceiver(sim, link_send=lambda seg: sent.append(seg))
    from throttle.packet import Segment
    syn = Segment(seq=100, ack=0, syn=True)
    recv.on_segment(syn, 0.0)
    assert recv.state == "SYN_RCVD"
    irs = recv.irs
    rcv_nxt0 = irs + 1

    ack = Segment(seq=200, ack=recv.iss + 1, ack_flag=True)
    recv.on_segment(ack, 0.01)
    assert recv.state == "ESTABLISHED"

    # segment 2 (out of order, arrives first)
    seg2 = Segment(seq=rcv_nxt0 + 5, ack=0, payload=b"world")
    recv.on_segment(seg2, 0.02)
    assert recv.rcv_nxt == rcv_nxt0  # nothing delivered yet, still waiting on the gap
    assert len(recv.assembled) == 0

    # segment 1 fills the gap -> both should drain in order
    seg1 = Segment(seq=rcv_nxt0, ack=0, payload=b"hello")
    recv.on_segment(seg1, 0.03)
    assert bytes(recv.assembled) == b"helloworld"
    assert recv.rcv_nxt == rcv_nxt0 + 10


def test_duplicate_segment_does_not_corrupt_stream():
    sim = Simulator()
    from throttle.tcp import TcpReceiver
    from throttle.packet import Segment
    recv = TcpReceiver(sim, link_send=lambda seg: None)
    syn = Segment(seq=100, ack=0, syn=True)
    recv.on_segment(syn, 0.0)
    rcv_nxt0 = recv.irs + 1
    ack = Segment(seq=200, ack=recv.iss + 1, ack_flag=True)
    recv.on_segment(ack, 0.01)

    seg1 = Segment(seq=rcv_nxt0, ack=0, payload=b"hello")
    recv.on_segment(seg1, 0.02)
    recv.on_segment(seg1, 0.03)  # exact duplicate (e.g. spurious retransmit)
    assert bytes(recv.assembled) == b"hello"
    assert recv.duplicate_segments == 1


def test_lost_final_handshake_ack_does_not_deadlock_connection():
    """If the sender's bare completion ACK is dropped, real TCP still
    establishes the connection off the next (ack-flagged) data segment.
    This is a regression test for a real deadlock bug found while building
    this simulator (see REVIEW.md)."""
    sim = Simulator()
    from throttle.tcp import TcpReceiver
    from throttle.packet import Segment

    recv = TcpReceiver(sim, link_send=lambda seg: None)
    syn = Segment(seq=100, ack=0, syn=True)
    recv.on_segment(syn, 0.0)
    rcv_nxt0 = recv.irs + 1
    # the bare completion ACK is "lost" -- never delivered to recv.on_segment

    # first data segment (carries ack_flag=True per real TCP) arrives instead
    data_seg = Segment(seq=rcv_nxt0, ack=recv.iss + 1, ack_flag=True, payload=b"hi")
    recv.on_segment(data_seg, 0.05)
    assert recv.state == "ESTABLISHED"
    assert bytes(recv.assembled) == b"hi"


def test_syn_timeout_retransmits_without_crashing():
    """Regression test for a real crash found by fuzzing (see REVIEW.md):
    a RTO firing on the SYN itself (i.e. the SYN was lost) used to always
    fall through to `_maybe_send_more`, which dereferences `self.irs`
    (the receiver's ISN) before the handshake has told the sender what it
    is -- TypeError. The SYN is dropped once here via 100% loss on the
    very first access-link send, forcing exactly that path."""
    rng = random.Random(0)
    sim = Simulator()
    topo = Topology(sim, 200_000, 60_000, 0.01, rng=rng)

    from throttle.network import AccessLink
    # Drop only the very first packet sent (the initial SYN); let
    # everything after it (the retransmitted SYN included) through.
    dropped = {"done": False}
    orig_add_flow = Topology.add_flow

    def patched_add_flow(self, flow_id, access_delay_s, on_deliver_to_receiver, on_deliver_to_sender):
        access = AccessLink(self.sim, access_delay_s)
        orig_send = access.send

        def send_once_dropping_first(pkt, on_deliver):
            if not dropped["done"]:
                dropped["done"] = True
                return  # drop it silently, like a lost SYN
            return orig_send(pkt, on_deliver)

        access.send = send_once_dropping_first
        self.access[flow_id] = access
        self.receiver_cb[flow_id] = on_deliver_to_receiver
        self.sender_cb[flow_id] = on_deliver_to_sender

    Topology.add_flow = patched_add_flow
    try:
        data = b"hello world" * 100
        conn = TcpConnection(sim, 0, topo, data, access_delay_s=0.01, cc_name="reno",
                              rng=rng, min_rto_s=0.2)
        conn.start()
        sim.run(until=30.0)  # must not raise
    finally:
        Topology.add_flow = orig_add_flow

    assert conn.sender.timeouts >= 1
    assert conn.sender.done and conn.receiver.done
    assert bytes(conn.receiver.assembled) == data


def test_fin_teardown_completes_and_marks_both_sides_done():
    sim, topo, conn, data = _run_transfer(5000)
    assert conn.sender.state == "CLOSED"
    assert conn.receiver.fin_received
    assert conn.finished


@pytest.mark.parametrize("cc_name", ["reno", "tahoe", "cubic"])
def test_all_algorithms_complete_a_transfer_correctly(cc_name):
    sim, topo, conn, data = _run_transfer(100_000, cc_name=cc_name, loss=0.01, seed=9,
                                           min_rto_s=0.2, cap=120.0)
    assert conn.sender.done and conn.receiver.done
    assert bytes(conn.receiver.assembled) == data


def test_reno_recovers_faster_than_tahoe_under_identical_loss():
    _, _, reno_conn, _ = _run_transfer(2_000_000, cc_name="reno", bandwidth=1_000_000,
                                        buffer=100_000, access_delay=0.02, loss=0.005,
                                        seed=21, cap=120.0)
    _, _, tahoe_conn, _ = _run_transfer(2_000_000, cc_name="tahoe", bandwidth=1_000_000,
                                         buffer=100_000, access_delay=0.02, loss=0.005,
                                         seed=21, cap=120.0)
    assert reno_conn.sender.done and tahoe_conn.sender.done
    assert reno_conn.sender.done_time < tahoe_conn.sender.done_time
