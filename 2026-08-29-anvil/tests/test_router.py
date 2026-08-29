import os
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from anvil.http_message import HeaderDict, Request  # noqa: E402
from anvil.router import Router, parse_range, serve_static  # noqa: E402


def make_request(method, path, headers=None):
    return Request(method, path, "HTTP/1.1", HeaderDict(headers or []), b"")


class TestPatternMatching(unittest.TestCase):
    def setUp(self):
        self.router = Router()

    def test_exact_route(self):
        self.router.add_route("GET", "/health", lambda r: "ok")
        handler, params, allowed = self.router.match("GET", "/health")
        self.assertIsNotNone(handler)
        self.assertEqual(params, {})

    def test_param_route(self):
        self.router.add_route("GET", "/users/{id}", lambda r: "ok")
        handler, params, allowed = self.router.match("GET", "/users/42")
        self.assertIsNotNone(handler)
        self.assertEqual(params, {"id": "42"})

    def test_multi_param_route(self):
        self.router.add_route("GET", "/a/{x}/b/{y}", lambda r: "ok")
        handler, params, allowed = self.router.match("GET", "/a/1/b/2")
        self.assertEqual(params, {"x": "1", "y": "2"})

    def test_no_match_404(self):
        self.router.add_route("GET", "/health", lambda r: "ok")
        handler, params, allowed = self.router.match("GET", "/nope")
        self.assertIsNone(handler)
        self.assertIsNone(allowed)

    def test_wrong_method_405_with_allow(self):
        self.router.add_route("GET", "/health", lambda r: "ok")
        self.router.add_route("POST", "/health", lambda r: "ok")
        handler, params, allowed = self.router.match("DELETE", "/health")
        self.assertIsNone(handler)
        self.assertEqual(allowed, {"GET", "POST"})

    def test_head_falls_back_to_get(self):
        self.router.add_route("GET", "/health", lambda r: "ok")
        handler, params, allowed = self.router.match("HEAD", "/health")
        self.assertIsNotNone(handler)

    def test_ws_route(self):
        self.router.add_ws_route("/ws/{room}", lambda req: object())
        factory, params = self.router.match_ws("/ws/general")
        self.assertIsNotNone(factory)
        self.assertEqual(params, {"room": "general"})


class TestParseRange(unittest.TestCase):
    def test_start_end(self):
        self.assertEqual(parse_range("bytes=0-99", 1000), (0, 99))

    def test_open_ended(self):
        self.assertEqual(parse_range("bytes=500-", 1000), (500, 999))

    def test_suffix(self):
        self.assertEqual(parse_range("bytes=-100", 1000), (900, 999))

    def test_suffix_larger_than_file(self):
        self.assertEqual(parse_range("bytes=-5000", 1000), (0, 999))

    def test_out_of_range_rejected(self):
        with self.assertRaises(ValueError):
            parse_range("bytes=2000-3000", 1000)

    def test_inverted_range_rejected(self):
        with self.assertRaises(ValueError):
            parse_range("bytes=100-50", 1000)

    def test_multi_range_signals_unsupported(self):
        with self.assertRaises(NotImplementedError):
            parse_range("bytes=0-10,20-30", 1000)

    def test_bad_unit_rejected(self):
        with self.assertRaises(ValueError):
            parse_range("items=0-10", 1000)


class TestStaticServing(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.content = b"Hello, Anvil! " * 100  # 1400 bytes
        with open(os.path.join(self.dir, "file.txt"), "wb") as f:
            f.write(self.content)
        os.makedirs(os.path.join(self.dir, "sub"), exist_ok=True)
        with open(os.path.join(self.dir, "sub", "index.html"), "w") as f:
            f.write("<h1>sub index</h1>")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_serves_full_file(self):
        req = make_request("GET", "/file.txt")
        resp = serve_static(req, self.dir, "file.txt")
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.body, self.content)
        self.assertEqual(resp.headers.get("Content-Type"), "text/plain; charset=utf-8")

    def test_directory_serves_index(self):
        req = make_request("GET", "/sub/")
        resp = serve_static(req, self.dir, "sub/")
        self.assertEqual(resp.status, 200)
        self.assertIn(b"sub index", resp.body)

    def test_404_for_missing_file(self):
        req = make_request("GET", "/nope.txt")
        resp = serve_static(req, self.dir, "nope.txt")
        self.assertEqual(resp.status, 404)

    def test_path_traversal_blocked(self):
        req = make_request("GET", "/../../../etc/passwd")
        resp = serve_static(req, self.dir, "../../../etc/passwd")
        self.assertEqual(resp.status, 403)

    def test_range_request(self):
        req = make_request("GET", "/file.txt", [("Range", "bytes=0-9")])
        resp = serve_static(req, self.dir, "file.txt")
        self.assertEqual(resp.status, 206)
        self.assertEqual(resp.body, self.content[0:10])
        self.assertEqual(resp.headers.get("Content-Range"), f"bytes 0-9/{len(self.content)}")

    def test_suffix_range_request(self):
        req = make_request("GET", "/file.txt", [("Range", "bytes=-10")])
        resp = serve_static(req, self.dir, "file.txt")
        self.assertEqual(resp.status, 206)
        self.assertEqual(resp.body, self.content[-10:])

    def test_unsatisfiable_range_416(self):
        req = make_request("GET", "/file.txt", [("Range", "bytes=999999-9999999")])
        resp = serve_static(req, self.dir, "file.txt")
        self.assertEqual(resp.status, 416)

    def test_etag_conditional_get_304(self):
        req = make_request("GET", "/file.txt")
        first = serve_static(req, self.dir, "file.txt")
        etag = first.headers.get("ETag")
        self.assertIsNotNone(etag)
        req2 = make_request("GET", "/file.txt", [("If-None-Match", etag)])
        second = serve_static(req2, self.dir, "file.txt")
        self.assertEqual(second.status, 304)

    def test_last_modified_conditional_get_304(self):
        req = make_request("GET", "/file.txt")
        first = serve_static(req, self.dir, "file.txt")
        last_mod = first.headers.get("Last-Modified")
        req2 = make_request("GET", "/file.txt", [("If-Modified-Since", last_mod)])
        second = serve_static(req2, self.dir, "file.txt")
        self.assertEqual(second.status, 304)

    def test_stale_if_modified_since_returns_200(self):
        req = make_request(
            "GET", "/file.txt",
            [("If-Modified-Since", "Mon, 01 Jan 1990 00:00:00 GMT")],
        )
        resp = serve_static(req, self.dir, "file.txt")
        self.assertEqual(resp.status, 200)

    def test_head_no_body_but_correct_length(self):
        req = make_request("HEAD", "/file.txt")
        resp = serve_static(req, self.dir, "file.txt")
        self.assertEqual(resp.body, b"")
        self.assertEqual(resp.headers.get("Content-Length"), str(len(self.content)))

    @unittest.skipUnless(hasattr(os, "symlink"), "platform has no symlink support")
    def test_symlink_escape_blocked(self):
        # a symlink *inside* the mount pointing outside it sails straight
        # past the lexical ".." check -- regression test for a Phase 3
        # review finding.
        secret_dir = tempfile.mkdtemp()
        try:
            with open(os.path.join(secret_dir, "secret.txt"), "w") as f:
                f.write("top secret")
            link_path = os.path.join(self.dir, "escape.txt")
            os.symlink(os.path.join(secret_dir, "secret.txt"), link_path)
            req = make_request("GET", "/escape.txt")
            resp = serve_static(req, self.dir, "escape.txt")
            self.assertEqual(resp.status, 403)
        finally:
            shutil.rmtree(secret_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
