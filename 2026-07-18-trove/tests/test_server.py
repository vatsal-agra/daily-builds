import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from trove.engine import Engine
from trove.index import InvertedIndex
from trove.server import TroveRequestHandler
from http.server import ThreadingHTTPServer


def build_fixture_index():
    idx = InvertedIndex()
    idx.add_document(
        "evil", "This mentions <script>alert(1)</script> and an onerror payload",
        title="XSS test doc", path="evil.md",
    )
    idx.add_document("d2", "quantum computer science fox", title="Quantum", path="q.md")
    idx.finalize()
    return idx


class TestServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        engine = Engine(build_fixture_index())
        handler = type("BoundHandler", (TroveRequestHandler,), {"engine": engine})
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=5)

    def get(self, path):
        url = f"http://127.0.0.1:{self.port}{path}"
        with urllib.request.urlopen(url, timeout=5) as resp:
            return resp.status, resp.read().decode("utf-8"), resp.headers.get("Content-Type")

    def get_json(self, path):
        status, body, _ = self.get(path)
        return status, json.loads(body)

    def test_index_page_served(self):
        status, body, content_type = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", content_type)
        self.assertIn("<title>Trove</title>", body)

    def test_search_endpoint_returns_json(self):
        status, data = self.get_json("/api/search?q=quantum")
        self.assertEqual(status, 200)
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["doc_id"], "d2")

    def test_search_result_never_contains_raw_html_tag_delimiters(self):
        # Structural XSS defense check: raw_tokens() strips punctuation
        # including '<' and '>', so a document containing a literal
        # <script> tag can never produce a snippet containing one either.
        status, data = self.get_json("/api/search?q=script")
        self.assertEqual(status, 200)
        self.assertEqual(len(data["results"]), 1)
        snippet = data["results"][0]["snippet"]
        self.assertNotIn("<", snippet)
        self.assertNotIn(">", snippet)

    def test_search_syntax_error_returns_error_field(self):
        status, data = self.get_json("/api/search?q=fox%20AND%20%28lazy")
        self.assertEqual(status, 200)
        self.assertIsNotNone(data["error"])
        self.assertEqual(data["results"], [])

    def test_empty_query_returns_empty_results(self):
        status, data = self.get_json("/api/search?q=")
        self.assertEqual(status, 200)
        self.assertEqual(data["results"], [])

    def test_suggest_endpoint(self):
        status, data = self.get_json("/api/suggest?prefix=quan")
        self.assertEqual(status, 200)
        self.assertIn("quantum", data["suggestions"])

    def test_suggest_endpoint_empty_prefix(self):
        status, data = self.get_json("/api/suggest?prefix=")
        self.assertEqual(data["suggestions"], [])

    def test_stats_endpoint(self):
        status, data = self.get_json("/api/stats")
        self.assertEqual(data["documents"], 2)
        self.assertGreater(data["terms"], 0)

    def test_unknown_path_returns_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.get("/nonexistent")
        self.assertEqual(ctx.exception.code, 404)

    def test_top_param_is_clamped_via_safe_int(self):
        status, data = self.get_json("/api/search?q=quantum&top=-5")
        self.assertEqual(status, 200)  # must not crash on a malicious/garbage top value
        status, data = self.get_json("/api/search?q=quantum&top=not_a_number")
        self.assertEqual(status, 200)


if __name__ == "__main__":
    unittest.main()
