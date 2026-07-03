"""The staging area ("index"): path -> (blob hash, mode), persisted as JSON.

Paths are always stored with forward slashes, relative to the repo
root, so the index file is portable across platforms.
"""

import json
import os

from .objects import MODE_FILE


class Index:
    def __init__(self, path):
        self.path = path
        self.entries = {}  # rel_path -> {"hash": ..., "mode": ...}
        if os.path.isfile(path):
            self._load()

    def _load(self):
        with open(self.path, "r", encoding="utf-8") as fh:
            raw = fh.read().strip()
        self.entries = json.loads(raw) if raw else {}

    def save(self):
        tmp = self.path + f".tmp.{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.entries, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, self.path)

    def set(self, rel_path, object_id, mode=MODE_FILE):
        self.entries[rel_path] = {"hash": object_id, "mode": mode}

    def remove(self, rel_path):
        self.entries.pop(rel_path, None)

    def get(self, rel_path):
        return self.entries.get(rel_path)

    def paths(self):
        return set(self.entries.keys())

    def as_dict(self):
        return {p: e["hash"] for p, e in self.entries.items()}
