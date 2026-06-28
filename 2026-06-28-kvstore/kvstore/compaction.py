"""
Compaction — merges SSTables to maintain the LSM tree invariant.

Leveled compaction strategy (LevelDB-style):
  L0: files can have overlapping key ranges; compact when ≥ L0_THRESHOLD files.
  L1+: non-overlapping sorted files per level; compact when total size > budget.

L0 → L1 compaction:
  Merge ALL L0 files + any overlapping L1 files into new sorted L1 SSTables.

LN → LN+1 compaction (N ≥ 1):
  Pick the L-N file that was least-recently compacted (round-robin).
  Find all LN+1 files whose range overlaps this file.
  Merge-sort; output new LN+1 SSTables. Delete old files.

Tombstone GC: at the deepest level, tombstones can be dropped entirely
(no older data can exist below them).
"""

import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .record import Record, RecordType
from .sstable import SSTableReader, SSTableWriter2
from .iterator import MergeIterator
from .manifest import Manifest

# Level 0 compaction trigger: files
L0_THRESHOLD = 4

# Level size budgets in bytes
LEVEL_SIZE_BUDGETS: Dict[int, int] = {
    1: 10 * 1024 * 1024,    # 10 MB
    2: 100 * 1024 * 1024,   # 100 MB
    3: 1024 * 1024 * 1024,  # 1 GB
}

MAX_SSTABLE_SIZE = 2 * 1024 * 1024  # 2 MB per output SSTable


def _level_size_budget(level: int) -> int:
    return LEVEL_SIZE_BUDGETS.get(level, (10 ** level) * 1024 * 1024)


def _level_size(db_dir: Path, manifest: Manifest, level: int) -> int:
    total = 0
    for fname in manifest.files_at_level(level):
        p = db_dir / fname
        if p.exists():
            total += p.stat().st_size
    return total


def needs_compaction(db_dir: Path, manifest: Manifest) -> Optional[int]:
    """Return the level that needs compaction, or None."""
    if manifest.level_file_count(0) >= L0_THRESHOLD:
        return 0
    for level in manifest.all_levels():
        if level == 0:
            continue
        budget = _level_size_budget(level)
        if _level_size(db_dir, manifest, level) > budget:
            return level
    return None


def _open_readers(db_dir: Path, filenames: List[str]) -> List[SSTableReader]:
    readers = []
    for fname in filenames:
        p = db_dir / fname
        if p.exists():
            readers.append(SSTableReader(p))
    return readers


def _key_range(readers: List[SSTableReader]) -> Tuple[Optional[bytes], Optional[bytes]]:
    """Return (min_key, max_key) across all readers."""
    mins, maxs = [], []
    for r in readers:
        mk = r.min_key
        if mk is not None:
            mins.append(mk)
        if r.max_key is not None:
            maxs.append(r.max_key)
    if not mins:
        return None, None
    return min(mins), max(maxs)


def _write_merged(
    db_dir: Path,
    manifest: Manifest,
    target_level: int,
    records_iter,
    max_level: int,
    bloom_fp_rate: float = 0.01,
) -> List[str]:
    """Write compacted records to new SSTables; return new filenames."""
    new_files: List[str] = []
    writer: Optional[SSTableWriter2] = None
    current_size = 0
    is_deepest = (target_level == max_level)

    def finish_writer():
        if writer is not None:
            writer.finish()

    fname = None
    for record in records_iter:
        # At deepest level, drop tombstones
        if is_deepest and record.rtype == RecordType.DELETE:
            continue

        if writer is None:
            fname = manifest.new_sst_filename()
            writer = SSTableWriter2(db_dir / fname, bloom_fp_rate)

        writer.add(record)
        current_size += 5 + len(record.key) + len(record.value)

        if current_size >= MAX_SSTABLE_SIZE:
            writer.finish()
            new_files.append(fname)
            manifest.add_file(target_level, fname)
            writer = None
            fname = None
            current_size = 0

    if writer is not None and fname is not None:
        writer.finish()
        new_files.append(fname)
        manifest.add_file(target_level, fname)

    return new_files


