"""A real lossy/delaying/reordering/duplicating UDP relay -- a userspace
"bad network in a box" between two real processes on localhost, used by the
`causeway send`/`causeway recv` live demo. It is not a mock: it forwards
real datagrams over real sockets, and every drop/duplicate/delay/reorder it
applies happens to bytes that actually left the sender's kernel socket.

Topology, using a single UDP socket (exactly like a userspace NAT/relay
distinguishes directions by source address instead of needing two sockets):

    sender  --datagrams-->  proxy (--listen)  --datagrams-->  receiver (--target)
    sender  <--datagrams--  proxy             <--datagrams--  receiver

The proxy remembers whichever address it first hears from as "the sender";
everything from that address is relayed toward --target, and everything
from --target is relayed back to the sender. Because the receiver only ever
sees traffic arriving from the proxy's own socket, it naturally replies to
*that* address -- closing the loop with no extra configuration needed on
either real endpoint.
"""
from __future__ import annotations

import argparse
import random
import socket
import threading
import time
from dataclasses import dataclass
from typing import Optional, Tuple

Addr = Tuple[str, int]


@dataclass
class ProxyConfig:
    listen: Addr
    target: Addr
    loss: float = 0.0
    dup: float = 0.0
    reorder: float = 0.0
    delay_ms: float = 0.0
    jitter_ms: float = 0.0
    seed: int = 0


class LossyProxy:
    def __init__(self, cfg: ProxyConfig, log=print):
        self.cfg = cfg
        self.log = log
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(cfg.listen)
        self.sender_addr: Optional[Addr] = None
        self.rng = random.Random(cfg.seed)
        self._lock = threading.Lock()
        self._pending_swap: Optional[tuple] = None  # (delay, payload, dest) awaiting a possible swap
        self.stats = {"received": 0, "dropped": 0, "duplicated": 0, "forwarded": 0}
        self._stop = threading.Event()

    def _schedule(self, payload: bytes, dest: Addr) -> None:
        # Every read of shared, mutable proxy state (rng, _pending_swap,
        # stats) happens under one lock acquisition, including the actual
        # swap. Only starting the Timer threads themselves -- which don't
        # touch any of that state until they fire -- happens outside it.
        # (In the current design `_schedule` is only ever called from the
        # single main recv loop anyway, so this was never exploitable, but
        # splitting the decision from the lock was a latent race waiting to
        # happen the moment that assumption changed.)
        with self._lock:
            self.stats["received"] += 1
            if self.rng.random() < self.cfg.loss:
                self.stats["dropped"] += 1
                return
            delay = max(0.0, (self.cfg.delay_ms + self.rng.random() * self.cfg.jitter_ms) / 1000.0)
            do_dup = self.rng.random() < self.cfg.dup
            dup_delay = delay + self.rng.random() * max(self.cfg.jitter_ms, 1.0) / 1000.0
            do_swap = self._pending_swap is not None and self.rng.random() < self.cfg.reorder
            swap_target = self._pending_swap
            if do_swap:
                self._pending_swap = None
            else:
                self._pending_swap = (delay, payload, dest)
            if do_dup:
                self.stats["duplicated"] += 1

        if do_swap:
            prev_delay, prev_payload, prev_dest = swap_target
            # Force this packet to be sent first, the previously-queued one second.
            threading.Timer(min(delay, prev_delay), self._send, args=(payload, dest)).start()
            threading.Timer(max(delay, prev_delay), self._send, args=(prev_payload, prev_dest)).start()
        else:
            threading.Timer(delay, self._send, args=(payload, dest)).start()

        if do_dup:
            threading.Timer(dup_delay, self._send, args=(payload, dest)).start()

    def _send(self, payload: bytes, dest: Addr) -> None:
        if self._stop.is_set():
            return
        try:
            self.sock.sendto(payload, dest)
            with self._lock:
                self.stats["forwarded"] += 1
        except OSError:
            pass

    def run(self, duration: Optional[float] = None) -> None:
        self.sock.settimeout(0.5)
        deadline = None if duration is None else time.monotonic() + duration
        self.log(f"causeway-proxy listening on {self.cfg.listen}, relaying to {self.cfg.target} "
                  f"(loss={self.cfg.loss} dup={self.cfg.dup} reorder={self.cfg.reorder} "
                  f"delay={self.cfg.delay_ms}ms jitter={self.cfg.jitter_ms}ms)")
        try:
            while not self._stop.is_set():
                if deadline is not None and time.monotonic() >= deadline:
                    break
                try:
                    data, addr = self.sock.recvfrom(65535)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if addr == self.cfg.target:
                    if self.sender_addr is not None:
                        self._schedule(data, self.sender_addr)
                    continue
                if self.sender_addr is None:
                    self.sender_addr = addr
                    self.log(f"causeway-proxy: learned sender address {addr}")
                if addr == self.sender_addr:
                    self._schedule(data, self.cfg.target)
        finally:
            self.sock.close()

    def stop(self) -> None:
        self._stop.set()


def _parse_addr(s: str) -> Addr:
    host, port = s.rsplit(":", 1)
    return (host, int(port))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="causeway proxy", description=__doc__)
    p.add_argument("--listen", required=True, help="host:port to receive on (senders point --peer here)")
    p.add_argument("--target", required=True, help="host:port of the real receiver to relay to")
    p.add_argument("--loss", type=float, default=0.0)
    p.add_argument("--dup", type=float, default=0.0)
    p.add_argument("--reorder", type=float, default=0.0)
    p.add_argument("--delay-ms", type=float, default=0.0)
    p.add_argument("--jitter-ms", type=float, default=0.0)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--duration", type=float, default=None, help="stop after this many seconds")
    args = p.parse_args(argv)

    cfg = ProxyConfig(
        listen=_parse_addr(args.listen), target=_parse_addr(args.target),
        loss=args.loss, dup=args.dup, reorder=args.reorder,
        delay_ms=args.delay_ms, jitter_ms=args.jitter_ms, seed=args.seed,
    )
    proxy = LossyProxy(cfg)
    try:
        proxy.run(duration=args.duration)
    except KeyboardInterrupt:
        pass
    print(f"causeway-proxy stats: {proxy.stats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
