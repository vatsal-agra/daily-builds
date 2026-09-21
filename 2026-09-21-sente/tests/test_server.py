"""Server API tests: spins up the real Sente HTTP server on an ephemeral
port in a background thread and drives it with real HTTP requests (no
mocking of the handler) -- covering error handling / invalid input, which
the brief calls out explicitly as something Phase 4 polish must get
right, not just the happy path.

Requires trained checkpoints to already exist (run
scripts/run_training_ttt.py and scripts/run_training_c4.py first) --
skips gracefully if they don't, rather than failing the whole suite.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import json
import threading
import time
import unittest
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer

ROOT = os.path.join(os.path.dirname(__file__), "..")
HAS_TTT_CKPT = os.path.isdir(os.path.join(ROOT, "checkpoints", "tictactoe")) and \
    len(os.listdir(os.path.join(ROOT, "checkpoints", "tictactoe"))) > 0
HAS_C4_CKPT = os.path.isdir(os.path.join(ROOT, "checkpoints", "connect4jr")) and \
    len(os.listdir(os.path.join(ROOT, "checkpoints", "connect4jr"))) > 0


def request(method, url, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                  headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


@unittest.skipUnless(HAS_TTT_CKPT, "requires a trained tictactoe checkpoint")
class TestServerAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from sente import server as server_mod
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server_mod.Handler)
        cls.port = cls.httpd.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.2)

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def test_health(self):
        status, body = request("GET", f"{self.base}/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])

    def test_index_page_served(self):
        req = urllib.request.Request(f"{self.base}/", method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            self.assertEqual(resp.status, 200)
            html = resp.read().decode()
            self.assertIn("Sente", html)
            self.assertIn("<script>", html)

    def test_reset_and_move_happy_path(self):
        status, body = request("POST", f"{self.base}/api/reset", {"game": "tictactoe", "human_side": "X"})
        self.assertEqual(status, 200)
        self.assertEqual(body["human_player"], 1)
        self.assertFalse(body["terminal"])
        legal = body["legal_moves"]
        self.assertTrue(len(legal) > 0)

        status, body2 = request("POST", f"{self.base}/api/move", {"action": legal[0]})
        self.assertEqual(status, 200)
        # a move was applied and (if not terminal) the agent auto-responded
        cells_after = body2["state"]["cells"]
        self.assertEqual(cells_after[legal[0]], 1)  # human's X landed there

    def test_reset_invalid_game(self):
        status, body = request("POST", f"{self.base}/api/reset", {"game": "chess", "human_side": "X"})
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_reset_invalid_side(self):
        status, body = request("POST", f"{self.base}/api/reset", {"game": "tictactoe", "human_side": "Q"})
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_move_missing_action(self):
        request("POST", f"{self.base}/api/reset", {"game": "tictactoe", "human_side": "X"})
        status, body = request("POST", f"{self.base}/api/move", {})
        self.assertEqual(status, 400)

    def test_move_non_integer_action(self):
        request("POST", f"{self.base}/api/reset", {"game": "tictactoe", "human_side": "X"})
        status, body = request("POST", f"{self.base}/api/move", {"action": "banana"})
        self.assertEqual(status, 400)
        self.assertIn("integer", body["error"])

    def test_move_occupied_cell_rejected(self):
        status, body = request("POST", f"{self.base}/api/reset", {"game": "tictactoe", "human_side": "X"})
        legal = body["legal_moves"]
        request("POST", f"{self.base}/api/move", {"action": legal[0]})
        # legal[0] is now occupied by the human's move; playing it again
        # must be rejected regardless of whose turn it is now.
        status, body2 = request("POST", f"{self.base}/api/move", {"action": legal[0]})
        self.assertEqual(status, 400)

    def test_move_out_of_range_action(self):
        request("POST", f"{self.base}/api/reset", {"game": "tictactoe", "human_side": "X"})
        status, body = request("POST", f"{self.base}/api/move", {"action": 999})
        self.assertEqual(status, 400)

    def test_malformed_json_body(self):
        req = urllib.request.Request(f"{self.base}/api/move", data=b"not json{{{",
                                      method="POST", headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=10)
            self.fail("expected HTTPError")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 400)
            body = json.loads(e.read())
            self.assertIn("error", body)

    def test_unknown_route_404(self):
        status, body = request("GET", f"{self.base}/api/does-not-exist")
        self.assertEqual(status, 404)

    def test_hint_does_not_apply_a_move(self):
        status, body = request("POST", f"{self.base}/api/reset", {"game": "tictactoe", "human_side": "X"})
        cells_before = list(body["state"]["cells"])
        status, viz = request("POST", f"{self.base}/api/hint", {})
        self.assertEqual(status, 200)
        self.assertIn("visit_counts", viz)
        status, state_after = request("GET", f"{self.base}/api/state")
        self.assertEqual(state_after["state"]["cells"], cells_before, "hint() must not mutate the board")

    @unittest.skipUnless(HAS_C4_CKPT, "requires a trained connect4jr checkpoint")
    def test_switch_to_connect4jr(self):
        status, body = request("POST", f"{self.base}/api/reset", {"game": "connect4jr", "human_side": "X"})
        self.assertEqual(status, 200)
        self.assertEqual(body["game"], "connect4jr")
        self.assertEqual(body["board_rows"], 4)
        self.assertEqual(body["board_cols"], 5)
        # switch back so later tests in this class see tictactoe again
        request("POST", f"{self.base}/api/reset", {"game": "tictactoe", "human_side": "X"})


if __name__ == "__main__":
    unittest.main()
