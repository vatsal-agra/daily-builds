"""NetworkSimulator: a UDP middlebox that actively misbehaves.

Every integration test and the curl oracle run *through* this, not around
it. Conceptually it's a tiny NAT gateway: clients send to its
`listen_addr`; for each distinct client address it opens a dedicated
server-facing UDP socket (so the real server still sees distinct source
addresses per client, exactly like a real NAT would preserve per-flow
source ports) and relays datagrams in both directions, independently
applying, per datagram:

  * loss       — drop with probability `loss`
  * duplication — deliver twice with probability `dup_prob`
  * reordering  — delay a fraction of packets by an extra
                  `reorder_delay` so they arrive after ones sent later
  * delay/jitter — a base one-way delay plus uniform jitter

A `seed` makes the loss/reorder/duplication *decisions* reproducible in
aggregate (same seed → same long-run loss rate, same fraction reordered);
because delivery itself runs on real OS threads against the real clock,
this is not a byte-for-byte deterministic replay the way a single-threaded
discrete-event simulator would be — it's real UDP sockets under real
scheduling, which is the point: Conduit has to survive an actually
unpredictable network, not a scripted one.
"""

import heapq
import random
import socket
import threading
import time


def _noop_trace(event, **fields):
    pass


class NetworkSimulator:
    def __init__(self, listen_addr, server_addr, loss=0.0, dup_prob=0.0,
                 reorder_prob=0.0, reorder_delay=0.05, delay=0.0, jitter=0.0,
                 seed=None, trace=None):
        self.server_addr = server_addr
        self.loss = loss
        self.dup_prob = dup_prob
        self.reorder_prob = reorder_prob
        self.reorder_delay = reorder_delay
        self.delay = delay
        self.jitter = jitter
        self._rng = random.Random(seed)
        self._rng_lock = threading.Lock()
        self._trace = trace or _noop_trace

        self.client_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.client_sock.bind(listen_addr)
        self.client_sock.settimeout(0.1)

        self._flows = {}
        self._flows_lock = threading.Lock()

        self._heap = []
        self._counter = 0
        self._heap_lock = threading.Lock()
        self._heap_cv = threading.Condition(self._heap_lock)

        self.stats = {"sent": 0, "dropped": 0, "duplicated": 0, "reordered": 0}
        self._stats_lock = threading.Lock()

        self._stop = threading.Event()
        self._threads = [
            threading.Thread(target=self._client_reader, daemon=True, name="netsim-c2s"),
            threading.Thread(target=self._scheduler, daemon=True, name="netsim-sched"),
        ]
        for t in self._threads:
            t.start()

    @property
    def local_addr(self):
        return self.client_sock.getsockname()

    # ------------------------------------------------------------------

    def _get_flow_socket(self, client_addr):
        with self._flows_lock:
            sock = self._flows.get(client_addr)
            if sock is None:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.bind(("0.0.0.0", 0))
                sock.settimeout(0.1)
                self._flows[client_addr] = sock
                t = threading.Thread(
                    target=self._server_reader, args=(client_addr, sock),
                    daemon=True, name="netsim-s2c",
                )
                t.start()
            return sock

    def _client_reader(self):
        while not self._stop.is_set():
            try:
                data, addr = self.client_sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            sock = self._get_flow_socket(addr)
            self._inject("c2s", data, sock, self.server_addr)

    def _server_reader(self, client_addr, sock):
        while not self._stop.is_set():
            try:
                data, _from = sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            self._inject("s2c", data, self.client_sock, client_addr)

    def _roll(self):
        with self._rng_lock:
            return self._rng.random()

    def _uniform(self, lo, hi):
        with self._rng_lock:
            return self._rng.uniform(lo, hi)

    def _inject(self, direction, data, out_sock, dest_addr):
        with self._stats_lock:
            self.stats["sent"] += 1

        if self._roll() < self.loss:
            with self._stats_lock:
                self.stats["dropped"] += 1
            self._trace("netsim_drop", direction=direction, size=len(data))
            return

        copies = 1
        if self.dup_prob and self._roll() < self.dup_prob:
            copies = 2
            with self._stats_lock:
                self.stats["duplicated"] += 1
            self._trace("netsim_dup", direction=direction, size=len(data))

        base = max(0.0, self.delay + (self._uniform(-self.jitter, self.jitter) if self.jitter else 0.0))
        for _ in range(copies):
            extra = 0.0
            if self.reorder_prob and self._roll() < self.reorder_prob:
                extra = self.reorder_delay
                with self._stats_lock:
                    self.stats["reordered"] += 1
                self._trace("netsim_reorder", direction=direction, size=len(data))
            self._schedule(base + extra, out_sock, dest_addr, data)

    def _schedule(self, delay, out_sock, dest_addr, data):
        deliver_at = time.monotonic() + delay
        with self._heap_cv:
            self._counter += 1
            heapq.heappush(self._heap, (deliver_at, self._counter, out_sock, dest_addr, data))
            self._heap_cv.notify()

    def _scheduler(self):
        with self._heap_cv:
            while not self._stop.is_set():
                if not self._heap:
                    self._heap_cv.wait(timeout=0.1)
                    continue
                deliver_at = self._heap[0][0]
                now = time.monotonic()
                if deliver_at > now:
                    self._heap_cv.wait(timeout=min(0.05, deliver_at - now))
                    continue
                _, _, out_sock, dest_addr, data = heapq.heappop(self._heap)
                try:
                    out_sock.sendto(data, dest_addr)
                except OSError:
                    pass

    def close(self):
        self._stop.set()
        self.client_sock.close()
        with self._flows_lock:
            for s in self._flows.values():
                s.close()
