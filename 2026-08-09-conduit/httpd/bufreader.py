"""A tiny buffered-reader adapter over anything with a socket-shaped
`recv(bufsize, timeout=...) -> bytes` method (ConduitSocket qualifies
directly; so does a plain TCP socket via a thin wrapper — see bridge.py).

HTTP parsing needs line-oriented reads for the request/status line and
headers, then exact-length (or until-close) reads for the body. Neither
primitive exists on a raw socket; this fills the gap the way every real
HTTP implementation's buffered reader does.
"""


class ConnectionClosed(Exception):
    pass


class BufferedReader:
    def __init__(self, sock, chunk_size=8192):
        self._sock = sock
        self._buf = bytearray()
        self._chunk_size = chunk_size
        self._eof = False

    def _fill(self, timeout=None):
        if self._eof:
            return False
        chunk = self._sock.recv(self._chunk_size, timeout=timeout)
        if not chunk:
            self._eof = True
            return False
        self._buf.extend(chunk)
        return True

    def read_line(self, timeout=None, max_len=65536):
        """Read up to and including the next b'\\r\\n' (CRLF stripped off
        the return value); returns None at a clean EOF with nothing left."""
        while True:
            idx = self._buf.find(b"\r\n")
            if idx != -1:
                line = bytes(self._buf[:idx])
                del self._buf[: idx + 2]
                return line
            if len(self._buf) > max_len:
                raise ValueError("header line too long")
            if not self._fill(timeout=timeout):
                if self._buf:
                    line = bytes(self._buf)
                    self._buf.clear()
                    return line
                return None

    def read_exact(self, n, timeout=None):
        while len(self._buf) < n:
            if not self._fill(timeout=timeout):
                raise ConnectionClosed(f"EOF after {len(self._buf)}/{n} bytes")
        data = bytes(self._buf[:n])
        del self._buf[:n]
        return data

    def read_until_close(self, timeout=None):
        while self._fill(timeout=timeout):
            pass
        data = bytes(self._buf)
        self._buf.clear()
        return data
