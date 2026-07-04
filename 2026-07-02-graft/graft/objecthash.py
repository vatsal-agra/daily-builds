"""Content-addressable object store: blob/tree/commit encoding, SHA-1 + zlib.

Loose-object format is bit-for-bit compatible with real Git:
    store = b"<type> <len(content)>\\0" + content
    sha1  = sha1(store).hexdigest()
    disk  = zlib.compress(store)   at objects/<sha[:2]>/<sha[2:]>
"""
import hashlib
import os
import zlib

VALID_TYPES = ("blob", "tree", "commit", "tag")


class ObjectError(Exception):
    pass


def _header(obj_type, content):
    return f"{obj_type} {len(content)}\0".encode("utf-8") + content


def hash_bytes(obj_type, content):
    """Return (sha1_hex, store_bytes) without writing anything."""
    if obj_type not in VALID_TYPES:
        raise ObjectError(f"unknown object type {obj_type!r}")
    store = _header(obj_type, content)
    sha1 = hashlib.sha1(store).hexdigest()
    return sha1, store


def object_path(objects_dir, sha1):
    return os.path.join(objects_dir, sha1[:2], sha1[2:])


def write_object(objects_dir, obj_type, content):
    """Hash + zlib-compress + write a loose object. Returns the sha1 hex."""
    sha1, store = hash_bytes(obj_type, content)
    path = object_path(objects_dir, sha1)
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        compressed = zlib.compress(store, level=1)
        tmp = path + f".tmp{os.getpid()}"
        with open(tmp, "wb") as f:
            f.write(compressed)
        os.replace(tmp, path)
    return sha1


def read_object_raw(objects_dir, sha1):
    """Return (obj_type, content_bytes) for a loose object, or raise."""
    path = object_path(objects_dir, sha1)
    if not os.path.exists(path):
        raise ObjectError(f"object {sha1} not found")
    with open(path, "rb") as f:
        store = zlib.decompress(f.read())
    nul = store.index(b"\0")
    header = store[:nul].decode("utf-8")
    obj_type, size_str = header.split(" ", 1)
    content = store[nul + 1:]
    if len(content) != int(size_str):
        raise ObjectError(f"object {sha1} size mismatch (corrupt)")
    return obj_type, content


# ---------------------------------------------------------------- tree ----

class TreeEntry:
    __slots__ = ("mode", "name", "sha1")

    def __init__(self, mode, name, sha1):
        self.mode = mode  # "100644", "100755", "120000", "40000" (dir)
        self.name = name
        self.sha1 = sha1

    def is_dir(self):
        return self.mode == "40000"

    def _sort_key(self):
        # Git sorts tree entries as if directory names had a trailing '/'.
        raw = self.name.encode("utf-8")
        return raw + b"/" if self.is_dir() else raw


def encode_tree(entries):
    """entries: list[TreeEntry] (any order in) -> canonical tree content bytes."""
    ordered = sorted(entries, key=TreeEntry._sort_key)
    out = bytearray()
    seen = set()
    for e in ordered:
        if e.name in seen:
            raise ObjectError(f"duplicate tree entry name {e.name!r}")
        seen.add(e.name)
        out += f"{e.mode} {e.name}".encode("utf-8")
        out += b"\0"
        out += bytes.fromhex(e.sha1)
    return bytes(out)


def decode_tree(content):
    entries = []
    i = 0
    n = len(content)
    while i < n:
        sp = content.index(b" ", i)
        mode = content[i:sp].decode("ascii")
        nul = content.index(b"\0", sp + 1)
        name = content[sp + 1:nul].decode("utf-8")
        sha1 = content[nul + 1:nul + 21].hex()
        entries.append(TreeEntry(mode, name, sha1))
        i = nul + 21
    return entries


# -------------------------------------------------------------- commit ----

def encode_commit(tree_sha, parents, author, committer, message):
    """author/committer: (name, email, unix_ts, tz_str) e.g. ('+0000')."""
    lines = [f"tree {tree_sha}"]
    for p in parents:
        lines.append(f"parent {p}")
    a_name, a_email, a_ts, a_tz = author
    c_name, c_email, c_ts, c_tz = committer
    lines.append(f"author {a_name} <{a_email}> {a_ts} {a_tz}")
    lines.append(f"committer {c_name} <{c_email}> {c_ts} {c_tz}")
    lines.append("")
    lines.append(message)
    text = "\n".join(lines)
    if not text.endswith("\n"):
        text += "\n"
    return text.encode("utf-8")


def decode_commit(content):
    text = content.decode("utf-8")
    header, _, message = text.partition("\n\n")
    tree_sha = None
    parents = []
    author = committer = None
    for line in header.split("\n"):
        if line.startswith("tree "):
            tree_sha = line[len("tree "):]
        elif line.startswith("parent "):
            parents.append(line[len("parent "):])
        elif line.startswith("author "):
            author = line[len("author "):]
        elif line.startswith("committer "):
            committer = line[len("committer "):]
    return {
        "tree": tree_sha,
        "parents": parents,
        "author": author,
        "committer": committer,
        "message": message,
    }
