# Silicon

A from-scratch **cycle-accurate 5-stage pipelined CPU simulator** for a
real subset of RISC-V (RV32I), in pure Python. It's not a toy interpreter
that just executes instructions one at a time — it models the actual
microarchitecture that makes a real CPU fast: instruction-level pipelining,
the data hazards that creates, the forwarding paths that resolve most of
them without stalling, branch prediction to keep the pipeline full across
control flow, and an L1 cache hierarchy that hides memory latency.

Two independent simulators execute the *same* RV32I machine code — a
sequential "golden model" (one instruction fully retires before the next
starts) and the cycle-accurate 5-stage pipeline — and their final
architectural state (every register, every byte of memory) is checked to
be **bit-identical**. Pipelining is a pure timing optimization: it's
allowed to change *when* work happens, never *what* the program computes.
That gives this project an unusually strong, cheap-to-run correctness
oracle, and it's how five real bugs were actually found (see `REVIEW.md`).

## Quickstart

```bash
cd 2026-08-24-silicon

# see the real RV32I machine code an assembly program compiles to
python3 -m silicon.cli assemble fibonacci

# run it on the simple sequential simulator
python3 -m silicon.cli run fibonacci

# run it on the real 5-stage pipeline, with caches, cross-checked against
# the sequential model
python3 -m silicon.cli pipeline fibonacci --predictor dynamic \
    --icache 1024:16:2 --dcache 1024:16:2 --check

# compare static vs dynamic branch prediction across 5 real programs
python3 -m silicon.cli bench

# render an interactive HTML pipeline diagram from a real captured trace
python3 -m silicon.cli viz gcd -o pipeline.html

# run everything end-to-end (this is what demo.sh / CI does)
python3 -m silicon.cli demo

# the full test suite
python3 -m unittest discover -s tests -v

# or all of the above in one shot
./demo.sh
```

Write your own RV32I assembly and point any subcommand at it:
`python3 -m silicon.cli run myprogram.s`.

## Why this, today

Every prior "build a language/runtime from scratch" project in this
repo's history — Coil's bytecode VM, Kiln's WASM interpreter, Ember's real
x86-64 JIT, nine different from-scratch Transformers, Unify's Hindley-
Milner type inferencer — has targeted either an interpreter/runtime or a
data structure. None has modeled the layer underneath all of those: the
actual hardware microarchitecture that turns "a program that runs" into
"a program that runs *fast*, and here is provably why." Pipelining,
hazard forwarding, branch prediction, and cache hierarchies are the
concrete engineering that makes every real CPU on the planet faster than
a naive one-instruction-at-a-time design — and this project builds all
four from first principles, with a correctness argument (cross-checking
against a golden model) that's unusually cheap to run and unusually
effective at catching real bugs, in exactly the same spirit as this
repo's SAT solvers checking themselves against brute force or its
version-control-system builds checking themselves against real `git`.

## Architecture

```
assembly text (.s)
      |
   silicon/assembler.py   -- real RV32I encoding: R/I/S/B/U/J formats,
      |                       opcode/funct3/funct7 fields, correct
      |                       immediate bit layouts, labels, pseudo-ops
      |
  32-bit machine words + symbol table
      |
      +-------------------------------+
      |                                |
silicon/functional_sim.py      silicon/pipeline_sim.py
sequential golden model         cycle-accurate 5-stage IF/ID/EX/MEM/WB
(one instruction fully           pipeline: per-cycle stage latches,
 retires before the next          RAW-hazard forwarding (EX/MEM->EX,
 starts; the ground truth)         MEM/WB->EX), load-use stall detection,
      |                            branch/jalr resolution in EX (2-cycle
      |                            penalty) + early jal resolution in ID
      |                            (1-cycle penalty), cache-integrated
      |                            multi-cycle stalls on a miss
      |                                |
      +------------- compare ----------+
        register file + full memory
        image must match EXACTLY
```

Supporting modules: `isa.py` (instruction formats/encode/decode, the
32-register file), `alu.py` (pure ALU/branch-condition functions),
`memory.py` (byte-addressable little-endian memory + register file),
`cache.py` (configurable set-associative LRU cache),
`branch_predictor.py` (static + dynamic 2-bit predictors),
`viz.py` (HTML pipeline-diagram renderer), `bench.py` (benchmark suite),
`cli.py` (the `silicon` command-line tool).

## Feature list

**Required (all 4 shipped, fully working, cross-verified):**

