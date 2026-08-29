"""A reverse proxy / load balancer, built on the same raw sockets as
everything else in Anvil -- but deliberately a *different* concurrency
model from `server.py`'s single-threaded event loop: one thread per
proxied connection, forwarding raw bytes both directions with a
background health checker pulling failing backends out of rotation. A
proxy doesn't need to understand HTTP framing at all (it isn't
terminating the protocol, just relaying it byte-for-byte), so a simpler
blocking model is the right tool here, not a limitation of the harder
event-loop design used for the origin server.
"""

import logging
import socket
import threading
import time

from .client import HttpClient

log = logging.getLogger("anvil.proxy")

PUMP_CHUNK = 65536


class Backend:
    __slots__ = ("host", "port", "healthy", "consecutive_failures")

    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.healthy = True
        self.consecutive_failures = 0

    @property
    def address(self):
        return (self.host, self.port)

    def __repr__(self):
        state = "up" if self.healthy else "down"
        return f"Backend({self.host}:{self.port}, {state})"


class NoBackendAvailable(Exception):
    pass


def _pump(src: socket.socket, dst: socket.socket, done: threading.Event):
    """Copy bytes from src to dst until src is closed or an error occurs,
    then half-close dst's write side so the far end sees EOF too."""
    try:
        while True:
            try:
                chunk = src.recv(PUMP_CHUNK)
            except OSError:
                break
            if not chunk:
                break
            try:
                dst.sendall(chunk)
            except OSError:
                break
    finally:
        try:
            dst.shutdown(socket.SHUT_WR)
        except OSError:
            pass
        done.set()


class LoadBalancer:
    """Round-robin (skipping unhealthy backends) reverse proxy."""

    def __init__(self, host, port, backends, health_path="/", health_interval=2.0,
                 health_timeout=1.0, unhealthy_threshold=2, backlog=128):
        self.host = host
        self.port = port
        self.backends = [Backend(h, p) for h, p in backends]
        self.health_path = health_path
        self.health_interval = health_interval
        self.health_timeout = health_timeout
        self.unhealthy_threshold = unhealthy_threshold
        self.backlog = backlog
        self._idx = 0
        self._lock = threading.Lock()
        self._lsock = None
        self._stop = threading.Event()
        self._health_thread = None
        self.stats = {"requests": 0, "failed": 0}

    def next_backend(self) -> Backend:
        with self._lock:
            healthy = [b for b in self.backends if b.healthy]
            if not healthy:
                raise NoBackendAvailable("no healthy backend available")
            backend = healthy[self._idx % len(healthy)]
            self._idx += 1
            return backend

    # -- health checking --------------------------------------------------

    def _check_one(self, backend: Backend):
        try:
            client = HttpClient(backend.host, backend.port, timeout=self.health_timeout)
            resp = client.get(self.health_path, keep_alive=False)
            ok = resp.status < 500
        except Exception:
            ok = False
        with self._lock:
            if ok:
                backend.consecutive_failures = 0
                if not backend.healthy:
                    log.info("backend %s:%s recovered", backend.host, backend.port)
                backend.healthy = True
            else:
                backend.consecutive_failures += 1
                if backend.consecutive_failures >= self.unhealthy_threshold and backend.healthy:
                    log.warning("backend %s:%s marked unhealthy", backend.host, backend.port)
                    backend.healthy = False

    def _health_loop(self):
        while not self._stop.is_set():
            for backend in self.backends:
                if self._stop.is_set():
                    return
                self._check_one(backend)
            self._stop.wait(self.health_interval)

    # -- lifecycle ----------------------------------------------------------

    def start(self):
        self._lsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._lsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._lsock.bind((self.host, self.port))
        self._lsock.listen(self.backlog)
        self.port = self._lsock.getsockname()[1]
        # Prime backend health synchronously so the very first proxied
        # request doesn't race an empty "all backends unknown" state.
        for backend in self.backends:
            self._check_one(backend)
        self._health_thread = threading.Thread(target=self._health_loop, daemon=True)
        self._health_thread.start()
        return self

    def stop(self):
        self._stop.set()
        if self._lsock is not None:
            try:
                self._lsock.close()
            except OSError:
                pass

    def serve_forever(self):
        if self._lsock is None:
            self.start()
        self._lsock.settimeout(0.5)
        while not self._stop.is_set():
            try:
                client_sock, addr = self._lsock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            t = threading.Thread(target=self._handle, args=(client_sock,), daemon=True)
            t.start()

    def _handle(self, client_sock: socket.socket):
        self.stats["requests"] += 1
        try:
            backend = self.next_backend()
        except NoBackendAvailable:
            self.stats["failed"] += 1
            try:
                client_sock.sendall(
                    b"HTTP/1.1 502 Bad Gateway\r\n"
                    b"Content-Type: text/plain\r\nContent-Length: 20\r\n"
                    b"Connection: close\r\n\r\nno backend available"
                )
            except OSError:
                pass
            client_sock.close()
            return
        try:
            backend_sock = socket.create_connection(backend.address, timeout=5)
        except OSError:
            self.stats["failed"] += 1
            with self._lock:
                backend.healthy = False
            try:
                client_sock.sendall(
                    b"HTTP/1.1 502 Bad Gateway\r\n"
                    b"Content-Type: text/plain\r\nContent-Length: 21\r\n"
                    b"Connection: close\r\n\r\nbackend not reachable"
                )
            except OSError:
                pass
            client_sock.close()
            return

        done_c2b = threading.Event()
        done_b2c = threading.Event()
        t1 = threading.Thread(target=_pump, args=(client_sock, backend_sock, done_c2b), daemon=True)
        t2 = threading.Thread(target=_pump, args=(backend_sock, client_sock, done_b2c), daemon=True)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        try:
            client_sock.close()
        except OSError:
            pass
        try:
            backend_sock.close()
        except OSError:
            pass
