"""
MANIFEST — tracks which SSTable files exist in each level.

Format (JSON lines, one operation per line):
  {"op": "add",    "level": 0, "file": "sst-00001.sst"}
  {"op": "remove", "level": 0, "file": "sst-00001.sst"}
  {"op": "seq",    "next_seq": 42}

On open, replay all ops in order to reconstruct current state.
Write-and-rename for atomicity on each flush/compaction.
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Set


class Manifest:
    def __init__(self, path: Path):
        self.path = path
        self._levels: Dict[int, List[str]] = {}  # level → ordered list of SST filenames
        self._next_seq: int = 1
        self._next_file_id: int = 1
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        with open(self.path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    op = json.loads(line)
                except json.JSONDecodeError:
                    break  # truncated line
                if op["op"] == "add":
                    lvl = op["level"]
                    fname = op["file"]
                    if lvl not in self._levels:
                        self._levels[lvl] = []
                    if fname not in self._levels[lvl]:
                        self._levels[lvl].append(fname)
                    # Track next file id
                    try:
                        fid = int(fname.split("-")[1].split(".")[0])
                        self._next_file_id = max(self._next_file_id, fid + 1)
                    except (IndexError, ValueError):
                        pass
                elif op["op"] == "remove":
                    lvl = op["level"]
                    fname = op["file"]
                    if lvl in self._levels and fname in self._levels[lvl]:
                        self._levels[lvl].remove(fname)
                elif op["op"] == "seq":
                    self._next_seq = max(self._next_seq, op["next_seq"])

    def _append(self, op: dict) -> None:
        with open(self.path, "a") as f:
            f.write(json.dumps(op) + "\n")

    def next_seq(self) -> int:
        seq = self._next_seq
        self._next_seq += 1
        return seq

    def bump_seq(self, by: int = 1) -> int:
        """Reserve `by` sequence numbers; return the first one."""
        start = self._next_seq
        self._next_seq += by
        self._append({"op": "seq", "next_seq": self._next_seq})
        return start

    def new_sst_filename(self) -> str:
        fid = self._next_file_id
        self._next_file_id += 1
        return f"sst-{fid:05d}.sst"

    def add_file(self, level: int, filename: str) -> None:
        if level not in self._levels:
            self._levels[level] = []
        self._levels[level].append(filename)
        self._append({"op": "add", "level": level, "file": filename})

    def remove_file(self, level: int, filename: str) -> None:
        if level in self._levels and filename in self._levels[level]:
            self._levels[level].remove(filename)
        self._append({"op": "remove", "level": level, "file": filename})

    def files_at_level(self, level: int) -> List[str]:
        return list(self._levels.get(level, []))

    def all_levels(self) -> List[int]:
        return sorted(self._levels.keys())

    def level_file_count(self, level: int) -> int:
        return len(self._levels.get(level, []))
