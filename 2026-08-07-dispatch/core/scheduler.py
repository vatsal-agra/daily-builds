"""Discrete-event CPU scheduling engine: FCFS, SJF, SRTF, Round Robin, Priority, MLFQ.

The simulator is event-driven (jumps the clock between arrivals/completions/quantum
expiries), not a fixed-timestep tick loop, so results are exact integer arithmetic,
not sampling-error-prone. Every algorithm below produces a `Schedule`: a Gantt chart
(list of (pid_or_None, start, end) intervals) plus a `ProcessResult` per process from
which waiting/turnaround/response time are derived (never hand-computed twice).
"""

from __future__ import annotations

from collections import deque

from core.process import Process, ProcessResult, Schedule


class SchedulerError(ValueError):
    pass


def _validate(processes):
    if not processes:
        raise SchedulerError("cannot schedule an empty process list")
    pids = [p.pid for p in processes]
    if len(set(pids)) != len(pids):
        dupes = sorted({p for p in pids if pids.count(p) > 1})
        raise SchedulerError(f"duplicate pid(s) in workload: {dupes}")


def _by_arrival(processes):
    return sorted(processes, key=lambda p: (p.arrival_time, p.pid))


def _append_run(gantt, pid, start, end):
    """Append a CPU-busy interval, merging with the previous interval if contiguous
    and for the same process (keeps the Gantt chart from splitting one RR quantum
    into multiple 1-unit-apart identical segments when nothing else ran between)."""
    if end <= start:
        return
    if gantt and gantt[-1][0] == pid and gantt[-1][2] == start:
        prev_pid, prev_start, _ = gantt[-1]
        gantt[-1] = (prev_pid, prev_start, end)
    else:
        gantt.append((pid, start, end))


def _append_idle(gantt, start, end):
    if end <= start:
        return
    if gantt and gantt[-1][0] is None and gantt[-1][2] == start:
        _, prev_start, _ = gantt[-1]
        gantt[-1] = (None, prev_start, end)
    else:
        gantt.append((None, start, end))


def _count_context_switches(gantt):
    """Count CPU handoffs between two *different* processes (idle gaps don't count
    as a switch by themselves — only process-to-process transitions do)."""
    switches = 0
    last_pid = None
    for pid, start, end in gantt:
        if pid is not None:
            if last_pid is not None and pid != last_pid:
                switches += 1
            last_pid = pid
    return switches


def _finalize(algorithm, gantt, processes, started, completed):
    results = {}
    for p in processes:
        results[p.pid] = ProcessResult(
            pid=p.pid, arrival_time=p.arrival_time, burst_time=p.burst_time,
            priority=p.priority, start_time=started[p.pid], completion_time=completed[p.pid],
        )
    return Schedule(algorithm=algorithm, gantt=gantt, results=results,
                     context_switches=_count_context_switches(gantt))


def _simulate_non_preemptive(processes, key_fn, algorithm):
    """Generic non-preemptive engine: once a process starts, it runs to completion.
    `key_fn(process, remaining_map, now)` picks the next process to run (min key wins)."""
    _validate(processes)
    arrived = _by_arrival(processes)
    n = len(arrived)
    remaining = {p.pid: p.burst_time for p in processes}
    ready = []
    t = 0
    i = 0
    gantt = []
    started = {}
    completed = {}
    while len(completed) < n:
        while i < n and arrived[i].arrival_time <= t:
            ready.append(arrived[i])
            i += 1
        if not ready:
            next_t = arrived[i].arrival_time
            _append_idle(gantt, t, next_t)
            t = next_t
            continue
        proc = min(ready, key=lambda p: key_fn(p, remaining, t))
        ready.remove(proc)
        started.setdefault(proc.pid, t)
        end = t + remaining[proc.pid]
        _append_run(gantt, proc.pid, t, end)
        remaining[proc.pid] = 0
        t = end
        completed[proc.pid] = t
    return _finalize(algorithm, gantt, processes, started, completed)


def _simulate_preemptive(processes, key_fn, algorithm):
    """Generic preemptive-on-arrival engine (SRTF, preemptive priority, aging priority):
    re-evaluates who should hold the CPU at every arrival event."""
    _validate(processes)
    arrived = _by_arrival(processes)
    n = len(arrived)
    remaining = {p.pid: p.burst_time for p in processes}
    ready = []
    t = 0
    i = 0
    gantt = []
    started = {}
    completed = {}
    while len(completed) < n:
        while i < n and arrived[i].arrival_time <= t:
            ready.append(arrived[i])
            i += 1
        if not ready:
            next_t = arrived[i].arrival_time
            _append_idle(gantt, t, next_t)
            t = next_t
            continue
        proc = min(ready, key=lambda p: key_fn(p, remaining, t))
        ready.remove(proc)
        started.setdefault(proc.pid, t)
        next_arrival = arrived[i].arrival_time if i < n else None
        run_until = t + remaining[proc.pid]
        if next_arrival is not None and next_arrival < run_until:
            run_until = next_arrival
        _append_run(gantt, proc.pid, t, run_until)
        remaining[proc.pid] -= (run_until - t)
        t = run_until
        if remaining[proc.pid] == 0:
            completed[proc.pid] = t
        else:
            ready.append(proc)
    return _finalize(algorithm, gantt, processes, started, completed)


# ---------------------------------------------------------------------------
# Algorithms
# ---------------------------------------------------------------------------

def fcfs(processes):
    """First-Come, First-Served: non-preemptive, pure arrival order."""
    return _simulate_non_preemptive(
        processes, key_fn=lambda p, rem, t: (p.arrival_time, p.pid), algorithm="FCFS")


