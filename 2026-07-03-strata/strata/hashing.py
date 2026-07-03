"""Content-addressed hashing: the framing used to derive object ids.

An object's id is SHA-256 over a self-describing frame:

    "<type> <len>\\0<content bytes>"

This is the same idea Git uses (with SHA-1/SHA-256) — hashing the frame
rather than the raw bytes means a blob, tree, and commit that happen to
contain the same bytes never collide, and the length prefix means the
hash commits to the exact byte count (no truncation ambiguity).
"""

import hashlib

VALID_TYPES = ("blob", "tree", "commit")


def frame(obj_type, content):
    if obj_type not in VALID_TYPES:
        raise ValueError(f"unknown object type: {obj_type!r}")
    if not isinstance(content, (bytes, bytearray)):
        raise TypeError("content must be bytes")
    header = f"{obj_type} {len(content)}\0".encode("ascii")
    return header + bytes(content)


def hash_object(obj_type, content):
    """Return the hex object id for (type, content) without touching disk."""
    return hashlib.sha256(frame(obj_type, content)).hexdigest()


def parse_frame(data):
    """Split raw stored bytes back into (type, content), validating the frame."""
    nul = data.find(b"\0")
    if nul == -1:
        raise ValueError("corrupt object: no header terminator found")
    header = data[:nul].decode("ascii", errors="replace")
    parts = header.split(" ", 1)
    if len(parts) != 2:
        raise ValueError(f"corrupt object: malformed header {header!r}")
    obj_type, len_str = parts
    if obj_type not in VALID_TYPES:
        raise ValueError(f"corrupt object: unknown type {obj_type!r}")
    try:
        length = int(len_str)
    except ValueError:
        raise ValueError(f"corrupt object: non-numeric length {len_str!r}")
    content = data[nul + 1:]
    if len(content) != length:
        raise ValueError(
            f"corrupt object: header declares {length} bytes, found {len(content)}"
        )
    return obj_type, content
