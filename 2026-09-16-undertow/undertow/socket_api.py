"""UndertowSocket — the public, application-facing API.

Wraps a real ``socket.socket`` UDP endpoint plus a ``Connection`` so an
application never touches packet framing directly: ``connect``/``accept``
does the 3-way handshake, ``send``/``recv``/``close`` move bytes.
"""

from __future__ import annotations

import socket as _socket

from .congestion import CongestionController
from .connection import Connection
from .packet import MSS


class _SockTransport:
    """Adapts a connected UDP socket to Connection's (sendto/recvfrom) shape."""

    def __init__(self, sock: _socket.socket) -> None:
        self.sock = sock

    def sendto(self, data: bytes) -> None:
        try:
            self.sock.send(data)
        except OSError:
            pass

    def recvfrom(self, bufsize: int, timeout: float) -> bytes | None:
        self.sock.settimeout(timeout)
        try:
            return self.sock.recv(bufsize)
        except OSError:
            return None


class UndertowSocket:
    def __init__(
        self,
        congestion_controller_factory=None,
        mss: int = MSS,
        initial_seq: int | None = None,
        bind_addr: tuple[str, int] = ("127.0.0.1", 0),
    ) -> None:
        self._sock = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
        self._sock.bind(bind_addr)
        self._cc_factory = congestion_controller_factory
        self._mss = mss
        self._initial_seq = initial_seq
        self.conn: Connection | None = None

    def local_address(self) -> tuple[str, int]:
        return self._sock.getsockname()

    def _make_connection(self) -> Connection:
        cc = self._cc_factory() if self._cc_factory else None
        return Connection(
            _SockTransport(self._sock),
            congestion_controller=cc,
            mss=self._mss,
            initial_seq=self._initial_seq,
        )

    def connect(self, remote_addr: tuple[str, int], timeout: float = 10.0) -> Connection:
        self._sock.connect(remote_addr)
        self.conn = self._make_connection()
        self.conn.connect(timeout=timeout)
        return self.conn

    def accept(self, remote_addr: tuple[str, int], timeout: float = 30.0) -> Connection:
        self._sock.connect(remote_addr)
        self.conn = self._make_connection()
        self.conn.accept(timeout=timeout)
        return self.conn

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass
