"""The event loop: a single OS thread, `selectors.DefaultSelector`
(epoll/kqueue/select under the hood, whichever the platform has), and a
small per-connection state machine. No `asyncio`, no thread-per-connection
-- this is the same readiness-driven model nginx/Node/Redis use, built
from the two primitives Python actually exposes for it: non-blocking
sockets and a selector.
"""

import logging
import selectors
import socket
import time

from .http_message import Response
from .http_parser import ParseError, RequestParser
from .router import HttpError
from . import websocket as ws

log = logging.getLogger("anvil.server")

RECV_CHUNK = 65536
IDLE_TIMEOUT = 300.0         # close a connection idle this long with no heartbeat response
WS_HEARTBEAT_INTERVAL = 25.0  # ping open WebSocket connections this often
MAX_OUTBUF_BYTES = 32 * 1024 * 1024  # backpressure ceiling


class WSConnection:
    """What a WebSocket application handler sees -- deliberately narrow:
    send text/binary, close, and know who's on the other end."""

    def __init__(self, conn):
        self._conn = conn

    @property
    def remote_addr(self):
        return self._conn.addr

    def send_text(self, s: str):
        self._conn.queue_out(ws.encode_text(s))

    def send_binary(self, b: bytes):
        self._conn.queue_out(ws.encode_binary(b))

    def close(self, code: int = 1000, reason: str = ""):
        self._conn.queue_out(ws.encode_close(code, reason))
        self._conn.closing_after_flush = True


class Connection:
    __slots__ = (
        "sock", "addr", "parser", "outbuf", "closing_after_flush",
        "upgraded", "ws_parser", "ws_app", "ws_wrapper", "last_active",
        "want_write", "server",
    )

    def __init__(self, sock, addr, server):
        self.sock = sock
        self.addr = addr
        self.server = server
        self.parser = RequestParser(max_body_bytes=server.max_body_bytes)
        self.outbuf = bytearray()
        self.closing_after_flush = False
        self.upgraded = False
        self.ws_parser = None
        self.ws_app = None
        self.ws_wrapper = None
        self.last_active = time.monotonic()
        self.want_write = False

    def queue_out(self, data: bytes):
        self.outbuf += data
        # A handler can queue bytes onto a connection that isn't the one
        # currently being serviced (e.g. broadcasting a chat message to
        # every other open WebSocket) -- re-arm write-readiness right away
        # rather than relying on that connection's next read event, which
        # may never come for an otherwise-idle listener.
        self.server._rearm(self)


