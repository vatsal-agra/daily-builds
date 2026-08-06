"""End-to-end tests for the JSON API server: a real HTTP client (stdlib
urllib) against a real ThreadingHTTPServer instance, exercising the same
code path the web UI uses. No chess logic is duplicated here -- these
tests only check the HTTP/JSON contract."""

import json
import threading
import unittest
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer

from zugzwang import server as server_module


class TestServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server_module.Handler)
        cls.port = cls.httpd.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def _get(self, path):
        try:
            with urllib.request.urlopen(self.base + path, timeout=10) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def _post(self, path, payload):
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.base + path, data=data, headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def setUp(self):
        # start every test from a clean, deterministic game
        self._post("/api/new", {"human_color": "white", "think_time": 0.3})

    def test_index_page_serves(self):
        with urllib.request.urlopen(self.base + "/", timeout=10) as resp:
            self.assertEqual(resp.status, 200)
            body = resp.read().decode("utf-8")
            self.assertIn("Zugzwang", body)

    def test_state_endpoint(self):
        status, body = self._get("/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(body["to_move"], "white")
        self.assertFalse(body["game_over"])
        self.assertIn("e2e4", body["legal_moves"])

    def test_legal_moves_for_square(self):
        status, body = self._get("/api/moves?square=e2")
        self.assertEqual(status, 200)
        dests = {m["to"] for m in body["moves"]}
        self.assertEqual(dests, {"e3", "e4"})

    def test_make_move_then_engine_replies(self):
        status, body = self._post("/api/move", {"uci": "e2e4"})
        self.assertEqual(status, 200)
        self.assertEqual(body["to_move"], "black")
        self.assertEqual(body["san_history"], ["e4"])

        status, body = self._post("/api/engine_move", {})
        self.assertEqual(status, 200)
        self.assertEqual(body["to_move"], "white")
        self.assertEqual(len(body["san_history"]), 2)
        self.assertIsNotNone(body["engine_info"])

    def test_illegal_move_rejected(self):
        status, body = self._post("/api/move", {"uci": "e2e5"})
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_malformed_move_rejected(self):
        status, body = self._post("/api/move", {"uci": "zz"})
        self.assertEqual(status, 400)

    def test_bad_fen_rejected_without_corrupting_session(self):
        # start a real game, then attempt (and fail) a bad reset
        self._post("/api/move", {"uci": "e2e4"})
        status, body = self._post("/api/new", {"fen": "garbage not a fen"})
        self.assertEqual(status, 400)
        # the earlier game must be completely unaffected
        status, body = self._get("/api/state")
        self.assertEqual(body["san_history"], ["e4"])

    def test_pgn_export_and_reimport_round_trip(self):
        self._post("/api/move", {"uci": "e2e4"})
        self._post("/api/move", {"uci": "e7e5"})
        status, body = self._get("/api/pgn")
        self.assertEqual(status, 200)
        pgn_text = body["pgn"]
        self.assertIn("1. e4 e5", pgn_text)

        status, body = self._post("/api/load_pgn", {"pgn": pgn_text})
        self.assertEqual(status, 200)
        self.assertEqual(body["san_history"], ["e4", "e5"])

    def test_load_garbage_pgn_rejected(self):
        status, body = self._post("/api/load_pgn", {"pgn": "not a pgn at all"})
        self.assertEqual(status, 400)

    def test_unknown_route_404(self):
        status, body = self._get("/api/nonexistent")
        self.assertEqual(status, 404)

    def test_new_game_with_custom_fen_and_black_to_move(self):
        black_first_fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
        status, body = self._post(
            "/api/new", {"fen": black_first_fen, "human_color": "black", "think_time": 0.3},
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["to_move"], "black")
        self.assertEqual(body["fen"], black_first_fen)


if __name__ == "__main__":
    unittest.main()
