"""Virtual memory page-replacement engine: FIFO, LRU, Optimal (MIN), Clock.

Each algorithm walks a page-reference string against a fixed number of physical
frames and records a full step-by-step trace (frame contents + fault/hit +
evicted page at every reference), not just a final fault count, so the HTML
visualizer can animate it and tests can check exact frame contents at any step.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


class VMError(ValueError):
    pass


@dataclass
class Step:
    index: int
    page: object
    frames: list          # snapshot AFTER this reference is serviced; None = empty slot
    fault: bool
    evicted: object = None


@dataclass
class Trace:
    algorithm: str
    num_frames: int
    ref_string: list
    steps: list
    faults: int

    @property
    def hits(self) -> int:
        return len(self.steps) - self.faults

    @property
    def fault_rate(self) -> float:
        return self.faults / len(self.steps) if self.steps else 0.0


def _validate(ref_string, num_frames):
    if num_frames <= 0:
        raise VMError(f"num_frames must be positive, got {num_frames}")
    if not ref_string:
        raise VMError("reference string must not be empty")


def fifo(ref_string, num_frames):
    """First-In-First-Out: evict whichever resident page was loaded longest ago,
    irrespective of how recently it was actually used. The classic algorithm that
    exhibits Belady's Anomaly."""
    _validate(ref_string, num_frames)
    queue = []  # front (index 0) = oldest-loaded
    faults = 0
    steps = []
    for idx, page in enumerate(ref_string):
        fault = page not in queue
        evicted = None
        if fault:
            faults += 1
            if len(queue) < num_frames:
                queue.append(page)
            else:
                evicted = queue.pop(0)
                queue.append(page)
        snapshot = list(queue) + [None] * (num_frames - len(queue))
        steps.append(Step(idx, page, snapshot, fault, evicted))
    return Trace("FIFO", num_frames, list(ref_string), steps, faults)


def lru(ref_string, num_frames):
    """Least Recently Used: evict the resident page whose most recent reference is
    furthest in the past. Provably a "stack algorithm" (never exhibits Belady's
    Anomaly: faults can only stay the same or decrease as frames increase)."""
    _validate(ref_string, num_frames)
    order = []  # index 0 = least recently used, end = most recently used
    faults = 0
    steps = []
    for idx, page in enumerate(ref_string):
        fault = page not in order
        evicted = None
        if fault:
            faults += 1
            if len(order) < num_frames:
                order.append(page)
            else:
                evicted = order.pop(0)
                order.append(page)
        else:
            order.remove(page)
            order.append(page)
        snapshot = list(order) + [None] * (num_frames - len(order))
        steps.append(Step(idx, page, snapshot, fault, evicted))
    return Trace("LRU", num_frames, list(ref_string), steps, faults)


def optimal(ref_string, num_frames):
    """Bélády's clairvoyant/MIN algorithm: evict the resident page whose *next* use
    lies furthest in the future (or is never used again). Requires knowing the
    whole reference string in advance — unimplementable in a real OS — but is the
    mathematically proven lower bound on fault count for any algorithm, and is the
    ground-truth baseline every other algorithm here is checked against."""
    _validate(ref_string, num_frames)
    resident = []  # order irrelevant, just a set of currently-loaded pages
    faults = 0
    steps = []
    n = len(ref_string)
    for idx, page in enumerate(ref_string):
        fault = page not in resident
        evicted = None
        if fault:
            faults += 1
            if len(resident) < num_frames:
                resident.append(page)
            else:
                def next_use(p):
                    try:
                        return ref_string.index(p, idx + 1)
                    except ValueError:
                        return math.inf
                victim = max(resident, key=next_use)
                evicted = victim
                resident[resident.index(victim)] = page
        snapshot = list(resident) + [None] * (num_frames - len(resident))
        steps.append(Step(idx, page, snapshot, fault, evicted))
    return Trace("Optimal", num_frames, list(ref_string), steps, faults)


def clock(ref_string, num_frames):
    """Clock / Second-Chance: an approximation of LRU using one reference bit per
    frame and a circular sweeping hand — evict the first frame the hand finds with
    a clear reference bit, clearing bits (giving a "second chance") along the way."""
    _validate(ref_string, num_frames)
    frame_pages = [None] * num_frames
    ref_bits = [0] * num_frames
    page_to_frame = {}
    hand = 0
    faults = 0
    steps = []
    for idx, page in enumerate(ref_string):
        evicted = None
        if page in page_to_frame:
            fault = False
            ref_bits[page_to_frame[page]] = 1
        else:
            fault = True
            faults += 1
            if None in frame_pages:
                slot = frame_pages.index(None)
            else:
                while ref_bits[hand] == 1:
                    ref_bits[hand] = 0
                    hand = (hand + 1) % num_frames
                slot = hand
                evicted = frame_pages[slot]
                del page_to_frame[evicted]
                hand = (hand + 1) % num_frames
            frame_pages[slot] = page
            ref_bits[slot] = 1
            page_to_frame[page] = slot
        snapshot = list(frame_pages)
        steps.append(Step(idx, page, snapshot, fault, evicted))
    return Trace("Clock", num_frames, list(ref_string), steps, faults)


ALGORITHMS = {"fifo": fifo, "lru": lru, "optimal": optimal, "clock": clock}


BELADY_REFERENCE_STRING = [1, 2, 3, 4, 1, 2, 5, 1, 2, 3, 4, 5]


def belady_anomaly_demo():
    """Reproduce the canonical Belady's Anomaly example: FIFO on
    [1,2,3,4,1,2,5,1,2,3,4,5] takes *more* faults with 4 frames than with 3."""
    trace_3 = fifo(BELADY_REFERENCE_STRING, 3)
    trace_4 = fifo(BELADY_REFERENCE_STRING, 4)
    return trace_3, trace_4