class Server:
    def __init__(self, host="127.0.0.1", port=8080, router=None,
                 backlog=128, max_body_bytes=10 * 1024 * 1024,
                 server_name="Anvil"):
        self.host = host
        self.port = port
        self.router = router
        self.backlog = backlog
        self.max_body_bytes = max_body_bytes
        self.server_name = server_name
        self._sel = selectors.DefaultSelector()
        self._lsock = None
        self._stop = False
        self._connections = {}  # fd -> Connection
        self._last_heartbeat = time.monotonic()

    # -- lifecycle ------------------------------------------------------

    def bind(self):
        self._lsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._lsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._lsock.bind((self.host, self.port))
        self._lsock.listen(self.backlog)
        self._lsock.setblocking(False)
        self.port = self._lsock.getsockname()[1]  # resolve port 0 -> actual
        self._sel.register(self._lsock, selectors.EVENT_READ, data=None)
        return self

    def stop(self):
        self._stop = True

    def close(self):
        for conn in list(self._connections.values()):
            self._drop(conn, reason="server shutdown")
        if self._lsock is not None:
            try:
                self._sel.unregister(self._lsock)
            except (KeyError, ValueError):
                pass
            self._lsock.close()
            self._lsock = None

    def serve_forever(self, poll_timeout=0.5):
        if self._lsock is None:
            self.bind()
        try:
            while not self._stop:
                events = self._sel.select(timeout=poll_timeout)
                for key, mask in events:
                    if key.data is None:
                        self._accept()
                    else:
                        self._service(key, mask)
                self._reap_idle()
                self._send_ws_heartbeats()
        finally:
            self.close()

    # -- accept / read / write ------------------------------------------

    def _accept(self):
        while True:
            try:
                sock, addr = self._lsock.accept()
            except BlockingIOError:
                return
            except OSError:
                return
            sock.setblocking(False)
            try:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except OSError:
                pass
            conn = Connection(sock, addr, self)
            self._connections[sock.fileno()] = conn
            self._sel.register(sock, selectors.EVENT_READ, data=conn)

    def _service(self, key, mask):
        conn = key.data
        try:
            if mask & selectors.EVENT_READ:
                self._on_readable(conn)
            if conn.sock.fileno() != -1 and mask & selectors.EVENT_WRITE:
                self._on_writable(conn)
        except OSError:
            self._drop(conn, reason="socket error")
            return
        if conn.sock.fileno() != -1:
            self._rearm(conn)

    def _rearm(self, conn):
        want_write = bool(conn.outbuf)
        events = selectors.EVENT_READ | (selectors.EVENT_WRITE if want_write else 0)
        if conn.want_write != want_write:
            conn.want_write = want_write
            try:
                self._sel.modify(conn.sock, events, data=conn)
            except (KeyError, ValueError, OSError):
                pass

    def _on_readable(self, conn):
        try:
            data = conn.sock.recv(RECV_CHUNK)
        except BlockingIOError:
            return
        except (ConnectionResetError, ConnectionAbortedError, TimeoutError):
            self._drop(conn, reason="reset")
            return
        if not data:
            self._drop(conn, reason="peer closed")
            return
        conn.last_active = time.monotonic()
        if conn.upgraded:
            self._feed_websocket(conn, data)
        else:
            self._feed_http(conn, data)

    def _on_writable(self, conn):
        if not conn.outbuf:
            return
        try:
            sent = conn.sock.send(conn.outbuf)
        except BlockingIOError:
            return
        except (BrokenPipeError, ConnectionResetError):
            self._drop(conn, reason="broken pipe")
            return
        del conn.outbuf[:sent]
        if not conn.outbuf and conn.closing_after_flush:
            self._drop(conn, reason="closed after flush")

    # -- HTTP side --------------------------------------------------------

    def _feed_http(self, conn, data):
        try:
            requests = conn.parser.feed(data)
        except ParseError as e:
            resp = Response.text(f"Bad Request: {e}", status=400)
            resp.headers.set("Connection", "close")
            conn.queue_out(resp.to_bytes())
            conn.closing_after_flush = True
            return
        for req in requests:
            self._handle_one_request(conn, req)
            if conn.upgraded or conn.closing_after_flush:
                break

    def _handle_one_request(self, conn, req):
        if len(conn.outbuf) > MAX_OUTBUF_BYTES:
            conn.closing_after_flush = True
            return

        want_close = self._wants_close(req)

        if ws.is_upgrade_request(req.headers) and self.router is not None:
            factory, params = self.router.match_ws(req.path)
            if factory is not None:
                self._do_ws_handshake(conn, req, factory, params)
                return

        try:
            resp = self._dispatch(req)
        except HttpError as e:
            resp = Response.text(e.message or "", status=e.status, headers=e.headers)
        except Exception:
            log.exception("unhandled error handling %s %s", req.method, req.target)
            resp = Response.text("Internal Server Error", status=500)

        resp.headers.set("Server", self.server_name)
        resp.headers.set("Connection", "close" if want_close else "keep-alive")
        include_body = req.method != "HEAD"
        conn.queue_out(resp.to_bytes(include_body=include_body))
        if want_close:
            conn.closing_after_flush = True

    def _wants_close(self, req):
        conn_header = (req.header("Connection") or "").lower()
        if "close" in conn_header:
            return True
        if req.version == "HTTP/1.0" and "keep-alive" not in conn_header:
            return True
        return False

    def _dispatch(self, req):
        if self.router is None:
            return Response.text("Not Found", status=404)
        handler, params, allowed = self.router.match(req.method, req.path)
        if handler is None:
            if allowed:
                return Response.text(
                    "Method Not Allowed", status=405,
                    headers=[("Allow", ", ".join(sorted(allowed)))],
                )
            return Response.text("Not Found", status=404)
        req.params = params or {}
        result = handler(req)
        if not isinstance(result, Response):
            raise TypeError(f"handler for {req.path} returned {type(result)!r}, not a Response")
        return result

    # -- WebSocket side ---------------------------------------------------

    def _do_ws_handshake(self, conn, req, factory, params):
        try:
            key = ws.validate_handshake(req.headers)
        except ws.WSProtocolError as e:
            resp = Response.text(f"Bad Request: {e}", status=400)
            resp.headers.set("Connection", "close")
            conn.queue_out(resp.to_bytes())
            conn.closing_after_flush = True
            return
        accept = ws.compute_accept(key)
        resp = Response(101, headers=[
            ("Upgrade", "websocket"),
            ("Connection", "Upgrade"),
            ("Sec-WebSocket-Accept", accept),
        ], body=b"")
        # 101 responses must not carry a Content-Length header at all.
        raw = self._strip_content_length(resp.to_bytes(include_body=False))
        conn.queue_out(raw)
        conn.upgraded = True
        conn.ws_parser = ws.WebSocketParser()
        req.params = params or {}
        conn.ws_app = factory(req)
        conn.ws_wrapper = WSConnection(conn)
        if hasattr(conn.ws_app, "on_open"):
            conn.ws_app.on_open(conn.ws_wrapper)
        # A client that didn't wait for the 101 before writing frames may
        # have had its first frame bytes land in this same recv() -- they're
        # sitting unconsumed in the (now-retired) HTTP parser's buffer.
        leftover = conn.parser.take_leftover()
        if leftover:
            self._feed_websocket(conn, leftover)

    @staticmethod
    def _strip_content_length(raw: bytes) -> bytes:
        head, _, rest = raw.partition(b"\r\n\r\n")
        lines = head.split(b"\r\n")
        lines = [l for l in lines if not l.lower().startswith(b"content-length:")]
        return b"\r\n".join(lines) + b"\r\n\r\n" + rest

    def _feed_websocket(self, conn, data):
        try:
            messages = conn.ws_parser.feed(data)
        except ws.WSProtocolError:
            conn.queue_out(ws.encode_close(1002, "protocol error"))
            conn.closing_after_flush = True
            return
        for msg in messages:
            self._handle_ws_message(conn, msg)
            if conn.closing_after_flush:
                break

    def _handle_ws_message(self, conn, msg):
        if msg.kind == "control":
            if msg.opcode == ws.OP_PING:
                conn.queue_out(ws.encode_pong(msg.payload))
            elif msg.opcode == ws.OP_PONG:
                pass
            elif msg.opcode == ws.OP_CLOSE:
                try:
                    code, reason = ws.parse_close_payload(msg.payload)
                except ws.WSProtocolError:
                    code, reason = 1002, ""
                conn.queue_out(ws.encode_close(code, ""))
                conn.closing_after_flush = True
                if conn.ws_app is not None and hasattr(conn.ws_app, "on_close"):
                    conn.ws_app.on_close(conn.ws_wrapper, code, reason)
            return
        # data frame
        try:
            if msg.opcode == ws.OP_TEXT:
                text = msg.payload.decode("utf-8")
                if conn.ws_app is not None and hasattr(conn.ws_app, "on_message"):
                    conn.ws_app.on_message(conn.ws_wrapper, text, "text")
            else:
                if conn.ws_app is not None and hasattr(conn.ws_app, "on_message"):
                    conn.ws_app.on_message(conn.ws_wrapper, msg.payload, "binary")
        except UnicodeDecodeError:
            conn.queue_out(ws.encode_close(1007, "invalid UTF-8"))
            conn.closing_after_flush = True
        except Exception:
            log.exception("unhandled error in WS on_message")
            conn.queue_out(ws.encode_close(1011, "internal error"))
            conn.closing_after_flush = True

    # -- teardown -----------------------------------------------------

    def _drop(self, conn, reason=""):
        fd = conn.sock.fileno()
        if conn.upgraded and conn.ws_app is not None and hasattr(conn.ws_app, "on_close"):
            try:
                conn.ws_app.on_close(conn.ws_wrapper, 1006, reason)
            except Exception:
                log.exception("error in ws on_close during teardown")
        try:
            self._sel.unregister(conn.sock)
        except (KeyError, ValueError):
            pass
        try:
            conn.sock.close()
        except OSError:
            pass
        if fd in self._connections:
            del self._connections[fd]

    def _reap_idle(self):
        now = time.monotonic()
        stale = [
            c for c in self._connections.values()
            if now - c.last_active > IDLE_TIMEOUT
        ]
        for conn in stale:
            self._drop(conn, reason="idle timeout")

    def _send_ws_heartbeats(self):
        now = time.monotonic()
        if now - self._last_heartbeat < WS_HEARTBEAT_INTERVAL:
            return
        self._last_heartbeat = now
        for conn in list(self._connections.values()):
            if conn.upgraded and not conn.closing_after_flush:
                conn.queue_out(ws.encode_ping(b"anvil"))
