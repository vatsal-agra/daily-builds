# Quarry — plan

## Concept
**Quarry** is a from-scratch general-purpose **memory allocator** (a `malloc` implementation) in C, plus the
tooling around it: a drop-in `LD_PRELOAD` replacement for glibc malloc, a heap-debugging mode, an allocation
**trace recorder**, and a **replay simulator** that runs the same recorded workload against several allocator
designs and compares their memory footprint, fragmentation and speed.

The repository already holds compilers, databases, VCSes, emulators, a terminal and a build system, but nothing
that sits underneath all of them: the allocator. Every one of those programs spends its life calling `malloc`,
and almost nobody has seen what happens behind it.

## Why it is interesting
* Allocator design is a pile of real trade-offs (speed vs. fragmentation vs. returning memory to the OS vs.
  thread scalability) that you only understand once you measure them on real workloads.
* It must be correct in the nastiest environment there is: being injected into `ls`, `python3`, `gcc`, `sort`
  with `LD_PRELOAD`, re-entered from signal-free but fork-heavy, multithreaded programs, before `main` runs.
* A trace → replay → compare loop turns "which allocator is better?" into something you can answer with data
  instead of folklore, including a time-lapse picture of how the heap fragments.

## Architecture
```
src/quarry.h          public C API of the core (q_malloc, q_free, ... q_stats, q_snapshot)
src/quarry_core.c     the allocator: reserved address space, page heap, slab size classes, thread caches
src/quarry_preload.c  libquarry.so: malloc/free/... interposition, debug mode, trace recorder, exit reports
src/qsim.c            replay simulator: trace reader, 5 allocator models, verifier, report + heap-map HTML
src/qgen.c            synthetic workload generator that writes traces in the same format
src/models.c          the comparison allocators (bump, first-fit boundary-tag, buddy)
tests/                API/stress/threads tests, debug-mode negative tests, real-program tests
tools/quarry          wrapper script:  quarry [--debug] [--trace F] [--stats] -- cmd ...
tools/qsym.py         turns "module+0xoff" leak-report frames into file:line using addr2line
Makefile, demo.sh
```
Core design (tcmalloc-flavoured, rewritten from first principles):
* one big `PROT_NONE→RW, MAP_NORESERVE` virtual reservation; ownership of a pointer = an address-range check;
* **page heap**: 4 KiB pages, spans (runs of pages) with a flat *pagemap* (page → span), best-fit free lists,
  split + immediate coalescing with both neighbours, lazy `madvise(MADV_DONTNEED)` scavenging, zero-page
  tracking so `calloc` of fresh/released memory skips `memset`;
* **small objects** (≤ 32 KiB): 40 size classes, slab spans carved lazily, per-class central partial lists,
  per-thread caches with batch refill/flush, spans returned to the page heap when completely free;
* **large objects**: whole spans; `realloc` grows/shrinks in place via neighbouring free spans;
* `memalign`/`posix_memalign`/`aligned_alloc` to any power-of-two alignment.

## Features
| # | Feature | Level |
|---|---------|-------|
| 1 | **Allocator core**: page heap + size-class slabs + thread caches + full malloc API (calloc overflow checks, realloc in place, aligned allocation, usable size) | **required** |
| 2 | **Drop-in `LD_PRELOAD` library** (`libquarry.so`) that runs real programs (fork-safe, thread-exit-safe, early-init-safe) | **required** |
| 3 | **Debug mode**: header + redzones, overflow/underflow/double-free/invalid-free/use-after-free (quarantine + poison) detection, uninitialised-memory fill, leak report grouped by allocation stack | **required** |
| 4 | **Trace recorder + replay simulator**: record any program's allocation stream; replay it against quarry, glibc and three textbook allocators (bump, first-fit, buddy) with per-block integrity verification and a comparison table | **required** |
| 5 | **Workload generator** (`qgen`): web-request bursts, tree churn, FIFO queues, fragmentation adversary, vector growth by realloc, phase changes | stretch |
| 6 | **Heap-map HTML**: time-lapse of page-level heap occupancy plus live-vs-footprint curves for every allocator | stretch |
| 7 | **Runtime statistics** (`QUARRY_STATS=1`): per-class slab utilisation, page-heap breakdown, peak footprint, op counts | stretch |
| 8 | `qsym.py` leak-stack symbolizer using addr2line | stretch |

## Phases
1. PLAN (this file). 2. Core + preload + debug + trace/sim (the 4 required). 3. Adversarial review →
REVIEW.md → fixes. 4. Stretch + polish. 5. Test suite + demo script, green. 6. README + LEDGER.
