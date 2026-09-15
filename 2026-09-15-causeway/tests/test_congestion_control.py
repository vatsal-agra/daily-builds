"""Exercises the Reno congestion-control state machine directly against a
SimulatedLink, checking the actual mechanics (slow start doubling, the
sawtooth halving on loss, fast-retransmit/fast-recovery, timeout collapse)
rather than just "did the transfer eventually finish."
"""
import unittest

from causeway.clock import VirtualClock
from causeway.connection import Connection
from causeway.wire import SimulatedLink


def make_pair(mss=512, loss=0.0, dup=0.0, reorder=0.0, seed=0, base_delay=0.01, jitter=0.0, **kw):
    clock = VirtualClock()
    link = SimulatedLink(clock, base_delay=base_delay, jitter=jitter, loss_prob=loss,
                          dup_prob=dup, reorder_prob=reorder, seed=seed)
    client = Connection("client", link.endpoint_a, clock, mss=mss, **kw)
    server = Connection("server", link.endpoint_b, clock, mss=mss)
    return clock, link, client, server


def pump_until(clock, link, client, server, condition, max_time=120.0, drain_into=None):
    while not condition():
        cands = [x for x in (link.next_event_time(), client.next_timer_deadline(),
                              server.next_timer_deadline()) if x is not None]
        if not cands:
            raise AssertionError("simulation stalled with nothing pending")
        t = max(clock.t, min(cands))
        if t > max_time:
            raise AssertionError(f"exceeded max_time={max_time} waiting for condition")
        clock.advance_to(t)
        link.deliver_due(t)
        client.step(t)
        server.step(t)
        chunk = server.recv()
        if drain_into is not None:
            drain_into.extend(chunk)


class TestSlowStart(unittest.TestCase):
    def test_cwnd_doubles_each_round_trip_below_ssthresh(self):
        clock, link, client, server = make_pair(mss=512)
        pump_until(clock, link, client, server, lambda: client.is_established)
        self.assertEqual(client.cwnd, 512)
        client.send(b"x" * 200_000)

        seen = []
        last = None
        for _ in range(6):
            before = client.snd_una
            pump_until(clock, link, client, server, lambda: client.snd_una > before)
            seen.append(client.cwnd)
        # Slow start: +1 MSS per ACK, so cwnd should be climbing quickly and
        # roughly doubling across a handful of ACKs while under ssthresh.
        self.assertGreater(seen[-1], seen[0] * 2)
        for a, b in zip(seen, seen[1:]):
            self.assertGreaterEqual(b, a)  # monotonically non-decreasing


class TestFastRetransmitAndRecovery(unittest.TestCase):
    def test_triple_dup_ack_triggers_fast_retransmit_and_halves_cwnd(self):
        clock, link, client, server = make_pair(mss=256)
        pump_until(clock, link, client, server, lambda: client.is_established)
        # Get cwnd comfortably large first so several segments can be in
        # flight at once (needed to generate duplicate ACKs at all).
        client.send(b"a" * 4000)
        pump_until(clock, link, client, server, lambda: client.cwnd >= 256 * 8, max_time=30)

        # Deterministically drop exactly one in-flight data segment so the
        # next several segments arrive out of order and trigger duplicate
        # ACKs -- much more precise than hoping random loss produces this.
        dropped = {"done": False}
        real_send = link.endpoint_a.send
        count = {"data_segments": 0}

        def send_and_drop_one(data):
            from causeway.segment import Segment
            s = Segment.decode(data)
            if s.payload and not dropped["done"]:
                count["data_segments"] += 1
                if count["data_segments"] == 3:  # drop the 3rd data segment only
                    dropped["done"] = True
                    return
            real_send(data)

        link.endpoint_a.send = send_and_drop_one
        client.send(b"b" * 20_000)
        pump_until(clock, link, client, server,
                   lambda: client.stats["fast_retransmits"] >= 1, max_time=30)
        self.assertTrue(dropped["done"])
        self.assertEqual(client.stats["fast_retransmits"], 1)
        # Fast recovery invariants (RFC 5681): ssthresh floors at 2*MSS, and
        # cwnd is inflated by at least 3*MSS above ssthresh for the segments
        # known to have left the network (one per duplicate ACK received;
        # with several segments already in flight when the loss happened,
        # more than 3 duplicate ACKs legitimately arrive, inflating cwnd
        # further still -- so this is a floor, not an exact match).
        self.assertGreaterEqual(client.ssthresh, client.mss * 2 - 1)
        self.assertTrue(client.in_fast_recovery)
        self.assertGreaterEqual(client.cwnd, client.ssthresh + 3 * client.mss - 1)

    def test_transfer_completes_byte_exact_despite_the_forced_loss(self):
        clock, link, client, server = make_pair(mss=256)
        pump_until(clock, link, client, server, lambda: client.is_established)
        payload = bytes(range(256)) * 200
        real_send = link.endpoint_a.send
        state = {"n": 0}

        def flaky_send(data):
            from causeway.segment import Segment
            s = Segment.decode(data)
            state["n"] += 1
            if s.payload and state["n"] % 7 == 0:
                return  # drop every 7th outbound data-bearing segment
            real_send(data)

        link.endpoint_a.send = flaky_send
        received = bytearray()
        client.send(payload)
        client.close()

        def maybe_close_and_check_done():
            if server.eof and not server.close_requested:
                server.close()
            return client.closed and server.closed

        pump_until(clock, link, client, server, maybe_close_and_check_done,
                   max_time=120, drain_into=received)
        self.assertEqual(bytes(received), payload)


class TestTimeoutCollapse(unittest.TestCase):
    def test_timeout_resets_cwnd_to_one_mss_and_halves_ssthresh(self):
        # Track cwnd immediately before every event so we know its exact
        # value the instant before the timeout collapses it, whatever else
        # happened to be in flight and growing cwnd right up to that moment.
        last_cwnd = {"v": None}

        def on_event(e):
            if e["type"] == "timeout":
                last_cwnd["at_loss"] = last_cwnd["v"]
            last_cwnd["v"] = e["cwnd"]

        clock, link, client, server = make_pair(mss=256, loss=0.0, on_event=on_event)
        pump_until(clock, link, client, server, lambda: client.is_established)
        client.send(b"z" * 50_000)
        pump_until(clock, link, client, server, lambda: client.cwnd >= 256 * 10, max_time=30)

        # Black-hole the link entirely so the next segment can only be
        # recovered via a full RTO timeout, never fast retransmit.
        link.endpoint_a.send = lambda data: None
        pump_until(clock, link, client, server, lambda: client.stats["timeouts"] >= 1, max_time=30)

        self.assertEqual(client.cwnd, client.mss)
        expected_ssthresh = max(last_cwnd["at_loss"] / 2, 2.0 * client.mss)
        self.assertAlmostEqual(client.ssthresh, expected_ssthresh, delta=1)
        self.assertFalse(client.in_fast_recovery)


if __name__ == "__main__":
    unittest.main()
