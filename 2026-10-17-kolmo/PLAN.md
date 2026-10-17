# Kolmo — PLAN

## Concept
**Kolmo** is a from-scratch lossless compression laboratory in Go (stdlib only, and even the
stdlib's `compress/*` is used *only* in tests as an independent oracle). It implements three
generations of compressor design behind one self-describing container format:

1. **LZ77 + Huffman** — a real DEFLATE (RFC 1951) / gzip (RFC 1952) encoder *and* decoder.
   Output is readable by `gzip -d`; input from `gzip` is readable by Kolmo.
2. **Block-sorting** — a bzip2-style pipeline: Burrows–Wheeler transform (suffix array by prefix
   doubling with radix sort) → move-to-front → zero-run-length (RUNA/RUNB) → canonical Huffman.
3. **Context mixing** — an lpaq-style bitwise predictor: hashed order-1..6 contexts + a word
   context, adaptive bit-history counters, a gated logistic mixer, SSE/APM stage, driving a
   32-bit binary arithmetic coder. Slow and small — it beats the other two by a wide margin on text.

The container (`KOL1`) stores the method, length and a CRC-32 and `kolmo compress -m auto`
tries every method and keeps the smallest.

## Why it's interesting
Compression is the clearest place where "prediction == understanding": a better model of the data
is literally a smaller file. This project lets you watch that gradient climb from 1977 (LZ77) through
1994 (BWT) to the PAQ lineage, on your own files, with every byte accounted for. Nothing in the
repo so far covers entropy coding.

## Architecture
```
cmd/kolmo/           CLI (compress, decompress, bench, inspect, heat)
internal/bitio/      LSB-first bit writer/reader (DEFLATE order)
internal/crc/        CRC-32 (IEEE), table driven, from scratch
internal/huff/       length-limited canonical Huffman (package-merge), decode tables
internal/deflate/    LZ77 matcher (hash chains, lazy), block writer (stored/fixed/dynamic), inflate, gzip
internal/bwt/        suffix array, BWT/IBWT, MTF, RLE0, block codec
internal/cm/         predictor (contexts, counters, mixer, APM), arithmetic coder, codec
internal/rans/       static order-0 / order-1 rANS codec
internal/container/  KOL1 format, method registry, auto selection
internal/heat/       per-byte cost report (HTML) from the CM model
```

## Features
| # | Feature | Tier |
|---|---------|------|
| 1 | DEFLATE/gzip codec — LZ77 hash-chain + lazy matching, stored/fixed/dynamic blocks, own inflate; gzip-interoperable both directions | **required** |
| 2 | BWT block-sorting codec — suffix array, BWT, MTF, RUNA/RUNB, canonical Huffman, multi-block | **required** |
| 3 | Context-mixing codec — orders 1–6 + word ctx, logistic mixer, APM, binary arithmetic coder | **required** |
| 4 | KOL1 container + CLI — method registry, CRC-32 integrity, `-m auto` best-of selection, corruption detection, `bench` table | **required** |
| 5 | rANS entropy codec (order-0 and order-1, static model) as a fifth method | stretch |
| 6 | `heat` — HTML report colouring every byte of a file by the bits the CM model spent on it | stretch |
| 7 | Compression levels (1–9) for DEFLATE with tunable chain depth / lazy | stretch |
| 8 | BWT multi-table Huffman (≤6 tables, 50-symbol groups, iterative refinement) — added after review finding R11 | stretch |

## Done means
Round-trip fuzzing for every method, interop against `compress/flate` and system `gzip`, corruption
tests, a demo script, and honest benchmark numbers in the README.
