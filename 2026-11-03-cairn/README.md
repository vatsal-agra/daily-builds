# Cairn — a garbage-collector laboratory

**What it is.** Cairn is a from-scratch managed heap with **five interchangeable, precise tracing
garbage collectors** — mark-sweep, Cheney semispace, generational (nursery + remembered set),
incremental snapshot-at-the-beginning (SATB), and sliding mark-compact — plus a small Lisp-flavoured
language whose values live *only* in that heap. Run the same program under every collector and the
output **and the final reachable object graph must be identical**, while pause times, footprint,
fragmentation and throughput differ. An independent **oracle** (canonical graph snapshots, heap
walks, invariant checks) watches every allocation, and a **differential fuzzer** hunts for
collector bugs against a collector-free reference run.

Rust 2021, zero dependencies (~4.5 k lines of library + ~1.2 k lines of tests).

```
$ cairn bench examples/bintrees.cairn --heap 400000 --nursery 20000
collector         wall    gc %      gcs     pauses  max pause  p99 pause  MMU1ms MMU10ms peak wds   Mwords/s     frag
marksweep      76.72ms    1.8%        2          2    819.6µs    588.5µs   0.180   0.918   400000       14.6       0%
semispace      63.62ms    0.8%        6          6    151.1µs     89.9µs   0.849   0.983   199998       17.7       0%
generational   73.05ms   12.2%       57         57    542.9µs    446.1µs   0.292   0.755   387249       15.4       6%
incremental    80.49ms    2.6%        5      12034     36.6µs      939ns   0.625   0.952   314836       14.0      48%
compact        60.21ms    5.3%        2          2     1.77ms     1.40ms   0.000   0.823   399999       18.7       0%
outputs identical across 5 collector(s)
```
(Timings vary per run; the shape does not: the incremental collector's worst pause is ~20× shorter
than a stop-the-world cycle, compaction pays one long pause for zero fragmentation.)

## How to run

```bash
cargo build --release                         # binary: target/release/cairn
cargo test --release                          # ~1 min: model-based, feature, hazard, fuzz, CLI tests
./verify.sh                                   # the full gate; ends with "ALL GREEN"

cairn run examples/cycles.cairn --gc incremental --stats     # run a program under one collector
cairn run prog.cairn --gc generational --verify              # oracle checks every allocation
cairn run prog.cairn --torture --verify                      # collect at every allocation
cairn compare examples/cache.cairn --verify                  # same output + same final graph everywhere?
cairn bench examples/bintrees.cairn --heap 400000            # pauses, MMU, footprint, fragmentation
cairn bench examples/bigvecs.cairn --heap 12000 --nursery 1000   # tight heap: who survives?
cairn report examples/bintrees.cairn -o report.html          # self-contained HTML (light/dark, no JS)
cairn fuzz --iters 200 --seed 1 [--torture] [--gcs a,b]      # differential fuzzing
cairn barrier-demo                                           # why write barriers exist (see below)
cairn list                                                   # collector names
```
Sizes are in 8-byte words (`--heap`, `--nursery`). Options: `--gc NAME`, `--seed N`, `--steps N`
(abort runaway programs), `--pace N` (incremental work per allocated word), `--no-barrier`.

## The mutator language

S-expressions; integers (63-bit, wrapping), `nil`, byte strings, pairs, vectors, globals (`def`),
top-level functions (`fn`), `let` (sequential), `set!`, `if`/`when`/`while`/`begin`/`and`/`or`.
Builtins: `+ - * / %` (variadic `+ - *`), comparisons, `eq`, `cons car cdr set-car! set-cdr!`,
`vector vref vset! vlen`, `str strcat strlen strref substr`, type predicates, `print`, `assert`,
`rand` (seeded), `digest` (collector-independent hash of the reachable subgraph), and GC controls
`(gc)`, `(gc-minor)`, `(gc-begin)` (start an incremental cycle *without* finishing it).

```lisp
(fn (ring n) …)            ; see examples/cycles.cairn — cyclic garbage reference counting can't free
(def table (vector 2000 nil))   ; examples/cache.cairn — old table, young values: the generational barrier
```
Examples: `hello bintrees churn cycles cache frag queue strings bigvecs`.

## Features (all shipped)

