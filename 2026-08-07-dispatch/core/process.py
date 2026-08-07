"""Process (PCB) model, workload loading, and per-process/aggregate result types."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Process:
    """A simulated process control block (PCB).

    priority: lower number = higher priority (standard OS convention, 0 = highest).
    """

    pid: str
    arrival_time: int
    burst_time: int
    priority: int = 0

    def __post_init__(self):
        if self.burst_time <= 0:
            raise ValueError(f"process {self.pid!r}: burst_time must be positive, got {self.burst_time}")
        if self.arrival_time < 0:
            raise ValueError(f"process {self.pid!r}: arrival_time must be >= 0, got {self.arrival_time}")


@dataclass
class ProcessResult:
    """Computed schedule outcome for one process."""

    pid: str
    arrival_time: int
    burst_time: int
    start_time: int          # first time it ever got the CPU (for response time)
    completion_time: int     # time its last unit of CPU finished
    priority: int = 0

    @property
    def turnaround_time(self) -> int:
        return self.completion_time - self.arrival_time

    @property
    def waiting_time(self) -> int:
        return self.turnaround_time - self.burst_time

    @property
    def response_time(self) -> int:
        return self.start_time - self.arrival_time

    def as_dict(self) -> dict:
        return {
            "pid": self.pid,
            "arrival_time": self.arrival_time,
            "burst_time": self.burst_time,
            "priority": self.priority,
            "start_time": self.start_time,
            "completion_time": self.completion_time,
            "turnaround_time": self.turnaround_time,
            "waiting_time": self.waiting_time,
            "response_time": self.response_time,
        }


@dataclass
class Schedule:
    """Full simulation output: a Gantt chart plus per-process results."""

    algorithm: str
    gantt: list          # list of (pid_or_None, start, end) intervals, time-ordered, non-overlapping
    results: dict         # pid -> ProcessResult
    context_switches: int = 0

    def ordered_results(self, order):
        return [self.results[p.pid] for p in order]

    def makespan(self) -> int:
        return self.gantt[-1][2] if self.gantt else 0

    def busy_time(self) -> int:
        return sum(end - start for pid, start, end in self.gantt if pid is not None)

    def idle_time(self) -> int:
        return sum(end - start for pid, start, end in self.gantt if pid is None)


def load_workload(path) -> list:
    """Load a list of Process objects from a JSON file: [{"pid","arrival_time","burst_time","priority"}, ...]"""
    data = json.loads(Path(path).read_text())
    procs = data["processes"] if isinstance(data, dict) else data
    return [
        Process(
            pid=str(p["pid"]),
            arrival_time=int(p["arrival_time"]),
            burst_time=int(p["burst_time"]),
            priority=int(p.get("priority", 0)),
        )
        for p in procs
    ]


def processes_from_dicts(dicts) -> list:
    return [Process(pid=str(p["pid"]), arrival_time=int(p["arrival_time"]),
                     burst_time=int(p["burst_time"]), priority=int(p.get("priority", 0)))
            for p in dicts]
