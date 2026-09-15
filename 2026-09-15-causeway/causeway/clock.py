"""Clocks: a real wall-clock one for live sockets, a virtual one for the
deterministic in-process network simulator.

The Connection engine only ever calls ``clock.now()``; it never touches
``time`` directly, which is what lets the exact same protocol code run
against a real UDP socket in real time and against a seeded, instantaneous
discrete-event simulation with identical logic.
"""
from __future__ import annotations

import time


class RealClock:
    def now(self) -> float:
        return time.monotonic()


class VirtualClock:
    """A clock whose value is set explicitly by a discrete-event driver."""

    def __init__(self, start: float = 0.0):
        self.t = start

    def now(self) -> float:
        return self.t

    def advance_to(self, t: float) -> None:
        if t < self.t:
            raise ValueError(f"virtual clock cannot go backwards: {t} < {self.t}")
        self.t = t
