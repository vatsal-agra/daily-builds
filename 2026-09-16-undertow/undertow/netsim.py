"""NetworkSimulator — a real UDP relay that drops, duplicates, reorders and
delays datagrams under a seeded RNG.

It is not a mock: it is an actual process-external (well, thread-external)
hop that two real ``socket.socket`` UDP endpoints send through. Everything
Undertow claims about surviving a lossy network is demonstrated against
this relay, not asserted in the abstract. Both peer addresses are known
up front (this is a point-to-point demo relay, not a general NAT), so the
relay never has to "learn" who's on the other side.
"""

from __future__ import annotations

import heapq
import itertools
import random
import socket
import threading
import time

RECV_BUFSIZE = 4096


class NetworkSimulator:
    def __init__(
        self,
        peer_a: tuple[str, int],
        peer_b: tuple[str, int],
        loss: float = 0.0,
        dup: float = 0.0,
        reorder: float = 0.0,
        min_delay: float = 0.0,
        max_delay: float = 0.0,
        seed: int = 0,
        bind_host: str = "127.0.0.1",
        bottleneck_bps: float = 0.0,
        bottleneck_buffer_bytes: int = 0,
    ) -> None:
        self.peer_a = peer_a
        self.peer_b = peer_b
        self.loss = loss
        self.dup = dup
        self.reorder = reorder
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.rng = random.Random(seed)

        # An optional real bottleneck on the a->b leg: a link that can only
        # drain `bottleneck_bps` bytes/sec through a `bottleneck_buffer_bytes`
        # queue. Unlike the random loss/delay above (bit-error-style noise,
        # uncorrelated with load), this produces genuine queueing delay that
        # *grows with how much is in flight* and tail-drops on overflow --
        # the actual phenomenon congestion control reacts to, and the only
        # way a delay-based controller (Vegas) has anything real to sense.
        self.bottleneck_bps = bottleneck_bps
        self.bottleneck_buffer_bytes = bottleneck_buffer_bytes
        self._bottleneck_lock = threading.Lock()
        self._bottleneck_free_at = 0.0

        self.sock_a = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock_a.bind((bind_host, 0))
        self.sock_b = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock_b.bind((bind_host, 0))
        self.leg_a_addr = self.sock_a.getsockname()
        self.leg_b_addr = self.sock_b.getsockname()

        self.stats = {"sent": 0, "dropped": 0, "duplicated": 0, "delayed": 0, "reordered": 0}
        self._stats_lock = threading.Lock()

        self._stop = False
        self._threads: list[threading.Thread] = []
        self._sched_lock = threading.Lock()
        self._sched_cv = threading.Condition(self._sched_lock)
        self._sched_heap: list[tuple[float, int, socket.socket, tuple[str, int], bytes]] = []
        self._counter = itertools.count()

    def start(self) -> None:
        self._threads = [
            threading.Thread(target=self._recv_loop, args=(self.sock_a, self.sock_b, self.peer_b, True), daemon=True),
            threading.Thread(target=self._recv_loop, args=(self.sock_b, self.sock_a, self.peer_a, False), daemon=True),
            threading.Thread(target=self._scheduler_loop, daemon=True),
        ]
        for t in self._threads:
            t.start()

    def stop(self) -> None:
        self._stop = True
        with self._sched_cv:
            self._sched_cv.notify_all()
        for sock in (self.sock_a, self.sock_b):
            try:
                sock.close()
            except OSError:
                pass

    def _bump(self, key: str) -> None:
        with self._stats_lock:
            self.stats[key] += 1

    def _recv_loop(
        self, recv_sock: socket.socket, send_sock: socket.socket, dest_addr: tuple[str, int], apply_bottleneck: bool
    ) -> None:
        recv_sock.settimeout(0.1)
        while not self._stop:
            try:
                data, _addr = recv_sock.recvfrom(RECV_BUFSIZE)
            except OSError:
                continue
            self._bump("sent")
            if self.rng.random() < self.loss:
                self._bump("dropped")
                continue

            if apply_bottleneck and self.bottleneck_bps > 0:
                if not self._bottleneck_forward(send_sock, dest_addr, data):
                    continue
                # the bottleneck queue already governs delay/ordering for
                # this leg; duplication can still happen independently
                if self.dup and self.rng.random() < self.dup:
                    self._bump("duplicated")
                    self._schedule(send_sock, dest_addr, data, 0.0)
                continue

            copies = 1
            if self.dup and self.rng.random() < self.dup:
                copies = 2
                self._bump("duplicated")

            for _ in range(copies):
                delay = 0.0
                if self.max_delay > 0:
                    delay = self.min_delay + self.rng.random() * (self.max_delay - self.min_delay)
                    self._bump("delayed")
                if self.reorder and self.rng.random() < self.reorder:
                    # push this copy well past its neighbours so ordering
                    # actually flips at the receiver, not just jitters
                    delay += max(self.max_delay, 0.02) * (2 + self.rng.random() * 2)
                    self._bump("reordered")
                self._schedule(send_sock, dest_addr, data, delay)

    def _bottleneck_forward(self, send_sock: socket.socket, dest_addr: tuple[str, int], data: bytes) -> bool:
        """Models a single output queue draining at `bottleneck_bps`, with
        `bottleneck_buffer_bytes` of buffer before it tail-drops. Returns
        False if the packet was dropped (buffer full)."""
        now = time.monotonic()
        service_time = len(data) / self.bottleneck_bps
        max_queue_delay = self.bottleneck_buffer_bytes / self.bottleneck_bps
        with self._bottleneck_lock:
            start = max(now, self._bottleneck_free_at)
            queue_delay = start - now
            if queue_delay > max_queue_delay:
                self._bump("dropped")
                return False
            self._bottleneck_free_at = start + service_time
        self._bump("delayed")
        self._schedule(send_sock, dest_addr, data, queue_delay + service_time)
        return True

    def _schedule(self, send_sock: socket.socket, dest_addr: tuple[str, int], data: bytes, delay: float) -> None:
        send_time = time.monotonic() + max(0.0, delay)
        with self._sched_cv:
            heapq.heappush(self._sched_heap, (send_time, next(self._counter), send_sock, dest_addr, data))
            self._sched_cv.notify_all()

    def _scheduler_loop(self) -> None:
        with self._sched_cv:
            while not self._stop:
                if not self._sched_heap:
                    self._sched_cv.wait(timeout=0.05)
                    continue
                send_time = self._sched_heap[0][0]
                now = time.monotonic()
                if send_time <= now:
                    _, _, send_sock, dest_addr, data = heapq.heappop(self._sched_heap)
                    self._sched_cv.release()
                    try:
                        send_sock.sendto(data, dest_addr)
                    except OSError:
                        pass
                    finally:
                        self._sched_cv.acquire()
                else:
                    self._sched_cv.wait(timeout=min(0.05, send_time - now))
