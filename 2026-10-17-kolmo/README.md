# Kolmo
Lossless compression lab in Go (stdlib only): DEFLATE/gzip, BWT block-sorting, context mixing, rANS.

**Status: Phase 2 (core build) complete.** See [PLAN.md](PLAN.md).

Built so far (all round-trip verified):
- `deflate` — LZ77 hash chains + lazy matching, stored/fixed/dynamic blocks, own inflate, gzip wrapper (interoperates with `gzip(1)` and `compress/flate`)
- `bwt` — suffix-array BWT → MTF → RUNA/RUNB → canonical Huffman
- `cm` — order 0–6 + word + sparse contexts, match model, 3 gated mixers, 2 APMs, arithmetic coder
- `rans0` / `rans1` — static rANS
- KOL1 container with CRC-32, `-m auto` best-of selection, CLI (`compress decompress inspect bench heat gzip gunzip`)

Quick taste (254 KB of English prose): gzip -9 91 987 B · bzip2 -9 77 083 B · Kolmo cm **67 937 B**.

```
cd 2026-10-17-kolmo && go build -o kolmo ./cmd/kolmo && ./kolmo bench ../LEDGER.md
```
