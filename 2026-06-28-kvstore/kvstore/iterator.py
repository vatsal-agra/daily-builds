"""
Iterator protocol for Strata.

MergeIterator merges multiple sorted iterators (MemTable + SSTables) into
a single key-ordered stream. It handles:
  - Deduplication: when the same key appears in multiple sources, the one
    with the highest sequence number wins.
  - Tombstone propagation: tombstones are yielded to allow callers to skip
    deleted keys.

Uses a min-heap over the current front element of each iterator.
"""

import heapq
from typing import Iterator, List, Optional, Tuple

from .record import Record, RecordType


class _HeapEntry:
    """Wrapper for heap ordering: (key, ~seq, source_idx)."""
    __slots__ = ("record", "idx")

    def __init__(self, record: Record, idx: int):
        self.record = record
        self.idx = idx

    def __lt__(self, other: "_HeapEntry") -> bool:
        # Primary sort: key ascending
        if self.record.key != other.record.key:
            return self.record.key < other.record.key
        # Secondary sort: seq descending (newer first)
        if self.record.seq != other.record.seq:
            return self.record.seq > other.record.seq
        # Tertiary: source index ascending (MemTable = index 0 = highest priority)
        return self.idx < other.idx


class MergeIterator:
    """
    Merges multiple sorted Record iterators, yielding deduplicated records
    in key order. For duplicate keys, the entry with the highest seq wins.
    Tombstones are included in output (caller decides whether to surface them).
    """

    def __init__(self, iters: List[Iterator[Record]]):
        self._iters = iters
        self._heap: List[_HeapEntry] = []
        self._last_key: Optional[bytes] = None

        # Prime the heap with first element of each iterator
        for i, it in enumerate(self._iters):
            self._advance(i, it)

    def _advance(self, idx: int, it: Iterator[Record]) -> None:
        try:
            record = next(it)
            heapq.heappush(self._heap, _HeapEntry(record, idx))
        except StopIteration:
            pass

    def __iter__(self) -> "MergeIterator":
        return self

    def __next__(self) -> Record:
        while self._heap:
            entry = heapq.heappop(self._heap)
            record = entry.record
            idx = entry.idx

            # Advance this iterator
            self._advance(idx, self._iters[idx])

            # Skip duplicate keys (keep only the first/highest-seq version)
            if self._last_key is not None and record.key == self._last_key:
                continue

            self._last_key = record.key
            return record

        raise StopIteration


class DBIterator:
    """
    Public iterator interface for DB.scan().
    Wraps MergeIterator and filters tombstones.
    """

    def __init__(self, merge_iter: MergeIterator):
        self._inner = merge_iter

    def __iter__(self) -> "DBIterator":
        return self

    def __next__(self) -> Tuple[bytes, bytes]:
        """Yield (key, value) pairs, skipping tombstones."""
        while True:
            record = next(self._inner)  # raises StopIteration when done
            if record.rtype == RecordType.PUT:
                return record.key, record.value
            # It's a tombstone — skip it
