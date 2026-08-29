"""A minimal HTTP/1.1 client built on raw sockets -- no `urllib`, no
`http.client`, no `requests`. It exists so Anvil's tests and load tool
exercise the wire protocol through an independent implementation rather
than the server round-tripping through itself, and so `demo.sh` has
something other than `curl` to point at the server.
"""

import socket

from .http_message import HeaderDict, Response


class ClientError(Exception):
    pass


class _BufferedSocket:
    """A tiny buffered reader over a blocking socket -- reads exactly the
    bytes asked for, keeping whatever's left over for the next call
    (needed because `recv()` has no concept of "just one header line")."""

    def __init__(self, sock):
        self.sock = sock
        self.buf = b""

    def read_line(self, limit=65536):
        while b"\r\n" not in self.buf:
            if len(self.buf) > limit:
                raise ClientError("line too long")
            chunk = self.sock.recv(4096)
            if not chunk:
                if self.buf:
                    raise ClientError("connection closed mid-line")
                raise ClientError("connection closed by peer")
            self.buf += chunk
        idx = self.buf.index(b"\r\n")
        line = self.buf[:idx]
        self.buf = self.buf[idx + 2:]
        return line

    def read_exact(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ClientError("connection closed while reading body")
            self.buf += chunk
        data = self.buf[:n]
        self.buf = self.buf[n:]
        return data

    def read_until_eof(self):
        while True:
            chunk = self.sock.recv(65536)
            if not chunk:
                break
            self.buf += chunk
        data = self.buf
        self.buf = b""
        return data


class HttpClient:
    """A persistent (keep-alive-aware) HTTP/1.1 client for one host:port."""

    def __init__(self, host, port, timeout=5.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock = None
        self._bs = None

    def connect(self):
        self._sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self._bs = _BufferedSocket(self._sock)

    def close(self):
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        self._sock = None
        self._bs = None

    def request(self, method, path, headers=None, body=b"", keep_alive=True):
        if self._sock is None:
            self.connect()
        if isinstance(body, str):
            body = body.encode("utf-8")
        h = HeaderDict(headers)
        if h.get("Host") is None:
            h.set("Host", f"{self.host}:{self.port}")
        if body and h.get("Content-Length") is None and h.get("Transfer-Encoding") is None:
            h.set("Content-Length", str(len(body)))
        h.set("Connection", "keep-alive" if keep_alive else "close")

        lines = [f"{method} {path} HTTP/1.1\r\n"]
        for k, v in h.items():
            lines.append(f"{k}: {v}\r\n")
        lines.append("\r\n")
        try:
            self._sock.sendall("".join(lines).encode("latin-1") + body)
            resp = self._read_response(method)
        except (OSError, ClientError):
            self.close()
            raise
        if not keep_alive or (resp.headers.get("Connection") or "").lower() == "close":
            self.close()
        return resp

    def get(self, path, headers=None, **kw):
        return self.request("GET", path, headers=headers, **kw)

    def post(self, path, body=b"", headers=None, **kw):
        return self.request("POST", path, headers=headers, body=body, **kw)

    def _read_response(self, method):
        bs = self._bs
        status_line = bs.read_line().decode("latin-1")
        parts = status_line.split(" ", 2)
        if len(parts) < 2:
            raise ClientError(f"malformed status line: {status_line!r}")
        version, status_s = parts[0], parts[1]
        reason = parts[2] if len(parts) > 2 else ""
        status = int(status_s)

        pairs = []
        while True:
            line = bs.read_line()
            if not line:
                break
            name, _, value = line.partition(b":")
            pairs.append((name.decode("latin-1").strip(), value.decode("latin-1").strip()))
        headers = HeaderDict(pairs)

        if method == "HEAD" or status in (204, 304) or (100 <= status < 200):
            return Response(status, headers, b"", reason=reason)

        te = (headers.get("Transfer-Encoding") or "").lower()
        cl = headers.get("Content-Length")
        if "chunked" in te:
            chunks = []
            while True:
                size_line = bs.read_line()
                size = int(size_line.split(b";")[0].strip(), 16)
                if size == 0:
                    while True:
                        trailer = bs.read_line()
                        if not trailer:
                            break
                    break
                chunks.append(bs.read_exact(size))
                crlf = bs.read_exact(2)
                if crlf != b"\r\n":
                    raise ClientError("malformed chunk terminator")
            body = b"".join(chunks)
        elif cl is not None:
            body = bs.read_exact(int(cl))
        else:
            body = bs.read_until_eof()
        return Response(status, headers, body, reason=reason)

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *exc):
        self.close()
