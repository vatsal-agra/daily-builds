"""Named preset workload/reference-string library, backed by the JSON files in this
directory so `dispatch`'s CLI and the test suite load exactly the same data."""

from __future__ import annotations

import json
from pathlib import Path

from core.process import load_workload

WORKLOADS_DIR = Path(__file__).parent

CPU_PRESETS = {
    "textbook_fcfs_sjf": WORKLOADS_DIR / "textbook_fcfs_sjf.json",
    "textbook_srtf": WORKLOADS_DIR / "textbook_srtf.json",
    "textbook_rr": WORKLOADS_DIR / "textbook_rr.json",
    "textbook_priority": WORKLOADS_DIR / "textbook_priority.json",
    "mixed_general": WORKLOADS_DIR / "mixed_general.json",
}


def list_cpu_presets():
    return sorted(CPU_PRESETS)


def load_cpu_preset(name):
    if name not in CPU_PRESETS:
        raise KeyError(f"unknown CPU workload preset {name!r}; choices: {list_cpu_presets()}")
    path = CPU_PRESETS[name]
    raw = json.loads(path.read_text())
    return load_workload(path), raw.get("quantum", 4), raw.get("description", "")


_VM_REFS_PATH = WORKLOADS_DIR / "vm_reference_strings.json"


def list_vm_presets():
    return sorted(json.loads(_VM_REFS_PATH.read_text()))


def load_vm_preset(name):
    data = json.loads(_VM_REFS_PATH.read_text())
    if name not in data:
        raise KeyError(f"unknown VM reference-string preset {name!r}; choices: {sorted(data)}")
    entry = data[name]
    return list(entry["ref_string"]), entry.get("description", "")