1. **Real RV32I assembler + encoder/decoder** — the actual RISC-V bit
   layouts (not a made-up encoding), labels, comments, and 12 standard
   pseudo-instructions (`li/mv/not/neg/j/jr/ret/call/beqz/bnez/nop`).
   Verified against the real-world RISC-V NOP encoding (`0x00000013`)
   and 470+ randomized round-trip cases across every instruction format.
2. **Sequential golden-model simulator** — correct two's-complement
   arithmetic, sign/zero-extended loads of every width, real branch/jump
   semantics. This is the ground truth everything else is checked against.
3. **Cycle-accurate 5-stage pipeline with hazard detection + forwarding**
   — real per-cycle IF/ID/EX/MEM/WB stage latches, EX/MEM→EX and
   MEM/WB→EX forwarding, a load-use hazard that correctly stalls exactly
   one cycle, and a pipeline flush on control-flow misprediction — proven
   to produce **bit-identical** final state to the golden model across
   5 real programs × 7 predictor/cache configurations each (35/35 clean).
4. **Branch prediction with a measured effect** — static predict-not-taken
   vs. a dynamic 2-bit saturating-counter predictor with a BTB; on
   `fibonacci.s` the dynamic predictor cuts mispredictions from 16 to 2
   and cycles from 118 to 104 — a real, measured number, not a claim.

**Stretch (both shipped):**

5. **Configurable L1 instruction + data cache hierarchy** wired into real
   pipeline timing — a miss adds real multi-cycle stalls (not an
   approximation), reported per program with real hit-rate statistics.
6. **Interactive HTML pipeline visualizer + benchmark suite** — `silicon
   viz` renders a real captured execution trace (not synthetic data) as a
   cycle × pipeline-stage grid, one row per *dynamic* instruction instance,
   with stalls and mispredicted flushes visibly color-coded (screenshot-
   verified in headless Chromium, zero console errors); `silicon bench`
   runs 5 real programs and reports measured cycles/CPI/hit-rate/speedup.

## Example programs (`programs/`)

- `fibonacci.s` — iterative Fibonacci; the canonical loop-prediction demo.
- `gcd.s` — Euclid's algorithm by subtraction (RV32I has no DIV/REM).
- `sumarray.s` — builds and sums a 10-element array; every iteration is a
  textbook load-use hazard (`lw` immediately consumed by the next `add`).
- `bubblesort.s` — in-place bubble sort; nested loops + a data-dependent
  swap branch. This is the program that caught bug #3 in `REVIEW.md`.
- `matmul.s` — 2×2 matrix multiply via a real `mul` subroutine (repeated
  addition, since RV32I has no multiply) called with real `jal`/`ret`.

## Verification

- `tests/` — 101 automated tests: ISA encode/decode fuzzing, assembler
  correctness and error handling, cache hit/miss/LRU behavior hand-
  verified against worked sequences, functional-simulator arithmetic and
  memory-width correctness, branch-predictor unit behavior, one regression
  test per real bug found in review, and the core 35-combination
  pipeline-vs-golden-model cross-check matrix.
- `demo.sh` — exercises every feature through the real CLI end-to-end,
  including a headless-Chromium screenshot check of the visualizer.
- `REVIEW.md` — the adversarial-review writeup: 7 real bugs found and
  fixed, with root-cause explanations (3 were genuine pipeline-timing
  correctness bugs, including one — a mispredicted branch's flush signal
  getting silently overwritten by the very next instruction's own
  unrelated flush — that only `bubblesort.s` under *static* prediction
  happened to expose).

## Where a human could take this next

- **More of RV32I / RV32M**: multiply/divide (a real `MUL`/`DIV` unit
  instead of `matmul.s`'s repeated-addition workaround), CSRs, `FENCE`.
- **Superscalar or out-of-order execution** — the natural next
  microarchitecture chapter after a scalar in-order pipeline: a second
  execute port, a reorder buffer, register renaming.
- **A real toolchain front-end**: compile a tiny C subset down to this
  RV32I encoder instead of hand-written assembly (Coil and Unify in this
  repo's history are both plausible starting points for the compiler
  half).
- **Deeper memory hierarchy**: an L2 cache, a TLB, or a store buffer with
  real memory-ordering hazards.
- **A cycle-by-cycle "why" explainer** in the HTML visualizer: click any
  stall or flush cell and see the exact hazard/misprediction that caused
  it, generated from the same real trace data already being captured.
