"""The content-addressable object store: .strata/objects/<2-hex>/<62-hex>.

Objects are immutable once written (same content -> same hash -> same
path, so a second write of identical content is a harmless no-op) and
zlib-deflated on disk. Every read re-hashes the decompressed frame and
compares it against the filename, so silent on-disk corruption (bit
rot, a hand-edited file, a truncated write) is caught instead of
silently returning bad data.
"""

import os
import zlib

from .hashing import frame, hash_object, parse_frame


class ObjectNotFound(KeyError):
    pass


class CorruptObject(Exception):
    pass


class ObjectStore:
    def __init__(self, objects_dir):
        self.objects_dir = objects_dir

    def _path(self, object_id):
        if len(object_id) != 64 or any(c not in "0123456789abcdef" for c in object_id):
            raise ValueError(f"not a valid object id: {object_id!r}")
        return os.path.join(self.objects_dir, object_id[:2], object_id[2:])

    def has(self, object_id):
        try:
            return os.path.isfile(self._path(object_id))
        except ValueError:
            return False

    def write(self, obj_type, content):
        object_id = hash_object(obj_type, content)
        path = self._path(object_id)
        if os.path.isfile(path):
            return object_id  # content-addressed: identical content already stored
        os.makedirs(os.path.dirname(path), exist_ok=True)
        compressed = zlib.compress(frame(obj_type, content), level=6)
        tmp_path = path + f".tmp.{os.getpid()}"
        with open(tmp_path, "wb") as fh:
            fh.write(compressed)
        os.replace(tmp_path, path)  # atomic on POSIX: no readers ever see a partial file
        return object_id

    def read(self, object_id):
        path = self._path(object_id)
        try:
            with open(path, "rb") as fh:
                compressed = fh.read()
        except FileNotFoundError:
            raise ObjectNotFound(object_id)
        try:
            raw = zlib.decompress(compressed)
            obj_type, content = parse_frame(raw)
        except (zlib.error, ValueError) as exc:
            raise CorruptObject(f"object {object_id} is corrupt: {exc}")
        actual_id = hash_object(obj_type, content)
        if actual_id != object_id:
            raise CorruptObject(
                f"object {object_id} failed integrity check (content hashes to {actual_id})"
            )
        return obj_type, content

    def iter_ids(self):
        if not os.path.isdir(self.objects_dir):
            return
        for prefix in sorted(os.listdir(self.objects_dir)):
            prefix_dir = os.path.join(self.objects_dir, prefix)
            if not os.path.isdir(prefix_dir) or len(prefix) != 2:
                continue
            for rest in sorted(os.listdir(prefix_dir)):
                if len(rest) == 62:
                    yield prefix + rest
