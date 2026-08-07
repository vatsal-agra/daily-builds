"""Aggregate scheduling metrics and multi-algorithm comparison."""

from __future__ import annotations

from core import scheduler


def aggregate(schedule) -> dict:
    """System-wide metrics derived from a Schedule's per-process results."""
    results = list(schedule.results.values())
    n = len(results)
    makespan = schedule.makespan()
    busy = schedule.busy_time()
    idle = schedule.idle_time()
    assert busy + idle == makespan, "busy + idle time must equal makespan"
    return {
        "algorithm": schedule.algorithm,
        "n_processes": n,
        "avg_waiting_time": sum(r.waiting_time for r in results) / n,
        "avg_turnaround_time": sum(r.turnaround_time for r in results) / n,
        "avg_response_time": sum(r.response_time for r in results) / n,
        "max_waiting_time": max(r.waiting_time for r in results),
        "cpu_utilization": busy / makespan if makespan else 0.0,
        "throughput": n / makespan if makespan else 0.0,
        "makespan": makespan,
        "context_switches": schedule.context_switches,
    }


def compare(processes, quantum=4, level_quanta=(4, 8, 16), boost_interval=None):
    """Run every CPU-scheduling algorithm over the same workload and return a
    list of aggregate-metric dicts, one per algorithm, in a fixed display order."""
    runs = [
        scheduler.fcfs(processes),
        scheduler.sjf(processes),
        scheduler.srtf(processes),
        scheduler.round_robin(processes, quantum=quantum),
        scheduler.priority_scheduling(processes, preemptive=False),
        scheduler.priority_scheduling(processes, preemptive=True),
        scheduler.mlfq(processes, level_quanta=level_quanta, boost_interval=boost_interval),
    ]
    return [aggregate(s) for s in runs], runs