def compact_level(
    db_dir: Path,
    manifest: Manifest,
    level: int,
    compaction_pointers: Dict[int, int],
    bloom_fp_rate: float = 0.01,
) -> None:
    """Perform one round of compaction for the given level."""
    max_level = max(manifest.all_levels() + [level + 1])

    if level == 0:
        _compact_l0(db_dir, manifest, compaction_pointers, bloom_fp_rate, max_level)
    else:
        _compact_ln(db_dir, manifest, level, compaction_pointers, bloom_fp_rate, max_level)


def _compact_l0(
    db_dir: Path,
    manifest: Manifest,
    compaction_pointers: Dict[int, int],
    bloom_fp_rate: float,
    max_level: int,
) -> None:
    """Merge all L0 files + overlapping L1 files into new L1 SSTables."""
    l0_files = manifest.files_at_level(0)
    if not l0_files:
        return

    l0_readers = _open_readers(db_dir, l0_files)

    # Find key range of all L0 files
    l0_min, l0_max = _key_range(l0_readers)
    if l0_min is None:
        for r in l0_readers:
            r.close()
        return

    # Find overlapping L1 files
    l1_files = manifest.files_at_level(1)
    l1_overlap: List[str] = []
    l1_readers: List[SSTableReader] = []
    for fname in l1_files:
        p = db_dir / fname
        if not p.exists():
            continue
        r = SSTableReader(p)
        if r.overlaps(l0_min, l0_max):
            l1_overlap.append(fname)
            l1_readers.append(r)
        else:
            r.close()

    # Merge-sort all: L0 files (each is a separate source) + L1 overlap
    # L0 files can have overlapping ranges; each is its own iterator.
    # L1 files are non-overlapping; merge them all together.
    all_iters = [r.iter_all() for r in l0_readers] + [r.iter_all() for r in l1_readers]
    merged = MergeIterator(all_iters)

    new_l1_files = _write_merged(
        db_dir, manifest, 1, merged, max_level, bloom_fp_rate
    )

    # Close readers
    for r in l0_readers + l1_readers:
        r.close()

    # Remove old files from manifest + disk
    for fname in l0_files:
        manifest.remove_file(0, fname)
        p = db_dir / fname
        if p.exists():
            p.unlink()

    for fname in l1_overlap:
        manifest.remove_file(1, fname)
        p = db_dir / fname
        if p.exists():
            p.unlink()


def _compact_ln(
    db_dir: Path,
    manifest: Manifest,
    level: int,
    compaction_pointers: Dict[int, int],
    bloom_fp_rate: float,
    max_level: int,
) -> None:
    """Pick one file from level N (round-robin) and compact with overlapping LN+1."""
    ln_files = manifest.files_at_level(level)
    if not ln_files:
        return

    # Round-robin: pick next file
    ptr = compaction_pointers.get(level, 0) % len(ln_files)
    compaction_pointers[level] = (ptr + 1) % max(1, len(ln_files))
    chosen_fname = ln_files[ptr]
    chosen_p = db_dir / chosen_fname
    if not chosen_p.exists():
        return

    chosen_reader = SSTableReader(chosen_p)
    c_min = chosen_reader.min_key
    c_max = chosen_reader.max_key

    if c_min is None:
        chosen_reader.close()
        return

    # Find overlapping LN+1 files
    ln1_files = manifest.files_at_level(level + 1)
    ln1_overlap: List[str] = []
    ln1_readers: List[SSTableReader] = []
    for fname in ln1_files:
        p = db_dir / fname
        if not p.exists():
            continue
        r = SSTableReader(p)
        if r.overlaps(c_min, c_max):
            ln1_overlap.append(fname)
            ln1_readers.append(r)
        else:
            r.close()

    all_iters = [chosen_reader.iter_all()] + [r.iter_all() for r in ln1_readers]
    merged = MergeIterator(all_iters)

    new_files = _write_merged(
        db_dir, manifest, level + 1, merged, max_level, bloom_fp_rate
    )

    chosen_reader.close()
    for r in ln1_readers:
        r.close()

    manifest.remove_file(level, chosen_fname)
    if chosen_p.exists():
        chosen_p.unlink()

    for fname in ln1_overlap:
        manifest.remove_file(level + 1, fname)
        p = db_dir / fname
        if p.exists():
            p.unlink()
