"""A from-scratch HTTP/1.1 server that speaks over Conduit sockets.

It never touches `socket.SOCK_STREAM`: `self.listener` is a
`conduit.api.Listener`, and every connection it accepts is a
`ConduitSocket`. HTTP itself — the request-line/header parsing,
Content-Length framing, keep-alive, HEAD/GET/POST semantics — is
implemented from scratch here; Conduit only supplies the reliable byte
stream underneath, exactly the role TCP plays for a normal HTTP server.
"""

import email.utils
import threading

from httpd.bufreader import BufferedReader, ConnectionClosed
from httpd.message import REASON_PHRASES, Request, Response

MAX_HEADERS = 200
KEEPALIVE_TIMEOUT = 15.0
HEADER_TIMEOUT = 10.0
BODY_TIMEOUT = 15.0


class HttpServer:
    def __init__(self, listener, handler, server_name="Conduit-httpd/1.0", trace=None):
        self.listener = listener
        self.handler = handler
        self.server_name = server_name
        self._trace = trace or (lambda *a, **k: None)
        self._stop = threading.Event()
        self._accept_thread = None
        self._conn_threads = []

    def start(self):
        self._accept_thread = threading.Thread(target=self._accept_loop, daemon=True, name="httpd-accept")
        self._accept_thread.start()

    def stop(self):
        self._stop.set()

    def _accept_loop(self):
        while not self._stop.is_set():
            try:
                conn = self.listener.accept(timeout=0.5)
            except Exception:
                continue
            t = threading.Thread(target=self._safe_handle, args=(conn,), daemon=True, name="httpd-conn")
            self._conn_threads.append(t)
            t.start()

    def _safe_handle(self, conn):
        try:
            self._handle_connection(conn)
        except Exception as exc:  # pragma: no cover - defensive
            self._trace("httpd_error", error=repr(exc))
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _handle_connection(self, conn):
        reader = BufferedReader(conn)
        first_request = True
        while True:
            timeout = HEADER_TIMEOUT if first_request else KEEPALIVE_TIMEOUT
            try:
                req = self._parse_request(reader, timeout)
            except ConnectionClosed:
                return
            except ValueError as exc:
                self._send_response(conn, Response(400, body=f"Bad Request: {exc}".encode()), False)
                return
            if req is None:
                return
            first_request = False

            keep_alive = self._wants_keepalive(req)
            try:
                resp = self.handler(req)
            except Exception as exc:
                resp = Response(500, body=f"Internal Server Error: {exc}".encode())
            self._send_response(conn, resp, keep_alive, suppress_body=(req.method == "HEAD"))
            self._trace("httpd_request", method=req.method, path=req.path, status=resp.status)
            if not keep_alive:
                return

    def _parse_request(self, reader, timeout):
        line = reader.read_line(timeout=timeout)
        if line is None:
            return None
        while line == b"":  # RFC 7230 allows leading CRLFs before a request
            line = reader.read_line(timeout=timeout)
            if line is None:
                return None
        try:
            method, path, version = line.decode("latin-1").split(" ")
        except ValueError:
            raise ValueError("malformed request line")
        if version not in ("HTTP/1.0", "HTTP/1.1"):
            raise ValueError(f"unsupported version {version!r}")

        headers = {}
        for _ in range(MAX_HEADERS):
            hline = reader.read_line(timeout=HEADER_TIMEOUT)
            if hline is None:
                raise ConnectionClosed("EOF mid-headers")
            if hline == b"":
                break
            key, sep, value = hline.decode("latin-1").partition(":")
            if not sep:
                raise ValueError(f"malformed header line {hline!r}")
            headers[key.strip().lower()] = value.strip()
        else:
            raise ValueError("too many headers")

        body = b""
        length_hdr = headers.get("content-length")
        if length_hdr is not None:
            try:
                n = int(length_hdr)
            except ValueError:
                raise ValueError("bad Content-Length")
            if n > 0:
                body = reader.read_exact(n, timeout=BODY_TIMEOUT)
        return Request(method, path, version, headers, body)

    @staticmethod
    def _wants_keepalive(req: Request) -> bool:
        conn_hdr = (req.header("connection") or "").lower()
        if req.version == "HTTP/1.1":
            return conn_hdr != "close"
        return conn_hdr == "keep-alive"

    def _send_response(self, conn, resp: Response, keep_alive: bool, suppress_body=False):
        headers = dict(resp.headers)
        headers.setdefault("Content-Length", str(len(resp.body)))
        headers.setdefault("Server", self.server_name)
        headers.setdefault("Date", email.utils.formatdate(usegmt=True))
        headers["Connection"] = "keep-alive" if keep_alive else "close"

        status_line = f"HTTP/1.1 {resp.status} {resp.reason}"
        header_lines = [f"{k}: {v}" for k, v in headers.items()]
        head = ("\r\n".join([status_line] + header_lines) + "\r\n\r\n").encode("latin-1")
        payload = head if suppress_body else head + resp.body
        conn.sendall(payload)
