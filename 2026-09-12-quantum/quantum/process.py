"""Process model: a sequence of alternating CPU and I/O bursts.

Real OS processes are not "one number of CPU time" — they run on the CPU
for a while, block on I/O, come back, run some more, and eventually
terminate. That distinction is what makes CPU-bound vs. I/O-bound behavior
(and therefore MLFQ's whole reason to exist) meaningful to model at all.
"""
from __future__ import annotations

from dataclasses import dataclass, field


class BurstKind:
    CPU = "CPU"
    IO = "IO"


@dataclass
class Burst:
    kind: str  # BurstKind.CPU or BurstKind.IO
    length: int  # ticks

    def __post_init__(self) -> None:
        if self.length <= 0:
            raise ValueError(f"burst length must be positive, got {self.length}")
        if self.kind not in (BurstKind.CPU, BurstKind.IO):
            raise ValueError(f"unknown burst kind {self.kind!r}")


@dataclass
class Process:
    """A process to be scheduled.

    `bursts` must start with a CPU burst (a process always needs the CPU
    at least once) and alternate CPU/IO/CPU/IO/.... The process terminates
    after its last burst completes.
    """

    pid: int
    arrival_time: int
    bursts: list[Burst]
    priority: int = 0  # lower number == higher priority (matches Unix `nice`)
    name: str = ""

    # --- runtime state, mutated by the scheduler; not part of identity ---
    burst_index: int = field(default=0, compare=False, repr=False)
    remaining_in_burst: int = field(default=0, compare=False, repr=False)
    completion_time: int | None = field(default=None, compare=False, repr=False)
    first_run_time: int | None = field(default=None, compare=False, repr=False)
    # (start_tick, end_tick, queue_level) for every contiguous slice this
    # process actually ran on the CPU — the raw material for a Gantt chart.
    run_intervals: list[tuple[int, int, int]] = field(
        default_factory=list, compare=False, repr=False
    )
    mlfq_level: int = field(default=0, compare=False, repr=False)
    dynamic_priority: float = field(default=0.0, compare=False, repr=False)

    def __post_init__(self) -> None:
        if not self.bursts:
            raise ValueError("a process must have at least one burst")
        if self.bursts[0].kind != BurstKind.CPU:
            raise ValueError("a process must start with a CPU burst")
        for i in range(1, len(self.bursts)):
            if self.bursts[i].kind == self.bursts[i - 1].kind:
                raise ValueError("bursts must strictly alternate CPU/IO")
        if not self.name:
            self.name = f"P{self.pid}"
        self.remaining_in_burst = self.bursts[0].length
        self.dynamic_priority = float(self.priority)

    def reset(self) -> None:
        """Reset all runtime state so the same Process can be replayed
        against a different scheduling algorithm."""
        self.burst_index = 0
        self.remaining_in_burst = self.bursts[0].length
        self.completion_time = None
        self.first_run_time = None
        self.run_intervals = []
        self.mlfq_level = 0
        self.dynamic_priority = float(self.priority)

    @property
    def total_cpu_time(self) -> int:
        return sum(b.length for b in self.bursts if b.kind == BurstKind.CPU)

    @property
    def current_burst(self) -> Burst:
        return self.bursts[self.burst_index]

    @property
    def is_finished(self) -> bool:
        return self.burst_index >= len(self.bursts)

    @property
    def in_cpu_phase(self) -> bool:
        return not self.is_finished and self.current_burst.kind == BurstKind.CPU

    def clone(self) -> "Process":
        """A fresh copy with identical bursts but reset runtime state —
        used to run the *same* workload through multiple algorithms
        without one run's state leaking into the next."""
        return Process(
            pid=self.pid,
            arrival_time=self.arrival_time,
            bursts=[Burst(b.kind, b.length) for b in self.bursts],
            priority=self.priority,
            name=self.name,
        )
