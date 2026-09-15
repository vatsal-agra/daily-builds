"""A discrete-event driver that runs a client/server Connection pair over a
SimulatedLink with no real-time waiting at all: the "clock" only ever jumps
straight to the next moment something actually happens (a packet arrives, a
retransmit timer or persist timer fires). That's what lets thousands of
seeded, adversarial (lossy/reordering/jittery) transfers run as a fast unit
test suite instead of a real-time integration test.
"""
from __future__ import annotations

import hashlib
from typing import Callable, List, Optional

from .clock import VirtualClock
from .connection import Connection
from .wire import SimulatedLink


class SimulationStalled(RuntimeError):
    """Raised when neither connection has any pending event or timer, but at
    least one of them isn't closed yet -- i.e. the protocol has deadlocked.
    This is a correctness invariant, not just a safety net: a real bug (the
    zero-window persist timer failing to arm, say) should surface as this
    exception in a test, not as a test that hangs forever."""


def run_transfer(
    data: bytes,
    *,
    mss: int = 536,
    client_recv_capacity: int = 64 * 1024,
    server_recv_capacity: int = 64 * 1024,
    loss: float = 0.0,
    dup: float = 0.0,
    reorder: float = 0.0,
    base_delay: float = 0.02,
    jitter: float = 0.01,
    seed: int = 0,
    max_virtual_time: float = 300.0,
    max_iterations: int = 2_000_000,
    on_event: Optional[Callable[[str, dict], None]] = None,
) -> dict:
    """Send `data` from a client Connection to a server Connection across a
    seeded lossy/reordering/duplicating SimulatedLink, drive both sides to a
    full graceful close, and return a result dict including whether the
    received bytes are a byte-exact match (by SHA-256) for what was sent."""

    clock = VirtualClock()
    link = SimulatedLink(
        clock, base_delay=base_delay, jitter=jitter, loss_prob=loss,
        dup_prob=dup, reorder_prob=reorder, seed=seed,
    )

    def client_ev(e):
        if on_event:
            on_event("client", e)

    def server_ev(e):
        if on_event:
            on_event("server", e)

    client = Connection("client", link.endpoint_a, clock, mss=mss,
                         recv_capacity=client_recv_capacity, on_event=client_ev)
    server = Connection("server", link.endpoint_b, clock, mss=mss,
                         recv_capacity=server_recv_capacity, on_event=server_ev)

    client.send(data)
    client.close()

    received = bytearray()
    iterations = 0
    while not (client.closed and server.closed):
        iterations += 1
        if iterations > max_iterations:
            raise SimulationStalled(
                f"exceeded {max_iterations} iterations without both sides closing "
                f"(client.closed={client.closed}, server.closed={server.closed})"
            )
        candidates: List[float] = []
        for x in (link.next_event_time(), client.next_timer_deadline(), server.next_timer_deadline()):
            if x is not None:
                candidates.append(x)
        if not candidates:
            raise SimulationStalled(
                "no pending network event or timer on either side, but the "
                f"connection is not closed (client.closed={client.closed}, "
                f"server.closed={server.closed}) -- protocol deadlock"
            )
        t = max(clock.t, min(candidates))
        if t > max_virtual_time:
            raise SimulationStalled(f"virtual time exceeded {max_virtual_time}s without closing")
        clock.advance_to(t)
        link.deliver_due(t)
        client.step(t)
        server.step(t)
        received.extend(server.recv())
        if server.eof and not server.close_requested:
            server.close()

    sha_sent = hashlib.sha256(data).hexdigest()
    sha_recv = hashlib.sha256(bytes(received)).hexdigest()
    return {
        "success": sha_sent == sha_recv and len(data) == len(received),
        "sha_sent": sha_sent,
        "sha_received": sha_recv,
        "bytes_sent": len(data),
        "bytes_received": len(received),
        "received": bytes(received),
        "virtual_time": clock.t,
        "iterations": iterations,
        "client_stats": dict(client.stats),
        "server_stats": dict(server.stats),
        "link_stats": dict(link.stats),
    }
