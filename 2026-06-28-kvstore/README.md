# Strata — LSM-Tree Key-Value Store

> **Status:** Phase 2 complete (core build). All 4 required features implemented and green.

A from-scratch implementation of the **Log-Structured Merge-tree** — the write-optimized
storage engine behind LevelDB, RocksDB, Cassandra, HBase, and InfluxDB.

## What It Is

Strata is a durable, embeddable key-value store that trades **O(1) amortized write cost**
for **read amplification** (mitigated by Bloom filters). Every write lands sequentially in
a Write-Ahead Log and an in-memory MemTable. When the MemTable fills, it flushes to an
immutable Sorted String Table (SSTable) on disk. A background compaction process merges
SSTables into progressively larger levels, eliminating duplicates and reclaiming space from
deleted keys.

## Architecture

```
Client API (put / get / delete / scan / write_batch / snapshot)
    │
    ├── MemTable (in-memory, multi-version, bisect-sorted)
    ├── WAL (append-only binary log with CRC-32 per record)
    │
    └── Level Manager
         ├── L0 (up to 4 overlapping SSTables)
         ├── L1 (≤10 MB, non-overlapping, sorted)
         ├── L2 (≤100 MB)
         └── L3 (≤1 GB)
                │
         SSTables: DataBlocks | FilterBlock (Bloom) | IndexBlock | Footer
```

## Quick Start

```bash
cd 2026-06-28-kvstore

# Interactive REPL
python -m kvstore.cli repl /tmp/mydb

# One-shot operations
python -m kvstore.cli put /tmp/mydb hello world
python -m kvstore.cli get /tmp/mydb hello
python -m kvstore.cli scan /tmp/mydb --start a --end z
python -m kvstore.cli info /tmp/mydb

# Benchmark
python -m kvstore.cli bench /tmp/mydb --n 20000 --mode all

# Run all tests
python -m unittest discover tests/ -v
```

## REPL Commands

```
strata> put KEY VALUE       store a key-value pair
strata> get KEY             retrieve a value
strata> del KEY             delete a key
strata> scan [S] [E]        scan keys in [S, E)
strata> snap                create a read snapshot (returns snap-id)
strata> snapget ID KEY      get KEY at a snapshot
strata> batch               start an atomic write batch
          put KEY VALUE     queue a put
          del KEY           queue a delete
          end               commit the batch
          abort             discard the batch
strata> compact             trigger manual compaction
strata> info                show level statistics
strata> quit                exit
```

## Features Shipped

### Required
- **R1 — MemTable + WAL** — Multi-version in-memory sorted map (supports snapshot reads)
  + CRC-checked append-only log; crash recovery via WAL replay on open; tombstones for deletes
- **R2 — SSTable Format** — Binary Sorted String Tables: DataBlocks (seq-number–preserving),
  FilterBlock (Bloom), IndexBlock (binary-searchable), 32-byte Footer; CRC-32 per block
- **R3 — Bloom Filter** — Per-SSTable Bloom filter (FNV-1a + DJB2 double hashing,
  Kirsch-Mitzenmacher technique); configurable FP rate (default 1%); serializable
- **R4 — Leveled Compaction** — L0→L1 (merge all L0 + overlapping L1), LN→LN+1
  (round-robin file selection); tombstone GC at deepest level; MANIFEST for durability

### Stretch
- **S1 — Snapshots** — `db.snapshot()` pins a sequence number; `db.get(key, snap)` reads
  at that point in time; multi-version MemTable correctly serves historical reads
- **S2 — Atomic Write Batches** — `WriteBatch` applies multiple put/delete operations
  atomically under a contiguous sequence number block
- **S3 — REPL + Benchmarks** — Full interactive REPL with `snap`/`snapget`/`batch`/`compact`
  commands; `bench` subcommand reports ops/sec and MB/sec for all four I/O patterns

## Design Highlights

### Why LSM Beats B+Tree for Writes
A B+tree write does a **random read** (fetch the leaf page) then a **random write** (update
it), costing two IOPS per record. An LSM write is purely sequential: append to WAL
(O(1)) + insert into MemTable (O(log N)). The I/O amplification is amortized across
compaction, which runs in the background and writes sequentially.

### Bloom Filter Math
For N expected items and false-positive rate p:
- Optimal bit count:   `m = -N * ln(p) / ln(2)²`
- Optimal hash count:  `k = (m/N) * ln(2)`
- Two base hashes (FNV-1a + DJB2), k independent hashes via: `h_i = h1 + i*h2`

### Multi-Version Concurrency
The MemTable stores ALL versions of each key in descending sequence-number order. A point
lookup at `max_seq` finds the first version with `seq <= max_seq`. This enables consistent
snapshot reads without any locks on the data path.

### SSTable Binary Layout
```
[DataBlock 0]    ← count(4) + [klen(2) vlen(2) type(1) seq(8) key value]× + crc(4)
[DataBlock 1]
...
[FilterBlock]    ← Bloom filter: k(1) + m(4) + bits
[IndexBlock]     ← count(4) + [klen(2) offset(8) size(4) last_key]×
[Footer: 32B]    ← filter_offset(8) filter_size(4) index_offset(8) index_size(4) MAGIC(8)
```

## Test Suite (72 tests)

| Module | Tests | Coverage |
|--------|-------|----------|
| bloom  | 8     | Correctness, no false negatives, FP rate, serialize roundtrip |
| wal    | 8     | Write/replay, corruption detection, binary keys, large values |
| memtable | 11  | CRUD, sorted scan, MVCC snapshot isolation, tombstones |
| sstable | 13   | Point lookup, range scan, Bloom filter, multi-block, binary keys |
| iterator | 9   | Merge dedup, tombstone filtering, empty iterators |
| db (integration) | 23 | Basic ops, persistence, WAL recovery, batches, snapshots, compaction, 5000-op differential oracle |

## Where a Human Could Take This Next

- **Block cache** — LRU cache of decoded DataBlocks to reduce file I/O on hot reads
- **Compression** — Snappy/LZ4/zstd for DataBlocks (dramatically reduces storage for text data)
- **Write buffer groups** — Allow concurrent MemTable flushes without blocking the write path
- **Column families** — Separate key spaces with independent compaction policies
- **Rate limiting** — Backpressure on writes when L0 is flooded, preventing read amplification spikes
- **Bloom filter partitioning** — Partitioned Bloom filters (like RocksDB) for better cache locality
- **WAL sync modes** — `O_DSYNC`, group commit, async write options for throughput/durability tradeoffs
- **MANIFEST versioning** — Full MANIFEST V2 (LevelDB protocol) for external tooling compatibility
- **Benchmark harness** — db_bench-style workload replay (YCSB, Zipfian, Fill-Random)
- **Merge operators** — Read-modify-write without separate read (like RocksDB's `Merge()`)
