"""Runs the full algorithm matrix over one workload and produces a report,
including two automatic correctness checks that double as findings:

  - Belady's Anomaly detection: does FIFO's fault count go *up* when given
    *more* frames, for this reference string?
  - Optimal-minimality: is Optimal's fault count <= every other
    algorithm's, for every frame count tested? (It must be, by the
    definition of "optimal" — if this ever fails, the simulator has a bug,
    not the theory.)
"""
from __future__ import annotations

from dataclasses import dataclass

from .memory import REPLACERS, simulate_memory
from .process import Process
from .scheduler import POLICIES, simulate


@dataclass
class SchedulerComparison:
    results: dict  # algorithm name -> SimulationResult.as_dict()

    def as_dict(self) -> dict:
        return self.results


@dataclass
class MemoryComparison:
    by_frames: dict  # frame_count -> {algorithm: MemoryResult.as_dict()}
    belady_anomaly: dict  # algorithm -> bool (True if faults increased with more frames)
    optimal_is_minimal: bool

    def as_dict(self) -> dict:
        return {
            "by_frames": self.by_frames,
            "belady_anomaly": self.belady_anomaly,
            "optimal_is_minimal": self.optimal_is_minimal,
        }


def compare_schedulers(processes: list[Process], scenarios: dict[str, dict] | None = None) -> SchedulerComparison:
    """`scenarios` maps a label -> {"algorithm": ..., **kwargs}. Defaults
    to one run of every registered algorithm with sane default params."""
    if scenarios is None:
        scenarios = {
            "FCFS": {"algorithm": "fcfs"},
            "SJF": {"algorithm": "sjf"},
            "SRTF": {"algorithm": "srtf"},
            "RoundRobin(q=4)": {"algorithm": "rr", "quantum": 4},
            "PriorityAging": {"algorithm": "priority"},
            "MLFQ": {"algorithm": "mlfq"},
        }
    results = {}
    for label, cfg in scenarios.items():
        cfg = dict(cfg)
        algo = cfg.pop("algorithm")
        results[label] = simulate(processes, algo, **cfg).as_dict()
    return SchedulerComparison(results=results)


def compare_memory(
    reference_string: list[int],
    frame_counts: list[int],
    tlb_capacity: int = 4,
) -> MemoryComparison:
    by_frames: dict[int, dict[str, dict]] = {}
    fault_history: dict[str, list[tuple[int, int]]] = {name: [] for name in REPLACERS}

    for frames in frame_counts:
        by_frames[frames] = {}
        for algo in REPLACERS:
            result = simulate_memory(reference_string, frames, algo, tlb_capacity=tlb_capacity)
            by_frames[frames][algo] = result.as_dict()
            fault_history[algo].append((frames, result.page_faults))

    belady_anomaly = {}
    for algo, history in fault_history.items():
        history.sort()
        anomaly = any(
            history[i][1] > history[i - 1][1] for i in range(1, len(history))
        )
        belady_anomaly[algo] = anomaly

    optimal_is_minimal = True
    for frames in frame_counts:
        opt_faults = by_frames[frames]["optimal"]["page_faults"]
        for algo in REPLACERS:
            if by_frames[frames][algo]["page_faults"] < opt_faults:
                optimal_is_minimal = False

    return MemoryComparison(
        by_frames=by_frames, belady_anomaly=belady_anomaly, optimal_is_minimal=optimal_is_minimal
    )


def brute_force_min_faults(reference_string: list[int], num_frames: int) -> int:
    """Exhaustive ground truth for small inputs: try every possible
    eviction decision at every fault (memoized over (position, frozenset
    of resident pages)) and return the true minimum number of page
    faults achievable by *any* algorithm, online or not.

    Exponential in the number of distinct pages resident at once — only
    safe for small `reference_string` / `num_frames`, which is exactly
    what it's for: an independent oracle to check Belady's MIN against.
    """
    from functools import lru_cache

    n = len(reference_string)

    @lru_cache(maxsize=None)
    def solve(pos: int, resident: frozenset) -> int:
        if pos == n:
            return 0
        page = reference_string[pos]
        if page in resident:
            return solve(pos + 1, resident)
        if len(resident) < num_frames:
            return 1 + solve(pos + 1, resident | {page})
        best = None
        for victim in resident:
            new_resident = frozenset((resident - {victim}) | {page})
            cost = 1 + solve(pos + 1, new_resident)
            if best is None or cost < best:
                best = cost
        return best

    result = solve(0, frozenset())
    solve.cache_clear()
    return result
