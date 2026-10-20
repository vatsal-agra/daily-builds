# Quarry

A from-scratch **memory allocator** (`malloc`) in C — and the tooling that makes an allocator
understandable: an `LD_PRELOAD` drop-in, a heap-debugging mode, an allocation **trace recorder**, and a
**replay simulator** that runs the same recorded workload on quarry, glibc and three textbook allocators and
tells you who wastes the most memory, who is slowest, and whether anyone corrupts your data.

```
make && make test                       # build everything, run 64 checks (≈1 minute)
./demo.sh                               # guided tour
tools/quarry -- ls -la                  # any program, on quarry. Node 22, gcc, python, awk, tar all run fine.
tools/quarry --debug -- ./myprog        # redzones, double/invalid free, use-after-free, leaks with stacks
tools/quarry --trace app.qtr -- ./app   # record every malloc/free/realloc ...
build/qsim compare app.qtr --html r.html  # ... replay on 5 allocators, scorecard + heap-map time-lapse
build/qgen mixed -n 300000 -o w.qtr     # or generate a synthetic workload (web tree queue frag vector mixed)
```
Requires Linux x86-64, gcc, make, Python 3 (tools/tests). The browser-report test uses Node + Playwright if present.

## How the allocator works (`src/quarry_core.c`, ~750 lines)
* One huge `MAP_NORESERVE` virtual reservation (256 GiB, halved until the OS agrees); "is this pointer mine?" is a range check.
* **Page heap**: 4 KiB pages in *spans*, a flat pagemap (page → span), exact-size free lists for 1–255 pages with a bitmap, a TLSF-style two-level index for bigger spans, split + immediate coalescing both ways, lazy `madvise(MADV_DONTNEED)` scavenging, and a per-span "known zero" flag so `calloc` of fresh/released memory never touches it (tested via RSS).
* **Small objects** (≤ 32 KiB): 40 size classes (≤ 12.5 % slab waste), slabs carved lazily, central partial lists, **thread caches** with batch refill/flush, empty slabs returned to the page heap.
* **Large objects**: whole spans; `realloc` grows/shrinks **in place** through neighbouring free pages; aligned allocation to any power of two.
* Fork-safe (atfork handlers), thread-exit-safe (pthread key destructor flushes the cache), safe to initialise lazily from inside `ld.so`.

## Features
| | Feature | Where |
|---|---|---|
| required | **Allocator core** — page heap, slabs, thread caches, full API (`malloc calloc realloc memalign posix_memalign aligned_alloc valloc pvalloc malloc_usable_size mallinfo2 malloc_trim`) | `src/quarry_core.c` |
| required | **LD_PRELOAD drop-in** `build/libquarry.so` | `src/quarry_preload.c` |
| required | **Debug mode** (`QUARRY_DEBUG=1`): 192-byte header + 8-byte front guard + 16-byte tail canary; overflow/underflow with byte counts, double free (with alloc *and* free stacks), invalid free, foreign pointer, use-after-free via 0xDD poison + quarantine ring (default 1024 blocks), 0xCD on fresh memory, `quarry_check_heap()`, exit-time leak report grouped by allocation stack, header-corruption detection | same |
| required | **Trace recorder + replay simulator** — `QUARRY_TRACE=file` (one total order across threads; children write `<file>.<pid>`), `qsim info`, `qsim compare` on quarry / glibc / first-fit / buddy / bump, each in a forked process; every block is fingerprinted and checked on free/realloc, calloc zero-ness and alignment verified, overlaps checked, per-call latency percentiles | `src/qsim.c`, `src/models.c` |
| stretch | **Workload generator** `qgen` (6 workloads, seeded) | `src/qgen.c` |
| stretch | **HTML report**: scorecard, memory-over-time chart (hover, toggle, linked to the map), quarry **heap-map time-lapse** (96 frames, play/scrub/hover), size histogram; light/dark, phone-width safe | `src/report.c`, `src/report_tpl.html` |
| stretch | **Statistics** (`QUARRY_STATS=1`, `tools/quarry --stats`): call counts, footprint/peak, per-class slab utilisation | preload |
| stretch | **`tools/qsym.py`** — resolves leak-report frames to function and file:line via addr2line | `tools/` |

