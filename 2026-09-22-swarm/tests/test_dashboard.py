import json
import threading
import time
import unittest
import urllib.request

from swarm import dashboard


class TestDashboardHub(unittest.TestCase):
    def setUp(self):
        self.server = dashboard.run_dashboard("127.0.0.1", 0)
        self.addCleanup(self._teardown)

    def _teardown(self):
        self.server.shutdown()
        self.server.server_close()

    def _url(self, path):
        return f"http://127.0.0.1:{self.server.server_port}{path}"

    def test_index_page_served(self):
        with urllib.request.urlopen(self._url("/"), timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            body = resp.read()
            self.assertIn(b"<html", body)
            self.assertIn(b"EventSource", body)

    def test_post_event_then_appears_in_history(self):
        evt = {"type": "hello", "node": "aa" * 20, "num_pieces": 3, "have_bitfield": "00"}
        req = urllib.request.Request(self._url("/events"), data=json.dumps(evt).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 204)
        self.assertEqual(len(self.server.history_snapshot()), 1)
        self.assertEqual(self.server.history_snapshot()[0]["type"], "hello")

    def test_malformed_post_rejected_cleanly(self):
        import urllib.error

        req = urllib.request.Request(self._url("/events"), data=b"not json", headers={"Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(cm.exception.code, 400)

    def test_unknown_get_path_404(self):
        import urllib.error

        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(self._url("/nope"), timeout=5)
        self.assertEqual(cm.exception.code, 404)

    def test_sse_stream_delivers_posted_events_live(self):
        received = []
        stop = threading.Event()

        def reader():
            with urllib.request.urlopen(self._url("/stream"), timeout=10) as resp:
                for raw_line in resp:
                    if stop.is_set():
                        return
                    line = raw_line.decode().strip()
                    if line.startswith("data: "):
                        received.append(json.loads(line[len("data: ") :]))
                        if len(received) >= 2:
                            return

        t = threading.Thread(target=reader, daemon=True)
        t.start()
        time.sleep(0.2)  # let the SSE client register before we publish
        self.server.publish({"type": "hello", "node": "bb" * 20})
        self.server.publish({"type": "piece_complete", "node": "bb" * 20, "piece": 3})
        t.join(timeout=5)
        stop.set()
        self.assertEqual(len(received), 2)
        self.assertEqual(received[0]["type"], "hello")
        self.assertEqual(received[1]["piece"], 3)

    def test_sse_stream_replays_history_to_late_joiner(self):
        self.server.publish({"type": "hello", "node": "cc" * 20})
        received = []

        def reader():
            with urllib.request.urlopen(self._url("/stream"), timeout=10) as resp:
                for raw_line in resp:
                    line = raw_line.decode().strip()
                    if line.startswith("data: "):
                        received.append(json.loads(line[len("data: ") :]))
                        return

        t = threading.Thread(target=reader, daemon=True)
        t.start()
        t.join(timeout=5)
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["node"], "cc" * 20)


class TestEventReporter(unittest.TestCase):
    def test_reported_events_reach_the_hub(self):
        server = dashboard.run_dashboard("127.0.0.1", 0)
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        reporter = dashboard.EventReporter(f"http://127.0.0.1:{server.server_port}")
        self.addCleanup(reporter.stop)
        reporter.report({"type": "hello", "node": "dd" * 20})
        deadline = time.monotonic() + 5
        while not server.history_snapshot() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(len(server.history_snapshot()), 1)

    def test_unreachable_dashboard_does_not_raise(self):
        # port 1 refuses connections immediately -- report() must never
        # propagate that failure back to the caller (a Node mid-transfer).
        reporter = dashboard.EventReporter("http://127.0.0.1:1")
        self.addCleanup(reporter.stop)
        reporter.report({"type": "hello", "node": "ee" * 20})
        time.sleep(0.3)  # give the background thread a chance to try and fail silently


if __name__ == "__main__":
    unittest.main()
