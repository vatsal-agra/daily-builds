# Reaper — a garbage-collector laboratory (C++17)

## Concept
Reaper is a managed heap with **six interchangeable garbage collectors** living on one flat
byte-addressed arena, plus the tooling to prove they are correct and to compare them:
a differential fuzzer, a heap verifier, a benchmark harness, a tiny mutator scripting language
and a heap-map visualiser. Objects are real bytes in a `uint64_t` arena (2-word header, pointer
slots, data words); references are arena offsets; "freed" memory is poisoned. Moving collectors
really move objects and really rewrite every pointer — so a bug shows up as corrupted data, not
a silent leak.

## Why it's interesting
GC is the part of a runtime nobody sees until it breaks. Every textbook algorithm has a
different trade-off (pause time, fragmentation, throughput, space overhead) and the only way to
*feel* them is to run them against the same workload. The distinctive idea here is the
**oracle**: a never-collecting heap executes the same deterministic mutator; after every N ops a
canonical, address-independent graph hash (BFS from roots) of each collector's heap must equal
the oracle's. That turns "does my GC work?" into a mechanical, fuzzable property.

## Architecture
```
src/heap.hpp       Heap base class: arena, roots (slot API), object layout, stats, alloc driver
src/heap.cpp       canonical graph hash, verifier, poison, stats formatting, shared mark helper
src/nogc.cpp       oracle heap (bump, never collects)
src/marksweep.cpp  free-list mark-sweep, address-ordered coalescing sweep
src/markcompact.cpp Lisp2 sliding compaction (3 passes: forward / update / move)
src/copying.cpp    Cheney semispace copying
src/generational.cpp nursery + compacted old gen, write barrier + remembered set, minor/major
src/incremental.cpp tri-colour incremental mark + lazy sweep, Dijkstra insertion barrier
src/workloads.cpp  deterministic mutators (binary-trees, list-churn, lru-cache, fragmenter, graph-fuzz)
src/script.cpp     mutator DSL interpreter
src/viz.cpp        heap-map HTML report
src/main.cpp       CLI
tests/test.cpp     test suite (unit + differential fuzz + mutation self-checks)
```
Mutators never hold raw refs: they address objects through **root slots** (`newObj(dst,..)`,
`store(objSlot,i,srcSlot)`, `load(dst,objSlot,i)`), which is what lets a moving collector
relocate anything at any allocation point.

## Features
| # | Feature | Status |
|---|---------|--------|
| 1 | Heap core: arena, object layout, root-slot mutator API, poisoning, heap **verifier** (linear walk, pointer-validity, no dangling refs) | **required** |
| 2 | Three classic collectors: **mark-sweep** (free list, coalescing), **mark-compact** (Lisp2), **Cheney copying** | **required** |
| 3 | **Generational** collector: nursery, promotion, write barrier + remembered set, minor/major GC | **required** |
| 4 | **Differential fuzzer + oracle**: canonical graph hash vs never-collecting heap across all collectors, random op streams | **required** |
| 5 | **Incremental tri-colour** collector with Dijkstra barrier & lazy sweep (pause-time story) | stretch |
| 6 | **Benchmark harness**: 5 workloads × all collectors; throughput, pauses (max/p99), fragmentation, CSV | stretch |
| 7 | **Mutator scripting DSL** (loops, expressions, asserts) runnable on any collector | stretch |
| 8 | **Heap-map HTML visualiser**: per-collector before/after-GC heap strips + pause timeline | stretch |
