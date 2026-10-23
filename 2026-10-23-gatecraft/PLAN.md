# Gatecraft — PLAN

## Concept
A from-scratch **hardware compiler + formal toolkit**: write synthesizable Verilog (a well-defined
subset), and Gatecraft elaborates it into an **And-Inverter Graph (AIG)** with flip-flops, simulates it
cycle-by-cycle (VCD waveforms out), **optimises** it (structural hashing, balancing, local rewriting,
SAT-sweeping a.k.a. FRAIG, sequential cleanup), **proves** original ≡ optimised (or two independently
written implementations equivalent) with a built-in **CDCL SAT solver**, and does bounded model
checking / k-induction on `assert property` statements. Stretch: k-LUT technology mapping and an HTML
report with a waveform viewer.

## Why it's interesting
The ledger has CPU simulators, a SAT solver, a Datalog/Prolog and a compiler — but nothing that goes
from *hardware description text* to *gates*. This is the logic-synthesis flow (Yosys + ABC + a model
checker) in miniature. It is a self-validating system: the optimiser's output is checked by the
prover, the prover's counterexamples are replayed in the simulator, and the elaborator is
differentially tested against an independent big-integer AST interpreter.

## Architecture
```
 .v source ──► hdl (lexer, parser, AST)
                 │
                 ▼
            elab: parameter eval, hierarchy flattening, width inference, symbolic execution of
                  always blocks (if/case/for, blocking & non-blocking), bit-blasting
                  (adders, multipliers, dividers, shifters, comparators)
                 │
                 ▼
              aig: strashed AIG + latches (clock, init)        ◄── sat: CDCL (2WL, 1-UIP, VSIDS,
                 │                                                       Luby restarts, assumptions)
     ┌───────────┼───────────────┬──────────────┬─────────────┐
     ▼           ▼               ▼              ▼             ▼
   sim (+VCD)   opt          equiv (comb/    bmc/k-ind     lutmap ─► BLIF
   TB scripts   balance,     seq-bounded,    assert/assume
                rewrite,     CEX replay)     properties
                fraig, seq
                cleanup
                 │
                 ▼
          emit: structural Verilog, BLIF, AIGER · report: HTML (stats, timing, waveforms)
```

## Features
| # | Feature | Tier |
|---|---------|------|
| 1 | **Verilog-subset frontend + elaborator → AIG**: modules, parameters, hierarchy, `assign`, `always @(*)`/`@(posedge clk)`, if/case/for, blocking+non-blocking, vectors, concat/replicate/slices, arithmetic/shift/compare/reduction ops, latch & loop diagnostics | **required** |
| 2 | **Cycle-accurate simulator + testbench scripts + VCD** (`set`/`tick`/`expect`/`print`/`repeat`/`randomize`), VCD loadable in GTKWave | **required** |
| 3 | **AIG optimiser**: strash, constant propagation, balancing, 2-level rewriting, SAT-sweeping (FRAIG), sequential cleanup (constant / duplicate latches), DCE; before/after report | **required** |
| 4 | **SAT-based equivalence checker**: miter → CDCL; combinational (state matched by register name) and bounded sequential; counterexample is *replayed in the simulator* to confirm | **required** |
| 5 | **BMC + k-induction** over `assert property` / `assume property` with counterexample trace to VCD | stretch |
| 6 | **k-LUT technology mapper** (cut enumeration, depth-optimal + area recovery) → BLIF, verified by SAT | stretch |
| 7 | **Export**: structural Verilog, BLIF, ASCII AIGER; **HTML report** with stats, critical path, waveform viewer | stretch |
| 8 | **Static timing**: unit-delay critical path report | secondary |

Required: 1–4. Stretch: 5, 6, 7 (+8 secondary).

## Verification strategy
* Go unit tests per package; SAT solver cross-checked against brute force and DRAT-free model checking.
* Elaborator differential test: random expressions evaluated by an independent `math/big` Verilog
  interpreter vs. AIG simulation.
* Optimiser: every pass output is SAT-proven equivalent to its input on the example designs.
* `demo.sh` runs the whole CLI end-to-end over the examples.

## Documented limits
Unsigned arithmetic only; single synchronous (posedge) style flops with initial value 0 unless
declared; no async reset, tri-state, memories-as-arrays, delays, or `generate`.

## Delivered (status at ship time)

| # | Feature | Tier | Status |
|---|---------|------|--------|
| 1 | Verilog-subset frontend + elaborator → AIG | required | shipped |
| 2 | Simulator + testbench scripts + VCD | required | shipped |
| 3 | AIG optimiser (strash, rewrite, balance, FRAIG, seq cleanup) | required | shipped |
| 4 | SAT equivalence checker with replayed counterexamples | required | shipped |
| 5 | BMC + k-induction | stretch | shipped |
| 6 | k-LUT technology mapper | stretch | shipped |
| 7 | Exports (Verilog/BLIF/AIGER) + HTML report with waveform viewer | stretch | shipped |
| 8 | Static timing (critical path) | secondary | shipped |
| 9 | *(added)* Sequential equivalence across state encodings via mined inductive invariants | stretch+ | shipped |
