"""A tick-driven, single-core CPU scheduler simulator.

One tick == one unit of virtual time == the interval [t, t+1). Every
algorithm below is expressed as a small `Policy` object with three hooks
that the shared `_Engine` loop calls at well-defined points:

  enqueue(p, t)             a process just became ready (arrival or the
                             end of an I/O burst) and must be added to
                             whatever internal structure the policy keeps.
  on_tick_start(t, running) called once per tick, before selection — used
                             for time-based bookkeeping (aging, MLFQ boost).
  select(t, running)        decide who runs *this* tick. May return
                             `running` again (continue), a different
                             process (switch/preempt), or None (idle).

Putting arrival handling, I/O-burst progression, completion/response-time
bookkeeping, and metrics entirely in the shared engine — and *only* the
"who runs next" decision in the policy — is what lets six different
scheduling algorithms share one, single, carefully-checked simulation
core instead of six independently-buggy tick loops.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from .process import BurstKind, Process

MAX_TICKS_PER_PROCESS = 100_000  # simulation safety cap, not a real limit


# --------------------------------------------------------------------------
# Results
# --------------------------------------------------------------------------


@dataclass
class ProcessMetrics:
    pid: int
    name: str
    arrival_time: int
    completion_time: int
    turnaround_time: int
    waiting_time: int
    response_time: int
    total_cpu_time: int
    total_io_time: int


@dataclass
class SimulationResult:
    algorithm: str
    gantt: list[tuple[int, int, int, int]]  # (start, end, pid, mlfq_level)
    metrics: list[ProcessMetrics]
    total_ticks: int
    idle_ticks: int
    context_switches: int

    @property
    def avg_waiting(self) -> float:
        return sum(m.waiting_time for m in self.metrics) / len(self.metrics)

    @property
    def avg_turnaround(self) -> float:
        return sum(m.turnaround_time for m in self.metrics) / len(self.metrics)

    @property
    def avg_response(self) -> float:
        return sum(m.response_time for m in self.metrics) / len(self.metrics)

    @property
    def cpu_utilization(self) -> float:
        return (self.total_ticks - self.idle_ticks) / self.total_ticks

    @property
    def throughput(self) -> float:
        return len(self.metrics) / self.total_ticks

    def as_dict(self) -> dict:
        return {
            "algorithm": self.algorithm,
            "gantt": self.gantt,
            "total_ticks": self.total_ticks,
            "idle_ticks": self.idle_ticks,
            "context_switches": self.context_switches,
            "avg_waiting": round(self.avg_waiting, 3),
            "avg_turnaround": round(self.avg_turnaround, 3),
            "avg_response": round(self.avg_response, 3),
            "cpu_utilization": round(self.cpu_utilization, 4),
            "throughput": round(self.throughput, 4),
            "processes": [
                {
                    "pid": m.pid,
                    "name": m.name,
                    "arrival_time": m.arrival_time,
                    "completion_time": m.completion_time,
                    "turnaround_time": m.turnaround_time,
                    "waiting_time": m.waiting_time,
                    "response_time": m.response_time,
                }
                for m in self.metrics
            ],
        }


# --------------------------------------------------------------------------
# Policies
# --------------------------------------------------------------------------


class FCFSPolicy:
    """Non-preemptive: run arrival order, straight through."""

    name = "FCFS"

    def __init__(self) -> None:
        self.queue: deque[Process] = deque()

    def enqueue(self, p: Process, t: int) -> None:
        self.queue.append(p)

    def on_tick_start(self, t: int, running: Process | None) -> None:
        pass

    def select(self, t: int, running: Process | None) -> Process | None:
        if running is not None:
            return running
        return self.queue.popleft() if self.queue else None


class SJFPolicy:
    """Non-preemptive Shortest-Job-First: among ready processes, run
    whichever has the smallest *next CPU burst*, chosen only when the CPU
    is actually free (never interrupts a running process)."""

    name = "SJF"

    def __init__(self) -> None:
        self.ready: list[Process] = []

    def enqueue(self, p: Process, t: int) -> None:
        self.ready.append(p)

    def on_tick_start(self, t: int, running: Process | None) -> None:
        pass

    def select(self, t: int, running: Process | None) -> Process | None:
        if running is not None:
            return running
        if not self.ready:
            return None
        best = min(self.ready, key=lambda p: (p.remaining_in_burst, p.arrival_time, p.pid))
        self.ready.remove(best)
        return best


class SRTFPolicy:
    """Preemptive Shortest-Remaining-Time-First: re-evaluated every tick.
    A newly-ready process with a shorter remaining CPU burst immediately
    takes the CPU from whoever is running."""

    name = "SRTF"

    def __init__(self) -> None:
        self.ready: list[Process] = []

    def enqueue(self, p: Process, t: int) -> None:
        self.ready.append(p)

    def on_tick_start(self, t: int, running: Process | None) -> None:
        pass

    def select(self, t: int, running: Process | None) -> Process | None:
        candidates = list(self.ready)
        if running is not None:
            candidates.append(running)
        if not candidates:
            return None
        best = min(candidates, key=lambda p: (p.remaining_in_burst, p.arrival_time, p.pid))
        if best is running:
            return running
        if best in self.ready:
            self.ready.remove(best)
        if running is not None:
            self.ready.append(running)  # preempted back into the pool
        return best


class RoundRobinPolicy:
    """Preemptive, fixed time quantum. New arrivals for tick `t` are
    enqueued (by the engine) before `select` runs, so a process whose
    quantum just expired is requeued *behind* same-tick arrivals — the
    standard convention that stops a CPU-bound job from looking like it
    "cuts in front of" a process that only just showed up."""

    name = "RoundRobin"

    def __init__(self, quantum: int) -> None:
        if quantum < 1:
            raise ValueError("quantum must be >= 1")
        self.quantum = quantum
        self.queue: deque[Process] = deque()
        self.slice_used = 0

    def enqueue(self, p: Process, t: int) -> None:
        self.queue.append(p)

    def on_tick_start(self, t: int, running: Process | None) -> None:
        pass

    def select(self, t: int, running: Process | None) -> Process | None:
        if running is not None:
            if self.slice_used < self.quantum:
                self.slice_used += 1
                return running
            self.queue.append(running)
            self.slice_used = 0
        if not self.queue:
            return None
        nxt = self.queue.popleft()
        self.slice_used = 1
        return nxt


class PriorityAgingPolicy:
    """Non-preemptive static priority (lower number = more urgent) with
    aging: every `aging_interval` ticks a still-waiting process's dynamic
    priority improves by `aging_rate`, so a low-priority process is
    mathematically guaranteed to eventually out-rank everything else
    waiting — this is what makes starvation impossible, not just unlikely.
    """

    name = "PriorityAging"

    def __init__(self, aging_rate: float = 1.0, aging_interval: int = 10) -> None:
        if aging_interval < 1:
            raise ValueError("aging_interval must be >= 1")  # else `% 0` crashes on the first tick
        self.aging_rate = aging_rate
        self.aging_interval = aging_interval
        self.ready: list[Process] = []
        self._waited: dict[int, int] = {}

    def enqueue(self, p: Process, t: int) -> None:
        p.dynamic_priority = float(p.priority)
        self._waited[p.pid] = 0
        self.ready.append(p)

    def on_tick_start(self, t: int, running: Process | None) -> None:
        for p in self.ready:
            self._waited[p.pid] += 1
            if self._waited[p.pid] % self.aging_interval == 0:
                p.dynamic_priority -= self.aging_rate

    def select(self, t: int, running: Process | None) -> Process | None:
        if running is not None:
            return running
        if not self.ready:
            return None
        best = min(self.ready, key=lambda p: (p.dynamic_priority, p.arrival_time, p.pid))
        self.ready.remove(best)
        return best


class MLFQPolicy:
    """Multi-level feedback queue, OSTEP-style:
      - a process starts at the top queue (level 0);
      - using its *entire* quantum at a level demotes it one level;
      - giving up the CPU for I/O *before* its quantum expires does NOT
        demote it (this is what lets interactive/I/O-bound jobs stay
        responsive);
      - every `boost_interval` ticks, every process in the system —
        queued *and* currently running — is reset to level 0. Without
        this, a steady trickle of short interactive jobs can starve a
        CPU-bound job at the bottom queue forever; Phase 3's adversarial
        review demonstrates exactly that failure with boosting disabled.
    """

    name = "MLFQ"

    def __init__(self, quantums: tuple[int, ...] = (4, 8, 16), boost_interval: int | None = 50):
        if len(quantums) < 1:
            raise ValueError("MLFQ needs at least one level")
        if any(q < 1 for q in quantums):
            raise ValueError(f"every MLFQ quantum must be >= 1, got {quantums}")
        if boost_interval is not None and boost_interval < 1:
            raise ValueError("boost_interval must be None (disabled) or >= 1")
        self.quantums = quantums
        self.boost_interval = boost_interval
        self.queues: list[deque[Process]] = [deque() for _ in quantums]
        self.slice_used = 0

    def enqueue(self, p: Process, t: int) -> None:
        level = min(p.mlfq_level, len(self.queues) - 1)
        p.mlfq_level = level
        self.queues[level].append(p)

    def on_tick_start(self, t: int, running: Process | None) -> None:
        if not self.boost_interval or t == 0 or t % self.boost_interval != 0:
            return
        for lvl in range(1, len(self.queues)):
            while self.queues[lvl]:
                p = self.queues[lvl].popleft()
                p.mlfq_level = 0
                self.queues[0].append(p)
        if running is not None and running.mlfq_level != 0:
            running.mlfq_level = 0
            self.slice_used = 0

    def select(self, t: int, running: Process | None) -> Process | None:
        if running is not None:
            quantum = self.quantums[running.mlfq_level]
            if self.slice_used < quantum:
                self.slice_used += 1
                return running
            new_level = min(running.mlfq_level + 1, len(self.queues) - 1)
            running.mlfq_level = new_level
            self.queues[new_level].append(running)
            self.slice_used = 0
        for q in self.queues:
            if q:
                nxt = q.popleft()
                self.slice_used = 1
                return nxt
        return None


POLICIES = {
    "fcfs": lambda **kw: FCFSPolicy(),
    "sjf": lambda **kw: SJFPolicy(),
    "srtf": lambda **kw: SRTFPolicy(),
    "rr": lambda **kw: RoundRobinPolicy(quantum=kw.get("quantum", 4)),
    "priority": lambda **kw: PriorityAgingPolicy(
        aging_rate=kw.get("aging_rate", 1.0), aging_interval=kw.get("aging_interval", 10)
    ),
    "mlfq": lambda **kw: MLFQPolicy(
        quantums=kw.get("quantums", (4, 8, 16)), boost_interval=kw.get("boost_interval", 50)
    ),
}


# --------------------------------------------------------------------------
# Engine
# --------------------------------------------------------------------------


def simulate(
    processes: list[Process],
    algorithm: str,
    context_switch_cost: int = 0,
    **policy_kwargs,
) -> SimulationResult:
    """Run `processes` (each reset to a pristine state) through the named
    scheduling algorithm and return full metrics + a Gantt trace."""
    if algorithm not in POLICIES:
        raise ValueError(f"unknown algorithm {algorithm!r}; choose from {sorted(POLICIES)}")
    procs = [p.clone() for p in processes]
    if not procs:
        raise ValueError("at least one process is required")
    pids = [p.pid for p in procs]
    if len(set(pids)) != len(pids):
        raise ValueError(f"process pids must be unique, got {pids}")
    if context_switch_cost < 0:
        raise ValueError("context_switch_cost must be >= 0")
    policy = POLICIES[algorithm](**policy_kwargs)

    arrivals_at: dict[int, list[Process]] = {}
    for p in procs:
        arrivals_at.setdefault(p.arrival_time, []).append(p)

    io_waiting: list[Process] = []
    running: Process | None = None
    done_count = 0
    total = len(procs)

    raw_ticks: list[tuple[int, int, int]] = []  # (t, pid, mlfq_level); pid=-1 means idle
    idle_ticks = 0
    context_switches = 0
    # Ticks of context-switch overhead still owed on the *current* running
    # process before it actually starts making progress. Modeled as "the
    # CPU has dispatched to it but isn't yet doing useful work" rather
    # than as a separate no-one-is-running phase — that would require
    # remembering the policy's already-committed choice in a second place
    # (an earlier version of this code did exactly that, discarded the
    # choice when the overhead finished, and lost the process forever).
    overhead_remaining = 0

    t = 0
    max_ticks = MAX_TICKS_PER_PROCESS * total
    while done_count < total:
        if t > max_ticks:
            raise RuntimeError(
                f"simulation exceeded {max_ticks} ticks without all processes finishing "
                "— likely a scheduler bug (a process stuck forever)."
            )

        for p in arrivals_at.get(t, []):
            policy.enqueue(p, t)

        policy.on_tick_start(t, running)
        chosen = policy.select(t, running)

        if chosen is not running and chosen is not None and running is not None:
            context_switches += 1
            if context_switch_cost > 0:
                overhead_remaining = context_switch_cost

        running = chosen
        if running is not None and running.first_run_time is None:
            running.first_run_time = t

        if running is None:
            idle_ticks += 1
            raw_ticks.append((t, -1, 0))
        elif overhead_remaining > 0:
            overhead_remaining -= 1
            idle_ticks += 1
            raw_ticks.append((t, -1, 0))  # paying switch-over cost, no progress yet
        else:
            running.remaining_in_burst -= 1
            raw_ticks.append((t, running.pid, running.mlfq_level))

        for p in io_waiting:
            p.remaining_in_burst -= 1

        if running is not None and running.remaining_in_burst == 0:
            finished = running
            running = None
            finished.burst_index += 1
            if finished.is_finished:
                finished.completion_time = t + 1
                done_count += 1
            else:
                finished.remaining_in_burst = finished.current_burst.length
                io_waiting.append(finished)

        io_waiting, done_count = _drain_finished_io(io_waiting, policy, t, done_count)
        t += 1

    total_ticks = t
    gantt = _compress_gantt(raw_ticks)
    metrics = [_process_metrics(p) for p in sorted(procs, key=lambda p: p.pid)]
    return SimulationResult(
        algorithm=policy.name,
        gantt=gantt,
        metrics=metrics,
        total_ticks=total_ticks,
        idle_ticks=idle_ticks,
        context_switches=context_switches,
    )


def _drain_finished_io(io_waiting, policy, t, done_count):
    still_waiting = []
    for p in io_waiting:
        if p.remaining_in_burst == 0:
            p.burst_index += 1
            if p.is_finished:
                p.completion_time = t + 1
                done_count += 1
            else:
                p.remaining_in_burst = p.current_burst.length
                policy.enqueue(p, t + 1)
        else:
            still_waiting.append(p)
    return still_waiting, done_count


def _compress_gantt(raw_ticks):
    """Turn a per-tick (t, pid, mlfq_level) list into minimal
    (start, end, pid, level) segments — pid=-1 represents idle.

    A segment also breaks on a level change even when the pid doesn't
    change: MLFQ can demote a process and immediately reselect that same
    process (it was the only one ready) — collapsing that into one segment
    would silently hide every demotion from the Gantt trace."""
    segments: list[tuple[int, int, int, int]] = []
    if not raw_ticks:
        return segments
    seg_start, seg_pid, seg_level = raw_ticks[0]
    for (t, pid, level) in raw_ticks[1:]:
        if pid != seg_pid or level != seg_level:
            segments.append((seg_start, t, seg_pid, seg_level))
            seg_start, seg_pid, seg_level = t, pid, level
    segments.append((seg_start, raw_ticks[-1][0] + 1, seg_pid, seg_level))
    return segments


def _process_metrics(p: Process) -> ProcessMetrics:
    assert p.completion_time is not None, f"process {p.pid} never completed"
    assert p.first_run_time is not None, f"process {p.pid} never ran"
    turnaround = p.completion_time - p.arrival_time
    total_cpu = sum(b.length for b in p.bursts if b.kind == BurstKind.CPU)
    total_io = sum(b.length for b in p.bursts if b.kind == BurstKind.IO)
    # "Waiting time" is ready-queue time only: turnaround minus every tick
    # actually spent doing useful work (CPU) or genuinely blocked (I/O).
    waiting = turnaround - total_cpu - total_io
    return ProcessMetrics(
        pid=p.pid,
        name=p.name,
        arrival_time=p.arrival_time,
        completion_time=p.completion_time,
        turnaround_time=turnaround,
        waiting_time=waiting,
        response_time=p.first_run_time - p.arrival_time,
        total_cpu_time=total_cpu,
        total_io_time=total_io,
    )
