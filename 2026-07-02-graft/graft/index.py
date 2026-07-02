"""The staging area: a flat path -> (mode, sha1, size, mtime) table.

Stored as newline-delimited records (not Git's binary index format — Graft's
byte-compatibility promise is scoped to loose *objects*, which are what real
`git cat-file`/`hash-object` can verify; the index is a private implementation
detail of the staging area, same as in real git).
"""
import os


class IndexEntry:
    __slots__ = ("path", "mode", "sha1", "size", "mtime")

    def __init__(self, path, mode, sha1, size, mtime):
        self.path = path
        self.mode = mode
        self.sha1 = sha1
        self.size = size
        self.mtime = mtime


def read_index(index_path):
    """Return dict path -> IndexEntry."""
    entries = {}
    if not os.path.exists(index_path):
        return entries
    with open(index_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            mode, sha1, size, mtime, path = line.split(" ", 4)
            entries[path] = IndexEntry(path, mode, sha1, int(size), float(mtime))
    return entries


def write_index(index_path, entries):
    lines = []
    for path in sorted(entries):
        e = entries[path]
        lines.append(f"{e.mode} {e.sha1} {e.size} {e.mtime} {e.path}")
    tmp = index_path + f".tmp{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
        if lines:
            f.write("\n")
    os.replace(tmp, index_path)
