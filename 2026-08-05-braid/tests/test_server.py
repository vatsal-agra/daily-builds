"""Tests for server.py: op-shape validation (REVIEW.md #6) and Hub
bookkeeping in isolation, plus a live-socket HTTP test class covering
static file serving, the path-traversal fix (REVIEW.md #5), and the
POST /op -> validate -> relay path against a real running instance. A
full multi-tab-*browser* check (SSE, live sync) lives outside this
unittest suite (Playwright, run via demo.sh) since that needs an actual
browser engine."""

import http.client
import json
import os
import socket
import sys
import threading
import time
import unittest
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import Handler, Hub, _is_valid_op_id, _validate_op


class TestOpValidation(unittest.TestCase):
    def test_valid_insert_passes(self):
        _validate_op({"type": "insert", "id": [1, "A"], "origin": None, "value": "x"})  # no raise

    def test_valid_insert_with_origin_passes(self):
        _validate_op({"type": "insert", "id": [2, "A"], "origin": [1, "A"], "value": "y"})

    def test_valid_delete_passes(self):
        _validate_op({"type": "delete", "id": [3, "A"], "target": [1, "A"]})

    def test_valid_restore_passes(self):
        _validate_op({"type": "restore", "id": [3, "A"], "target": [1, "A"]})

    def test_not_a_dict_rejected(self):
        with self.assertRaises(ValueError):
            _validate_op("not an op")

    def test_unknown_type_rejected(self):
        with self.assertRaises(ValueError):
            _validate_op({"type": "pwn", "id": [1, "A"]})

    def test_missing_id_rejected(self):
        with self.assertRaises(ValueError):
            _validate_op({"type": "insert", "origin": None, "value": "x"})

    def test_insert_missing_value_rejected(self):
        with self.assertRaises(ValueError):
            _validate_op({"type": "insert", "id": [1, "A"], "origin": None})

    def test_insert_multichar_value_rejected(self):
        with self.assertRaises(ValueError):
            _validate_op({"type": "insert", "id": [1, "A"], "origin": None, "value": "ab"})

    def test_insert_empty_value_rejected(self):
        with self.assertRaises(ValueError):
            _validate_op({"type": "insert", "id": [1, "A"], "origin": None, "value": ""})

    def test_insert_single_emoji_value_accepted(self):
        # one code point, two UTF-16 units -- must NOT be rejected as "multi-char"
        _validate_op({"type": "insert", "id": [1, "A"], "origin": None, "value": "\U0001F600"})

    def test_delete_missing_target_rejected(self):
        with self.assertRaises(ValueError):
            _validate_op({"type": "delete", "id": [1, "A"]})

    def test_bad_id_shapes_rejected(self):
        bad_ids = ["not-a-pair", [1], [1, "A", "extra"], ["A", 1], [1.5, "A"], [True, "A"], None]
        for bad in bad_ids:
            with self.assertRaises(ValueError, msg=f"id {bad!r} should be rejected"):
                _validate_op({"type": "insert", "id": bad, "origin": None, "value": "x"})

    def test_is_valid_op_id_directly(self):
        self.assertTrue(_is_valid_op_id([1, "A"]))
        self.assertFalse(_is_valid_op_id([1, ""]))
        self.assertFalse(_is_valid_op_id(None))
        self.assertFalse(_is_valid_op_id([1, "A", "extra"]))


