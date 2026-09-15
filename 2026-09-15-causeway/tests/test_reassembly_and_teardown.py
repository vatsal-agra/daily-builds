import unittest

from causeway.clock import VirtualClock
from causeway.connection import Connection
from causeway.segment import ACK, Segment
from causeway.wire import SimulatedLink
from tests.test_congestion_control import make_pair, pump_until


class TestOutOfOrderReassembly(unittest.TestCase):
    def test_forced_reorder_still_delivers_in_order_with_no_duplication(self):
        clock, link, client, server = make_pair(mss=64, loss=0.0, reorder=1.0, jitter=0.01, seed=5)
        pump_until(clock, link, client, server, lambda: client.is_established)
        payload = bytes(range(256)) * 20  # many small segments to reorder
        client.send(payload)
        client.close()
        received = bytearray()

        def done():
            if server.eof and not server.close_requested:
                server.close()
            return client.closed and server.closed

        pump_until(clock, link, client, server, done, max_time=60, drain_into=received)
        self.assertEqual(bytes(received), payload)

    def test_duplicate_segments_are_not_delivered_twice(self):
        clock, link, client, server = make_pair(mss=64, loss=0.0, dup=1.0, seed=9)
        pump_until(clock, link, client, server, lambda: client.is_established)
        payload = bytes(range(200))
        client.send(payload)
        client.close()
        received = bytearray()

        def done():
            if server.eof and not server.close_requested:
                server.close()
            return client.closed and server.closed

        pump_until(clock, link, client, server, done, max_time=60, drain_into=received)
        self.assertEqual(bytes(received), payload)  # not doubled, not corrupted


class TestGracefulClose(unittest.TestCase):
    def test_standard_close_reaches_closed_on_both_sides(self):
        clock, link, client, server = make_pair(mss=512, loss=0.0)
        pump_until(clock, link, client, server, lambda: client.is_established)
        client.send(b"done soon")
        client.close()

        def done():
            if server.eof and not server.close_requested:
                server.close()
            return client.closed and server.closed

        pump_until(clock, link, client, server, done, max_time=30)
        self.assertTrue(client.closed)
        self.assertTrue(server.closed)

    def test_survives_a_lost_final_ack(self):
        """The classic TCP TIME_WAIT scenario: the very last ACK (client's
        ACK of the server's FIN) is dropped. The server must not hang
        forever waiting for it -- its own un-acked FIN simply times out and
        retransmits like any other segment, the client (still in TIME_WAIT)
        re-ACKs it, and both sides still reach CLOSED."""
        clock = VirtualClock()
        link = SimulatedLink(clock, base_delay=0.01, jitter=0.0, seed=0)
        client = Connection("client", link.endpoint_a, clock, mss=512)
        server = Connection("server", link.endpoint_b, clock, mss=512)

        pump_until(clock, link, client, server, lambda: client.is_established)
        client.send(b"short message")
        client.close()

        dropped_one = {"done": False}
        original_send = link.endpoint_a.send  # capture before overwriting, to avoid self-recursion

        def send_with_one_drop(data: bytes) -> None:
            try:
                s = Segment.decode(data)
            except ValueError:
                s = None
            # The final ACK: a pure ACK (no payload) sent by the client
            # while the server still has an outstanding (unacked) FIN.
            if (s is not None and not dropped_one["done"] and s.flags == ACK and not s.payload
                    and server.fin_sent and not server.fin_acked):
                dropped_one["done"] = True
                return
            original_send(data)

        link.endpoint_a.send = send_with_one_drop

        def done():
            if server.eof and not server.close_requested:
                server.close()
            return client.closed and server.closed

        pump_until(clock, link, client, server, done, max_time=30)
        self.assertTrue(dropped_one["done"], "test didn't actually get a chance to drop the final ACK")
        self.assertTrue(client.closed)
        self.assertTrue(server.closed)


if __name__ == "__main__":
    unittest.main()
