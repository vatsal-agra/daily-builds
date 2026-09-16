import hashlib
import os
import random
import sys
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from undertow.netsim import NetworkSimulator
from undertow.socket_api import UndertowSocket

TIMEOUT = 15.0


def _transfer(payload: bytes, loss=0.0, dup=0.0, reorder=0.0, min_delay=0.0, max_delay=0.0, seed=0, client_isn=None, timeout=TIMEOUT):
    server = UndertowSocket()
    client = UndertowSocket(initial_seq=client_isn)
    saddr = server.local_address()
    caddr = client.local_address()

    sim = NetworkSimulator(
        peer_a=caddr, peer_b=saddr, loss=loss, dup=dup, reorder=reorder,
        min_delay=min_delay, max_delay=max_delay, seed=seed,
    )
    sim.start()
    result = {}

    def run_server():
        conn = server.accept(sim.leg_b_addr, timeout=timeout)
        result["recv"] = conn.recv_all(timeout=timeout)
        conn.close(timeout=timeout)

    t = threading.Thread(target=run_server, daemon=True)
    t.start()
    try:
        conn = client.connect(sim.leg_a_addr, timeout=timeout)
        conn.send(payload)
        conn.close(timeout=timeout)
        t.join(timeout=timeout)
    finally:
        sim.stop()
        client.close()
        server.close()
    return result.get("recv", b""), conn


class TestHandshakeAndBasicTransfer(unittest.TestCase):
    def test_clean_link_small_payload(self):
        payload = b"the quick brown fox jumps over the lazy dog" * 20
        got, conn = _transfer(payload)
        self.assertEqual(got, payload)
        self.assertEqual(conn.state, "CLOSED")

    def test_empty_payload_still_completes_handshake_and_close(self):
        got, conn = _transfer(b"")
        self.assertEqual(got, b"")
        self.assertEqual(conn.state, "CLOSED")

    def test_multi_segment_payload_exact_mss_boundary(self):
        from undertow.packet import MSS

        payload = bytes((i % 256) for i in range(MSS * 3))
        got, _ = _transfer(payload)
        self.assertEqual(got, payload)

    def test_large_random_payload(self):
        rng = random.Random(123)
        payload = bytes(rng.getrandbits(8) for _ in range(300_000))
        got, _ = _transfer(payload)
        self.assertEqual(hashlib.sha256(got).hexdigest(), hashlib.sha256(payload).hexdigest())


class TestSequenceWraparound(unittest.TestCase):
    def test_transfer_across_2_32_boundary(self):
        payload = b"wrap-around-bytes-" * 3000
        isn = (1 << 32) - 40
        got, _ = _transfer(payload, client_isn=isn)
        self.assertEqual(got, payload)


class TestLossyLink(unittest.TestCase):
    def test_survives_moderate_loss_dup_reorder(self):
        rng = random.Random(7)
        payload = bytes(rng.getrandbits(8) for _ in range(250_000))
        got, conn = _transfer(
            payload, loss=0.05, dup=0.03, reorder=0.05, min_delay=0.001, max_delay=0.01, seed=42
        )
        self.assertEqual(hashlib.sha256(got).hexdigest(), hashlib.sha256(payload).hexdigest())
        # real retransmission must have happened for this to be a meaningful test
        self.assertGreater(len([e for e in conn.trace_log if e["event"] == "retransmit"]), 0)

    def test_survives_moderate_loss_multiple_seeds(self):
        for seed in (1, 2, 3, 4):
            rng = random.Random(seed)
            payload = bytes(rng.getrandbits(8) for _ in range(60_000))
            got, _ = _transfer(payload, loss=0.04, dup=0.02, reorder=0.03, max_delay=0.008, seed=seed)
            self.assertEqual(got, payload, f"mismatch for seed={seed}")


class TestCongestionBehaviorUnderLoss(unittest.TestCase):
    def test_ssthresh_drops_after_loss_on_a_lossy_link(self):
        rng = random.Random(5)
        payload = bytes(rng.getrandbits(8) for _ in range(400_000))
        _, conn = _transfer(payload, loss=0.06, dup=0.02, reorder=0.04, max_delay=0.01, seed=5)
        stats = conn.stats()
        # a real loss event must have pulled ssthresh below its huge initial value
        self.assertLess(stats["ssthresh"], 64 * 1024)

    def test_cwnd_trace_shows_growth_from_one_segment(self):
        payload = b"x" * 100_000
        _, conn = _transfer(payload)
        cwnd_events = [e["cwnd"] for e in conn.trace_log if e["event"] == "cwnd"]
        self.assertTrue(cwnd_events)
        self.assertGreater(max(cwnd_events), min(cwnd_events))


class TestRTOUnderTimeout(unittest.TestCase):
    def test_single_retransmit_only_touches_head_of_window_not_whole_burst(self):
        # regression test for a cascading-timeout bug: an RTO on the oldest
        # unacked segment must not cause siblings sent at the same time to
        # be judged against an already-backed-off RTO and time out too.
        rng = random.Random(99)
        payload = bytes(rng.getrandbits(8) for _ in range(400_000))
        got, conn = _transfer(
            payload, loss=0.08, dup=0.03, reorder=0.06, min_delay=0.002, max_delay=0.015, seed=99, timeout=45.0
        )
        self.assertEqual(got, payload)
        # The real regression signal is that this completes at all within
        # `timeout` above: the original cascading-backoff bug made one
        # segment's exponential RTO backoff apply to sibling segments sent
        # under a smaller RTO, so timeouts compounded (4s, then ~5s, then
        # ~10s gaps) and a 400KB transfer never finished. As a secondary
        # sanity check, the timeout count should track roughly with the
        # network's actual loss rate (~8% of ~290 segments), not blow up
        # into the hundreds a cascade would produce.
        timeouts = [e for e in conn.trace_log if e["event"] == "rto_timeout"]
        self.assertLess(len(timeouts), 100)


if __name__ == "__main__":
    unittest.main()
