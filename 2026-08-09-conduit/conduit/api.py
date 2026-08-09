"""Public entry points: `connect()` for clients, `Listener` for servers.

Both are thin wiring around `transport.ConduitSocket` — they own the real
OS UDP socket(s) and hand `ConduitSocket` two things: a `send_raw(bytes)`
callable, and a `queue.Queue` that raw incoming datagrams get pushed into.
Everything protocol-level (handshake, reliability, congestion control)
lives in `transport.py`; this module never looks inside a segment.
"""

import queue
import socket as _socket
import threading

from conduit.segment import FLAG_ACK, FLAG_SYN, Segment, SegmentError
from conduit.transport import (
    DEFAULT_MSS,
    DEFAULT_RECV_WINDOW,
    ConduitSocket,
    ConduitTimeout,
)

RECV_BUFSIZE = 65535


def connect(addr, mss=DEFAULT_MSS, recv_window=DEFAULT_RECV_WINDOW, trace=None,
            timeout=5.0, bind_addr=("0.0.0.0", 0)):
    """Open a Conduit connection to `addr = (host, port)`.

    Owns a dedicated UDP socket for the lifetime of the connection —
    exactly the resource shape a real TCP `connect()` has (one socket per
    connection on the client side).
    """
    raw_sock = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
    raw_sock.bind(bind_addr)
    incoming: "queue.Queue" = queue.Queue()
    stop = threading.Event()

    def reader():
        raw_sock.settimeout(0.2)
        while not stop.is_set():
            try:
                data, _from = raw_sock.recvfrom(RECV_BUFSIZE)
            except _socket.timeout:
                continue
            except OSError:
                break
            incoming.put(data)

    reader_thread = threading.Thread(target=reader, daemon=True, name="conduit-client-reader")
    reader_thread.start()

    def send_raw(data):
        raw_sock.sendto(data, addr)

    def teardown():
        stop.set()
        raw_sock.close()

    local_port = raw_sock.getsockname()[1]
    conn = ConduitSocket(
        send_raw, incoming, mss=mss, recv_window_cap=recv_window, trace=trace,
        peer_addr=addr, name=f"client:{local_port}", on_teardown=teardown,
    )
    try:
        conn.connect(timeout=timeout)
    except Exception:
        # Handshake failed (timeout/reset) — connect() never got a chance to
        # register `teardown` as a close hook the caller will invoke, since
        # there's no established connection for them to call close() on.
        # Without this, a failed connect() leaks the reader thread and the
        # UDP socket for the life of the process.
        conn._stop_engine()
        teardown()
        raise
    return conn


class Listener:
    """A Conduit listening endpoint: one shared UDP socket demultiplexing
    many connections by (source ip, source port), exactly like a real TCP
    listening socket demultiplexes by the 4-tuple."""

    def __init__(self, bind_addr, mss=DEFAULT_MSS, recv_window=DEFAULT_RECV_WINDOW,
                 trace=None, backlog=32, prune_interval=1.0):
        self._sock = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
        self._sock.bind(bind_addr)
        self._sock.settimeout(0.2)
        self.mss = mss
        self.recv_window = recv_window
        self._trace = trace
        self._connections = {}  # addr -> ConduitSocket
        self._accept_backlog: "queue.Queue" = queue.Queue(maxsize=backlog)
        self._stop = threading.Event()
        self._prune_interval = prune_interval
        self._demux_thread = threading.Thread(target=self._demux_loop, daemon=True, name="conduit-listener-demux")
        self._demux_thread.start()

    @property
    def local_addr(self):
        return self._sock.getsockname()

    def _demux_loop(self):
        last_prune = 0.0
        import time as _time
        while not self._stop.is_set():
            try:
                data, addr = self._sock.recvfrom(RECV_BUFSIZE)
            except _socket.timeout:
                data = None
            except OSError:
                break

            if data is not None:
                conn = self._connections.get(addr)
                if conn is not None:
                    conn._incoming.put(data)
                else:
                    self._maybe_accept_new(data, addr)

            now = _time.monotonic()
            if now - last_prune > self._prune_interval:
                self._prune_closed()
                last_prune = now

    def _maybe_accept_new(self, data, addr):
        try:
            seg = Segment.decode(data)
        except SegmentError:
            return
        if not seg.has(FLAG_SYN) or seg.has(FLAG_ACK):  # require a bare SYN — a fresh handshake
            return

        def send_raw(d, _addr=addr):
            self._sock.sendto(d, _addr)

        conn = ConduitSocket(
            send_raw, queue.Queue(), mss=self.mss, recv_window_cap=self.recv_window,
            trace=self._trace, peer_addr=addr, name=f"server:{addr[1]}",
        )
        self._connections[addr] = conn
        conn._begin_as_server(seg.seq)
        try:
            self._accept_backlog.put_nowait(conn)
        except queue.Full:
            pass  # backlog full — drop the connection, matching a real listen() backlog overflow

    def _prune_closed(self):
        dead = [addr for addr, c in self._connections.items() if c.state in ("CLOSED_FINAL", "RESET")]
        for addr in dead:
            del self._connections[addr]

    def accept(self, timeout=None):
        conn = self._accept_backlog.get(timeout=timeout)
        conn.wait_established(timeout=5.0)
        return conn

    def close(self):
        self._stop.set()
        for conn in list(self._connections.values()):
            conn._stop_engine()
        self._sock.close()
