"""Git-compatible object model: blobs, trees, commits.

Every object is encoded in exactly the byte format real Git uses
(`<type> <size>\\0<payload>`, SHA-1 addressed, zlib-deflated on disk) so
that hashes produced here are byte-identical to `git hash-object` /
`git mktree` / `git commit-tree` given the same inputs. That equivalence
is what the test suite checks — it is the whole point of building this
on the real object format instead of inventing a simpler one.
"""

from __future__ import annotations

import hashlib
import zlib
import os
import stat as statmod
from dataclasses import dataclass, field
from typing import Optional

MODE_FILE = "100644"
MODE_EXEC = "100755"
MODE_DIR = "40000"  # git writes directory entries WITHOUT a leading zero
MODE_SYMLINK = "120000"


def mode_for_path(path: str) -> str:
    st = os.lstat(path)
    if statmod.S_ISLNK(st.st_mode):
        return MODE_SYMLINK
    if st.st_mode & 0o111:
        return MODE_EXEC
    return MODE_FILE


def sha1_hex(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def frame(obj_type: str, payload: bytes) -> bytes:
    """Build the `<type> <len>\\0<payload>` byte stream Git hashes."""
    header = f"{obj_type} {len(payload)}\0".encode("ascii")
    return header + payload


def hash_object_bytes(obj_type: str, payload: bytes) -> tuple[str, bytes]:
    """Return (sha1_hex, raw_store_bytes) for the given object contents."""
    store = frame(obj_type, payload)
    return sha1_hex(store), store


class ObjectStore:
    """Content-addressable store rooted at <repo_dir>/objects."""

    def __init__(self, objects_dir: str):
        self.objects_dir = objects_dir

    def _path(self, sha: str) -> str:
        return os.path.join(self.objects_dir, sha[:2], sha[2:])

    def has(self, sha: str) -> bool:
        return os.path.exists(self._path(sha))

    def write_raw(self, obj_type: str, payload: bytes) -> str:
        sha, store = hash_object_bytes(obj_type, payload)
        path = self._path(sha)
        if not os.path.exists(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            compressed = zlib.compress(store, level=6)
            tmp = path + f".tmp{os.getpid()}"
            with open(tmp, "wb") as f:
                f.write(compressed)
            os.replace(tmp, path)
        return sha

    def read_raw(self, sha: str) -> tuple[str, bytes]:
        """Return (obj_type, payload) for the object with this sha."""
        path = self._path(sha)
        if not os.path.exists(path):
            raise KeyError(f"object not found: {sha}")
        with open(path, "rb") as f:
            store = zlib.decompress(f.read())
        header, _, payload = store.partition(b"\0")
        obj_type, _, _size = header.partition(b" ")
        return obj_type.decode("ascii"), payload

    # -- typed helpers -----------------------------------------------

    def write_blob(self, data: bytes) -> str:
        return self.write_raw("blob", data)

    def read_blob(self, sha: str) -> bytes:
        obj_type, payload = self.read_raw(sha)
        if obj_type != "blob":
            raise ValueError(f"{sha} is not a blob (is {obj_type})")
        return payload

    def write_tree(self, entries: list["TreeEntry"]) -> str:
        return self.write_raw("tree", encode_tree(entries))

    def read_tree(self, sha: str) -> list["TreeEntry"]:
        obj_type, payload = self.read_raw(sha)
        if obj_type != "tree":
            raise ValueError(f"{sha} is not a tree (is {obj_type})")
        return decode_tree(payload)

    def write_commit(self, commit: "Commit") -> str:
        return self.write_raw("commit", commit.encode())

    def read_commit(self, sha: str) -> "Commit":
        obj_type, payload = self.read_raw(sha)
        if obj_type != "commit":
            raise ValueError(f"{sha} is not a commit (is {obj_type})")
        return Commit.decode(payload)


@dataclass(order=False)
class TreeEntry:
    mode: str
    name: str
    sha: str  # hex

    def sort_key(self) -> bytes:
        # Git compares tree entries as raw bytes, but a directory's name
        # sorts as if it had a trailing '/' — otherwise "a" < "a.txt" would
        # disagree with "a/" < "a.txt" once the directory's *contents* are
        # considered. This is the well-known base_name_compare rule.
        name_bytes = self.name.encode("utf-8")
        if self.mode == MODE_DIR:
            return name_bytes + b"/"
        return name_bytes


def encode_tree(entries: list[TreeEntry]) -> bytes:
    ordered = sorted(entries, key=lambda e: e.sort_key())
    out = bytearray()
    for e in ordered:
        out += f"{e.mode} {e.name}".encode("utf-8")
        out += b"\0"
        out += bytes.fromhex(e.sha)
    return bytes(out)


def decode_tree(payload: bytes) -> list[TreeEntry]:
    entries = []
    i = 0
    n = len(payload)
    while i < n:
        sp = payload.index(b" ", i)
        mode = payload[i:sp].decode("ascii")
        nul = payload.index(b"\0", sp + 1)
        name = payload[sp + 1:nul].decode("utf-8")
        sha_bytes = payload[nul + 1:nul + 21]
        sha = sha_bytes.hex()
        entries.append(TreeEntry(mode=mode, name=name, sha=sha))
        i = nul + 21
    return entries


@dataclass
class Commit:
    tree: str
    parents: list[str] = field(default_factory=list)
    author_name: str = "Palimpsest"
    author_email: str = "palimpsest@local"
    author_time: int = 0
    author_tz: str = "+0000"
    committer_name: str = "Palimpsest"
    committer_email: str = "palimpsest@local"
    committer_time: int = 0
    committer_tz: str = "+0000"
    message: str = ""

    def encode(self) -> bytes:
        lines = [f"tree {self.tree}"]
        for p in self.parents:
            lines.append(f"parent {p}")
        lines.append(
            f"author {self.author_name} <{self.author_email}> "
            f"{self.author_time} {self.author_tz}"
        )
        lines.append(
            f"committer {self.committer_name} <{self.committer_email}> "
            f"{self.committer_time} {self.committer_tz}"
        )
        lines.append("")
        msg = self.message if self.message.endswith("\n") else self.message + "\n"
        header = "\n".join(lines) + "\n" + msg
        return header.encode("utf-8")

    @staticmethod
    def decode(payload: bytes) -> "Commit":
        text = payload.decode("utf-8")
        header, _, message = text.partition("\n\n")
        c = Commit(tree="", message=message)
        for line in header.split("\n"):
            if line.startswith("tree "):
                c.tree = line[len("tree "):]
            elif line.startswith("parent "):
                c.parents.append(line[len("parent "):])
            elif line.startswith("author "):
                rest = line[len("author "):]
                name, email, ts, tz = _parse_identity_line(rest)
                c.author_name, c.author_email = name, email
                c.author_time, c.author_tz = ts, tz
            elif line.startswith("committer "):
                rest = line[len("committer "):]
                name, email, ts, tz = _parse_identity_line(rest)
                c.committer_name, c.committer_email = name, email
                c.committer_time, c.committer_tz = ts, tz
        return c


def _parse_identity_line(rest: str) -> tuple[str, str, int, str]:
    # "Name <email> 1234567890 +0000"
    name, _, tail = rest.partition("<")
    email, _, tail = tail.partition(">")
    ts_tz = tail.strip().split(" ")
    ts, tz = int(ts_tz[0]), ts_tz[1]
    return name.strip(), email, ts, tz
