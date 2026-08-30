"""Integration coverage for the live explorer server -- specifically a
regression test for two Phase 3 findings (#6, #7 in REVIEW.md) that no
pure-unit test could catch, because they only manifest when the network's
gossip clock and block timestamps are driven by real elapsed time rather
than a test's own explicit round counter."""
import http.client
import json
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import server as srv


class TestLiveGossipConvergence(unittest.TestCase):
    """Regression test for REVIEW.md finding #6: SimNetwork's virtual clock
    used to never advance past scheduled message latency, so live nodes
    never actually received each other's blocks."""

    def test_ticking_the_network_actually_delivers_gossip(self):
        net = srv.Network(seed=7)
        # Network.tick()'s own timestamp throttle (REVIEW.md finding #7) caps
        # its long-run rate at ~1 real second per tick once the recorded
        # clock catches up to real time, which happens almost immediately
        # here -- so a handful of ticks is both enough to observe gossip
        # (3 nodes round-robin: 2-3 ticks covers everyone at least once) and
        # keeps this test from taking a minute.
        for _ in range(8):
            net.tick()
        status = net.status()
        total_accepted_from_peers = sum(n["blocks_accepted_from_peers"] for n in status["nodes"].values())
        self.assertGreater(total_accepted_from_peers, 0,
                            "no node ever accepted a block from a peer -- gossip is not being delivered")


class TestExplorerHTTPServer(unittest.TestCase):
    """Spins up the real HTTP server on an ephemeral port for a few seconds
    -- covers the actual do_GET/do_POST paths, not just the Network class,
    including the Phase 3 path-traversal fix (finding #3)."""

    @classmethod
    def setUpClass(cls):
        import threading
        from http.server import ThreadingHTTPServer

        cls.network = srv.Network(seed=3)
        srv.Handler.network = cls.network
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.Handler)
        cls.port = cls.httpd.server_address[1]
        cls.server_thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.server_thread.start()
        cls.stop_mining = threading.Event()
        cls.mining_thread = threading.Thread(
            target=srv.mining_loop, args=(cls.network, cls.stop_mining), daemon=True)
        cls.mining_thread.start()
        time.sleep(1.5)  # let a few blocks get mined before the tests below run

    @classmethod
    def tearDownClass(cls):
        cls.stop_mining.set()
        cls.httpd.shutdown()

    def _get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp.status, body

    def test_index_page_served(self):
        status, body = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"Genesis", body)

    def test_status_endpoint(self):
        status, body = self._get("/api/status")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(set(data["names"]), {"Ada", "Grace", "Katherine"})

    def test_path_traversal_is_rejected(self):
        # Regression test for REVIEW.md finding #3: the old catch-all static
        # handler would have read this file straight off disk.
        for path in ["/../../../etc/passwd", "/../src/crypto.py", "/etc/passwd"]:
            status, _ = self._get(path)
            self.assertEqual(status, 404, f"{path} should 404, not be served")

    def test_unknown_api_route_404s_cleanly(self):
        status, _ = self._get("/api/does-not-exist")
        self.assertEqual(status, 404)

    def test_faucet_and_send_round_trip(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        status_data = json.loads(self._get("/api/status")[1])
        grace_address = status_data["nodes"]["Grace"]["address"]
        body = json.dumps({"node": "Ada", "to_address": grace_address}).encode()
        conn.request("POST", "/api/faucet", body=body, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        result = json.loads(resp.read())
        conn.close()
        self.assertTrue(result["ok"], result.get("reason"))


if __name__ == "__main__":
    unittest.main()
