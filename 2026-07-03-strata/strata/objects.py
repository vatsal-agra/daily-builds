"""Blob / Tree / Commit: the three object kinds, and their (de)serialization.

Encodings are intentionally simple, deterministic text/binary formats
(not pickle, not JSON) so that identical logical content always
produces identical bytes -> identical hash, and so a human can `xxd`
an object and read it.
"""

from dataclasses import dataclass, field

MODE_FILE = "100644"
MODE_EXEC = "100755"
MODE_DIR = "40000"


class InvalidObject(Exception):
    pass


# ---------------------------------------------------------------- Blob ----

def blob_content(data):
    """A blob's stored content *is* the raw file bytes — identity mapping."""
    return bytes(data)


# ---------------------------------------------------------------- Tree ----

@dataclass(frozen=True)
class TreeEntry:
    mode: str
    name: str
    object_id: str
    kind: str  # "blob" or "tree"


def _validate_entry_name(name):
    """A tree entry name must be a single path segment: reject path
    separators and `.`/`..`, which could otherwise let a crafted or
    corrupted tree object escape the working directory root when its
    path gets joined onto disk during checkout."""
    if not name or name in (".", "..") or "/" in name or "\\" in name:
        raise InvalidObject(f"illegal tree entry name {name!r}")
    if "\t" in name or "\n" in name or "\0" in name:
        raise InvalidObject(f"illegal character in tree entry name {name!r}")


def encode_tree(entries):
    """entries: iterable of TreeEntry. Serialized sorted by name for determinism."""
    for e in entries:
        _validate_entry_name(e.name)
    lines = []
    for e in sorted(entries, key=lambda e: e.name):
        lines.append(f"{e.mode} {e.kind} {e.object_id}\t{e.name}\n")
    return "".join(lines).encode("utf-8")


def decode_tree(content):
    text = content.decode("utf-8")
    entries = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if not line:
            continue
        try:
            meta, name = line.split("\t", 1)
            mode, kind, object_id = meta.split(" ")
        except ValueError:
            raise InvalidObject(f"malformed tree entry on line {lineno}: {line!r}")
        if kind not in ("blob", "tree"):
            raise InvalidObject(f"unknown tree entry kind {kind!r} on line {lineno}")
        if len(object_id) != 64:
            raise InvalidObject(f"malformed object id on line {lineno}: {object_id!r}")
        _validate_entry_name(name)
        entries.append(TreeEntry(mode=mode, name=name, object_id=object_id, kind=kind))
    return entries


# -------------------------------------------------------------- Commit ----

@dataclass(frozen=True)
class Commit:
    tree: str
    parents: tuple
    author: str
    timestamp: int
    message: str


def encode_commit(commit):
    lines = [f"tree {commit.tree}\n"]
    for p in commit.parents:
        lines.append(f"parent {p}\n")
    lines.append(f"author {commit.author} {commit.timestamp}\n")
    lines.append("\n")
    lines.append(commit.message)
    if not commit.message.endswith("\n"):
        lines.append("\n")
    return "".join(lines).encode("utf-8")


def decode_commit(content):
    text = content.decode("utf-8")
    if "\n\n" in text:
        header, message = text.split("\n\n", 1)
    else:
        header, message = text, ""
    tree = None
    parents = []
    author = None
    timestamp = None
    for line in header.splitlines():
        if line.startswith("tree "):
            tree = line[len("tree "):].strip()
        elif line.startswith("parent "):
            parents.append(line[len("parent "):].strip())
        elif line.startswith("author "):
            rest = line[len("author "):]
            name_part, _, ts_part = rest.rpartition(" ")
            author = name_part
            try:
                timestamp = int(ts_part)
            except ValueError:
                raise InvalidObject(f"malformed commit timestamp: {ts_part!r}")
    if tree is None or author is None or timestamp is None:
        raise InvalidObject("malformed commit: missing tree/author/timestamp header")
    return Commit(tree=tree, parents=tuple(parents), author=author,
                  timestamp=timestamp, message=message)
