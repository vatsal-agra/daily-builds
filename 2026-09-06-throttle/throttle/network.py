"""Packet-level discrete-event network simulation.

`Simulator` is a plain heap-based discrete-event clock. `Link` is a
single-server FIFO queue: finite bandwidth (so a packet takes
`size_bytes / bandwidth_Bps` seconds to *serialize* onto the wire), a
finite drop-tail buffer (a packet that arrives when the buffer is already
full is dropped — real router behavior, not a probability roll standing in
for it), a fixed one-way propagation delay, and optionally independent
random loss (modeling line noise / wireless bit errors, unrelated to
congestion) and reordering (modeling ECMP/multi-path fan-out on a real
network, here approximated as extra jitter on the propagation leg).

`AccessLink` is the much simpler "last mile": a fixed propagation delay
with no serialization cost and no queue, used for the per-flow legs of a
dumbbell topology so that different flows can have different RTTs while
still sharing one real bottleneck `Link` in the middle.

Because `Link.enqueue` is only ever called from inside the simulator's own
event-processing loop, and every accepted packet's departure is itself a
scheduled event, `Link.queue_bytes` is always an accurate reflection of
the current backlog at the moment a new packet arrives — no separate
"tick" logic is needed to keep it in sync, even with multiple flows
enqueuing to the same shared link at interleaved simulated times.
"""
from __future__ import annotations

import heapq
import itertools
import random
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

from .packet import Segment


class Simulator:
    """Heap-based discrete-event clock. Events fire strictly in time order;
    ties are broken by insertion order so behavior is deterministic given a
    fixed sequence of `schedule` calls (which it is, for a given seed)."""

    def __init__(self) -> None:
        self.now: float = 0.0
        self._heap: List[Tuple[float, int, Callable[[], None]]] = []
        self._counter = itertools.count()
        self._stopped = False

    def schedule_at(self, t: float, callback: Callable[[], None]) -> None:
        if t < self.now:
            raise ValueError(f"cannot schedule in the past: {t} < {self.now}")
        heapq.heappush(self._heap, (t, next(self._counter), callback))

    def schedule_after(self, dt: float, callback: Callable[[], None]) -> None:
        self.schedule_at(self.now + dt, callback)

    def stop(self) -> None:
        self._stopped = True

    def run(self, until: Optional[float] = None) -> None:
        self._stopped = False
        while self._heap and not self._stopped:
            t, _, cb = self._heap[0]
            if until is not None and t > until:
                self.now = until  # simulated up to `until` with no events left in that span
                return
            heapq.heappop(self._heap)
            self.now = t
            cb()
        if until is not None and self.now < until:
            self.now = until  # ran out of events entirely, but still "simulated" up to `until`


@dataclass
class LinkStats:
    delivered: int = 0
    delivered_bytes: int = 0
    dropped_overflow: int = 0
    dropped_random: int = 0
    queue_samples: List[Tuple[float, int]] = field(default_factory=list)
    max_queue_bytes: int = 0


class Link:
    """A bandwidth-limited, finite-buffer, drop-tail FIFO link."""

    def __init__(
        self,
        sim: Simulator,
        bandwidth_Bps: float,
        buffer_bytes: int,
        prop_delay_s: float,
        loss_prob: float = 0.0,
        reorder_prob: float = 0.0,
        rng: Optional[random.Random] = None,
        name: str = "link",
    ) -> None:
        self.sim = sim
        self.bandwidth_Bps = bandwidth_Bps
        self.buffer_bytes = buffer_bytes
        self.prop_delay_s = prop_delay_s
        self.loss_prob = loss_prob
        self.reorder_prob = reorder_prob
        self.rng = rng or random.Random()
        self.name = name

        self.queue_bytes = 0
        self.free_at = 0.0
        self.stats = LinkStats()

    def _record_queue_sample(self) -> None:
        self.stats.queue_samples.append((self.sim.now, self.queue_bytes))
        if self.queue_bytes > self.stats.max_queue_bytes:
            self.stats.max_queue_bytes = self.queue_bytes

    def send(self, packet: Segment, on_deliver: Callable[[Segment, float], None]) -> None:
        """Attempt to put `packet` onto the wire now (`self.sim.now`)."""
        now = self.sim.now
        size = packet.size_bytes

        if self.loss_prob > 0.0 and self.rng.random() < self.loss_prob:
            self.stats.dropped_random += 1
            return

        if self.queue_bytes + size > self.buffer_bytes:
            self.stats.dropped_overflow += 1
            return

        self.queue_bytes += size
        self._record_queue_sample()

        start = max(self.free_at, now)
        service_time = size / self.bandwidth_Bps
        finish = start + service_time
        self.free_at = finish

        def _depart() -> None:
            self.queue_bytes -= size
            self._record_queue_sample()
            self.stats.delivered += 1
            self.stats.delivered_bytes += size

            extra = 0.0
            if self.reorder_prob > 0.0 and self.rng.random() < self.reorder_prob:
                # Model reordering as extra jitter on the propagation leg —
                # enough that a later-sent, less-jittered packet can arrive
                # first, which is what "reordering" means from the
                # receiver's point of view.
                extra = self.rng.uniform(0.0, 4.0 * self.prop_delay_s + 1e-6)

            arrival = finish + self.prop_delay_s + extra
            self.sim.schedule_at(arrival, lambda: on_deliver(packet, arrival))

        self.sim.schedule_at(finish, _depart)

    def utilization(self, duration: float) -> float:
        if duration <= 0:
            return 0.0
        return (self.stats.delivered_bytes) / (self.bandwidth_Bps * duration)


class AccessLink:
    """A fixed-delay, unlimited-bandwidth, unbuffered "last mile" leg —
    exists purely to give each flow its own RTT contribution before it
    joins the shared bottleneck link in a dumbbell topology."""

    def __init__(self, sim: Simulator, delay_s: float, loss_prob: float = 0.0,
                 rng: Optional[random.Random] = None) -> None:
        self.sim = sim
        self.delay_s = delay_s
        self.loss_prob = loss_prob
        self.rng = rng or random.Random()

    def send(self, packet: Segment, on_deliver: Callable[[Segment, float], None]) -> None:
        if self.loss_prob > 0.0 and self.rng.random() < self.loss_prob:
            return
        arrival = self.sim.now + self.delay_s
        self.sim.schedule_at(arrival, lambda: on_deliver(packet, arrival))
