# Reaper — a garbage-collector laboratory

Five interchangeable garbage collectors on one flat, byte-addressed heap — **mark-sweep, mark-compact (Lisp2),
Cheney copying, generational (write barrier + remembered set) and incremental tri-colour** — plus the tooling to
*prove* they are correct and *see* how they differ: a heap verifier, a differential fuzzer that checks every collector
against a never-collecting oracle, a benchmark harness, a mutator scripting language, and a heap-map HTML visualiser.

C++17, no dependencies. ~2 800 lines. `make && ./demo.sh`.

```
$ ./reaper bench --workload lru-cache
collector       wall ms      Mw/s   minor   major  pause tot  pause max  pause p99     moved   frag
marksweep          20.8     112.7       0      40     4.86ms    0.142ms    0.142ms         0    84%   <- fragmented
markcompact        10.2     229.5       0      39     5.28ms    0.297ms    0.297ms     19998     0%
copying             7.0     336.2       0      90     1.53ms    0.047ms    0.034ms     46221     0%
generational        9.1     256.1     119      23     3.83ms    0.236ms    0.131ms     60983     0%
incremental        40.0      58.5       0      71     6.74ms    0.037ms    0.003ms         0    42%   <- shortest pauses
```

## How it works

Objects are real words in a `uint64_t` arena: a 2-word header (`size | #pointer-slots | mark | forwarded | remembered | tag`
plus an aux word for forwarding addresses / free-list links), then pointer slots, then data words. References are arena
offsets. Free memory is **poisoned** (`0xDEAD…`), so a stale pointer reads garbage instead of silently "working".

Mutators never hold raw references. They address objects through 64 **root slots** (`newObj(dst,…)`, `store(objSlot,i,srcSlot)`,
`load(dst,objSlot,i)`) — that is what lets moving collectors relocate anything at any allocation, and it gives the collectors an
exact root set with no stack scanning.

| collector | moves? | allocation | idea | what to look for |
|---|---|---|---|---|
| `marksweep` | no | first-fit free list (split + address-ordered coalescing sweep) | mark from roots, sweep the arena | fragmentation climbs (80 %+ on `fragmenter`, `lru-cache`) |
| `markcompact` | yes | bump | Lisp2: compute forwarding → rewrite pointers → slide | zero fragmentation, 3 passes per GC |
| `copying` | yes | bump | Cheney: evacuate roots, scan to-space breadth-first | uses only half the arena, but GC cost ∝ live data |
| `generational` | yes | bump nursery + compacted old gen | minor GCs promote survivors; store barrier records old→young pointers in a remembered set; large objects are pretenured | short pauses on `lru-cache`; barrier counters in `reaper run` |
| `incremental` | no | free list + lazy sweep | tri-colour marking in slices interleaved with allocation; **Dijkstra insertion barrier**; atomic root rescan to terminate | max pause 3–10× lower than stop-the-world, at ~2× throughput cost |

### The correctness story (the interesting part)

1. **Oracle.** `nogc` is a bump allocator that never collects. A deterministic mutator (seeded RNG whose decisions depend only on
   address-independent state) runs on the oracle and on the collector under test *in lockstep*.
2. **Canonical graph hash.** Every N steps both heaps are walked breadth-first from the root slots; every object contributes its
   shape, tag, data words and the *visit index* of each child. Addresses never enter the hash, so a moving collector and the
   oracle must produce the same number — any lost, duplicated, mis-forwarded or clobbered object changes it.
3. **Verifier.** Linear heap walk (headers sane, sizes tile the heap, no leftover forwarding bits), every reachable pointer
   hits a real object start, free blocks fully poisoned (write-after-free), free-list/accounting cross-checks, generational
   remembered-set invariant ("every old→young pointer is remembered").
4. **Precision.** After the run a full GC must leave `used == live` words — otherwise a collector that merely *leaks* would
   pass the hash test.
5. **Mutation testing of the tests.** `tests/mutate.py` plants 16 realistic GC bugs (barrier removed, roots not rewritten,
   sweep forgets mark bits, off-by-one slide, missing root rescan…) and demands the fuzzer kills every one. This is how I
   found that the first version of the fuzz suite could not see a missing incremental write barrier (see REVIEW.md).

## Run it

