# Spillway — a register-allocation laboratory

Spillway compiles a small three-address IR for a machine with only **K physical registers**, using interchangeable allocators — Chaitin–Briggs graph colouring (with coalescing), Poletto linear scan, and a spill-everything baseline — then **executes both the original and the allocated code and demands identical behaviour**. Every number it prints (spills, moves, cycles) comes from running real machine code under a cost model.

Go 1.24, standard library only (~3,300 lines incl. tests).

## Run it
```bash
go build -o spillway ./cmd/spillway
./spillway compare examples/pressure.ir -k 6 -args 20     # three allocators side by side
./spillway run     examples/collatz.ir  -k 5 -args 30     # print the machine code + verify
./spillway sweep   examples/poly.ir -kmax 12 -args 3      # cycles as K grows
./spillway live    examples/sumsq.ir                       # liveness, loop depth, intervals
./spillway report  examples/bubble.ir -k 5 -args 24 -o r.html   # visual HTML report
./spillway gen -seed 3 -vars 16 -shuffle > rand.ir         # random program
./spillway fuzz -n 300                                      # differential fuzzing
go test ./...        # unit + property tests (≈15 s)
./demo.sh            # 43 CLI acceptance checks
```
`-args "5;10;20"` runs several input vectors. A sample report is checked in: `sample-report.html`.

Example (`pressure.ir`, 11 values live across a hot loop, K = 6):
```
alloc     K  instrs  sp.ld  sp.st   movs spilled    cycles dyn.spill  dyn.mov  verified
color     6      81     22     17      0      11      2701      554        0  yes
linear    6      97     34     20      1      10      3385      720       20  yes
naive     6     113     43     28      0      20      4653     1042        0  yes
```

## IR in 30 seconds
```
func sumsq(1) {          ; one parameter
entry:
  n = arg 0              ; read parameter
  s = const 0
  jmp head
head:
  c = lt i, n            ; ops: add sub mul div rem and or xor shl shr lt le eq ne
  br c, body, done       ; also: mov load store print jmp ret
...
```
Operands are registers or integer literals. 64-bit signed words, 256-word memory (addresses masked), `div`/`rem` by zero = 0 so every program is total.

## Features
1. **IR toolchain** — parser with line-numbered errors, validator (reads of possibly-undefined registers, unreachable `ret`), CFG, bitset liveness to a fixed point, natural-loop depth via dominators, reference interpreter.
2. **Graph-colouring allocator** — Appel/George iterated register coalescing: simplify / Briggs-conservative coalesce / freeze / optimistic potential-spill, loop-weighted cost/degree spill metric, biased colour selection, spill-rewrite loop until fixed point.
3. **Linear-scan allocator** — Poletto–Sarkar over doubled-position intervals, furthest-end spilling, move hints; plus the `naive` spill-everything baseline.
4. **K-register machine + verifier** — VM with a cycle model, spill load/store counters, differential comparison of return value / output / memory, and an independent interference checker that recomputes liveness itself.
5. **Post-allocation clean-up** — store→load forwarding, dead spill-store removal, stack-slot sharing (switch off with `-nopost`).
6. **Random program generator + fuzzer** — structured, terminating programs with if/else, nested loops, memory, optional block-layout shuffling; every allocator × K × coalescing × 5 inputs.
7. **K-sweep** — table and chart of cycles / spill traffic versus register count.
8. **HTML report** — self-contained, light/dark, mobile-friendly: head-to-head cards, sweep chart, live-range charts coloured by register, interference graph, annotated assembly.

## Verification
* `go test` — hand-computed liveness/loop depth/interference, coalescing legality, spill-choice-by-loop-depth, tamper detection (a corrupted machine program must be flagged `MISCOMPILE`), forwarding/slot-sharing on hand-built code, error paths, plus a 500-program fuzz.
* **Mutation-tested harness**: 8 deliberately injected allocator bugs; 7 are caught immediately, 1 is provably equivalent (see REVIEW.md).
* Fuzz totals during development: >30,000 allocations / 150,000 differential executions, zero divergences.

## Why I built this today
Nothing in this repo had touched a compiler back-end. Register allocation is the textbook place where theory (graph colouring is NP-complete) meets heuristics, and where it is easy to be *quietly wrong*. I wanted something where "does it work?" has a rigorous answer — run both programs and compare — and where the interesting part (why colouring beats linear scan on loops, what coalescing buys, how much spill-everywhere wastes) is directly visible.

## Where a human could take this next
* Live-range **splitting** and rematerialisation of constants instead of spill-everywhere.
* Lifetime **holes** (second-chance binpacking) for linear scan; SSA form with phi-based allocation (Hack/Wimmer).
* Pre-coloured registers, a calling convention, `call` instructions and caller/callee-saved registers.
* A real back-end: emit x86-64 or RISC-V assembly and run it.
* Smarter spill metrics (profile-guided weights), George coalescing test, iterated spill cost updates.
* Interactive viewer that steps through simplify/coalesce/select.

See PLAN.md (design) and REVIEW.md (adversarial review).
