"""
DB — main entry point for Strata LSM-tree key-value store.

Public API:
  db = DB.open(path)
  db.put(key: bytes, value: bytes)
  db.get(key: bytes) -> bytes | None
  db.delete(key: bytes)
  db.scan(start=None, end=None) -> Iterator[(key, value)]
  db.write_batch(batch: WriteBatch)
  db.snapshot() -> Snapshot
  db.compact()
  db.info() -> dict
  db.close()

All keys and values are bytes. String helpers are provided in the CLI.
"""

import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

from .batch import WriteBatch
from .compaction import compact_level, needs_compaction, L0_THRESHOLD
from .iterator import DBIterator, MergeIterator
from .manifest import Manifest
from .memtable import MemTable
from .record import Record, RecordType
from .snapshot import Snapshot
from .sstable import SSTableReader, SSTableWriter2
from .wal import WAL


@dataclass
class Options:
    memtable_size: int = 4 * 1024 * 1024   # 4 MB → flush to L0
    bloom_fp_rate: float = 0.01
    max_open_files: int = 64
    auto_compact: bool = True               # compact after each flush


class DB:
    """LSM-tree key-value store."""

    def __init__(self, db_dir: Path, options: Optional[Options] = None):
        self._dir = db_dir
        self._opts = options or Options()
        self._lock = threading.Lock()

        self._dir.mkdir(parents=True, exist_ok=True)

        self._manifest = Manifest(self._dir / "MANIFEST")
        self._memtable = MemTable(self._opts.memtable_size)
        self._imm_memtable: Optional[MemTable] = None  # being flushed
        self._wal: Optional[WAL] = None
        self._wal_path: Optional[Path] = None
        self._seq: int = self._manifest._next_seq
        self._compaction_pointers: Dict[int, int] = {}

        # Cached open SSTable readers (LRU-free simple cache for now)
        self._readers: Dict[str, SSTableReader] = {}

        self._recover()

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    @classmethod
    def open(cls, path, options: Optional[Options] = None) -> "DB":
        return cls(Path(path), options)

    def put(self, key: bytes, value: bytes) -> None:
        if not isinstance(key, bytes):
            raise TypeError(f"key must be bytes, got {type(key).__name__}")
        if not isinstance(value, bytes):
            raise TypeError(f"value must be bytes, got {type(value).__name__}")
        with self._lock:
            self._put_locked(key, value)

    def get(self, key: bytes, snapshot: Optional[Snapshot] = None) -> Optional[bytes]:
        if not isinstance(key, bytes):
            raise TypeError(f"key must be bytes, got {type(key).__name__}")
        max_seq = snapshot.seq if snapshot else 2**63
        with self._lock:
            return self._get_locked(key, max_seq)

    def delete(self, key: bytes) -> None:
        if not isinstance(key, bytes):
            raise TypeError(f"key must be bytes, got {type(key).__name__}")
        with self._lock:
            self._delete_locked(key)

    def scan(self, start: Optional[bytes] = None, end: Optional[bytes] = None,
             snapshot: Optional[Snapshot] = None) -> Iterator[Tuple[bytes, bytes]]:
        """Return an iterator over (key, value) pairs in [start, end)."""
        max_seq = snapshot.seq if snapshot else 2**63
        with self._lock:
            return self._scan_locked(start, end, max_seq)

    def write_batch(self, batch: WriteBatch) -> None:
        """Apply all operations in batch atomically."""
        with self._lock:
            if not batch._ops:
                return
            # Reserve a contiguous block of sequence numbers
            base_seq = self._alloc_seqs(len(batch._ops))
            for i, (rtype, key, value) in enumerate(batch._ops):
                seq = base_seq + i
                if rtype == RecordType.PUT:
                    self._wal_append(seq, RecordType.PUT, key, value)
                    self._memtable.put(key, value, seq)
                else:
                    self._wal_append(seq, RecordType.DELETE, key, b"")
                    self._memtable.delete(key, seq)
            self._maybe_flush_locked()

    def snapshot(self) -> Snapshot:
        """Return a Snapshot pinning the current sequence number."""
        with self._lock:
            return Snapshot(self._seq - 1)

    def compact(self) -> None:
        """Force a compaction pass."""
        with self._lock:
            level = needs_compaction(self._dir, self._manifest)
            if level is None:
                # Force L0 if any files exist there
                if self._manifest.level_file_count(0) > 0:
                    level = 0
                else:
                    return
            compact_level(
                self._dir, self._manifest, level,
                self._compaction_pointers, self._opts.bloom_fp_rate
            )
            self._close_stale_readers()

    def info(self) -> dict:
        """Return level statistics."""
        with self._lock:
            levels = {}
            for level in self._manifest.all_levels():
                files = self._manifest.files_at_level(level)
                total_bytes = sum(
                    (self._dir / f).stat().st_size
                    for f in files
                    if (self._dir / f).exists()
                )
                levels[level] = {
                    "files": len(files),
                    "bytes": total_bytes,
                    "filenames": files,
                }
            return {
                "memtable_size": self._memtable.approximate_size,
                "memtable_entries": len(self._memtable),
                "next_seq": self._seq,
                "levels": levels,
                "db_dir": str(self._dir),
            }

    def close(self) -> None:
        with self._lock:
            if self._wal:
                self._wal.sync()
                self._wal.close()
                self._wal = None
            for r in self._readers.values():
                r.close()
            self._readers.clear()

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _recover(self) -> None:
        """Replay WAL to reconstruct MemTable after a crash."""
        wal_path = self._dir / "wal.log"
        max_seq = self._seq

        for record in WAL.replay(wal_path):
            if record.rtype == RecordType.PUT:
                self._memtable.put(record.key, record.value, record.seq)
            else:
                self._memtable.delete(record.key, record.seq)
            max_seq = max(max_seq, record.seq + 1)

        self._seq = max_seq
        self._manifest._next_seq = max(self._manifest._next_seq, self._seq)

        # Open the WAL for appending
        self._wal_path = wal_path
        self._wal = WAL(wal_path)

    def _alloc_seqs(self, count: int = 1) -> int:
        """Allocate `count` sequence numbers; return the first one."""
        start = self._seq
        self._seq += count
        return start

    def _wal_append(self, seq: int, rtype: RecordType, key: bytes, value: bytes) -> None:
        if self._wal:
            self._wal.append(seq, rtype, key, value)

    def _put_locked(self, key: bytes, value: bytes) -> None:
        seq = self._alloc_seqs()
        self._wal_append(seq, RecordType.PUT, key, value)
        self._memtable.put(key, value, seq)
        self._maybe_flush_locked()

    def _delete_locked(self, key: bytes) -> None:
        seq = self._alloc_seqs()
        self._wal_append(seq, RecordType.DELETE, key, b"")
        self._memtable.delete(key, seq)
        self._maybe_flush_locked()

    def _get_locked(self, key: bytes, max_seq: int) -> Optional[bytes]:
        # 1. Check active MemTable
        result = self._memtable.get(key, max_seq)
        if result is not None:
            value, rtype = result
            return value if rtype == RecordType.PUT else None

        # 2. Check immutable MemTable
        if self._imm_memtable:
            result = self._imm_memtable.get(key, max_seq)
            if result is not None:
                value, rtype = result
                return value if rtype == RecordType.PUT else None

        # 3. Search SSTables level by level
        for level in sorted(self._manifest.all_levels()):
            files = self._manifest.files_at_level(level)
            if level == 0:
                # L0: check all files, newest first (last added = newest)
                for fname in reversed(files):
                    reader = self._get_reader(fname)
                    if reader is None:
                        continue
                    res = reader.get(key, max_seq)
                    if res is not None:
                        value, rtype = res
                        return value if rtype == RecordType.PUT else None
            else:
                # L1+: binary search for the file whose range contains key
                fname = self._find_file_for_key(files, key)
                if fname is None:
                    continue
                reader = self._get_reader(fname)
                if reader is None:
                    continue
                res = reader.get(key, max_seq)
                if res is not None:
                    value, rtype = res
                    return value if rtype == RecordType.PUT else None

        return None

    def _find_file_for_key(self, files: List[str], key: bytes) -> Optional[str]:
        """Binary-search sorted L1+ files for one that might contain key."""
        # L1+ files have non-overlapping ranges sorted by key.
        # We need the file where min_key <= key <= max_key.
        # We use max_key for binary search since that's what we have in the index.
        lo, hi = 0, len(files) - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            reader = self._get_reader(files[mid])
            if reader is None:
                return None
            if reader.max_key is None:
                return None
            if reader.max_key < key:
                lo = mid + 1
            elif reader.min_key is not None and reader.min_key > key:
                hi = mid - 1
            else:
                return files[mid]
        return None

    def _scan_locked(self, start, end, max_seq) -> DBIterator:
        """Build a MergeIterator across all sources and return a DBIterator."""
        iters = []

        # MemTable
        iters.append(self._memtable.scan(start, end, max_seq))

        # Immutable MemTable
        if self._imm_memtable:
            iters.append(self._imm_memtable.scan(start, end, max_seq))

        # SSTables
        for level in sorted(self._manifest.all_levels()):
            files = self._manifest.files_at_level(level)
            for fname in files:
                reader = self._get_reader(fname)
                if reader is None:
                    continue
                iters.append(reader.scan(start, end, max_seq))

        return DBIterator(MergeIterator(iters))

    def _maybe_flush_locked(self) -> None:
        if not self._memtable.is_full():
            return
        self._flush_memtable_locked()

    def _flush_memtable_locked(self) -> None:
        """Write MemTable to a new L0 SSTable."""
        records = list(self._memtable.iter_all())
        if not records:
            return

        fname = self._manifest.new_sst_filename()
        writer = SSTableWriter2(self._dir / fname, self._opts.bloom_fp_rate)
        for r in records:
            writer.add(r)
        writer.finish()

        self._manifest.add_file(0, fname)
        self._manifest.bump_seq(0)  # persist next_seq

        # Rotate WAL: delete old log first, then open a fresh one
        if self._wal:
            self._wal.sync()
            self._wal.close()
            self._wal = None
        if self._wal_path and self._wal_path.exists():
            self._wal_path.unlink()
        self._wal_path = self._dir / "wal.log"
        self._wal = WAL(self._wal_path)

        # Reset MemTable
        self._memtable = MemTable(self._opts.memtable_size)

        # Maybe compact
        if self._opts.auto_compact:
            level = needs_compaction(self._dir, self._manifest)
            if level is not None:
                compact_level(
                    self._dir, self._manifest, level,
                    self._compaction_pointers, self._opts.bloom_fp_rate
                )
                self._close_stale_readers()

    def _get_reader(self, fname: str) -> Optional[SSTableReader]:
        if fname in self._readers:
            return self._readers[fname]
        p = self._dir / fname
        if not p.exists():
            return None
        try:
            reader = SSTableReader(p)
            self._readers[fname] = reader
            return reader
        except Exception:
            return None

    def _close_stale_readers(self) -> None:
        """Close readers for files no longer in the manifest."""
        live: set = set()
        for level in self._manifest.all_levels():
            live.update(self._manifest.files_at_level(level))
        stale = [f for f in list(self._readers) if f not in live]
        for f in stale:
            self._readers[f].close()
            del self._readers[f]
