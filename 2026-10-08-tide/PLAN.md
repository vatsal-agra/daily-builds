# Tide — a time-series database in Go

## Concept
Tide is a from-scratch, dependency-free time-series database (TSDB): Facebook-Gorilla
bit-level compression of timestamps and floats, a CRC-framed write-ahead log, an
in-memory head that flushes to immutable on-disk blocks, a small query language with
label matchers / rollups / group-by, and an HTTP server with a live SVG dashboard.

## Why it's interesting
Time-series storage is a perfect "small but deep" systems problem: the compression
(delta-of-delta + XOR) shrinks 16-byte samples to ~1-2 bytes, crash recovery has real
subtleties (torn WAL tails, crash between block rename and WAL truncate), and the
query engine needs counter-reset-aware `rate`. Nothing in the ledger covers TSDBs.

## Architecture
```
 line protocol ─► HTTP /write ─► Store.Append ─► WAL (crc frames, fsync) ─► Head (gorilla chunks / series)
                                                       │ flush
                                                       ▼
                                           Block files  b-<minT>-<maxT>.blk  (chunks + index + crc footer)
 query text ─► query.Parse ─► Plan ─► Store.Select (head ∪ blocks, merge+dedupe) ─► bucket/aggregate ─► JSON
 dashboard (embedded HTML+SVG) ◄── HTTP /query, /series, /stats
```
Packages: `gorilla` (codec), `wal`, `store` (head, blocks, compaction, retention),
`query` (lexer/parser/evaluator), `server` (HTTP + UI), `cmd/tide` (serve, gen, query, bench).

## Features
| # | Feature | Status |
|---|---------|--------|
| 1 | Gorilla codec: delta-of-delta timestamps + XOR floats, bit-exact round-trip | **required** |
| 2 | Durable storage: WAL with CRC + torn-tail recovery, head chunks, flush to blocks, reopen | **required** |
| 3 | Query language: label matchers (`= != =~ !~`), per-series funcs (avg/min/max/sum/count/last/rate/increase/pNN), `by()` grouping, cross-series agg, `step`/`range` | **required** |
| 4 | HTTP API (line-protocol ingest, /query, /series, /stats, /flush) + live dashboard with SVG charts | **required** |
| 5 | Compaction (merge + dedupe blocks) and retention (drop expired blocks) | stretch |
| 6 | Alert rules evaluated against queries with threshold + `for` duration, surfaced in API/UI | stretch |
| 7 | Synthetic workload generator + compression benchmark (`tide gen`, `tide bench`) | stretch |
