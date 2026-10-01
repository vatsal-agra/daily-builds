# Skein
Streaming probabilistic data-structure toolkit in Go (stdlib only) + CLI.

**Status: Phase 3 — adversarial review done (see REVIEW.md); 10 issues found and fixed.** Core sketches + CLI work end-to-end. Stretch features (MinHash/LSH are in; HTML report next) and final docs follow.

```
go build -o skein ./cmd/skein && ./skein stats -f 1 -v 2 data.tsv
go test ./...
```
