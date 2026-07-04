"""
WriteBatch — accumulate multiple put/delete operations for atomic application.

The batch is applied under a contiguous block of sequence numbers.
"""

from typing import List, Tuple
from .record import RecordType


class WriteBatch:
    """Collect put/delete operations; applied atomically by DB.write_batch()."""

    def __init__(self):
        self._ops: List[Tuple[RecordType, bytes, bytes]] = []

    def put(self, key: bytes, value: bytes) -> "WriteBatch":
        if not isinstance(key, bytes):
            raise TypeError(f"key must be bytes, got {type(key).__name__}")
        if not isinstance(value, bytes):
            raise TypeError(f"value must be bytes, got {type(value).__name__}")
        self._ops.append((RecordType.PUT, key, value))
        return self

    def delete(self, key: bytes) -> "WriteBatch":
        if not isinstance(key, bytes):
            raise TypeError(f"key must be bytes, got {type(key).__name__}")
        self._ops.append((RecordType.DELETE, key, b""))
        return self

    def __len__(self):
        return len(self._ops)

    def __iter__(self):
        return iter(self._ops)

    def clear(self) -> None:
        self._ops.clear()