class TestHub(unittest.TestCase):
    def test_relay_appends_to_log_and_broadcasts(self):
        hub = Hub()
        q = hub.subscribe("B")
        op = {"type": "insert", "id": [1, "A"], "origin": None, "value": "x"}
        hub.relay_op("A", op)
        self.assertEqual(hub.snapshot_ops(), [op])
        event = q.get_nowait()
        self.assertEqual(event, {"kind": "op", "from": "A", "op": op})

    def test_unsubscribe_removes_subscriber_and_announces_leave(self):
        hub = Hub()
        hub.subscribe("A")
        q_b = hub.subscribe("B")
        hub.update_presence("A", "Alice", 0, "#ff0000")
        q_b.get_nowait()  # drain the presence event we don't care about here
        self.assertIn("A", hub.subscribers)
        hub.unsubscribe("A")
        self.assertNotIn("A", hub.subscribers)
        self.assertNotIn("A", hub.snapshot_presence())
        leave_event = q_b.get_nowait()
        self.assertEqual(leave_event, {"kind": "presence_leave", "site": "A"})

    def test_unsubscribe_with_no_prior_presence_does_not_crash(self):
        hub = Hub()
        hub.subscribe("A")
        hub.unsubscribe("A")  # no presence entry was ever set for A
        self.assertNotIn("A", hub.subscribers)

    def test_presence_updates_and_broadcasts(self):
        hub = Hub()
        q = hub.subscribe("B")
        hub.update_presence("A", "Alice", 5, "#ff0000")
        self.assertEqual(hub.snapshot_presence()["A"]["name"], "Alice")
        self.assertEqual(hub.snapshot_presence()["A"]["cursor"], 5)
        event = q.get_nowait()
        self.assertEqual(event["kind"], "presence")
        self.assertEqual(event["name"], "Alice")

    def test_bootstrap_snapshot_is_a_copy_not_a_live_reference(self):
        hub = Hub()
        op = {"type": "insert", "id": [1, "A"], "origin": None, "value": "x"}
        hub.relay_op("A", op)
        snap = hub.snapshot_ops()
        snap.append("mutate me")
        self.assertEqual(len(hub.snapshot_ops()), 1)  # the hub's own log is untouched


def _free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class TestLiveServer(unittest.TestCase):
    """Spins up a real ThreadingHTTPServer with the real Handler class —
    exercises the actual HTTP layer, not just the validation functions."""

    @classmethod
    def setUpClass(cls):
        cls.port = _free_port()
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", cls.port), Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", cls.port), timeout=1):
                    break
            except (ConnectionRefusedError, OSError):
                time.sleep(0.05)

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        # each Handler request reads the module-level HUB global, so
        # swapping it out per-test gives every test a clean document
        # without needing to restart the actual server/socket.
        import server as server_module
        server_module.HUB = Hub()

    def _get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp.status, body

    def _post(self, path, obj):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        body = json.dumps(obj).encode("utf-8")
        conn.request("POST", path, body=body, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp.status, data

    def test_index_serves_html(self):
        status, body = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"Braid", body)

    def test_static_js_served(self):
        status, body = self._get("/static/rga.js")
        self.assertEqual(status, 200)
        self.assertIn(b"RGADocument", body)

    def test_unknown_path_404s(self):
        status, _ = self._get("/does-not-exist")
        self.assertEqual(status, 404)

    def test_path_traversal_via_raw_dotdot_is_blocked(self):
        """REVIEW.md #5: a raw '..' segment (a real client can send this
        even though curl/browsers normalize it away first) must not
        escape the static/ directory."""
        status, _ = self._get("/static/../cli.py")
        self.assertEqual(status, 403)

    def test_valid_op_is_accepted_and_relayed(self):
        status, body = self._post("/op", {"from": "A", "op": {
            "type": "insert", "id": [1, "A"], "origin": None, "value": "h",
        }})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"ok": True})

    def test_malformed_op_is_rejected_with_400(self):
        status, _ = self._post("/op", {"from": "A", "op": {"type": "insert", "id": [1, "A"]}})
        self.assertEqual(status, 400)

    def test_presence_post_accepted(self):
        status, body = self._post("/presence", {"site": "A", "name": "Alice", "cursor": 3, "color": "#f00"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"ok": True})

    def test_bootstrap_replays_prior_ops_to_a_new_connection(self):
        self._post("/op", {"from": "A", "op": {
            "type": "insert", "id": [1, "A"], "origin": None, "value": "h",
        }})
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", "/events?site=B")
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        chunk = resp.fp.readline()  # "data: {...}\n"
        self.assertTrue(chunk.startswith(b"data: "))
        event = json.loads(chunk[len(b"data: "):])
        self.assertEqual(event["kind"], "bootstrap")
        self.assertEqual(len(event["ops"]), 1)
        self.assertEqual(event["ops"][0]["value"], "h")
        conn.close()


if __name__ == "__main__":
    unittest.main()
