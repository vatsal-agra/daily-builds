"""
MemTable — in-memory multi-version sorted key-value store.

Stores ALL versions of each key as a (seq, rtype, value) list sorted by
seq DESCENDING (newest first), so snapshot reads can find the appropriate
version via a linear scan.  Unique keys are kept in a sorted list via bisect
for efficient range scans.

Internal structure:
  _versions: dict[bytes, list[(seq, rtype, value)]]  sorted by seq desc
  _keys:     sorted list[bytes]  — unique keys in byte order
"""

import bisect
from typing import Iterator, Optional, Tuple

from .record import Record, RecordType


class MemTable:
    def __init__(self, size_limit: int = 4 * 1024 * 1024):  # 4 MB default
        self.size_limit = size_limit
        self._versions: dict = {}  # key → [(seq, rtype, value), ...]  desc by seq
        self._keys: list = []      # sorted unique keys
        self._size: int = 0

    def put(self, key: bytes, value: bytes, seq: int) -> None:
        self._add(key, seq, RecordType.PUT, value)

    def delete(self, key: bytes, seq: int) -> None:
        self._add(key, seq, RecordType.DELETE, b"")

    def _add(self, key: bytes, seq: int, rtype: RecordType, value: bytes) -> None:
        if key not in self._versions:
            bisect.insort(self._keys, key)
            self._versions[key] = []
        # Insert in descending seq order (newest first)
        vlist = self._versions[key]
        # Fast path: seq is newer than everything (common case)
        if not vlist or seq > vlist[0][0]:
            vlist.insert(0, (seq, rtype, value))
        else:
            # Insert at correct position to keep descending order
            lo, hi = 0, len(vlist)
            while lo < hi:
                mid = (lo + hi) // 2
                if vlist[mid][0] > seq:
                    lo = mid + 1
                else:
                    hi = mid
            vlist.insert(lo, (seq, rtype, value))
        self._size += len(key) + len(value) + 16

    def get(self, key: bytes, max_seq: int = 2**63) -> Optional[Tuple[bytes, RecordType]]:
        """Return (value, rtype) for the latest version with seq <= max_seq, else None."""
        vlist = self._versions.get(key)
        if vlist is None:
            return None
        for seq, rtype, value in vlist:
            if seq <= max_seq:
                return value, rtype
        return None

    def scan(self, start: Optional[bytes] = None, end: Optional[bytes] = None,
             max_seq: int = 2**63) -> Iterator[Record]:
        """Yield the newest visible Record per key in key order within [start, end)."""
        lo = bisect.bisect_left(self._keys, start) if start is not None else 0
        for key in self._keys[lo:]:
            if end is not None and key >= end:
                break
            result = self.get(key, max_seq)
            if result is not None:
                value, rtype = result
                # Find the seq of the chosen version
                for seq, rt, val in self._versions[key]:
                    if seq <= max_seq:
                        yield Record(key, val, seq, rt)
                        break

    def iter_all(self, max_seq: int = 2**63) -> Iterator[Record]:
        """Yield the newest visible Record per key (including tombstones) in key order."""
        for key in self._keys:
            result = self.get(key, max_seq)
            if result is not None:
                value, rtype = result
                for seq, rt, val in self._versions[key]:
                    if seq <= max_seq:
                        yield Record(key, val, seq, rt)
                        break

    def is_full(self) -> bool:
        return self._size >= self.size_limit

    @property
    def approximate_size(self) -> int:
        return self._size

    def __len__(self):
        return len(self._keys)
