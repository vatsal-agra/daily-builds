"""Discrete-event network core.

Everything downstream of this file (congestion control, fairness/bufferbloat
experiments) rides on real simulated physics: a packet takes real
serialization time to get onto a link (size / bandwidth), real propagation
delay to cross it, and can sit in a real, finite, capacity-bounded FIFO
queue waiting for the shared bottleneck link to be free. There is no
formula that skips straight from "N flows, cwnd X" to "throughput Y" —
every byte of throughput this simulator reports came from an actual packet
that actually crossed an actual queue in simulated time.
"""

from __future__ import annotations

import heapq
import itertools
from collections import deque
from typing import Callable, Optional


class EventQueue:
    """A min-heap of (time, insertion_order, callback) triples.

    insertion_order breaks ties deterministically (same-timestamp events
    fire in the order they were scheduled) and avoids ever comparing two
    callables, which heapq would otherwise attempt on a time tie.
    """

    def __init__(self) -> None:
        self._heap: list[tuple[float, int, Callable[[], None]]] = []
        self._counter = itertools.count()
        self.now: float = 0.0

    def schedule(self, delay: float, callback: Callable[[], None]) -> float:
        if delay < 0:
            raise ValueError(f"cannot schedule an event {delay}s in the past")
        t = self.now + delay
        heapq.heappush(self._heap, (t, next(self._counter), callback))
        return t

    def run_until(self, t_end: float) -> None:
        while self._heap and self._heap[0][0] <= t_end:
            t, _, cb = heapq.heappop(self._heap)
            self.now = t
            cb()
        self.now = max(self.now, t_end)

    def pending_events(self) -> int:
        return len(self._heap)


class REDConfig:
    """Random Early Detection active-queue-management parameters."""

    def __init__(self, min_th: int, max_th: int, max_p: float = 0.1, w_q: float = 0.02):
        if not (0 <= min_th < max_th):
            raise ValueError("require 0 <= min_th < max_th")
        if not (0 < max_p <= 1):
            raise ValueError("max_p must be in (0, 1]")
        self.min_th = min_th
        self.max_th = max_th
        self.max_p = max_p
        self.w_q = w_q


class Bottleneck:
    """The single shared, capacity-bounded resource every flow contends for.

    Packets from every flow funnel into one FIFO queue in front of one
    egress link of finite bandwidth. Admission is either drop-tail (drop
    when the queue is full) or RED (probabilistic early drop as the
    exponentially-weighted-moving-average queue length grows past a
    threshold, well before the queue is actually full).
    """

    def __init__(
        self,
        ev: EventQueue,
        bandwidth_bps: float,
        capacity_packets: int,
        prop_delay_s: float,
        deliver_callback: Callable[["Packet"], None],
        red: Optional[REDConfig] = None,
        on_drop: Optional[Callable[["Packet"], None]] = None,
        rng=None,
    ):
        if bandwidth_bps <= 0 or capacity_packets <= 0 or prop_delay_s < 0:
            raise ValueError("invalid bottleneck parameters")
        self.ev = ev
        self.bandwidth_bps = bandwidth_bps
        self.capacity = capacity_packets
        self.prop_delay_s = prop_delay_s
        self.deliver_callback = deliver_callback
        self.red = red
        self.on_drop = on_drop
        self._rng = rng
        self.queue: deque = deque()
        self.busy = False
        self.avg_queue = 0.0
        # (time, queue_length_after_event) samples for visualization/tests.
        self.queue_samples: list[tuple[float, int]] = []
        self.drop_count = 0
        self.delivered_count = 0

    def _sample(self) -> None:
        self.queue_samples.append((self.ev.now, len(self.queue)))

    def _admit(self, packet) -> bool:
        q_len = len(self.queue)
        if self.red is not None:
            self.avg_queue = (1 - self.red.w_q) * self.avg_queue + self.red.w_q * q_len
            if q_len >= self.capacity:
                return False
            if self.avg_queue < self.red.min_th:
                return True
            if self.avg_queue >= self.red.max_th:
                return False
            p = self.red.max_p * (self.avg_queue - self.red.min_th) / (
                self.red.max_th - self.red.min_th
            )
            return self._rng.random() >= p
        self.avg_queue = q_len
        return q_len < self.capacity

    def enqueue(self, packet) -> None:
        if self._admit(packet):
            self.queue.append(packet)
            self._sample()
            if not self.busy:
                self._serve_next()
        else:
            self.drop_count += 1
            if self.on_drop is not None:
                self.on_drop(packet)

    def _serve_next(self) -> None:
        if not self.queue:
            self.busy = False
            return
        self.busy = True
        packet = self.queue.popleft()
        self._sample()
        serialization_s = (packet.size_bytes * 8) / self.bandwidth_bps

        def _done() -> None:
            self.delivered_count += 1
            self.ev.schedule(self.prop_delay_s, lambda p=packet: self.deliver_callback(p))
            self._serve_next()

        self.ev.schedule(serialization_s, _done)


class Network:
    """Glues one shared Bottleneck to however many flows are registered on
    it, and tracks the physical-packet-conservation bookkeeping used by the
    invariant tests: every physical transmission (``phys_id``) ends the run
    in exactly one of {delivered, dropped, still in flight}."""

    def __init__(self, ev: EventQueue, bandwidth_bps: float, capacity_packets: int,
                 prop_delay_s: float, red: Optional[REDConfig] = None, rng=None):
        self.ev = ev
        self.flows: dict[int, object] = {}
        self.sent_ids: set[int] = set()
        self.delivered_ids: set[int] = set()
        self.dropped_ids: set[int] = set()
        self.bottleneck = Bottleneck(
            ev,
            bandwidth_bps,
            capacity_packets,
            prop_delay_s,
            deliver_callback=self._on_delivered,
            red=red,
            on_drop=self._on_drop,
            rng=rng,
        )

    def add_flow(self, flow) -> None:
        self.flows[flow.flow_id] = flow

    @staticmethod
    def _key(packet) -> tuple[int, int]:
        # phys_id is only unique *within* a flow's own sender (each Sender
        # counts its own physical transmissions from 0), so the network-wide
        # unique key is the (flow_id, phys_id) pair.
        return (packet.flow_id, packet.phys_id)

    def register_inflight(self, packet) -> None:
        self.sent_ids.add(self._key(packet))

    def _on_delivered(self, packet) -> None:
        self.delivered_ids.add(self._key(packet))
        self.flows[packet.flow_id].on_data_delivered(packet)

    def _on_drop(self, packet) -> None:
        self.dropped_ids.add(self._key(packet))

    def in_flight_ids(self) -> set[int]:
        return self.sent_ids - self.delivered_ids - self.dropped_ids
