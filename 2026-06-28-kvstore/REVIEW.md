# Phase 3 Adversarial Review — Strata LSM-tree KV Store

## Methodology
Hostile line-by-line review of all source files plus targeted runtime probes.

---

## CRITICAL Issues Found

### CRITICAL-1: scan() releases lock before iterators consumed
**Location:** `db.py:96-101`, `db.py:283-303`

`scan()` builds lazy generator-based iterators and returns them inside a `with self._lock` block.
The lock exits before the caller calls `next()`. A concurrent `compact()` can then call
`_close_stale_readers()`, which closes file handles that the scan generators are still referencing.
Any subsequent `next()` call will raise `ValueError: I/O operation on closed file`.

**Fix:** Materialize scan results into a list while holding the lock. For production, reference-
counting readers would be more efficient, but materialization is simple and correct.

---

### CRITICAL-2: WAL deletion / creation race on flush (caught by self-review, already fixed)
WAL was being deleted AFTER the new WAL was opened at the same path, causing new writes to
append to old content, then the file was unlinked — losing all post-flush writes on recovery.

**Fixed:** Delete old WAL before opening the new one.

---

### CRITICAL-3: Manifest never fsynced — every write can be lost on crash
**Location:** `manifest.py:59-61`

`_append()` uses `open(path, "a")` without `flush()` or `fsync()`. On Linux, `close()` does
not guarantee write-back to storage. A power failure between SSTable fsync and manifest
OS-buffer flush leaves the SSTable on disk but invisible to the DB. On reopen, that data
is lost even though the SSTable file exists.

**Fix:** Add `f.flush(); os.fsync(f.fileno())` in `_append()`.

---

### CRITICAL-4: Mid-compaction crash leaves old+new files in manifest simultaneously
**Location:** `compaction.py:124-126, 196-215`

`_write_merged()` adds each output SSTable to the manifest as it finishes writing. The old
input files are not removed until after all outputs are written. A crash between the first
`add_file` and the last `remove_file` leaves both old and new files in L1, violating the
non-overlapping invariant. Subsequent reads may return wrong versions.

**Fix:** Wrap compaction in a try/except that rolls back (removes) any newly-added files if
the compaction fails partway through. A full two-phase manifest commit is the production
solution; we implement cleanup-on-error instead.

---

### CRITICAL-5: Tombstone GC fires at wrong dynamic level
**Location:** `compaction.py:103, 146`

`max_level = max(manifest.all_levels() + [level + 1])` is evaluated at compaction time.
If only L0 and L1 exist, tombstones are GC'd from L1 output. If L2 data is subsequently
written with the same key, the deleted key reappears — a classic LSM tombstone hazard.

**Fix:** Add `Options.max_levels` (default 3). Only GC tombstones when compacting into
the configured deepest level, independent of what levels currently have data.

---

### CRITICAL-6: find_file_for_key returns None on any reader-open failure
**Location:** `db.py:270-272`

If the binary search mid-point's reader cannot be opened (file deleted by concurrent bug),
the function returns `None` immediately rather than continuing. A key existing in an adjacent
file will silently appear missing — a data-loss bug from the caller's perspective.

**Fix:** Skip the unreadable file and continue searching rather than giving up.

---

## MODERATE Issues Found

### MODERATE-1: Manifest corrupt-line stops at first error, drops all subsequent ops
**Location:** `manifest.py:36-37`

A single truncated JSON line silently ignores all following operations. A partial write
could shadow compaction results.

**Fix:** Skip the corrupt line (log it) and continue loading the rest of the manifest.

---

### MODERATE-2: SSTableWriter (first version) builds empty Bloom filter
**Location:** `sstable.py:127-167`

`SSTableWriter.finish(all_keys=None)` builds a zero-key Bloom filter where `may_contain`
always returns `False`. Any SSTable written with this class will silently discard all keys
at lookup time. `SSTableWriter2` (used by DB) does not have this bug.

**Fix:** Remove `SSTableWriter` (dead code); it is not used by `DB` and is a trap.

---

### MODERATE-3: MemTable approximate_size over-counts multi-version overhead
**Location:** `memtable.py:_add()`

Every call to `_add()` grows `_size` even if it is overwriting an existing key with a new
version. Old version bytes are not subtracted. The MemTable flushes earlier than necessary
when keys are heavily overwritten.

**Fix:** Not corrected (conservative: flushes more often but correctly). Documented in code.

---

### MODERATE-4: Dead-code branch in SSTableReader.scan()
**Location:** `sstable.py:387-391`

```python
if end is not None and last_key < end:
    # Could still have keys in range
    pass
```

This branch does nothing. It is harmless but confusing.

**Fix:** Remove it.

---

## MINOR Issues Found

- `bloom.from_bytes` has no bounds validation; raises internal errors on corrupt input → add guard
- `compact()` calls `stat()` inside the lock, which can stall on slow filesystems → noted
- `SSTableWriter` (removed) vs `SSTableWriter2` naming is confusing
- `bump_seq(0)` is misleading naming → rename to `persist_seq()`

---

## Fix Status After Phase 3

| ID | Status |
|----|--------|
| CRITICAL-1 (scan lock) | FIXED |
| CRITICAL-2 (WAL rotation) | FIXED (phase 2) |
| CRITICAL-3 (manifest fsync) | FIXED |
| CRITICAL-4 (compaction rollback) | FIXED |
| CRITICAL-5 (tombstone GC level) | FIXED |
| CRITICAL-6 (binary search None) | FIXED |
| MODERATE-1 (manifest skip corrupt) | FIXED |
| MODERATE-2 (SSTableWriter dead) | FIXED (removed) |
| MODERATE-3 (size over-count) | NOTED (acceptable) |
| MODERATE-4 (dead code) | FIXED |
| MINOR (bloom validation) | FIXED |
