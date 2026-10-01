# Skein
Streaming probabilistic data-structure toolkit in Go (stdlib only) + CLI.

**Status: Phase 2 — core built.** HyperLogLog, Count-Min + SpaceSaving, Bloom + Cuckoo filters, t-digest, binary save/load/merge, and the `skein` CLI (`stats`, `count`, `top`, `quantile`, `member`, `sim`, `dups`, `merge`, `inspect`) work end-to-end. See PLAN.md.

```
go build -o skein ./cmd/skein && ./skein stats -f 1 -v 2 data.tsv
go test ./...
```
