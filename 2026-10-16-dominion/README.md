# Dominion

An optimizing compiler middle- and back-end built from scratch in Go: **Dom source → SSA IR → optimizer → register allocator → VM**.

**Status: Phase 4 (stretch + polish) complete.** Required features 1-4 and stretch features 5-8 all work
(differential fuzzer, HTML report, tail-recursion elimination + loop unrolling, benchmark table). See
[PLAN.md](PLAN.md) and [REVIEW.md](REVIEW.md); final documentation arrives in Phase 6.

Quick try:

```
go run ./cmd/dom bench examples/*.dom          # cycles at -O0..-O3, every level cross-checked
go run ./cmd/dom report -O3 examples/matmul.dom # open examples/matmul.report.html
go run ./cmd/dom fuzz -n 500                    # differential fuzzer
```
