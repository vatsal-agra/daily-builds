# REVIEW — adversarial pass on Reaper

Method: I attacked the Phase-2 build as a hostile reviewer would — wrote exhaustion / misuse / scale tests,
ran every collector × workload at default settings, **mutation-tested the fuzzer itself** (break a collector on
purpose, demand the harness notice), and read the code for invariants nothing exercised. Every finding below was
reproduced first, then fixed, then re-run.

| # | Sev | Finding (how it was found) | Fix |
|---|-----|----------------------------|-----|
| 1 | **High** | **Mark-sweep allocation was O(heap).** Splitting a free block re-poisoned the entire remainder; 20 000 allocations took 15 s (found by a 200k-node chain test that never finished). | Splits now write only the new header; the interior is already poison. 200k allocs: ~15 ms. |
| 2 | **High** | **Incremental collector fragmented itself to death.** Running every workload at default settings, `fragmenter` died with *"heap exhausted … 71 474 of 1 048 576 words in use, fragmentation 96 %"*. Free blocks were coalesced only inside one sweep slice (256 words), so no free block could ever exceed one slice. | The trailing free block of a slice is held back (`pend`) and extended by the next slice; flushed to the free list when a live object intervenes or the sweep ends. Same workload now ends at 5 % fragmentation. |
| 3 | **High** | **The fuzzer could not detect a missing incremental write barrier.** Mutation test: removing the Dijkstra shading still passed 10/10 seeds, because with a small live set the mark phase finishes in 2–3 allocations — too short a window for the hide-a-pointer race. The oracle test was giving false confidence. | New `pointer-shuffle` workload (relocates whole subtrees from parent to parent while garbage drives GC, tree reachable only from its root). Same mutant now fails 5/5 seeds at every slice size; the intact collector passes. |
| 4 | **High** | **The fuzzer could not detect leaking collectors.** A collector that "forgets" to free some objects has an identical reachable graph to the oracle. Mutation test (keep every tag-3 object) passed. | After the run the harness forces a full GC and demands `usedWords == liveWords` — a precision check. The leaky mutant now fails: *"2239 words in use but only 161 are live"*. |
| 5 | Med | Incremental `pace()` computed `usedWords()` by walking the free list on **every allocation** (O(free blocks)); `lru-cache` took 198 ms vs 5 ms for generational. | `MarkSweepHeap` keeps a `freeW` counter; `usedWords()` is O(1); verifier cross-checks the counter against the list. |
| 6 | Med | Incremental trigger would **collect continuously** when more than 60 % of the heap was live (free < 40 % is always true). | A cycle also needs `allocSince ≥ lastLive/4 + 64`. Thrash test (70 % live, 200k allocs): 103 cycles instead of one per allocation. |
| 7 | Med | `peak live` stat was only updated by full collections, so a generational run that never did a major GC reported 0. | Minor GCs record retained words (documented as an upper bound). |
| 8 | Med | Huge `--heap` died with a bare `std::bad_alloc`; heaps above 2³¹ words silently overflow the 32-bit `Ref`. | Factory rejects > 2²⁸ words with an explanation; `main` maps `bad_alloc` to a readable error. |
| 9 | Med | OOM message said nothing useful. | Reports words in use / capacity / fragmentation % — which is exactly what distinguishes "full" from "fragmented". |
| 10 | Med | Typos like `--stpes 5` were silently ignored and the default was used. | Each command whitelists its options; unknown ones are an error. |
| 11 | Low | `fuzz --seeds 0` printed "0/0 seeds identical" and exited 0 — a vacuous pass. | Rejected (`--seeds`/`--steps` ≥ 1). |
| 12 | Low | Default heap (1 Mi words) was so large most workloads ran **zero** collections — the benchmark measured nothing. | Per-workload default heap sizes chosen so every collector collects dozens to hundreds of times. |
| 13 | Low | `PointerShuffle` first draft overwrote slots (dropping subtrees → tree stayed ~24 nodes, so marking was trivial) and could build depth > 55, overflowing the 64 root slots (`vector::_M_range_check`). | Relocation only targets empty slots, never deepens a node; documented in the workload. |
| 14 | Info | Known limitations accepted (documented in README): mark-sweep skips a free block whose remainder would be exactly 1 word; copying uses half the arena; generational promotes survivors immediately (no aging) so it suffers nepotism/premature promotion; allocation is single-threaded. | — |

Fresh run-through after the fixes: `make test` (0 failures), `reaper fuzz` over all 6 workloads × 5 collectors × several seeds
(0 failures), full run matrix at default settings (no OOM, no corruption, verifier clean), mutants of the barrier and of the
sweeper both killed. None of the 14 issues above reproduces.

## Addendum — findings from Phase 5 (verification)

Running the 16-mutant harness (`tests/mutate.py`) against the Phase-4 code turned up three more problems — two in the
test-suite and one in the collector:

| # | Sev | Finding | Fix |
|---|-----|---------|-----|
| 15 | High | **Two incremental-GC mutants survived**: "no root rescan at mark termination" and "no allocate-black". The mutator never kept a white object *only* in a root slot across a collector step, so the root-rescan path was untested. | `pointer-shuffle` now detaches a subtree and holds it only in a root slot for a few steps before re-attaching it; the rescan mutant is killed (crashes on the dangling slot). |
| 16 | Med | The allocate-black mutant survived because it is an **equivalent mutant**: with a Dijkstra store barrier *and* an atomic root rescan, a fresh object is always either stored (barrier shades it) or still in a root slot (rescan finds it). Allocating black only adds floating garbage. | Deleted the dead `onAllocated` hook from the incremental collector instead of keeping unneeded code; mutant removed from the list with this note. |
| 17 | Low | Mutants that corrupt roots crash the process (SIGSEGV) rather than report cleanly — still a kill, but ugly. | Accepted: the harness reports "crashed (exit -11)". Noted in README limitations. |
| 18 | Low | `print` in the script language could not show loop variables. | Words starting with `$` are evaluated as expressions. |

Final state: 101 test groups / 1 000 680 checks green in <2 s; 16/16 mutants killed; `demo.sh` green.
