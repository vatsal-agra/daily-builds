"""End-to-end tests against a *real* running Anvil server over *real* TCP
sockets -- no mocking of socket/selectors anywhere. Covers keep-alive
connection reuse, pipelining, chunked bodies, static file Range/ETag
serving over the wire, and a full RFC 6455 WebSocket handshake + echo
round trip using a from-scratch client built for this test (not anvil's
own encoder used to decode its own output).
"""

import base64
import hashlib
import os
import shutil
import socket
import struct
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from anvil import Router, Server, Response  # noqa: E402
from anvil.client import HttpClient  # noqa: E402
from anvil import websocket as ws  # noqa: E402

STATIC_CONTENT = b"0123456789" * 50  # 500 bytes, easy to slice-check


class EchoWSApp:
    def __init__(self, req):
        self.messages = []

    def on_open(self, conn):
        conn.send_text("hello")

    def on_message(self, conn, payload, kind):
        if kind == "text":
            conn.send_text("echo:" + payload)
        else:
            conn.send_binary(b"echo:" + payload)

    def on_close(self, conn, code, reason):
        pass


def build_router(static_dir):
    router = Router()

    @router.route("GET", "/")
    def index(req):
        return Response.text("root")

    @router.route("GET", "/greet/{name}")
    def greet(req):
        return Response.json({"hello": req.params["name"]})

    @router.route("POST", "/echo")
    def echo(req):
        return Response(200, headers=[("Content-Type", "application/octet-stream")], body=req.body)

    @router.route("GET", "/slow")
    def slow(req):
        time.sleep(0.3)
        return Response.text("done sleeping")

    router.mount_static("/static", static_dir)
    router.add_ws_route("/ws", EchoWSApp)
    return router


class AnvilServerTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.static_dir = tempfile.mkdtemp()
        with open(os.path.join(cls.static_dir, "hello.txt"), "wb") as f:
            f.write(STATIC_CONTENT)
        cls.router = build_router(cls.static_dir)
        cls.server = Server(host="127.0.0.1", port=0, router=cls.router)
        cls.server.bind()
        cls.port = cls.server.port
        cls.thread = threading.Thread(target=cls.server.serve_forever, kwargs={"poll_timeout": 0.05}, daemon=True)
        cls.thread.start()
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()
        cls.thread.join(timeout=5)
        shutil.rmtree(cls.static_dir, ignore_errors=True)

    def client(self):
        return HttpClient("127.0.0.1", self.port, timeout=5)


class TestBasicRequests(AnvilServerTestCase):
    def test_get_root(self):
        c = self.client()
        resp = c.get("/")
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.body, b"root")
        c.close()

    def test_route_param(self):
        c = self.client()
        resp = c.get("/greet/world")
        self.assertEqual(resp.status, 200)
        self.assertIn(b'"world"', resp.body)
        c.close()

    def test_404(self):
        c = self.client()
        resp = c.get("/nope")
        self.assertEqual(resp.status, 404)
        c.close()

    def test_405_with_allow_header(self):
        c = self.client()
        resp = c.request("DELETE", "/")
        self.assertEqual(resp.status, 405)
        self.assertIn("GET", resp.headers.get("Allow"))
        c.close()

    def test_post_body_roundtrip(self):
        c = self.client()
        resp = c.post("/echo", body=b"raw bytes here")
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.body, b"raw bytes here")
        c.close()

    def test_head_request_no_body(self):
        c = self.client()
        resp = c.request("HEAD", "/")
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.body, b"")
        c.close()


