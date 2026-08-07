"""Independent tick-based reference simulators used ONLY by the test suite to
cross-check core/scheduler.py's event-driven engine. Deliberately re-derived
from the algorithm definitions rather than by reading scheduler.py, and
deliberately much simpler/slower (1 time unit at a time) so a bug shared
between "the fast engine" and "the oracle" is unlikely -- they don't share
any code.
"""
from collections import deque


def tick_oracle(processes, policy):
    """policy in {'fcfs','sjf','srtf','priority','priority_p'}."""
    remaining = {p.pid: p.burst_time for p in processes}
    arrival = {p.pid: p.arrival_time for p in processes}
    priority = {p.pid: p.priority for p in processes}
    burst = {p.pid: p.burst_time for p in processes}
    started = {}
    completed = {}
    t = 0
    n = len(processes)
    current = None
    max_t = sum(remaining.values()) + max(arrival.values()) + 10

    def arrived_by(now):
        return [p for p in processes if p.arrival_time <= now and remaining[p.pid] > 0]

    while len(completed) < n and t < max_t:
        avail = arrived_by(t)
        if not avail:
            t += 1
            current = None
            continue
        if policy == "fcfs":
            proc = min(avail, key=lambda p: (arrival[p.pid], p.pid))
        elif policy == "sjf":
            proc = min(avail, key=lambda p: (burst[p.pid], arrival[p.pid], p.pid)) if current is None else current
        elif policy == "srtf":
            proc = min(avail, key=lambda p: (remaining[p.pid], arrival[p.pid], p.pid))
        elif policy == "priority":
            proc = min(avail, key=lambda p: (priority[p.pid], arrival[p.pid], p.pid)) if current is None else current
        elif policy == "priority_p":
            proc = min(avail, key=lambda p: (priority[p.pid], arrival[p.pid], p.pid))
        else:
            raise ValueError(policy)
        current = proc
        if proc.pid not in started:
            started[proc.pid] = t
        remaining[proc.pid] -= 1
        t += 1
        if remaining[proc.pid] == 0:
            completed[proc.pid] = t
            current = None
    return started, completed


def rr_oracle(processes, quantum):
    remaining = {p.pid: p.burst_time for p in processes}
    started = {}
    completed = {}
    t = 0
    n = len(processes)
    arrived_sorted = sorted(processes, key=lambda p: (p.arrival_time, p.pid))
    i = 0
    q = deque()

    def admit(now):
        nonlocal i
        while i < n and arrived_sorted[i].arrival_time <= now:
            q.append(arrived_sorted[i])
            i += 1

    admit(0)
    while len(completed) < n:
        if not q:
            t = arrived_sorted[i].arrival_time
            admit(t)
            continue
        proc = q.popleft()
        started.setdefault(proc.pid, t)
        run = min(quantum, remaining[proc.pid])
        for _ in range(run):
            t += 1
            admit(t)
        remaining[proc.pid] -= run
        if remaining[proc.pid] == 0:
            completed[proc.pid] = t
        else:
            q.append(proc)
    return started, completed
