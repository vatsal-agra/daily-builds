"""
Core record types shared across WAL, MemTable, and SSTable.
"""

from enum import IntEnum


class RecordType(IntEnum):
    PUT = 0
    DELETE = 1


class Record:
    __slots__ = ("key", "value", "seq", "rtype")

    def __init__(self, key: bytes, value: bytes, seq: int, rtype: RecordType):
        self.key = key
        self.value = value
        self.seq = seq
        self.rtype = rtype

    def is_tombstone(self) -> bool:
        return self.rtype == RecordType.DELETE

    def __repr__(self):
        v = self.value[:16].hex() if self.rtype == RecordType.PUT else "(deleted)"
        return f"Record({self.key!r} seq={self.seq} {v})"
