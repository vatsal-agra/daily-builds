import os
import shutil
import tempfile
import threading
import unittest

from conduit.api import Listener, connect
from httpd.message import Response
from httpd.server import HttpServer
from httpd.static import StaticFileHandler


def do_request(addr, raw_request: bytes, timeout=5.0) -> bytes:
    conn = connect(addr, timeout=timeout)
    conn.sendall(raw_request)
    out = b""
    while True:
        chunk = conn.recv(4096, timeout=timeout)
        if not chunk:
            break
        out += chunk
        # Stop once we've read a full Content-Length-framed response body
        # (keep-alive connections won't EOF on their own).
        if b"\r\n\r\n" in out:
            head, _, body = out.partition(b"\r\n\r\n")
            cl = None
            for line in head.split(b"\r\n")[1:]:
                if line.lower().startswith(b"content-length:"):
                    cl = int(line.split(b":", 1)[1].strip())
            if cl is not None and len(body) >= cl:
                break
    conn.close()
    return out


class HttpTestBase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        with open(os.path.join(self.tmpdir, "index.html"), "w") as f:
            f.write("<h1>home</h1>")
        with open(os.path.join(self.tmpdir, "hello.txt"), "w") as f:
            f.write("hello world")
        os.mkdir(os.path.join(self.tmpdir, "sub"))
        with open(os.path.join(self.tmpdir, "sub", "deep.txt"), "w") as f:
            f.write("deep file")
        self.listener = Listener(("127.0.0.1", 0))
        self.server = HttpServer(self.listener, StaticFileHandler(self.tmpdir))
        self.server.start()

    def tearDown(self):
        self.server.stop()
        self.listener.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @property
    def addr(self):
        return self.listener.local_addr


class TestStaticServer(HttpTestBase):
    def test_get_index(self):
        resp = do_request(self.addr, b"GET / HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
        self.assertIn(b"HTTP/1.1 200 OK", resp)
        self.assertIn(b"<h1>home</h1>", resp)
        self.assertIn(b"Content-Type: text/html", resp)

    def test_get_text_file(self):
        resp = do_request(self.addr, b"GET /hello.txt HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
        self.assertIn(b"200 OK", resp)
        self.assertIn(b"hello world", resp)
        self.assertIn(b"Content-Length: 11", resp)

    def test_nested_path(self):
        resp = do_request(self.addr, b"GET /sub/deep.txt HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
        self.assertIn(b"deep file", resp)

    def test_404(self):
        resp = do_request(self.addr, b"GET /nope.txt HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
        self.assertIn(b"HTTP/1.1 404 Not Found", resp)

    def test_path_traversal_blocked(self):
        resp = do_request(
            self.addr, b"GET /../../../../etc/passwd HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n"
        )
        # Either normalized back inside root (404, no such file) or blocked outright (403) —
        # what must NEVER happen is 200 with /etc/passwd's contents.
        self.assertNotIn(b"root:", resp)
        self.assertTrue(b"404" in resp or b"403" in resp)

    def test_head_has_no_body(self):
        resp = do_request(self.addr, b"HEAD /hello.txt HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
        self.assertIn(b"200 OK", resp)
        self.assertIn(b"Content-Length: 11", resp)
        head, _, body = resp.partition(b"\r\n\r\n")
        self.assertEqual(body, b"")

    def test_method_not_allowed(self):
        resp = do_request(self.addr, b"DELETE /hello.txt HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
        self.assertIn(b"405", resp)

    def test_keepalive_multiple_requests_same_connection(self):
        conn = connect(self.addr, timeout=5.0)
        for _ in range(3):
            conn.sendall(b"GET /hello.txt HTTP/1.1\r\nHost: x\r\n\r\n")
            out = b""
            while b"\r\n\r\n" not in out or len(out.split(b"\r\n\r\n", 1)[1]) < 11:
                out += conn.recv(4096, timeout=5.0)
            self.assertIn(b"200 OK", out)
            self.assertIn(b"hello world", out)
        conn.close()

    def test_malformed_request_gets_400(self):
        resp = do_request(self.addr, b"NOT A REQUEST LINE\r\n\r\n")
        self.assertIn(b"400", resp)


class TestDynamicHandler(unittest.TestCase):
    def setUp(self):
        def handler(req):
            if req.path == "/echo" and req.method == "POST":
                return Response(200, headers={"Content-Type": "text/plain"}, body=req.body)
            return Response(404, body=b"not found")

        self.listener = Listener(("127.0.0.1", 0))
        self.server = HttpServer(self.listener, handler)
        self.server.start()

    def tearDown(self):
        self.server.stop()
        self.listener.close()

    def test_post_echo(self):
        body = b"hello from a POST body, with some length to it"
        req = (
            b"POST /echo HTTP/1.1\r\nHost: x\r\nContent-Length: " + str(len(body)).encode() +
            b"\r\nConnection: close\r\n\r\n" + body
        )
        resp = do_request(self.listener.local_addr, req)
        self.assertIn(b"200 OK", resp)
        self.assertTrue(resp.endswith(body))


if __name__ == "__main__":
    unittest.main()
