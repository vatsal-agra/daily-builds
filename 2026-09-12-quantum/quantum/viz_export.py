"""Serializes a full simulation run (scheduling + memory) into the single
JSON blob the visualizer consumes. Every number in it comes from a real
run of the engines in `scheduler.py`/`memory.py` — nothing here is
hand-authored or hardcoded."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from .compare import compare_memory, compare_schedulers
from .process import BurstKind, Process
from .workload import make_belady_anomaly_string, make_processes, make_reference_string


def export_full_demo(
    seed: int = 42,
    n_processes: int = 8,
    ref_length: int = 60,
    frame_counts: tuple[int, ...] = (2, 3, 4, 5, 6),
) -> dict:
    processes = make_processes(n_processes, seed=seed)
    sched_cmp = compare_schedulers(processes)

    process_payload = [
        {
            "pid": p.pid,
            "name": p.name,
            "arrival_time": p.arrival_time,
            "priority": p.priority,
            "bursts": [{"kind": b.kind, "length": b.length} for b in p.bursts],
            "total_cpu_time": p.total_cpu_time,
        }
        for p in processes
    ]

    locality_ref = make_reference_string(ref_length, num_pages=12, seed=seed, working_set_size=4)
    locality_cmp = compare_memory(locality_ref, list(frame_counts))

    belady_ref = make_belady_anomaly_string()
    belady_cmp = compare_memory(belady_ref, [3, 4])

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": seed,
        "scheduler": {
            "processes": process_payload,
            "runs": sched_cmp.as_dict(),
        },
        "memory": {
            "locality": {
                "reference_string": locality_ref,
                "frame_counts": list(frame_counts),
                **locality_cmp.as_dict(),
            },
            "belady_anomaly_demo": {
                "reference_string": belady_ref,
                "frame_counts": [3, 4],
                **belady_cmp.as_dict(),
            },
        },
    }


def export_to_file(path: str, **kwargs) -> dict:
    data = export_full_demo(**kwargs)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    return data
