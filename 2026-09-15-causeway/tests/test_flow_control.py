"""Proves flow control (receiver-advertised window) is a genuinely separate
control loop from congestion control: a fast sender with an enormous,
unloss-limited cwnd is still throttled purely by a small receiver buffer,
and a receiver that stops draining its buffer can still bring the sender to
a full stop and later resume it -- the classic zero-window / persist-timer
scenario -- without either side deadlocking.
"""
import unittest

from causeway.clock import VirtualClock
from causeway.connection import Connection
from causeway.wire import SimulatedLink
from tests.test_congestion_control import make_pair, pump_until


class TestFlowControlThrottlesIndependentlyOfCongestionControl(unittest.TestCase):
    def test_small_receiver_buffer_caps_in_flight_bytes_even_at_zero_loss(self):
        clock, link, client, server = make_pair(mss=256, loss=0.0)
        server.recv_capacity = 512  # tiny compared to what cwnd will reach
        pump_until(clock, link, client, server, lambda: client.is_established)

        client.send(b"q" * 100_000)
        max_in_flight_seen = 0
        received = bytearray()
        for _ in range(400):
            if client.snd_nxt >= client.snd_una + 100_000:
                break
            cands = [x for x in (link.next_event_time(), client.next_timer_deadline(),
                                  server.next_timer_deadline()) if x is not None]
            if not cands:
                break
            t = max(clock.t, min(cands))
            clock.advance_to(t)
            link.deliver_due(t)
            client.step(t)
            server.step(t)
            received.extend(server.recv())
            max_in_flight_seen = max(max_in_flight_seen, client.bytes_in_flight)
            # cwnd should be climbing well past the receiver's tiny buffer if
            # given the chance -- proving flow control, not congestion
            # control, is what's actually capping the sender.
            if client.cwnd > 4000:
                break

        self.assertGreater(client.cwnd, 4000, "cwnd should have grown large under zero loss")
        # bytes in flight must never exceed roughly the receiver's buffer,
        # regardless of how large cwnd got.
        self.assertLessEqual(max_in_flight_seen, 512 + 256)  # one MSS of slack for the in-order edge

    def test_zero_window_persist_probe_avoids_deadlock_and_eventually_resumes(self):
        clock, link, client, server = make_pair(mss=128, loss=0.0, persist_base=0.2, persist_max=1.0)
        server.recv_capacity = 128
        pump_until(clock, link, client, server, lambda: client.is_established)

        client.send(b"r" * 5000)
        received = bytearray()
        # Deliberately never call server.recv() for a long stretch: the
        # receive buffer fills, advertises a zero window, and the sender
        # must fall back to probing rather than sending nothing forever.
        started_probing = False
        for _ in range(2000):
            cands = [x for x in (link.next_event_time(), client.next_timer_deadline(),
                                  server.next_timer_deadline()) if x is not None]
            if not cands:
                raise AssertionError("stalled before any persist probe was sent")
            t = max(clock.t, min(cands))
            clock.advance_to(t)
            link.deliver_due(t)
            client.step(t)
            server.step(t)
            if client.stats["persist_probes"] >= 1:
                started_probing = True
                break
        self.assertTrue(started_probing, "sender never fell back to zero-window probing")
        self.assertEqual(client.peer_rwnd, 0)

        # Now the application finally starts draining -- the window should
        # reopen and the transfer should complete normally, proving the
        # persist mechanism doesn't leave the connection stuck forever.
        def drain_and_maybe_close():
            if server.eof and not server.close_requested:
                server.close()
            return client.closed and server.closed

        client.close()
        pump_until(clock, link, client, server, drain_and_maybe_close, max_time=60, drain_into=received)
        self.assertEqual(bytes(received), b"r" * 5000)


if __name__ == "__main__":
    unittest.main()
