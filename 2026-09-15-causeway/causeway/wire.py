"""Wire implementations: what a Connection actually sends bytes over.

Both implementations expose the same tiny interface -- ``send(data)`` and
``poll() -> list[bytes]`` -- so ``Connection`` never knows or cares whether
it's talking to a real kernel UDP socket or a seeded in-process network
simulation. That's deliberate: the exact same protocol state machine that
gets fuzz-tested thousands of times a second against ``SimulatedLink`` is
the code driving the real two-process file transfer over ``RealUdpWire``.
"""
from __future__ import annotations

import heapq
import itertools
import random
import socket
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from .clock import VirtualClock


class RealUdpWire:
    """A real UDP socket, wrapped down to send()/poll()."""

    def __init__(self, sock: socket.socket, peer_addr):
        self.sock = sock
        self.peer_addr = peer_addr
        self.sock.setblocking(False)

    def send(self, data: bytes) -> None:
        self.sock.sendto(data, self.peer_addr)

    def poll(self) -> List[bytes]:
        out = []
        while True:
            try:
                data, addr = self.sock.recvfrom(65535)
            except BlockingIOError:
                break
            except OSError:
                break
            # Lock onto the first peer we hear from if we don't have one yet
            # (server side, before the client's address is known).
            if self.peer_addr is None:
                self.peer_addr = addr
            if addr == self.peer_addr:
                out.append(data)
        return out


@dataclass(order=True)
class _Event:
    deliver_at: float
    seq: int
    dest: "SimWire" = field(compare=False)
    data: bytes = field(compare=False)


class SimulatedLink:
    """A seeded, discrete-event, in-process lossy/reordering/duplicating
    network between exactly two endpoints, driven by a VirtualClock.

    Delay is drawn per packet as ``base_delay + Uniform(0, jitter)``, which
    on its own produces occasional genuine reordering (a packet sent later
    can draw a shorter delay and arrive first) without needing a separate
    "reorder" mechanism to fake it. An explicit ``reorder_prob`` on top of
    that forces some pairs of consecutive packets to swap delivery order
    outright, so tests aren't at the mercy of randomly getting *some*
    reordering.
    """

    def __init__(
        self,
        clock: VirtualClock,
        *,
        base_delay: float = 0.02,
        jitter: float = 0.01,
        loss_prob: float = 0.0,
        dup_prob: float = 0.0,
        reorder_prob: float = 0.0,
        seed: int = 0,
    ):
        self.clock = clock
        self.base_delay = base_delay
        self.jitter = jitter
        self.loss_prob = loss_prob
        self.dup_prob = dup_prob
        self.reorder_prob = reorder_prob
        self.rng = random.Random(seed)
        self._heap: List[_Event] = []
        self._counter = itertools.count()
        self._pending_swap: Optional[_Event] = None
        self.stats = {"sent": 0, "dropped": 0, "duplicated": 0, "delivered": 0}
        self.endpoint_a = SimWire(self, "a")
        self.endpoint_b = SimWire(self, "b")

    def _other(self, wire: "SimWire") -> "SimWire":
        return self.endpoint_b if wire is self.endpoint_a else self.endpoint_a

    def _emit(self, sender: "SimWire", data: bytes) -> None:
        self.stats["sent"] += 1
        if self.rng.random() < self.loss_prob:
            self.stats["dropped"] += 1
            return
        dest = self._other(sender)
        delay = self.base_delay + self.rng.random() * self.jitter
        ev = _Event(self.clock.now() + delay, next(self._counter), dest, data)

        if self._pending_swap is not None and self.rng.random() < self.reorder_prob:
            # Force this packet to arrive before the previously queued one.
            prev = self._pending_swap
            ev.deliver_at, prev.deliver_at = min(ev.deliver_at, prev.deliver_at), max(
                ev.deliver_at, prev.deliver_at
            )
            self._pending_swap = None
        else:
            self._pending_swap = ev

        heapq.heappush(self._heap, ev)
        self.stats["delivered"] += 1
        if self.rng.random() < self.dup_prob:
            self.stats["duplicated"] += 1
            dup_delay = delay + self.rng.random() * self.jitter
            heapq.heappush(
                self._heap,
                _Event(self.clock.now() + dup_delay, next(self._counter), dest, data),
            )

    def next_event_time(self) -> Optional[float]:
        return self._heap[0].deliver_at if self._heap else None

    def deliver_due(self, now: float) -> None:
        """Move every event scheduled at or before `now` into its
        destination endpoint's inbox. Called by the simulation driver after
        advancing the virtual clock."""
        while self._heap and self._heap[0].deliver_at <= now + 1e-12:
            ev = heapq.heappop(self._heap)
            ev.dest.inbox.append(ev.data)


class SimWire:
    """One endpoint of a SimulatedLink -- what a Connection actually holds."""

    def __init__(self, link: SimulatedLink, name: str):
        self.link = link
        self.name = name
        self.inbox: List[bytes] = []

    def send(self, data: bytes) -> None:
        self.link._emit(self, data)

    def poll(self) -> List[bytes]:
        out, self.inbox = self.inbox, []
        return out
