"""A hand-rolled, incremental HTTP/1.1 request parser.

Deliberately not `http.server`/`socketserver`/`email.message` -- this is a
byte-stream state machine you `feed()` bytes into as they arrive from
`recv()`, in whatever chunks the kernel happens to hand back. It must cope
with:

  * a request split across many `feed()` calls (a header split mid-line,
    a body split mid-chunk),
  * several pipelined requests arriving in a single `feed()` call,
  * `Content-Length` bodies and `Transfer-Encoding: chunked` bodies
    (including trailers),
  * and it must reject malformed input with `ParseError` rather than
    hanging or throwing something an event loop can't recover from.

One `RequestParser` instance is reused for the lifetime of a keep-alive
connection; `feed()` returns the list of `Request` objects that became
complete during that call (usually 0 or 1, occasionally more than 1 for
pipelined input).
"""

from .http_message import HeaderDict, Request

MAX_LINE_BYTES = 8192          # request line / a single header line
MAX_HEADER_BYTES = 32768       # total header block
MAX_CHUNK_SIZE_LINE = 64
DEFAULT_MAX_BODY_BYTES = 10 * 1024 * 1024


class ParseError(Exception):
    """Malformed input the parser can't make sense of. The caller (the
    server) should respond 400 and close the connection."""


class RequestParser:
    def __init__(self, max_body_bytes=DEFAULT_MAX_BODY_BYTES, on_expect_continue=None):
        self.max_body_bytes = max_body_bytes
        # Called synchronously the instant headers finish parsing, if the
        # request carried `Expect: 100-continue` -- fires well before the
        # (possibly large) body has arrived, so the caller can write a
        # "100 Continue" interim response immediately. Without this, any
        # RFC 7231-compliant client that waits for permission before
        # sending a large body (curl included, past a size threshold)
        # would stall forever waiting on us, and we'd stall forever
        # waiting on its body: a real deadlock, not a hang under load.
        self.on_expect_continue = on_expect_continue
        self._buf = b""
        self._state = "line"
        self._start_line = None
        self._headers = []
        self._header_bytes = 0
        self._remaining = 0
        self._chunk_phase = "size"
        self._body_chunks = []
        self._chunked_total = 0
        self._trailers = []

    def take_leftover(self) -> bytes:
        """Drain and return whatever raw bytes are sitting in the internal
        buffer past the last complete request -- used when a connection
        upgrades to WebSocket, so bytes a client pipelined right after its
        handshake request (before waiting for the 101) aren't silently
        dropped when byte routing switches to the WS frame parser."""
        leftover = self._buf
        self._buf = b""
        return leftover

    def feed(self, data: bytes):
        if data:
            self._buf += data
        out = []
        while True:
            req = self._step()
            if req is None:
                break
            out.append(req)
        return out

    # -- state machine -----------------------------------------------

    def _step(self):
        if self._state == "line":
            return self._step_line()
        if self._state == "headers":
            return self._step_headers()
        if self._state == "body_length":
            return self._step_body_length()
        if self._state == "body_chunked":
            return self._step_chunked()
        if self._state == "done_no_body":
            return self._complete(b"")
        raise AssertionError(f"unreachable parser state {self._state!r}")

    def _step_line(self):
        idx = self._buf.find(b"\r\n")
        if idx == -1:
            if len(self._buf) > MAX_LINE_BYTES:
                raise ParseError("request line too long")
            return None
        line = self._buf[:idx]
        self._buf = self._buf[idx + 2:]
        if not line:
            # RFC 7230 3.5: servers SHOULD ignore a leading empty line.
            return self._step_line()
        if len(line) > MAX_LINE_BYTES:
            raise ParseError("request line too long")
        try:
            text = line.decode("latin-1")
            method, target, version = text.split(" ")
        except ValueError:
            raise ParseError("malformed request line")
        if version not in ("HTTP/1.0", "HTTP/1.1"):
            raise ParseError(f"unsupported HTTP version {version!r}")
        if not method or not target:
            raise ParseError("malformed request line")
        self._start_line = (method, target, version)
        self._headers = []
        self._header_bytes = 0
        self._state = "headers"
        return self._step()

    def _step_headers(self):
        idx = self._buf.find(b"\r\n")
        if idx == -1:
            if len(self._buf) > MAX_HEADER_BYTES:
                raise ParseError("header block too large")
            return None
        line = self._buf[:idx]
        self._buf = self._buf[idx + 2:]
        if not line:
            return self._finish_headers()
        self._header_bytes += len(line) + 2
        if self._header_bytes > MAX_HEADER_BYTES:
            raise ParseError("header block too large")
        if len(self._headers) >= 200:
            raise ParseError("too many header fields")
        if line[:1] in (b" ", b"\t"):
            # obs-fold (RFC 7230 3.2.4): explicitly not supported.
            raise ParseError("obsolete header line folding is not supported")
        if b":" not in line:
            raise ParseError("malformed header line (no colon)")
        name, _, value = line.partition(b":")
        name_s = name.decode("latin-1")
        if not name_s or " " in name_s or "\t" in name_s:
            raise ParseError("malformed header field name")
        value_s = value.decode("latin-1").strip(" \t")
        self._headers.append((name_s, value_s))
        return self._step()

    def _finish_headers(self):
        headers = HeaderDict(self._headers)
        expect = headers.get("Expect")
        if expect is not None and expect.strip().lower() == "100-continue" and self.on_expect_continue:
            self.on_expect_continue()
        te = headers.get("Transfer-Encoding")
        cl = headers.get("Content-Length")
        if te is not None:
            # We only understand the "chunked" coding itself -- anything
            # layered with it (gzip, deflate, ...) would leave us decoding
            # the chunk *framing* correctly while silently handing the
            # still-encoded bytes to the application as if they were the
            # real body. Reject rather than silently corrupt.
            codings = [c.strip().lower() for c in te.split(",")]
            if codings != ["chunked"]:
                raise ParseError(f"unsupported Transfer-Encoding: {te!r}")
            if cl is not None:
                # 7230 3.3.3: a message with both must be treated as
                # invalid (classic request-smuggling vector) -- reject it.
                raise ParseError("both Content-Length and Transfer-Encoding present")
            self._state = "body_chunked"
            self._chunk_phase = "size"
            self._body_chunks = []
            self._chunked_total = 0
            return self._step()
        if cl is not None:
            all_lengths = [v.strip() for v in headers.get_all("Content-Length")]
            if len(all_lengths) > 1 and len(set(all_lengths)) > 1:
                raise ParseError("conflicting Content-Length headers")
            try:
                length = int(all_lengths[0])
            except ValueError:
                raise ParseError("malformed Content-Length")
            if length < 0:
                raise ParseError("negative Content-Length")
            if length > self.max_body_bytes:
                raise ParseError("request body too large")
            self._remaining = length
            self._state = "body_length"
            return self._step()
        self._state = "done_no_body"
        return self._step()

    def _step_body_length(self):
        if len(self._buf) < self._remaining:
            return None
        body = self._buf[:self._remaining]
        self._buf = self._buf[self._remaining:]
        return self._complete(bytes(body))

    def _step_chunked(self):
        while True:
            if self._chunk_phase == "size":
                idx = self._buf.find(b"\r\n")
                if idx == -1:
                    if len(self._buf) > MAX_CHUNK_SIZE_LINE:
                        raise ParseError("chunk size line too long")
                    return None
                size_line = self._buf[:idx]
                self._buf = self._buf[idx + 2:]
                size_field = size_line.split(b";", 1)[0].strip()
                if not size_field or any(c not in b"0123456789abcdefABCDEF" for c in size_field):
                    raise ParseError("malformed chunk size")
                size = int(size_field, 16)
                self._remaining = size
                self._chunk_phase = "data" if size > 0 else "trailers"
                continue
            if self._chunk_phase == "data":
                need = self._remaining + 2
                if len(self._buf) < need:
                    return None
                chunk = self._buf[:self._remaining]
                terminator = self._buf[self._remaining:need]
                if terminator != b"\r\n":
                    raise ParseError("malformed chunk terminator")
                self._buf = self._buf[need:]
                self._chunked_total += len(chunk)
                if self._chunked_total > self.max_body_bytes:
                    raise ParseError("chunked request body too large")
                self._body_chunks.append(chunk)
                self._chunk_phase = "size"
                continue
            if self._chunk_phase == "trailers":
                idx = self._buf.find(b"\r\n")
                if idx == -1:
                    if len(self._buf) > MAX_LINE_BYTES:
                        raise ParseError("trailer line too long")
                    return None
                line = self._buf[:idx]
                self._buf = self._buf[idx + 2:]
                if not line:
                    body = b"".join(self._body_chunks)
                    return self._complete(body)
                if b":" not in line:
                    raise ParseError("malformed trailer field")
                name, _, value = line.partition(b":")
                self._trailers.append(
                    (name.decode("latin-1"), value.decode("latin-1").strip())
                )
                continue
            raise AssertionError("unreachable chunk phase")

    def _complete(self, body: bytes) -> Request:
        method, target, version = self._start_line
        req = Request(
            method, target, version,
            HeaderDict(self._headers), body,
            trailers=HeaderDict(self._trailers),
        )
        # reset for the next request on this (possibly keep-alive) connection
        self._state = "line"
        self._start_line = None
        self._headers = []
        self._header_bytes = 0
        self._body_chunks = []
        self._trailers = []
        return req