def sjf(processes):
    """Shortest Job First: non-preemptive, shortest total burst first."""
    return _simulate_non_preemptive(
        processes, key_fn=lambda p, rem, t: (p.burst_time, p.arrival_time, p.pid), algorithm="SJF")


def srtf(processes):
    """Shortest Remaining Time First: preemptive SJF — re-picks the globally-shortest
    remaining burst on every new arrival."""
    return _simulate_preemptive(
        processes, key_fn=lambda p, rem, t: (rem[p.pid], p.arrival_time, p.pid), algorithm="SRTF")


def priority_scheduling(processes, preemptive=False):
    """Priority scheduling. Lower `priority` value = higher priority (0 = highest)."""
    key_fn = lambda p, rem, t: (p.priority, p.arrival_time, p.pid)
    if preemptive:
        return _simulate_preemptive(processes, key_fn, algorithm="Priority (preemptive)")
    return _simulate_non_preemptive(processes, key_fn, algorithm="Priority (non-preemptive)")


def round_robin(processes, quantum):
    """Round Robin with a fixed time quantum. Arrivals during a running quantum are
    enqueued *before* the preempted process re-joins the ready queue (standard
    textbook convention), so a process never cuts in front of an arrival that beat
    it back to the queue."""
    if quantum <= 0:
        raise SchedulerError(f"quantum must be positive, got {quantum}")
    _validate(processes)
    arrived = _by_arrival(processes)
    n = len(arrived)
    remaining = {p.pid: p.burst_time for p in processes}
    ready = deque()
    t = 0
    i = 0
    gantt = []
    started = {}
    completed = {}

    def admit_arrivals(now):
        nonlocal i
        while i < n and arrived[i].arrival_time <= now:
            ready.append(arrived[i])
            i += 1

    admit_arrivals(0)
    while len(completed) < n:
        if not ready:
            next_t = arrived[i].arrival_time
            _append_idle(gantt, t, next_t)
            t = next_t
            admit_arrivals(t)
            continue
        proc = ready.popleft()
        started.setdefault(proc.pid, t)
        run_for = min(quantum, remaining[proc.pid])
        run_until = t + run_for
        _append_run(gantt, proc.pid, t, run_until)
        remaining[proc.pid] -= run_for
        t = run_until
        admit_arrivals(t)
        if remaining[proc.pid] == 0:
            completed[proc.pid] = t
        else:
            ready.append(proc)
    return _finalize("Round Robin", gantt, processes, started, completed)


def mlfq(processes, level_quanta=(4, 8, 16), boost_interval=None):
    """Multi-Level Feedback Queue: `len(level_quanta)` ready queues, level 0 highest
    priority; a scheduling decision always dispatches from the lowest non-empty
    level index and runs it to completion or to the end of its quantum (no
    preemption *mid-quantum* by new arrivals, the common simplified/textbook
    convention that keeps demotion unambiguous). A process that reaches the end of
    its quantum without finishing is demoted one level (floor: the last level);
    a process that finishes within its quantum is done. `boost_interval`, if set,
    periodically resets every *waiting* (not currently running) process back to
    level 0 between dispatches — the classic MLFQ starvation fix."""
    if not level_quanta or any(q <= 0 for q in level_quanta):
        raise SchedulerError("level_quanta must be a non-empty list of positive integers")
    _validate(processes)
    arrived = _by_arrival(processes)
    n = len(arrived)
    remaining = {p.pid: p.burst_time for p in processes}
    levels = [deque() for _ in level_quanta]
    t = 0
    i = 0
    gantt = []
    started = {}
    completed = {}
    last_boost = 0

    def admit_arrivals(now):
        nonlocal i
        while i < n and arrived[i].arrival_time <= now:
            levels[0].append(arrived[i])
            i += 1

    def do_boost(now):
        nonlocal last_boost
        if boost_interval is None:
            return
        while now - last_boost >= boost_interval:
            for lvl in range(1, len(levels)):
                while levels[lvl]:
                    levels[0].append(levels[lvl].popleft())
            last_boost += boost_interval

    admit_arrivals(0)
    while len(completed) < n:
        do_boost(t)
        active_levels = [lvl for lvl in range(len(levels)) if levels[lvl]]
        if not active_levels:
            next_t = arrived[i].arrival_time
            if boost_interval is not None:
                next_t = min(next_t, last_boost + boost_interval)
            _append_idle(gantt, t, next_t)
            t = next_t
            admit_arrivals(t)
            continue
        lvl = active_levels[0]
        proc = levels[lvl].popleft()
        started.setdefault(proc.pid, t)
        quantum = level_quanta[lvl]
        run_for = min(quantum, remaining[proc.pid])
        run_until = t + run_for
        _append_run(gantt, proc.pid, t, run_until)
        remaining[proc.pid] -= run_for
        t = run_until
        admit_arrivals(t)
        if remaining[proc.pid] == 0:
            completed[proc.pid] = t
        else:
            # only reaches here by exhausting its quantum (run_for == quantum,
            # since run_for < quantum would have meant remaining hit 0 above) -> demote
            new_lvl = min(lvl + 1, len(levels) - 1)
            levels[new_lvl].append(proc)
    return _finalize(f"MLFQ{list(level_quanta)}", gantt, processes, started, completed)


ALGORITHMS = {
    "fcfs": lambda procs, **kw: fcfs(procs),
    "sjf": lambda procs, **kw: sjf(procs),
    "srtf": lambda procs, **kw: srtf(procs),
    "rr": lambda procs, **kw: round_robin(procs, kw.get("quantum", 4)),
    "priority": lambda procs, **kw: priority_scheduling(procs, preemptive=kw.get("preemptive", False)),
    "mlfq": lambda procs, **kw: mlfq(procs, level_quanta=kw.get("level_quanta", (4, 8, 16)),
                                      boost_interval=kw.get("boost_interval")),
}