```bash
make                       # builds ./reaper
make test                  # 101 test groups, ~1M checks, <2 s
./demo.sh                  # builds, tests, fuzzes, mutates, benchmarks, scripts, visualises — exits non-zero on any failure

./reaper list                                          # collectors + workloads
./reaper run generational lru-cache                    # one run; stats incl. write-barrier counters
./reaper run incremental pointer-shuffle --param 8 --verify-every 100
./reaper bench [--workload W] [--scale 0.5] [--csv out.csv]
./reaper fuzz --gc all --workload all --seeds 5        # differential fuzz vs. the oracle
./reaper script examples/barrier.rpr --gc generational
./reaper viz out.html --workload fragmenter            # open out.html in a browser
python3 tests/mutate.py [collector]                    # mutation-test the test-suite
```
Options: `--heap WORDS` (default depends on the workload), `--steps N`, `--seed N`, `--param N` (nursery words for
`generational`; slice size for `incremental`), `--verify-every N`.

### Script language (`*.rpr`)
```
alloc <slot> <nptrs> <ndata> [tag]     store <obj> <i> <src>     nil <obj> <i>     load <dst> <obj> <i>
set <slot> <j> <value>                 move <dst> <src>          clear <slot>      gc [minor|full]
let <name> <expr>                      repeat <n> [as var] { … } print stats|hash|live|slot <n>|<words…>
expect null|set <slot>   expect data <slot> <j> <value>   expect live|words <n>   expect used <= <n>   expect verify
```
Expressions support `+ - * / %`, parentheses, hex and `$var`. Errors are reported as `file:line: message`.
`examples/barrier.rpr` is a 15-line regression test for the generational write barrier; `cycles.rpr` collects 5 000 cyclic garbage structures.

## Feature list (all shipped)

**Required**
1. Heap core — arena, object layout, root-slot mutator API, poisoning, **verifier**
2. Mark-sweep, mark-compact (Lisp2), Cheney copying collectors
3. Generational collector — nursery, promotion, pretenuring, write barrier, remembered set, minor/major GC
4. Differential fuzzer + oracle — canonical graph hash, precision check, 6 workloads, any seed/heap/steps

**Stretch**
5. Incremental tri-colour collector — Dijkstra barrier, lazy sweep with cross-slice coalescing, pacing
6. Benchmark harness — 6 workloads × 5 collectors, pauses (total/max/p99), throughput, fragmentation, CSV
7. Mutator scripting language — loops, expressions, assertions, shipped examples
8. Heap-map HTML visualiser — time-lapse of the arena per collector + pause timelines (`examples/heapmap-fragmenter.html`)

Workloads: `binary-trees`, `list-churn`, `lru-cache` (old table, young entries), `fragmenter` (mixed-size churn + big contiguous
requests), `pointer-shuffle` (relocates subtrees while GC runs — the write-barrier torture test), `graph-fuzz` (random cyclic mutation).

## Why I built this today

The ledger is full of things *built from scratch* but nothing about the machinery underneath every managed runtime. GC is the
rare topic where the algorithms are short but the failure modes are vicious — a missed barrier corrupts memory three
collections later. So the build is organised around making GC bugs *loud*: poison, verifier, oracle, precision check, and a
fuzzer that is itself fuzzed. Phase 3 paid for that: the adversarial review found the incremental collector fragmenting
itself to death, an O(heap) allocation path, and — most embarrassing — that my own fuzzer could not detect a missing write barrier.

## Known limits
- Single-threaded; "incremental" means interleaved slices, not concurrent.
- Generational promotes survivors immediately (no aging), so it shows nepotism and premature promotion.
- Mark-sweep never splits off a 1-word remainder (a header needs 2 words); copying only uses half the arena.
- `peak retained` for generational is an upper bound (old gen may hold dead objects until a major GC).
- A mutator bug that corrupts roots can crash the process rather than raise a clean error (the harness reports "crashed").
- Timings are wall-clock on a shared box: trust the *shape* (pause max, fragmentation, moved), not the third digit.

## Where a human could take this next
- **Concurrent / parallel marking** with real threads and a snapshot-at-the-beginning (Yuasa) barrier; compare to the Dijkstra one here.
- **Aging + survivor spaces** for the generational collector, card marking instead of an object remembered set, adaptive nursery sizing.
- **Region-based (G1-style) collector** with evacuation of the most-garbage regions first; or **Immix** (line/block mark-region).
- **Conservative stack scanning** so the mutator can hold raw pointers — a real C front-end for the heap.
- Reference counting with cycle collection (Bacon–Rajan), weak references and finalisation.
- A language front-end (the script DSL → a small Lisp) so real programs, not synthetic workloads, drive the collectors.
- Plot `bench --csv` output in the visualiser; add allocation-site profiling to explain *why* a collector fragments.
