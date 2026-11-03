# Adversarial review

Method: attack the build as a hostile reviewer — (a) feed the CLI/language garbage, (b) try to make each
collector lose or corrupt an object, (c) check whether the *test machinery itself* can be fooled, since an
insensitive oracle is worse than none. Every finding below was reproduced before being fixed;
`review_check.sh` re-runs the probes and ends `ALL CLEAN`.

| # | Severity | Finding (how it was reproduced) | Fix |
|---|----------|---------------------------------|-----|
| R1 | high (oracle) | **False positive:** `check_heap` flagged "dangling pointer" on *unreachable* garbage (incremental mid-sweep: dead A points to already-freed B). First Phase-2 test run failed with this on a correct collector. | Pointer validity is now checked only for objects reachable from the roots; unreachable garbage may legitimately point at reclaimed memory. |
| R2 | high (oracle) | **Oracle blind spot:** in the hand-built SATB hazard (`tests/barrier.rs`) the lost object was freed *and its block immediately reused* by the next allocation, so "is it a FREE block?" saw a healthy-looking pair. Heap walk alone cannot detect this. | Detection relies on canonical-snapshot equality across every allocation (+ the sweep-phase "reachable but white" invariant); the barrier test now asserts the graph changes when the barrier is off. |
| R3 | high (test power) | **Fuzzer could not find the bug it exists to find:** 1,500 random programs ran the incremental collector with the barrier *disabled* and all "passed" — marking finished inside a single loop iteration so the hoist-then-delete hazard never overlapped it. | Generator now emits `(gc-begin)` (start an incremental cycle without finishing it), explicit hoist-and-delete statements, a long ballast chain, and per-seed varied pacing/triggers. No-barrier incremental is now caught at seed 14 (<1 s). New `--no-barrier` generational mode is caught by the oracle too (`old object … points to young … but is not remembered`). |
| R4 | medium (UX) | `cairn run f.cairn --bogus 5` silently accepted the unknown option and swallowed its value. | Strict option table; unknown options are an error. |
| R5 | medium | `--heap 999999999999999` aborted the process (`memory allocation of 8000000000000000 bytes failed`, exit 134, backtrace). | Heap/nursery capped at 2^28 words with a clean error. |
| R6 | medium | Generational with a small `--heap` and the default 32768-word nursery left the old generation 64 words: instant bogus OOM on `heap 2000`. | Nursery is capped at heap/4. |
| R7 | medium | Generational minor GC only checked *total* free words before promoting; a fragmented old generation could fail mid-evacuation. | Pre-check also needs a free block as large as the biggest possible nursery object; otherwise a major GC runs first; failure reports free words *and* largest block. |
| R8 | low | `Generational::check_invariants` used `Vec::contains` per object (O(n²)), making `--verify` unusable on big heaps. | HashSet. |
| R9 | medium | Incremental collector recorded one pause per allocation without bound (memory growth in long runs). | Detailed log capped at 200k pauses, the rest aggregated (count/total/max) so totals stay exact. |
| R10 | medium | Incremental trigger was a fixed fraction of the heap: with >50 % live data a new cycle started immediately after the previous one (GC thrash). | Adaptive trigger: never closer to the last live size than half the remaining headroom. (9 cycles for 87k allocated words on a 67 %-live heap.) |
| R11 | low | `(print 99999999999999999999)` reported `unknown variable '9999…'`. | Reader says "integer … does not fit in 63 bits". |
| R12 | low (UX) | `+`, `-`, `*` were strictly binary — the reviewer tripped over it three times writing examples. | Variadic `+ - *`, unary `-`. |
| R13 | process | `target/` was committed in the first local commit (400 files, ~100 MB). Caught before pushing. | `.gitignore`, history rewritten before the first push. |

## Known limits (deliberate, documented — not defects)
- Strings are byte strings: `substr` can split a UTF-8 character; output is lossy-decoded.
- Integers are 63-bit and wrap on overflow.
- The generational collector promotes on *first* survival (no aging/survivor space) — premature tenuring is
  visible in `cache`/`queue` stats. A minor GC needs old-generation headroom (see R7).
- No closures / first-class functions in Cairn: kept out to keep the root-stack discipline obvious.
- `collect(full=false)` is a full collection for every non-generational collector.
- Mark-sweep can fail with free words > request (fragmentation) — shown on purpose by `examples/` +
  `cairn bench` (compact and incremental succeed where mark-sweep reports `largest block 518`).

## Re-run gate
`./review_check.sh` → every row R3–R12 re-probed; R1/R2/R7/R8 covered by `tests/barrier.rs` and `tests/model.rs`
(model-based test: random op streams checked against a plain-Rust shadow graph after *every* operation).
