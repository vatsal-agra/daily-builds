# Cairn — a garbage-collector laboratory

## Concept
Cairn is a **from-scratch managed heap with five interchangeable precise garbage collectors**
(mark-sweep, Cheney semispace, generational, incremental snapshot-at-the-beginning, sliding
mark-compact) plus a tiny Lisp-flavoured mutator language whose values live *only* in that heap.
Every collector sits behind one `Gc` trait, so the same program can be run under all of them and
compared: the program output and the final reachable object graph must be **identical** under every
collector, while pause times, footprint, throughput and fragmentation differ.

## Why it's interesting
- This repo has compilers, VMs, filesystems, allocators (Quarry is malloc) — but no *tracing GC*.
  Quarry manages raw memory for C; Cairn is what sits underneath a managed language.
- GC bugs are famously invisible until much later ("lost object" under a missing write barrier).
  So the lab ships an independent **oracle**: a canonical-graph snapshot compared across every
  collection, plus structural heap-walk invariants and a tri-colour invariant checker. Turning the
  incremental collector's barrier off makes the oracle catch real corruption — a demo of *why*
  barriers exist.
- Moving collectors force a GC-safe interpreter (explicit root stack, no raw pointers in Rust locals
  across allocation) — the part of GC engineering that actually bites.

## Architecture
```
src/
  heap.rs         Value tagging (63-bit ints / heap addresses), object header, Gc trait, Stats, FreeList
  marksweep.rs    non-moving; size-binned free list; explicit mark stack; coalescing sweep
  semispace.rs    Cheney copying collector, forwarding pointers
  generational.rs bump-allocated nursery + mark-sweep old gen; promotion; remembered set write barrier
  incremental.rs  tri-colour SATB (Yuasa) with allocate-black, paced mark/sweep increments, switchable barrier
  compact.rs      Lisp2 sliding compaction (mark, compute forwarding, update refs, slide)
  verify.rs       canonical graph snapshot, heap walk invariants, differential helpers
  lang.rs         s-expression reader, resolver (slots), AST
  vm.rs           GC-safe tree-walking evaluator over the explicit root stack, builtins
  bench.rs        run a program under all collectors: pauses, MMU, footprint, throughput
  fuzz.rs         random mutator program generator for differential fuzzing
  report.rs       self-contained HTML report (heap-map timeline, pause chart)
  main.rs         CLI: run / bench / fuzz / report / barrier-demo
examples/         .cairn workload programs (binary trees, churn, cycles, cache, fragmentation…)
tests/            integration + property tests
verify.sh         full gate: fmt/clippy-ish build, tests, demos with assertions
```
Object layout: `[header][payload…]`, header = kind | fwd | mark | grey | remembered | age | len.
Kinds: PAIR, VEC, STR (raw bytes, not scanned), FREE. Address 0 is `nil`.

## Features
| # | Feature | Status |
|---|---------|--------|
| 1 | Heap model + **mark-sweep** (binned free list, coalescing) and **Cheney semispace** behind one `Gc` trait | **required** |
| 2 | **Generational** collector: nursery, promotion, remembered-set write barrier, minor/major cycles | **required** |
| 3 | **Incremental SATB** tri-colour collector: deletion barrier, allocate-black, paced mark & sweep steps, barrier kill-switch | **required** |
| 4 | **Cairn mutator language + GC-safe VM** with oracle verification (canonical graph diff, heap walk, torture mode `--torture`) | **required** |
| 5 | **Sliding mark-compact** collector (Lisp2) | stretch |
| 6 | **Bench harness**: pauses, max pause, MMU curve, footprint, fragmentation across all collectors | stretch |
| 7 | **HTML report**: per-collector heap-map timeline + pause chart | stretch |
| 8 | **Differential fuzzer**: random programs must agree across all collectors | stretch |
