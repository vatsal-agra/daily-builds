# PLAN — LSM-Tree Key-Value Store ("Strata")

## Concept

Strata is a write-optimized key-value store built from the ground up, implementing
the Log-Structured Merge-tree — the data structure at the heart of LevelDB, RocksDB,
Cassandra, HBase, and InfluxDB.

The central insight of an LSM tree: **always write sequentially**. Incoming writes
land in a fast in-memory buffer (MemTable) plus a sequential Write-Ahead Log (WAL).
When the MemTable fills, it is flushed to an immutable Sorted String Table (SSTable)
on disk. Reads check the MemTable first, then cascade through levels of SSTables.
A background compaction process merges SSTables into progressively larger, sorted
levels, reclaiming space from deleted/overwritten entries and maintaining read
performance. This gives **O(1) amortized write throughput** at the cost of
**read amplification** (mitigated by Bloom filters).

## Why It's Interesting

1. **Different trade-off family from PicoSQL** — B+trees are read-optimized
   (O(log N) write). LSM trees flip this: O(1) writes, amplified reads —
   a completely different engineering philosophy.

2. **Deep algorithmic content** — Bloom filters, merge-iterators, CRC integrity,
   binary block encoding, leveled compaction policy, sequence numbers for MVCC.

3. **Production relevance** — Every major NoSQL system uses LSM trees.
   Understanding them at the source level demystifies an enormous design space.

4. **Testable correctness** — We can differential-test the DB against a naive
   Python dict over thousands of operations, and verify every structural invariant
   of the SSTable files.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Client API  →  DB (db.py)                              │
│    get/put/delete/scan/batch/snapshot                   │
├─────────────────────────────────────────────────────────┤
│  MemTable (memtable.py)  │  WAL (wal.py)                │
│  Skip-list sorted map    │  Append-only binary log      │
├─────────────────────────────────────────────────────────┤
│  Level Manager (levels.py)                              │
│    L0: 4 files max before trigger                       │
│    L1: 10 MB max; L2: 100 MB; L3: 1 GB (all sorted)   │
├─────────────────────────────────────────────────────────┤
│  SSTable (sstable.py)                                   │
│    DataBlocks | FilterBlock | IndexBlock | Footer       │
├─────────────────────────────────────────────────────────┤
│  Bloom Filter (bloom.py) — one per SSTable              │
│  Merge Iterator (iterator.py) — cross-level reads       │
│  Compaction (compaction.py) — L0→L1, LN→LN+1           │
└─────────────────────────────────────────────────────────┘
```

### Data Flow

**Write path:**
1. Append (key, value, seqno, PUT) record to WAL
2. Insert into MemTable
3. When MemTable exceeds threshold → freeze as Immutable MemTable
4. Flush Immutable MemTable to L0 SSTable; recycle WAL segment

**Read path:**
1. Check active MemTable
2. Check immutable MemTable (if any)
3. For each level L0..LN:
   - L0: probe *every* file (L0 files can overlap)
   - L1+: binary-search for the one file that could contain the key
   - For each candidate file: check Bloom filter (skip if absent)
   - If Bloom says "maybe": open SSTable, binary-search index, read data block
4. Return first (latest seqno) non-tombstone hit, or NOT_FOUND

**Compaction:**
- L0→L1: merge all L0 files with overlapping L1 range; output sorted L1 SSTables
- LN→LN+1: pick file with oldest compaction pointer; find overlapping files in LN+1;
  merge-sort all; output new LN+1 files; delete old files

## File Formats

### WAL Record
```
[CRC-32: 4B][seq: 8B][type: 1B (0=PUT, 1=DELETE)][klen: 4B][vlen: 4B][key][value]
```

### SSTable Layout
```
[DataBlock 0]     ← sorted (key, value) pairs, block-encoded
[DataBlock 1]
...
[DataBlock N]
[FilterBlock]     ← Bloom filter bytes for all keys in this file
[IndexBlock]      ← one entry per DataBlock: (last_key, offset, size)
[Footer: 32B]     ← filter_offset(8) + filter_size(4) + index_offset(8) + index_size(4) + MAGIC(8)
```

### DataBlock Encoding
```
[entry_count: 4B]
[key_len: 2B][val_len: 2B][type: 1B][key][value]  × entry_count
[crc32: 4B]
```

### IndexBlock Encoding
```
[entry_count: 4B]
[key_len: 2B][offset: 8B][size: 4B][key]  × entry_count
```

## Feature List

### Required (4)

**R1 — MemTable + Write-Ahead Log**
- In-memory sorted map using bisect (keys bytes-ordered)
- WAL: binary append-only log with CRC-32 per record
- Crash recovery: replay WAL on open to reconstruct MemTable
- Tombstones for deletes
- Auto-flush MemTable to L0 when threshold exceeded

**R2 — SSTable Format (Writer + Reader)**
- Binary SSTable format: data blocks, filter block, index block, footer
- Writer: builds and writes a complete SSTable from a sorted iterator
- Reader: point-lookup (index binary search → block decode) + range scan
- CRC-32 integrity check on each data block

**R3 — Bloom Filter per SSTable**
- From-scratch Bloom filter (double-hashing with FNV1a + DJB2 variants)
- Configurable false-positive rate (default 1%)
- Embedded in SSTable FilterBlock
- Skips SSTable during point lookup when key is definitely absent

**R4 — Leveled Compaction**
- L0 trigger: compact when ≥4 files accumulate
- L1+ trigger: compact when level size exceeds budget (10MB, 100MB, …)
- Merge-sort compaction: reads overlapping files, writes new sorted output
- Tombstone GC: drops tombstones at the bottom level with no older data
- Updates MANIFEST after each compaction (which files exist per level)

### Stretch (3)

**S1 — Snapshots (MVCC-lite)**
- Snapshot = a frozen sequence number
- Reads at a snapshot ignore entries with seqno > snapshot.seqno
- `db.snapshot()` returns an opaque Snapshot object; `db.get(key, snap)` reads at it

**S2 — Batch Writes (Atomic)**
- `WriteBatch` accumulates multiple put/delete operations
- Applied atomically to WAL + MemTable under a single seqno range
- All operations in a batch are either all visible or none

**S3 — REPL + Benchmarks**
- Interactive CLI: `get`, `put`, `del`, `scan`, `batch`, `compact`, `info`, `snap`
- Benchmark subcommand: sequential write, random write, sequential read, random read
- `info` shows level stats: files per level, bytes, estimated read amplification
- Throughput reported in ops/sec and MB/sec

## Implementation Stack

- **Language:** Pure Python 3, stdlib only
- **External tools in tests only:** none (differential testing uses a dict oracle)
- **File I/O:** `struct`, `os`, `io`, `pathlib`
- **Hashing:** hand-rolled FNV-1a + DJB2 for Bloom; `binascii.crc32` for WAL/SSTable integrity
- **Sorting:** `bisect` for MemTable
