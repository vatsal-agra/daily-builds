"""A real, unreliable UDP relay.

This is not a mocked "pretend this packet was lost" flag checked by the
application. NetSim binds a genuine UDP socket, receives genuine datagrams
sent by the two endpoints, and for each one independently decides (via
`random`) whether to actually forward it at all, forward it after a random
delay (real wall-clock scheduling), or forward it twice (duplication). A
packet that's "lost" here is simply never handed to `sendto()` again — from
the endpoints' point of view, it vanished into the network, exactly like a
real dropped packet would.

Delayed delivery is driven by a single scheduler thread pulling from a
`heapq`-ordered queue rather than one OS thread per packet (an earlier
version used `threading.Timer` per datagram, which under any real send rate
spawns dozens of concurrent OS threads and introduces enough GIL contention
to spuriously delay ACKs past their RTO even with zero configured loss —
observed directly: a zero-loss transfer produced real retransmits purely
from relay-side scheduling jitter). One thread, one heap, precise wakeups.

Only two endpoints are supported (a client and a server address), matching
a simple two-party relay/NAT pinhole: whichever of the two configured
addresses a datagram arrives from, it gets forwarded towards the other.
"""
import heapq
import itertools
import random
import socket
import threading
import time


class NetSim:
    def __init__(
        self,
        listen_addr,
        peer_a,
        peer_b,
        loss=0.0,
        dup_prob=0.0,
        delay_range=(0.0, 0.0),
        reorder_prob=0.0,
        reorder_extra_delay=0.05,
        rng=None,
        on_event=None,
    ):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(listen_addr)
        self.listen_addr = self.sock.getsockname()
        self.peer_a = peer_a
        self.peer_b = peer_b
        self.loss = loss
        self.dup_prob = dup_prob
        self.delay_min, self.delay_max = delay_range
        self.reorder_prob = reorder_prob
        self.reorder_extra_delay = reorder_extra_delay
        self.rng = rng or random.Random()
        self.on_event = on_event or (lambda *a, **kw: None)

        self._running = False
        self._recv_thread = None
        self._deliver_thread = None
        self._counter = itertools.count()
        self._heap = []  # (deliver_at, seq, dest, data, tag)
        self._cv = threading.Condition()
        self.stats = {"forwarded": 0, "dropped": 0, "duplicated": 0, "reordered": 0}

    def _other(self, src):
        if src[0] == self.peer_a[0] and src[1] == self.peer_a[1]:
            return self.peer_b
        return self.peer_a

    def _schedule(self, deliver_at, dest, data, tag):
        with self._cv:
            heapq.heappush(self._heap, (deliver_at, next(self._counter), dest, data, tag))
            self._cv.notify_all()

    def _handle_datagram(self, data, src):
        dest = self._other(src)

        if self.rng.random() < self.loss:
            self.stats["dropped"] += 1
            self.on_event("drop", src=src, dest=dest, nbytes=len(data))
            return

        now = time.monotonic()
        delay = self.rng.uniform(self.delay_min, self.delay_max)
        if self.reorder_prob > 0 and self.rng.random() < self.reorder_prob:
            delay += self.reorder_extra_delay
            self.stats["reordered"] += 1

        self._schedule(now + delay, dest, data, "forward")

        if self.rng.random() < self.dup_prob:
            self.stats["duplicated"] += 1
            dup_delay = delay + self.rng.uniform(0.001, 0.02)
            self._schedule(now + dup_delay, dest, data, "duplicate")

    def _recv_loop(self):
        self.sock.settimeout(0.2)
        while self._running:
            try:
                data, src = self.sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            self._handle_datagram(data, src)

    def _deliver_loop(self):
        with self._cv:
            while self._running:
                if not self._heap:
                    self._cv.wait(0.2)
                    continue
                deliver_at = self._heap[0][0]
                now = time.monotonic()
                if deliver_at > now:
                    self._cv.wait(min(deliver_at - now, 0.2))
                    continue
                _, _, dest, data, tag = heapq.heappop(self._heap)
                self._cv.release()
                try:
                    self.stats["forwarded"] += 1
                    self.on_event(tag, dest=dest, nbytes=len(data))
                    try:
                        self.sock.sendto(data, dest)
                    except OSError:
                        pass
                finally:
                    self._cv.acquire()

    def start(self):
        self._running = True
        self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._deliver_thread = threading.Thread(target=self._deliver_loop, daemon=True)
        self._recv_thread.start()
        self._deliver_thread.start()

    def stop(self):
        self._running = False
        with self._cv:
            self._cv.notify_all()
        if self._recv_thread:
            self._recv_thread.join(timeout=1.0)
        if self._deliver_thread:
            self._deliver_thread.join(timeout=1.0)
        self.sock.close()
