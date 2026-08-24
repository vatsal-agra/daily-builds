# Silicon — a from-scratch pipelined CPU

## Concept

A cycle-accurate simulator of a real 5-stage RISC-V (RV32I-subset) CPU
core: an assembler that turns assembly text into real RV32I machine
words using the actual bit encodings the RISC-V spec defines, a
sequential "golden" reference simulator that executes those machine
words instruction-by-instruction, and a **cycle-accurate 5-stage
pipeline simulator** (IF → ID → EX → MEM → WB) with real data-hazard
detection and forwarding, a branch predictor with pipeline flush on
misprediction, and configurable L1 instruction/data caches wired into
the pipeline's timing model. Two independent simulators (sequential
and pipelined) execute the *same* machine code and must land on
*bit-identical* final architectural state — the pipeline is only
allowed to change *when* work happens, never *what* the program
computes. That gives this build an unusually strong, cheap-to-check
correctness oracle, in the same spirit as this repo's SAT solvers
checking themselves against brute force or its VCS builds checking
themselves against real `git`.

## Why this is interesting

Every prior "language" build in this repo's history (Coil's bytecode
VM, Kiln's WASM interpreter, Ember's x86-64 JIT, nine different
from-scratch Transformers, Unify's type inferencer) has targeted
either a *runtime* (interpret this) or a *data structure* (learn
this). None has modeled the actual hardware microarchitecture that
makes a modern CPU fast: instruction-level parallelism via pipelining,
the data hazards that parallelism creates, forwarding paths that
resolve most of them without stalling, branch prediction to keep the
pipeline full across control flow, and the memory hierarchy (caches)
that hides DRAM latency. This is the missing layer between "a program
that runs" and "a program that runs *fast*, and here is provably why."
It is also unusually verifiable: pipelining is a *timing*
optimization, so a pipelined CPU and a naive one-instruction-at-a-time
CPU running the same binary must always compute the same answer —
any divergence is a real bug, not a matter of interpretation.

## Architecture

```
assembly text (.s)
      |
   [assembler.py]  -- real RV32I encoding (opcode/funct3/funct7, I/S/B/U/J imm layouts)
      |
  32-bit machine words + symbol table
      |
      +----------------------------+
      |                            |
[functional_sim.py]         [pipeline_sim.py]
sequential golden model     5-stage IF/ID/EX/MEM/WB
(1 instr fully retires      per-cycle stage registers,
 before the next starts)    hazard detection + forwarding,
      |                     branch predictor + flush,
      |                     cache-integrated stalls
      |                            |
      +------------ compare -------+
        (register file + memory
         must match exactly)
```

Supporting modules:
- `isa.py` — instruction formats, opcode/funct tables, encode/decode,
  32-register file with x0 hardwired to zero, ABI register names.
- `cache.py` — configurable-size/associativity/LRU set-associative
  cache with real tag/index/offset address decomposition and hit/miss
  accounting, usable standalone or wired into the pipeline.
- `branch_predictor.py` — static "predict not-taken" plus a dynamic
  2-bit saturating-counter branch history table with a small BTB.
- `viz.py` — renders a captured cycle-by-cycle pipeline trace to a
  self-contained interactive HTML diagram.
- `cli.py` — the `silicon` command-line tool tying it together.

## Feature list

**Required (core, must work end-to-end with zero stubs):**

1. **Real RV32I assembler + encoder/decoder.** Parses assembly text
   (labels, comments, the full R/I/S/B/U/J instruction set, common
   pseudo-instructions `nop/li/mv/j/jr/ret/not/neg/beqz/bnez`) into
   real 32-bit RISC-V machine words with the spec's actual bit
   layouts — verified by round-tripping every instruction through
   encode→decode and by checking known reference encodings (e.g. the
   real-world RISC-V NOP encoding `0x00000013`).
2. **Sequential golden-model simulator.** Executes a real RV32I binary
   instruction-by-instruction (fetch/decode/execute/writeback fully
   sequential, no overlap) with a real byte-addressable little-endian
   memory, correct sign/zero-extension on every load width, and
   correct two's-complement arithmetic/branch/shift semantics.
3. **Cycle-accurate 5-stage pipeline with hazard detection +
   forwarding.** A real IF/ID/EX/MEM/WB pipeline with per-cycle stage
   latches, full RAW-hazard detection, EX→EX / MEM→EX / WB→ID
   forwarding paths, a load-use hazard that correctly stalls one
   cycle when forwarding alone can't resolve it, and a pipeline flush
   on control-flow redirection — verified to produce **bit-identical**
   final register/memory state to the sequential golden model across
   a suite of real assembly programs, while independently reporting
   real cycle counts, stall counts, and CPI (cycles per instruction).
4. **Branch prediction with measurable effect.** Both a static
   predict-not-taken policy and a dynamic 2-bit saturating-counter
   predictor (with a small branch-target buffer) are implemented and
   selectable; a loop-heavy benchmark program demonstrably gets a
   measurably lower misprediction penalty (fewer flushed cycles) under
   the dynamic predictor than under static prediction — a real,
   measured number, not an assertion.

**Stretch:**

5. **Configurable L1 cache hierarchy wired into pipeline timing.**
   Separate instruction and data caches (configurable size,
   associativity, block size, LRU replacement) sit between IF/MEM and
   memory; a cache miss adds a configurable number of real stall
   cycles to the pipeline, and hit/miss rates are reported per
   program — demonstrating that cache configuration measurably changes
   total run time on the same binary.
6. **Interactive HTML pipeline visualizer + benchmark suite.** A
   `viz` command renders a real captured execution trace (not
   synthetic data) as a cycle × pipeline-stage grid — one row per
   instruction, one column per cycle — color-coding stalls (bubbles)
   and flushed (mispredicted) instructions, with a register-file
   panel and a cache hit/miss timeline; a `bench` command runs a
   small library of real assembly programs (bubble sort, Fibonacci,
   GCD, array sum, matrix multiply) and reports cycles / instructions
   / CPI / cache hit-rate / measured speedup over a naive
   5-cycles-per-instruction non-pipelined baseline.

## Verification strategy

- **Functional correctness:** every pipeline run's final register
  file and memory image must exactly match the sequential golden
  model's, for every test program, including ones deliberately
  written to trigger back-to-back RAW hazards, load-use hazards, and
  taken/not-taken branches in tight loops.
- **Encoding correctness:** every instruction form round-trips through
  encode→decode; a handful of instructions are checked against known
  real-world RISC-V machine-code bytes as an external sanity check.
- **Timing plausibility:** cycle counts obey known bounds (an N-cycle,
  hazard-free straight-line program pipelined takes `N + 4` cycles for
  a 5-stage pipeline; each load-use stall or branch misprediction adds
  its known, counted penalty) — checked directly against the
  simulator's own stall/flush counters, not just eyeballed.
