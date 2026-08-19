"""End-to-end tests against the real HTTP API — a genuine
ThreadingHTTPServer bound to an ephemeral port, hit with real requests,
not mocked. Verifies the browser-facing contract, including the same
partition-isolation and delete_range-atomicity guarantees the core
library tests check directly."""

import json
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from skein.web import server as webserver


def _post(base, path, payload):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(base + path, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _get(base, path):
    try:
        with urllib.request.urlopen(base + path, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


class TestWebPlayground(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), webserver.Handler)
        cls.port = cls.httpd.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.server_thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.server_thread.start()

        cls._stop_ticker = False

        def tick_loop():
            while not cls._stop_ticker:
                time.sleep(0.05)
                webserver.STATE.tick()

        cls.ticker_thread = threading.Thread(target=tick_loop, daemon=True)
        cls.ticker_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls._stop_ticker = True
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        webserver.STATE.reset()

    def test_index_serves_html(self):
        with urllib.request.urlopen(self.base + "/", timeout=5) as resp:
            status = resp.status
            body = resp.read().decode()
        self.assertEqual(status, 200)
        self.assertIn("<title>", body)
        self.assertIn("Skein", body)

    def test_state_endpoint_lists_all_three_sites(self):
        status, data = _get(self.base, "/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(set(data["sites"]), {"Alice", "Bob", "Carol"})

    def test_type_propagates_and_converges(self):
        _post(self.base, "/api/type", {"site": "Alice", "pos": 0, "text": "hi"})
        time.sleep(0.5)
        _, data = _get(self.base, "/api/state")
        self.assertEqual(data["sites"]["Bob"]["text"], "hi")
        self.assertTrue(data["converged"])

    def test_bad_site_name_is_400_not_a_crash(self):
        status, data = _post(self.base, "/api/type", {"site": "Nope", "pos": 0, "text": "x"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_unknown_route_is_404(self):
        status, data = _get(self.base, "/api/does-not-exist")
        self.assertEqual(status, 404)

    def test_partition_and_heal_via_api(self):
        _post(self.base, "/api/partition", {"site": "Bob"})
        _post(self.base, "/api/type", {"site": "Alice", "pos": 0, "text": "z"})
        time.sleep(0.5)
        _, data = _get(self.base, "/api/state")
        self.assertEqual(data["sites"]["Bob"]["text"], "", "Bob is partitioned, must not see the edit yet")
        self.assertTrue(data["sites"]["Bob"]["partitioned"])

        _post(self.base, "/api/heal", {"site": "Bob"})
        time.sleep(0.5)
        _, data = _get(self.base, "/api/state")
        self.assertEqual(data["sites"]["Bob"]["text"], "z")
        self.assertFalse(data["sites"]["Bob"]["partitioned"])

    def test_undo_redo_via_api(self):
        _post(self.base, "/api/type", {"site": "Alice", "pos": 0, "text": "hi"})
        _, data = _post(self.base, "/api/undo", {"site": "Alice"})
        self.assertEqual(data["sites"]["Alice"]["text"], "h")
        _, data = _post(self.base, "/api/redo", {"site": "Alice"})
        self.assertEqual(data["sites"]["Alice"]["text"], "hi")

    def test_oversized_delete_range_is_rejected_atomically(self):
        """The delete_range data-loss bug from REVIEW.md, exercised
        through the real HTTP API this time, not just the library."""
        _post(self.base, "/api/type", {"site": "Alice", "pos": 0, "text": "hello"})
        status, _ = _post(self.base, "/api/delete", {"site": "Alice", "pos": 0, "count": 9999})
        self.assertEqual(status, 400)
        _, state = _get(self.base, "/api/state")
        self.assertEqual(state["sites"]["Alice"]["text"], "hello")

    def test_chaos_knobs_endpoint(self):
        status, data = _post(self.base, "/api/chaos", {"drop": 0.5, "dup": 0.3, "latency_min": 2, "latency_max": 5})
        self.assertEqual(status, 200)
        self.assertAlmostEqual(data["network"]["drop_prob"], 0.5)
        self.assertAlmostEqual(data["network"]["dup_prob"], 0.3)
        self.assertEqual(data["network"]["latency_range"], [2, 5])

    def test_reset_endpoint_clears_state(self):
        _post(self.base, "/api/type", {"site": "Alice", "pos": 0, "text": "hi"})
        _post(self.base, "/api/reset", {})
        _, data = _get(self.base, "/api/state")
        self.assertEqual(data["sites"]["Alice"]["text"], "")


if __name__ == "__main__":
    unittest.main()