Other environment knobs: `QUARRY_ABORT=0` (report and continue), `QUARRY_QUARANTINE=N`, `QUARRY_LEAKS=0|all`, `QUARRY_LOG=file`.

## Results (300 k-event generated workloads, `qsim compare`, best of 3)
Overhead = peak memory held from the OS ÷ peak live bytes requested; "after free" = memory still held once everything is freed and the allocator is asked to trim.

| workload | quarry | glibc | first-fit | buddy | bump |
|---|---|---|---|---|---|
| mixed — overhead | **1.22×** | 1.38× | 1.42× | 1.66× | 7.17× |
| mixed — after free | **128 KiB** | 64 MiB | 88 MiB | 103 MiB | 443 MiB |
| vector (realloc growth) — overhead | **1.17×** | 1.31× | 1.56× | 1.62× | 38× |
| queue (window swells 15×) — overhead | 1.18× | 1.77× | **1.04×** | 1.49× | 2.41× |
| frag (adversary) — overhead | 1.69× | 1.65× | 1.49× | 2.11× | 1.48× |
| mixed — ns/event | 178–204 | 189–242 | 257–274 | 163–171 | 584–691 |

Honest reading: quarry wins on memory returned to the OS and realloc-heavy loads, is competitive in speed (microbenchmarks: 20 M single-thread ops 0.24 s vs glibc 0.33 s; 8 threads 0.35 s vs 0.59 s), and **loses** to a plain first-fit on the queue workload and does not beat glibc/first-fit on the adversarial fragmentation trace (bump "wins" there only because nothing is ever reused). Numbers vary run to run; `ns/event` includes first-touch page faults.

## Verification
`make test` (= `tests/run_tests.sh`) — **64 checks**, all green: 800 k API assertions (also under ASan+UBSan), 8-thread stress with cross-thread frees (also under ThreadSanitizer), real programs (`ls find sort awk tar|gzip python3 gcc bash`) producing byte-identical output under `LD_PRELOAD`, 22 debug-mode cases incl. false-positive hunts on real programs, trace round-trips (real python3 trace, multi-threaded trace, shell-script children, 6 generated workloads) verified on every allocator, 40 corrupted traces fuzzed through qsim, the HTML report loaded in headless Chromium in light and dark. `REVIEW.md` lists the 15 problems found by attacking the first version, each reproduced, fixed and guarded.

## Limitations
`realloc()` of a pointer quarry doesn't own fails with `EINVAL` (free of one is ignored); without debug mode a double free is caught only if the object is still in this thread's cache or on the shared list; use-after-free is caught when a block leaves quarantine or at exit, not at the access (no guard pages); `mallopt` is a no-op; Linux x86-64 only; a trace killed by a signal loses ≤ 2048 buffered events; qsim holds a trace in memory (24 B/event); the first-fit/buddy models are teaching models (they never return memory).

## Why this today
The ledger already had compilers, databases, a VCS, emulators, a terminal and a build system — but nothing *underneath* all of them. Every one of those programs lives on `malloc`, and an allocator is a perfect "small spec, deep trade-offs" project: it has to be correct inside programs you didn't write, and its quality can be *measured* — which is what the trace/replay loop is for.

## Where a human could take this next
* Per-CPU (rseq) caches and a lock-free central list; today the central free lists share one mutex.
* Guard-page mode (`mprotect`) for exact use-after-free and overflow detection at the faulting instruction, like a lightweight ASan.
* Huge-page awareness (THP-aligned spans, release in 2 MiB units) and live-range-aware slab choice (prefer the fullest slab) to cut fragmentation on `frag`.
* Capture traces with `uprobes`/eBPF so *unmodified, statically linked* programs can be recorded; add a streaming trace reader.
* More models (jemalloc-style extents, TLSF, Hoard) and a score that weights time and space, plus a CI job that fails when a workload regresses.
* macOS/aarch64 ports (the core only needs `mmap`, `madvise`, pthreads).
