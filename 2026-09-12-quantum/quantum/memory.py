"""A from-scratch virtual memory manager: page table + TLB + demand paging
+ four page-replacement algorithms.

The interesting property of this domain (unlike, say, a scheduler) is that
one algorithm — Belady's MIN/Optimal — has a *proven* lower bound on page
faults, because it is allowed to see the future. That gives every other
algorithm here a real yardstick instead of a vibe: FIFO and LRU and Clock
are all just different guesses at "which page won't be needed for a
while," and Optimal is the answer key.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TLB:
    """A tiny fully-associative TLB with LRU eviction, sitting in front of
    the page table. A TLB hit means "no page-table walk needed" — modeled
    here purely as a hit/miss counter, since we don't simulate physical
    memory-access latency in cycles."""

    capacity: int = 4
    _order: list[int] = field(default_factory=list)  # most-recently-used at the end
    _map: dict[int, int] = field(default_factory=dict)  # vpage -> frame
    hits: int = 0
    misses: int = 0

    def lookup(self, vpage: int) -> int | None:
        if vpage in self._map:
            self.hits += 1
            self._order.remove(vpage)
            self._order.append(vpage)
            return self._map[vpage]
        self.misses += 1
        return None

    def install(self, vpage: int, frame: int) -> None:
        if self.capacity <= 0:
            return  # TLB disabled
        if vpage in self._map:
            self._order.remove(vpage)
        elif len(self._map) >= self.capacity:
            oldest = self._order.pop(0)
            del self._map[oldest]
        self._map[vpage] = frame
        self._order.append(vpage)

    def invalidate(self, vpage: int) -> None:
        if vpage in self._map:
            self._order.remove(vpage)
            del self._map[vpage]

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 0.0


@dataclass
class AccessRecord:
    tick: int
    vpage: int
    tlb_hit: bool
    page_fault: bool
    evicted_vpage: int | None
    frame: int


@dataclass
class MemoryResult:
    algorithm: str
    num_frames: int
    accesses: list[AccessRecord]
    frame_timeline: list[list[int | None]]  # frame contents after each access
    tlb_hits: int
    tlb_misses: int

    @property
    def page_faults(self) -> int:
        return sum(1 for a in self.accesses if a.page_fault)

    @property
    def fault_rate(self) -> float:
        return self.page_faults / len(self.accesses) if self.accesses else 0.0

    @property
    def tlb_hit_rate(self) -> float:
        total = self.tlb_hits + self.tlb_misses
        return self.tlb_hits / total if total else 0.0

    def as_dict(self) -> dict:
        return {
            "algorithm": self.algorithm,
            "num_frames": self.num_frames,
            "page_faults": self.page_faults,
            "fault_rate": round(self.fault_rate, 4),
            "tlb_hit_rate": round(self.tlb_hit_rate, 4),
            "accesses": [
                {
                    "tick": a.tick,
                    "vpage": a.vpage,
                    "tlb_hit": a.tlb_hit,
                    "page_fault": a.page_fault,
                    "evicted_vpage": a.evicted_vpage,
                    "frame": a.frame,
                }
                for a in self.accesses
            ],
            "frame_timeline": self.frame_timeline,
        }


class _Replacer:
    """Base class for a replacement policy. Subclasses track whatever
    bookkeeping they need and implement `touch`/`evict`."""

    name = "base"

    def __init__(self, num_frames: int, future: list[int] | None = None):
        self.num_frames = num_frames
        self.future = future  # only used by Optimal

    def touch(self, vpage: int, tick: int) -> None:
        """Called on every access to a resident page (hit or the access
        right after a fault brings it in) so recency/order state stays
        current."""
        raise NotImplementedError

    def choose_victim(self, resident: list[int]) -> int:
        """Pick which resident virtual page to evict."""
        raise NotImplementedError

    def on_evict(self, vpage: int) -> None:
        pass


class FIFOReplacer(_Replacer):
    name = "FIFO"

    def __init__(self, num_frames: int, future=None):
        super().__init__(num_frames, future)
        self._order: list[int] = []  # load order, oldest first

    def touch(self, vpage: int, tick: int) -> None:
        if vpage not in self._order:
            self._order.append(vpage)

    def choose_victim(self, resident: list[int]) -> int:
        return self._order[0]

    def on_evict(self, vpage: int) -> None:
        self._order.remove(vpage)


class LRUReplacer(_Replacer):
    name = "LRU"

    def __init__(self, num_frames: int, future=None):
        super().__init__(num_frames, future)
        self._order: list[int] = []  # least-recently-used first

    def touch(self, vpage: int, tick: int) -> None:
        if vpage in self._order:
            self._order.remove(vpage)
        self._order.append(vpage)

    def choose_victim(self, resident: list[int]) -> int:
        return self._order[0]

    def on_evict(self, vpage: int) -> None:
        self._order.remove(vpage)


class ClockReplacer(_Replacer):
    """Second-chance / clock: an approximation of LRU using one reference
    bit per frame and a circulating hand, instead of a full recency order."""

    name = "Clock"

    def __init__(self, num_frames: int, future=None):
        super().__init__(num_frames, future)
        self._ring: list[int] = []  # resident vpages in load order (circular)
        self._ref: dict[int, bool] = {}
        self._hand = 0

    def touch(self, vpage: int, tick: int) -> None:
        if vpage not in self._ring:
            self._ring.append(vpage)
        self._ref[vpage] = True

    def choose_victim(self, resident: list[int]) -> int:
        n = len(self._ring)
        while True:
            candidate = self._ring[self._hand % n]
            if not self._ref.get(candidate, False):
                return candidate
            self._ref[candidate] = False
            self._hand += 1

    def on_evict(self, vpage: int) -> None:
        self._ring.remove(vpage)
        self._ref.pop(vpage, None)
        if self._ring:
            self._hand %= len(self._ring)
        else:
            self._hand = 0


class OptimalReplacer(_Replacer):
    """Belady's MIN: evict the resident page whose next use is farthest in
    the future (or never used again). Requires full lookahead over the
    reference string — impossible for a real OS, but a genuine, provable
    lower bound on achievable page faults for *any* algorithm."""

    name = "Optimal"

    def __init__(self, num_frames: int, future: list[int]):
        super().__init__(num_frames, future)
        self._pos = 0  # index into `future` of the access just served

    def touch(self, vpage: int, tick: int) -> None:
        self._pos = tick + 1  # next lookup starts just after this access

    def choose_victim(self, resident: list[int]) -> int:
        farthest = -1
        victim = resident[0]
        for vp in resident:
            try:
                next_use = self.future.index(vp, self._pos)
            except ValueError:
                return vp  # never used again — the ideal victim
            if next_use > farthest:
                farthest = next_use
                victim = vp
        return victim


REPLACERS = {
    "fifo": FIFOReplacer,
    "lru": LRUReplacer,
    "clock": ClockReplacer,
    "optimal": OptimalReplacer,
}


def simulate_memory(
    reference_string: list[int],
    num_frames: int,
    algorithm: str,
    tlb_capacity: int = 4,
) -> MemoryResult:
    if algorithm not in REPLACERS:
        raise ValueError(f"unknown algorithm {algorithm!r}; choose from {sorted(REPLACERS)}")
    if num_frames < 1:
        raise ValueError("num_frames must be >= 1")
    if not reference_string:
        raise ValueError("reference_string must not be empty")

    replacer = REPLACERS[algorithm](num_frames, future=reference_string)
    tlb = TLB(capacity=tlb_capacity)

    # frame table: list of length num_frames, each slot None or a vpage
    frames: list[int | None] = [None] * num_frames
    page_to_frame: dict[int, int] = {}
    free_frames = list(range(num_frames))

    accesses: list[AccessRecord] = []
    timeline: list[list[int | None]] = []

    for tick, vpage in enumerate(reference_string):
        tlb_frame = tlb.lookup(vpage)
        if tlb_frame is not None:
            replacer.touch(vpage, tick)
            accesses.append(AccessRecord(tick, vpage, True, False, None, tlb_frame))
            timeline.append(list(frames))
            continue

        if vpage in page_to_frame:
            frame = page_to_frame[vpage]
            replacer.touch(vpage, tick)
            tlb.install(vpage, frame)
            accesses.append(AccessRecord(tick, vpage, False, False, None, frame))
            timeline.append(list(frames))
            continue

        # Page fault: bring `vpage` in, evicting someone if memory is full.
        evicted_vpage = None
        if free_frames:
            frame = free_frames.pop()
        else:
            resident = [p for p in frames if p is not None]
            evicted_vpage = replacer.choose_victim(resident)
            frame = page_to_frame.pop(evicted_vpage)
            replacer.on_evict(evicted_vpage)
            tlb.invalidate(evicted_vpage)

        frames[frame] = vpage
        page_to_frame[vpage] = frame
        replacer.touch(vpage, tick)
        tlb.install(vpage, frame)
        accesses.append(AccessRecord(tick, vpage, False, True, evicted_vpage, frame))
        timeline.append(list(frames))

    return MemoryResult(
        algorithm=replacer.name,
        num_frames=num_frames,
        accesses=accesses,
        frame_timeline=timeline,
        tlb_hits=tlb.hits,
        tlb_misses=tlb.misses,
    )
