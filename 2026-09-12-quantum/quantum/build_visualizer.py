"""Bakes a fresh simulation run into visualizer/index.html as embedded
JSON — a single self-contained file, openable directly via `file://`,
with zero fetch/CORS dependency on a running server."""
from __future__ import annotations

import json
import os

from .viz_export import export_full_demo

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_PATH = os.path.join(HERE, "..", "visualizer", "template.html")
OUTPUT_PATH = os.path.join(HERE, "..", "visualizer", "index.html")
MARKER = "/*__QUANTUM_DATA__*/"


def build(seed: int = 42, n_processes: int = 8, ref_length: int = 60, output_path: str | None = None) -> str:
    data = export_full_demo(seed=seed, n_processes=n_processes, ref_length=ref_length)
    with open(TEMPLATE_PATH) as f:
        template = f.read()
    if MARKER not in template:
        raise RuntimeError(f"template missing {MARKER} injection point")
    payload = json.dumps(data)
    out = template.replace(MARKER, payload)
    out_path = output_path or OUTPUT_PATH
    with open(out_path, "w") as f:
        f.write(out)
    return out_path


if __name__ == "__main__":
    path = build()
    print(f"wrote {path}")