class TestKeepAliveAndPipelining(AnvilServerTestCase):
    def test_connection_reused_across_requests(self):
        c = self.client()
        c.get("/")
        sock_before = c._sock
        c.get("/greet/again")
        self.assertIs(c._sock, sock_before)  # same TCP connection, no reconnect
        c.close()

    def test_connection_close_header_closes_socket(self):
        c = self.client()
        c.get("/", keep_alive=False)
        self.assertIsNone(c._sock)

    def test_raw_pipelined_requests_single_write(self):
        """Two requests written in ONE send() call, arriving as one (or a
        split) TCP segment -- proves the parser handles pipelining, not
        just the convenience client which sends one at a time."""
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        raw = (
            b"GET / HTTP/1.1\r\nHost: h\r\nConnection: keep-alive\r\n\r\n"
            b"GET /greet/pipe HTTP/1.1\r\nHost: h\r\nConnection: close\r\n\r\n"
        )
        sock.sendall(raw)
        data = b""
        deadline = time.time() + 5
        while time.time() < deadline:
            chunk = sock.recv(65536)
            if not chunk:
                break
            data += chunk
        sock.close()
        self.assertEqual(data.count(b"HTTP/1.1 200"), 2)
        self.assertIn(b'"pipe"', data)

    def test_many_concurrent_keepalive_clients(self):
        """Proves the single-threaded event loop actually serves many
        connections concurrently rather than blocking one at a time --
        includes a /slow request that would serialize everything behind
        it if the loop ever made a blocking call."""
        results = []
        lock = threading.Lock()

        def worker(path):
            c = self.client()
            resp = c.get(path)
            with lock:
                results.append((path, resp.status))
            c.close()

        threads = []
        paths = ["/slow"] + [f"/greet/{i}" for i in range(20)]
        start = time.time()
        for p in paths:
            t = threading.Thread(target=worker, args=(p,))
            t.start()
            threads.append(t)
        for t in threads:
            t.join(timeout=5)
        elapsed = time.time() - start
        self.assertEqual(len(results), len(paths))
        self.assertTrue(all(status == 200 for _, status in results))
        # if /slow blocked the loop, this would take >= 0.3s * 21; instead
        # everything should finish close to the single /slow duration.
        self.assertLess(elapsed, 2.0)


class TestChunkedTransfer(AnvilServerTestCase):
    def test_chunked_post(self):
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        body = b"first-second-third"
        raw = (
            b"POST /echo HTTP/1.1\r\nHost: h\r\nTransfer-Encoding: chunked\r\n"
            b"Connection: close\r\n\r\n"
            b"6\r\nfirst-\r\n7\r\nsecond-\r\n5\r\nthird\r\n0\r\n\r\n"
        )
        sock.sendall(raw)
        data = b""
        deadline = time.time() + 5
        while time.time() < deadline:
            chunk = sock.recv(65536)
            if not chunk:
                break
            data += chunk
        sock.close()
        self.assertIn(b"200 OK", data)
        self.assertTrue(data.endswith(body))


class TestStaticFileServing(AnvilServerTestCase):
    def test_full_file(self):
        c = self.client()
        resp = c.get("/static/hello.txt")
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.body, STATIC_CONTENT)
        c.close()

    def test_range_request_matches_curl_semantics(self):
        c = self.client()
        resp = c.get("/static/hello.txt", headers=[("Range", "bytes=10-19")])
        self.assertEqual(resp.status, 206)
        self.assertEqual(resp.body, STATIC_CONTENT[10:20])
        self.assertEqual(resp.headers.get("Content-Range"), f"bytes 10-19/{len(STATIC_CONTENT)}")
        c.close()

    def test_conditional_get_304(self):
        c = self.client()
        first = c.get("/static/hello.txt")
        etag = first.headers.get("ETag")
        second = c.get("/static/hello.txt", headers=[("If-None-Match", etag)])
        self.assertEqual(second.status, 304)
        c.close()

    def test_missing_file_404(self):
        c = self.client()
        resp = c.get("/static/nope.txt")
        self.assertEqual(resp.status, 404)
        c.close()


