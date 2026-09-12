"""Multiprogramming and thrashing, Denning's working-set model.

The classic (and, the first time you see it, genuinely counter-intuitive)
result: as you admit *more* concurrent processes to a system with a fixed
pool of physical frames, throughput at first goes *up* — more processes
means that while one is blocked servicing a page fault (real disk I/O,
orders of magnitude slower than a memory access), another ready process
can keep the CPU busy instead of it sitting idle. But past a point,
throughput collapses: once frames-per-process drops below what each
process's working set actually needs, *everyone* is faulting *all the
time*, there's rarely anyone actually ready to run, and the system spends
nearly all its time waiting on page-ins instead of computing. Admitting
still more work then makes the system do *less* useful work per unit
time, not more. That's thrashing, and it only shows up at all if the
simulation models the CPU/page-fault overlap that causes the initial
rise — a purely serial, one-thing-at-a-time simulation would only ever
show monotonic decline, no cliff.

This module simulates a fixed pool of physical frames shared *globally*
(any process's fault can evict any other's page) by several concurrently
running processes, each replaying its own realistic locality-of-reference
memory stream, dispatched round-robin one access per CPU tick, with a
faulting process going properly off the ready queue for the fault's
service time — exactly the mechanism that produces the real curve.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from .workload import make_reference_string

MAX_TICKS_PER_ACCESS = 1000  # simulation safety cap, not a real limit


def working_set_sizes(reference_string: list[int], window: int) -> list[int]:
    """Denning's WS(t, window): the number of *distinct* pages referenced
    in the last `window` accesses, computed at every point in time."""
    sizes = []
    counts: dict[int, int] = {}
    dq: list[int] = []
    for page in reference_string:
        dq.append(page)
        counts[page] = counts.get(page, 0) + 1
        if len(dq) > window:
            old = dq.pop(0)
            counts[old] -= 1
            if counts[old] == 0:
                del counts[old]
        sizes.append(len(counts))
    return sizes


@dataclass
class MultiprogrammingResult:
    num_processes: int
    num_frames: int
    total_accesses: int
    page_faults: int
    makespan: int  # wall-clock ticks until every process finished its stream
    idle_ticks: int
    avg_working_set_demand: float  # sum, across processes, of avg WS size

    @property
    def fault_rate(self) -> float:
        return self.page_faults / self.total_accesses

    @property
    def throughput(self) -> float:
        """Total accesses served per unit of wall-clock time — the metric
        that actually collapses under thrashing. Rises with more
        concurrent processes while there are still enough frames to go
        around (CPU/fault overlap keeps the CPU busier), then collapses
        once demand outstrips the frame pool."""
        return self.total_accesses / self.makespan

    def as_dict(self) -> dict:
        return {
            "num_processes": self.num_processes,
            "num_frames": self.num_frames,
            "page_faults": self.page_faults,
            "fault_rate": round(self.fault_rate, 4),
            "makespan": self.makespan,
            "idle_ticks": self.idle_ticks,
            "throughput": round(self.throughput, 5),
            "avg_working_set_demand": round(self.avg_working_set_demand, 2),
        }


def simulate_multiprogramming(
    num_frames: int,
    num_processes: int,
    ref_length: int = 200,
    num_pages: int = 12,
    working_set_size: int = 4,
    fault_service_time: int = 20,
    seed: int = 0,
) -> MultiprogrammingResult:
    """Each of `num_processes` runs its own `ref_length`-access locality
    workload against a single shared pool of `num_frames` physical frames
    under global LRU. One CPU tick dispatches exactly one ready process's
    next access; a fault takes that process off the ready queue for
    `fault_service_time` ticks (modeling real disk-service latency)
    while every *other* ready process keeps using the CPU — the overlap
    that makes low-degree multiprogramming a net win before it becomes a
    net loss."""
    if num_frames < 1:
        raise ValueError("num_frames must be >= 1")
    if num_processes < 1:
        raise ValueError("num_processes must be >= 1")
    if ref_length < 1:
        raise ValueError("ref_length must be >= 1")

    streams = [
        make_reference_string(
            ref_length, num_pages=num_pages, seed=seed * 10_000 + pid,
            working_set_size=working_set_size,
        )
        for pid in range(num_processes)
    ]
    ws_demand = sum(
        sum(working_set_sizes(stream, window=working_set_size * 2)) / len(stream)
        for stream in streams
    )

    order: list[tuple[int, int]] = []  # global LRU order of (pid, vpage)
    resident: set[tuple[int, int]] = set()
    free_frames = num_frames

    cursor = [0] * num_processes
    ready: deque[int] = deque(range(num_processes))
    blocked_until: dict[int, int] = {}  # pid -> tick it rejoins the ready queue
    finished = [False] * num_processes
    finished_count = 0
    # A single disk services page-ins one at a time (a real, finite I/O
    # resource) — this is what actually makes thrashing collapse
    # throughput rather than just raise the fault rate: once faults
    # arrive faster than one every `fault_service_time` ticks, a real
    # FIFO queue forms and every process's *own* service time grows
    # without bound, on top of the fixed per-fault cost.
    disk_free_at = 0

    total_faults = 0
    idle_ticks = 0
    t = 0
    max_ticks = MAX_TICKS_PER_ACCESS * ref_length * num_processes

    while finished_count < num_processes:
        if t > max_ticks:
            raise RuntimeError(f"multiprogramming simulation exceeded {max_ticks} ticks")

        for pid in [p for p, until in blocked_until.items() if until <= t]:
            del blocked_until[pid]
            ready.append(pid)

        if not ready:
            idle_ticks += 1
            t += 1
            continue

        pid = ready.popleft()
        vpage = streams[pid][cursor[pid]]
        key = (pid, vpage)
        was_fault = key not in resident

        if was_fault:
            total_faults += 1
            if free_frames > 0:
                free_frames -= 1
            else:
                victim = order.pop(0)
                resident.discard(victim)
            resident.add(key)
            order.append(key)
        else:
            order.remove(key)
            order.append(key)

        cursor[pid] += 1
        if cursor[pid] == ref_length:
            finished[pid] = True
            finished_count += 1
            # Process exits: free every frame it still holds. These keys
            # are pid-scoped, so this pid is always the sole owner.
            for leftover in [k for k in resident if k[0] == pid]:
                resident.discard(leftover)
                order.remove(leftover)
                free_frames += 1
        elif was_fault:
            # Blocked off the ready queue until the single shared disk
            # actually gets to this fault (FIFO queueing, not just a
            # fixed per-fault cost) — this is both the overlap (everyone
            # else keeps using the CPU while this one waits) and the
            # thrashing bottleneck (queueing delay grows without bound
            # once faults arrive faster than the disk can drain them).
            service_start = max(t + 1, disk_free_at)
            disk_free_at = service_start + fault_service_time
            blocked_until[pid] = disk_free_at
        else:
            ready.append(pid)  # a hit: instantly eligible again

        t += 1

    return MultiprogrammingResult(
        num_processes=num_processes,
        num_frames=num_frames,
        total_accesses=ref_length * num_processes,
        page_faults=total_faults,
        makespan=t,
        idle_ticks=idle_ticks,
        avg_working_set_demand=ws_demand,
    )


def find_thrashing_cliff(
    num_frames: int,
    max_processes: int = 12,
    **kwargs,
) -> list[MultiprogrammingResult]:
    """Sweep the degree of multiprogramming from 1 to `max_processes` with
    a fixed frame pool, returning one result per degree — the raw material
    for plotting the classic throughput-rises-then-collapses curve."""
    return [
        simulate_multiprogramming(num_frames, n, **kwargs) for n in range(1, max_processes + 1)
    ]
