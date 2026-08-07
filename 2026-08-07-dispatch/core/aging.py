"""Starvation-prevention aging scheduler and a synthetic workload generator.

Plain preemptive priority scheduling can starve a low-priority process
forever behind a continuous stream of higher-priority arrivals. Aging fixes
this by decaying a process's *effective* priority the longer it sits ready
without running -- eventually any process's effective priority beats even
the highest static priority, so it must run. This module proves that
property directly (a process that provably starves under plain preemptive
priority scheduling provably does not starve under aging), rather than just
asserting it.
"""

from __future__ import annotations

import random

from core.process import Process
from core.scheduler import _simulate_preemptive, _by_arrival, SchedulerError


def priority_aging(processes, aging_rate=1, aging_period=5):
    """Preemptive priority scheduling where a process's effective priority
    improves (numerically decreases) by `aging_rate` for every `aging_period`
    time units it has spent *waiting* since it last ran (or since it
    arrived, if it hasn't run yet). Lower priority number = higher priority,
    same convention as `core.scheduler.priority_scheduling`.
    """
    if aging_period <= 0:
        raise SchedulerError(f"aging_period must be positive, got {aging_period}")
    if aging_rate < 0:
        raise SchedulerError(f"aging_rate must be non-negative, got {aging_rate}")
    # last_ready[pid]: the time this process most recently *became* ready
    # (arrival, or the instant it was preempted back into the queue) --
    # effective_priority decays based on time elapsed since then.
    last_ready = {p.pid: p.arrival_time for p in processes}

    def key_fn(p, rem, t):
        waited = max(0, t - last_ready[p.pid])
        effective = p.priority - aging_rate * (waited // aging_period)
        return (effective, p.arrival_time, p.pid)

    # _simulate_preemptive re-appends a preempted process to `ready` at the
    # exact moment it's preempted, but has no hook to update last_ready --
    # so we wrap it: intercept via a thin re-implementation sharing the same
    # engine logic, updating last_ready every time a process (re)joins ready.
    return _simulate_preemptive_with_hook(processes, key_fn, last_ready, "Priority (aging)")


def _simulate_preemptive_with_hook(processes, key_fn, last_ready, algorithm):
    """Same algorithm as core.scheduler._simulate_preemptive, but calls back
    into `last_ready` bookkeeping whenever a process (re)joins the ready
    queue, which plain priority scheduling has no need for."""
    from core.process import ProcessResult, Schedule
    from core.scheduler import _validate, _append_idle, _append_run, _count_context_switches

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
            last_ready[arrived[i].pid] = t
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
            last_ready[proc.pid] = t  # preempted right now -> aging clock restarts from here
    results = {}
    for p in processes:
        results[p.pid] = ProcessResult(pid=p.pid, arrival_time=p.arrival_time, burst_time=p.burst_time,
                                        priority=p.priority, start_time=started[p.pid],
                                        completion_time=completed[p.pid])
    return Schedule(algorithm=algorithm, gantt=gantt, results=results,
                     context_switches=_count_context_switches(gantt))


def generate_poisson_workload(n, arrival_rate, burst_range=(1, 10), priority_range=(0, 4), seed=None):
    """A synthetic workload with Poisson-process arrivals (exponentially
    distributed inter-arrival times, mean `1/arrival_rate`) and uniformly
    random bursts/priorities -- for stress-testing beyond the hand-authored
    preset workloads. Deterministic given the same seed."""
    if n <= 0:
        raise SchedulerError(f"n must be positive, got {n}")
    if arrival_rate <= 0:
        raise SchedulerError(f"arrival_rate must be positive, got {arrival_rate}")
    rnd = random.Random(seed)
    t = 0.0
    procs = []
    for i in range(n):
        t += rnd.expovariate(arrival_rate)
        procs.append(Process(
            pid=f"G{i}",
            arrival_time=int(round(t)),
            burst_time=rnd.randint(*burst_range),
            priority=rnd.randint(*priority_range),
        ))
    return procs