class TestWebSocketEndToEnd(AnvilServerTestCase):
    def _handshake(self, sock, path="/ws"):
        key = base64.b64encode(os.urandom(16)).decode()
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{self.port}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        ).encode()
        sock.sendall(req)
        data = b""
        while b"\r\n\r\n" not in data:
            data += sock.recv(4096)
        head, _, rest = data.partition(b"\r\n\r\n")
        self.assertIn(b"101", head)
        expected_accept = base64.b64encode(
            hashlib.sha1((key + ws.WS_MAGIC).encode()).digest()
        ).decode()
        self.assertIn(expected_accept.encode(), head)
        self.assertNotIn(b"Content-Length", head)
        return rest  # leftover bytes already read past the handshake, if any

    def test_handshake_and_echo(self):
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        leftover = self._handshake(sock)
        parser = ws.WebSocketParser(require_mask=False)
        msgs = parser.feed(leftover)
        while not msgs:
            msgs = parser.feed(sock.recv(4096))
        self.assertEqual(msgs[0].payload, b"hello")  # on_open greeting

        sock.sendall(ws.encode_frame(ws.OP_TEXT, b"ping-from-test", mask=True))
        msgs = []
        while not msgs:
            msgs = parser.feed(sock.recv(4096))
        self.assertEqual(msgs[0].payload, b"echo:ping-from-test")
        sock.close()

    def test_fragmented_client_message(self):
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        leftover = self._handshake(sock)
        parser = ws.WebSocketParser(require_mask=False)
        msgs = parser.feed(leftover)
        while not msgs:
            msgs = parser.feed(sock.recv(4096))  # drain greeting

        f1 = ws.encode_frame(ws.OP_TEXT, b"frag-", fin=False, mask=True)
        f2 = ws.encode_frame(ws.OP_CONTINUATION, b"mented", fin=True, mask=True)
        sock.sendall(f1)
        sock.sendall(f2)
        msgs = []
        while not msgs:
            msgs = parser.feed(sock.recv(4096))
        self.assertEqual(msgs[0].payload, b"echo:frag-mented")
        sock.close()

    def test_ping_pong(self):
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        leftover = self._handshake(sock)
        parser = ws.WebSocketParser(require_mask=False)
        msgs = parser.feed(leftover)
        while not msgs:
            msgs = parser.feed(sock.recv(4096))  # greeting

        sock.sendall(ws.encode_frame(ws.OP_PING, b"pingdata", mask=True))
        msgs = []
        while not msgs:
            msgs = parser.feed(sock.recv(4096))
        self.assertEqual(msgs[0].kind, "control")
        self.assertEqual(msgs[0].opcode, ws.OP_PONG)
        self.assertEqual(msgs[0].payload, b"pingdata")
        sock.close()

    def test_close_handshake(self):
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        leftover = self._handshake(sock)
        parser = ws.WebSocketParser(require_mask=False)
        msgs = parser.feed(leftover)
        while not msgs:
            msgs = parser.feed(sock.recv(4096))  # greeting

        sock.sendall(ws.encode_frame(ws.OP_CLOSE, struct.pack("!H", 1000), mask=True))
        msgs = []
        while not msgs:
            msgs = parser.feed(sock.recv(4096))
        self.assertEqual(msgs[0].opcode, ws.OP_CLOSE)
        # server must close the TCP connection shortly after its close frame
        deadline = time.time() + 5
        closed = False
        while time.time() < deadline:
            chunk = sock.recv(4096)
            if chunk == b"":
                closed = True
                break
        self.assertTrue(closed)
        sock.close()

    def test_non_get_handshake_rejected(self):
        # RFC 6455 4.1: the handshake MUST be a GET request -- regression
        # test for a Phase 3 review finding.
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (
            f"POST /ws HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n"
            "Content-Length: 0\r\n\r\n"
        ).encode()
        sock.sendall(req)
        data = sock.recv(4096)
        self.assertIn(b"400", data)
        sock.close()

    def test_expect_100_continue_answered_before_body_needed(self):
        # Regression test for a Phase 3 review finding: curl (and any
        # RFC 7231-compliant client) sends "Expect: 100-continue" before a
        # large body and waits for permission -- without support for this,
        # both sides would stall forever.
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        body = b"y" * 5000
        req = (
            f"POST /echo HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n"
            f"Content-Length: {len(body)}\r\nExpect: 100-continue\r\n"
            "Connection: close\r\n\r\n"
        ).encode()
        sock.sendall(req)
        interim = b""
        deadline = time.time() + 5
        while time.time() < deadline and b"\r\n\r\n" not in interim:
            interim += sock.recv(4096)
        self.assertTrue(interim.startswith(b"HTTP/1.1 100 Continue"))
        # Body deliberately sent only *after* seeing the 100 -- if the
        # server were blocked waiting on it before answering, this test
        # would hang until the socket timeout instead of completing.
        sock.sendall(body)
        final = b""
        deadline = time.time() + 5
        while time.time() < deadline:
            chunk = sock.recv(65536)
            if not chunk:
                break
            final += chunk
        self.assertIn(b"200 OK", final.split(b"\r\n\r\n", 1)[0])
        self.assertTrue(final.endswith(body))
        sock.close()

    def test_bad_handshake_missing_key_rejected(self):
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        req = (
            f"GET /ws HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        ).encode()
        sock.sendall(req)
        data = sock.recv(4096)
        self.assertIn(b"400", data)
        sock.close()


if __name__ == "__main__":
    unittest.main()
