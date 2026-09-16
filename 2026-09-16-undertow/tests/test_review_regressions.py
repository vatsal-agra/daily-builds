"""Regression tests for bugs found during the Phase 3 adversarial review.
See REVIEW.md for the full writeup of each one.
"""

import os
import random
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from undertow.netsim import NetworkSimulator
from undertow.socket_api import UndertowSocket


class TestHandshakeSeqAdvance(unittest.TestCase):
    def test_connect_completes_promptly_on_a_clean_link(self):
        # Regression: _enqueue_control() forgot to advance send_next past
        # the SYN's one byte of sequence space, so send_una (which the
        # peer's ACK correctly set to iss+1) could never again equal
        # send_next (stuck at iss) and the handshake-complete check never
        # fired -- connect()/accept() hung until their own timeout no
        # matter how clean the link was.
        server = UndertowSocket()
        client = UndertowSocket()
        saddr = server.local_address()
        server_conn = {}

        def run_server():
            server_conn["conn"] = server.accept(client.local_address(), timeout=3)
            server_conn["conn"].recv_all(timeout=3)
            server_conn["conn"].close(timeout=3)

        t = threading.Thread(target=run_server, daemon=True)
        t.start()
        t0 = time.monotonic()
        conn = client.connect(saddr, timeout=3)
        elapsed = time.monotonic() - t0
        self.assertTrue(conn.is_established)
        self.assertLess(elapsed, 1.0, "handshake should complete in well under a second on localhost")
        conn.close(timeout=3)
        t.join(timeout=3)
        client.close()
        server.close()


class TestCascadingTimeoutRegression(unittest.TestCase):
    def test_rto_timer_tracks_only_send_una_not_whichever_segment_is_oldest(self):
        # Regression: _handle_timers used to pick "whichever unacked
        # segment has the oldest send_time" to check against the RTO. Once
        # the head-of-line segment (send_una) got retransmitted, its
        # send_time became "now", so this flipped to checking a *different*
        # segment sent earlier under a smaller RTO -- but the check used
        # the *current*, already-backed-off RTO value, timing that segment
        # out far earlier than it should have and doubling the backoff
        # again. That cascaded across every segment in the original burst,
        # and a 400KB transfer under 8% loss never finished.
        rng = random.Random(99)
        payload = bytes(rng.getrandbits(8) for _ in range(400_000))

        server = UndertowSocket()
        client = UndertowSocket()
        saddr = server.local_address()
        caddr = client.local_address()
        sim = NetworkSimulator(
            peer_a=caddr, peer_b=saddr, loss=0.08, dup=0.03, reorder=0.06,
            min_delay=0.002, max_delay=0.015, seed=99,
        )
        sim.start()
        result = {}

        def run_server():
            conn = server.accept(sim.leg_b_addr, timeout=40)
            result["recv"] = conn.recv_all(timeout=40)
            conn.close(timeout=40)

        t = threading.Thread(target=run_server, daemon=True)
        t.start()
        conn = client.connect(sim.leg_a_addr, timeout=40)
        conn.send(payload)
        # this used to never return within any reasonable timeout
        conn.close(timeout=45)
        t.join(timeout=45)
        sim.stop()
        client.close()
        server.close()

        self.assertEqual(result.get("recv"), payload)


class TestZeroWindowDeadlockRegression(unittest.TestCase):
    def test_sender_recovers_once_slow_receiver_drains_its_buffer(self):
        # Regression: nothing told a stalled sender that the receiver's
        # app finally called recv() and freed up window space, because a
        # pure ACK carrying the new window was never sent on its own, and
        # a lost window-update wasn't retried either. A receiver whose app
        # was merely slow to start reading -- not misbehaving -- would
        # deadlock the whole connection forever.
        rng = random.Random(3)
        payload = bytes(rng.getrandbits(8) for _ in range(200_000))  # > the 64KB recv window

        server = UndertowSocket()
        client = UndertowSocket()
        saddr = server.local_address()
        caddr = client.local_address()
        result = {}

        def run_server():
            conn = server.accept(caddr, timeout=10)
            time.sleep(2)  # app is slow to start reading; window fills to 0
            result["recv"] = conn.recv_all(timeout=15)
            conn.close(timeout=10)

        t = threading.Thread(target=run_server, daemon=True)
        t.start()
        conn = client.connect(saddr, timeout=10)
        conn.send(payload)
        conn.close(timeout=20)  # used to hang until this raised TimeoutError
        t.join(timeout=15)
        client.close()
        server.close()

        self.assertEqual(result.get("recv"), payload)
        probes = [e for e in conn.trace_log if e["event"] == "persist_probe"]
        self.assertGreater(len(probes), 0, "the zero-window stall should have triggered at least one persist probe")


class TestFullDuplex(unittest.TestCase):
    def test_both_directions_transfer_concurrently(self):
        def read_exact(conn, n, timeout=15):
            out = bytearray()
            while len(out) < n:
                out.extend(conn.recv(n - len(out), timeout=timeout))
            return bytes(out)

        server = UndertowSocket()
        client = UndertowSocket()
        saddr = server.local_address()
        caddr = client.local_address()
        c2s = bytes(random.Random(11).getrandbits(8) for _ in range(150_000))
        s2c = bytes(random.Random(22).getrandbits(8) for _ in range(150_000))
        result = {}

        def run_server():
            conn = server.accept(caddr, timeout=15)
            conn.send(s2c)
            result["server_recv"] = read_exact(conn, len(c2s))
            conn.close(timeout=15)

        t = threading.Thread(target=run_server, daemon=True)
        t.start()
        conn = client.connect(saddr, timeout=15)
        conn.send(c2s)
        got = read_exact(conn, len(s2c))
        conn.close(timeout=15)
        t.join(timeout=15)
        client.close()
        server.close()

        self.assertEqual(got, s2c)
        self.assertEqual(result.get("server_recv"), c2s)


class TestResetAbort(unittest.TestCase):
    def test_abort_sends_rst_and_peer_sees_a_clean_error(self):
        server = UndertowSocket()
        client = UndertowSocket()
        saddr = server.local_address()
        caddr = client.local_address()
        result = {}

        def run_server():
            conn = server.accept(caddr, timeout=5)
            try:
                conn.recv_all(timeout=5)
                result["outcome"] = "no error raised"
            except ConnectionError as e:
                result["outcome"] = str(e)

        t = threading.Thread(target=run_server, daemon=True)
        t.start()
        conn = client.connect(saddr, timeout=5)
        conn.send(b"partial data")
        time.sleep(0.2)
        conn.abort(reason="unit test")
        t.join(timeout=5)
        client.close()
        server.close()

        self.assertEqual(result.get("outcome"), "connection reset")
        self.assertEqual(conn.state, "CLOSED")
        with self.assertRaises(ConnectionError):
            conn.send(b"should fail")


if __name__ == "__main__":
    unittest.main()