| # | Feature | Where |
|---|---------|-------|
| 1 | **Heap model + mark-sweep** (size-binned free list, address-order coalescing, explicit mark stack) and **Cheney semispace** (forwarding pointers, sharing preserved) behind one `Gc` trait | `heap.rs` `marksweep.rs` `semispace.rs` |
| 2 | **Generational**: bump nursery, promotion on first survival, large-object bypass, **remembered-set write barrier**, minor/major cycles with headroom checks | `generational.rs` |
| 3 | **Incremental SATB** tri-colour collector: Yuasa deletion barrier, allocate-black, paced mark *and* sweep increments paid by allocation, adaptive trigger, barrier kill-switch | `incremental.rs` |
| 4 | **Cairn language + GC-safe VM** (explicit root stack; moving collectors rewrite it) with the **oracle**: canonical snapshot compared across every allocation, structural heap check, tri-colour/remembered-set invariants, torture mode | `lang.rs` `vm.rs` `verify.rs` |
| 5 | **Sliding mark-compact** (Lisp2: mark → forward → rewrite → slide, order-preserving) | `compact.rs` |
| 6 | **Bench harness**: wall/GC time, pause count, max & p99 pause, **MMU** (exact, any window), peak footprint, fragmentation, honest OOM reporting | `bench.rs` |
| 7 | **HTML report**: MMU chart, occupancy + pause timelines and final heap map per collector | `report.rs` |
| 8 | **Differential fuzzer**: random programs (aliasing, cycles, hoist-and-delete, forced/partial collections) vs. a collector-free reference; verifies with the oracle and under torture | `fuzz.rs` |
| – | `barrier-demo`: hand-built hazards showing a lost object when a barrier is removed | `demo.rs` |

### Why barriers exist — `cairn barrier-demo`
```
== incremental SATB: hoist a child into a root, then delete the heap edge — barrier OFF
   mutator: root2 = H.0   (X is now held by a root that the collector will never rescan)
   mutator: H.0 = nil   (deletion barrier is OFF: nobody tells the collector)
   oracle: CORRUPTION — reachable graph changed: a live object was freed and its memory reused
== generational: old object points at a nursery object — barrier OFF
   oracle: CORRUPTION — old object 401 slot 0 points to young 1 but is not remembered
```
With the barriers on, the same scenarios are silent. (Note the first one: the freed block was
*immediately reused*, so a "is it a FREE block?" check sees nothing — only comparing the reachable
graph across the allocation catches it. That finding shaped the oracle; see REVIEW.md R2.)

## Verification
`./verify.sh` runs: warnings-as-errors build + `cargo fmt --check`; the test suite (model-based test
that checks every collector against a plain-Rust shadow graph after *every* operation, per-feature
tests, hazard tests, CLI error paths, report checks); `review_check.sh` (probes from REVIEW.md);
every example under every collector with the oracle on; torture mode; the barrier demo; bench and
report generation; 160 fuzzed programs × 5 collectors; and a negative control — the fuzzer **must**
catch the incremental collector with its barrier removed.

## Design notes
- **Object layout**: `[header][payload]`; header packs kind, FWD/MARK/GREY/REM bits, age and length. Every
  object is ≥ 2 words so a forwarding pointer always fits. Address 0 is `nil`; ints are tagged, so
  there are no unboxed floats and no conservative scanning — collectors are *precise*.
- **GC safety**: the evaluator never holds a Value in a Rust local across an allocation; temporaries
  live on the root stack, which a moving collector updates in place.
- **Why SATB needs no remark**: roots are scanned once at cycle start; anything loaded afterwards was
  reachable then (or is new and allocated black), and the deletion barrier shades what mutation would hide.
- **Incremental sweep**: the free list is emptied when sweeping starts and refilled *behind* the sweep
  pointer, so the allocator only ever hands out already-swept, white blocks.

## Known limits (deliberate)
Byte strings (a `substr` can split UTF-8), 63-bit wrapping ints, no closures, generational promotes on
first survival (premature tenuring shows in the stats), a minor GC needs old-generation headroom,
`collect(full=false)` is a full GC for non-generational collectors, single-threaded. Pause times are
wall-clock on whatever machine runs the bench — compare shapes, not absolutes.

## Why I built this today
The repo already has compilers, VMs, a TLS stack, a filesystem, and a malloc (Quarry) — but nothing that
*reclaims* memory automatically. A garbage collector is the part of a managed runtime where bugs are
invisible until much later, so the interesting engineering isn't the algorithms; it's building the
machinery that can *prove* a collector right (or catch it lying): an oracle, a fuzzer with teeth, and a
negative control. Cairn makes that visible: remove one line (a write barrier) and the oracle lights up.

## Where a human could take this next
- **Concurrent collection**: real threads, with the SATB collector marking on a background thread and
  the barrier as a lock-free buffer (the single-threaded design is arranged so this is a refactor, not a rewrite).
- **Aging / survivor spaces** and adaptive nursery sizing for the generational collector; card marking
  instead of a remembered-object list.
- **Region-based (G1/Immix-style) collector** with evacuation of mostly-dead regions; line-based
  fragmentation reduction without full compaction.
- **Closures, floats, finalizers, weak references** in the language — each stresses the collectors differently
  (ephemerons are famously hard to get right).
- **Conservative stack scanning** mode, and a `--trace` that emits per-GC logs in a Chrome-tracing format.
- Port the oracle to a real runtime's heap (e.g. check a JVM heap dump against a shadow graph).
