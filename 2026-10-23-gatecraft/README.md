# Gatecraft

**A from-scratch hardware compiler and formal toolkit, in Go with zero dependencies.**
Write Verilog; Gatecraft elaborates it into an And-Inverter Graph, simulates it cycle by cycle
(VCD waveforms), optimises it, **proves** the optimised netlist equivalent with its own SAT solver,
finds or proves properties with bounded model checking + k-induction, maps it onto FPGA-style LUTs,
and writes an interactive HTML report. It is the logic-synthesis flow of Yosys + ABC + a model
checker, rebuilt small enough to read in an afternoon — and it checks its own work: every optimiser
pass is SAT-verified, every counterexample is replayed in the simulator, and the whole thing is
differentially tested against independent oracles.

```
$ gatecraft opt examples/tinycpu.v
before: inputs=3(3b) outputs=5(39b) latches=86 ands=2275 depth=84
...
after:  inputs=3(3b) outputs=5(39b) latches=60 ands=832 depth=43
verified: every pass and the end-to-end result are SAT-proved equivalent (102 obligations, 1778 conflicts)
AND gates 2275 → 832 (-63.4%), latches 86 → 60, depth 84 → 43

$ gatecraft check examples/lock.v           # a combination lock; the property says "it never opens"
FAILED   never_opens   counterexample at cycle 4 (replay confirmed)
           cycle  0: rst=0 enter=1 digit=3        ← bounded model checking recovered the code 3-1-4-1
           cycle  1: rst=0 enter=1 digit=1
           cycle  2: rst=0 enter=1 digit=4
           cycle  3: rst=0 enter=1 digit=1
PROVED   open_means_done   by 4-induction
```

## Run it

Requires Go ≥ 1.24. No other dependencies (Node + Playwright are used only by an optional browser check).

```bash
go build -o gatecraft ./cmd/gatecraft

./gatecraft elab   examples/tinycpu.v -timing            # netlist statistics + critical path
./gatecraft sim    examples/tinycpu.v -tb examples/tinycpu.tb -vcd cpu.vcd
./gatecraft opt    examples/tinycpu.v -o tinycpu_opt.v   # also .blif / .aag
./gatecraft equiv  examples/adder_rtl.v examples/adder_kogge.v
./gatecraft equiv  examples/detect_onehot.v examples/detect_binary.v   # different state encodings
./gatecraft check  examples/lock.v                       # BMC + k-induction
./gatecraft map    examples/tinycpu.v -k 6 -o cpu.blif   # LUT mapping, SAT-verified
./gatecraft report examples/tinycpu.v -tb examples/tinycpu.tb -o report.html
./gatecraft emit   examples/fifo4.v -format aag
```

Verify everything (format, vet, 86 tests incl. fuzzers, 53-step CLI demo, headless-browser check):

```bash
./verify.sh        # prints ALL GREEN
./demo.sh          # just the end-to-end CLI demo
```

Exit codes: `0` ok / proved, `1` failure found (bug, failing check, failing property), `2` usage or input error,
`3` inconclusive.

## Features

1. **Verilog-subset frontend → AIG.** Hand-written lexer and recursive-descent parser; elaborator with
   parameters (`-P W=8`, `$clog2`, localparams), hierarchy flattening, named/positional ports, Verilog
   context-width rules, bit/part/indexed-part selects (dynamic too), concatenation/replication, all
   arithmetic/bitwise/shift/compare/reduction/ternary operators (adders, multipliers, restoring dividers,
   barrel shifters are bit-blasted), `assign`, `always @*`, `always @(posedge clk)`, blocking and non-blocking
   assignments, `if`/`case`/`for` (unrolled), `initial` reset values, `assert/assume property`. A symbolic
   executor merges branches into muxes and **diagnoses** inferred latches, combinational loops (with the path),
   multiple drivers, undriven nets, mixed blocking/non-blocking use, and port-width mismatches.
2. **Cycle-accurate simulator, testbench scripts, VCD.** `set`/`tick`/`eval`/`expect`/`print`/`randomize`/
   `repeat`/`seed`/`reset`; hierarchical VCD loadable in GTKWave/Surfer; failing checks exit non-zero.
3. **Optimiser.** Structural hashing, constant propagation, two-level rewriting, depth balancing,
   **SAT-sweeping (FRAIG)** with simulation-guided candidate classes and counterexample refinement, and
   **sequential cleanup** (dead, stuck-at-reset and duplicate registers found by inductive fixpoints). Every
   pass is checked by the equivalence checker; removals are recorded so the proof survives them.
4. **SAT equivalence checker.** Hand-written CDCL solver (2-watched literals, 1-UIP learning, VSIDS, phase
   saving, Luby restarts, clause-DB reduction, assumptions). Both designs are fused into **one
   structurally-hashed miter** (identical logic vanishes before SAT), swept, then decided. Combinational and
   register-matched designs get a proof; counterexamples are replayed in the simulator and can be exported as
   a runnable testbench (`-cex`).
5. **Model checking.** BMC + k-induction over `assert property` with `assume property` constraints and
   simple-path strengthening; failing traces replay in the simulator and export to VCD.
6. **Sequential equivalence across different state encodings.** One-hot vs binary FSM, compare-and-wrap vs
   lookup-table counters: fuse into a product machine, **mine inductive invariants** (Houdini over constant /
   2- / 3-literal register clauses from simulation, filtered by reset and made inductive by SAT) and run
   k-induction with them as lemmas — an unbounded proof with no state matching.
7. **LUT mapper.** k-feasible cut enumeration (k = 2–6), depth-optimal cover, area recovery under the depth
   bound; BLIF output; verified by simulation and by SAT (LUTs → AIG → equivalence).
8. **Exports.** Structural Verilog (re-parseable, keeps properties), BLIF, ASCII AIGER (also readable, so
   external AIGER benchmarks work as inputs).
9. **HTML report.** Self-contained page (light/dark): stats, optimisation log with bars, collapsed critical
   path, LUT mapping table, property results with input traces, and an interactive **waveform viewer**
   (zoom, pan, filter, hex/dec/bin, value readout under the cursor).

## Language reference (what the subset accepts)

Supported: `module` with ANSI or classic port lists, `parameter`/`localparam`, `input`/`output`/`wire`/`reg`,
`integer` (loop variables only), `assign`, `always @*` / `@(a or b)` (treated as `@*`) / `@(posedge clk)`,
`initial` (constant reg initialisation), instances, `if/else`, `case`, `for` with constant bounds,
`assert property (...)` / `assume property (...)`, optionally labelled. Numbers: `8'hFF`, `4'b1010`, `'d9`, `12`.

Semantics worth knowing: unsigned arithmetic; flops power up to 0 unless given an initial value;
`x / 0` yields all-ones and `x % 0` yields the dividend (RISC-V convention); clocks must be top-level inputs.

Rejected with a clear message: `signed`, `>>>`, x/z/`?` literals, `casez`, async reset / multi-edge
sensitivity, `negedge`, memories (`reg [7:0] m [0:3]`), `generate`/`genvar`, functions/tasks, delays,
`inout`, tri-state. Two blocks cannot drive different bits of one vector. Multi-clock designs simulate fine but
the sequential formal engines (BMC / induction / bounded equivalence) require one clock domain.

Testbench scripts (`*.tb`): `set <in> <value>` · `tick [clock] [n]` · `eval` · `reset` · `expect <sig> [op] <value>` ·
`print <sig>...` · `randomize [in...]` · `seed <n>` · `repeat <n> … end` · `#` comments. Signals can be ports,
registers, or hierarchical nets such as `u_rf.x3[2]`.

## How it is verified

* **Differential testing.** Random expressions (700) and random procedural programs (250 × 24 cycles) are run
  through the AIG and through an independent `math/big` Verilog interpreter and must agree bit for bit;
  the fuzzers were themselves mutation-tested.
* **Optimiser fuzzing.** 400 random sequential netlists laced with redundancy: simulate-before/after and SAT-check.
* **Checker fuzzing.** 400 mutants: no simulation-visible difference may be called equivalent; every
  counterexample must replay.
* **Explicit-state oracles.** BMC/induction verdicts on 300 random machines are compared with a BFS over all
  reachable states; mined invariants are checked against every reachable state; induction is required never to
  prove a pair that differs on a reachable state.
* **Round trips** (Verilog/AIGER/BLIF writers vs readers/interpreters), a VCD parser, and 53 CLI steps.
* [REVIEW.md](REVIEW.md) lists the 16 bugs and shortcuts the adversarial pass found, each with its regression test.

## Architecture

```
 .v ─► hdl (lexer, parser) ─► elab (params, hierarchy, widths, symbolic exec, bit-blasting) ─► aig
                                                                                              │
   sat (CDCL) ◄──── aig.Encoder (Tseitin) ◄────────────────────────────────────────────────────┤
     ▲                                                                                        │
     ├─ equiv: strashed miter + FRAIG, state matching, BMC, k-induction, invariant mining      │
     ├─ aig.Fraig (SAT sweeping)                                                               │
     └─ lutmap / emit / report / sim (VCD, testbench scripts) ◄───────────────────────────────┘
```

`internal/sat` solver · `internal/aig` graph, bit-vector builders, simulator, passes (sweep, rewrite, balance,
FRAIG, seqclean), timing · `internal/hdl` front end · `internal/elab` elaborator · `internal/sim` simulator,
scripts, VCD · `internal/equiv` formal engines · `internal/lutmap` mapper · `internal/emit` writers + AIGER reader ·
`internal/report` HTML · `examples/` 22 designs and testbenches (a TinyCPU, FIFO, traffic light, lock, adders, FSMs, …).
About 9.3k lines of Go plus 3.5k lines of tests.

## Numbers from the examples

| design | result |
|---|---|
| TinyCPU (hierarchical, 86 flops) | 2275 → 832 AND gates (−63 %), 86 → 60 flops, depth 84 → 43; proves PC never leaves 0…10 by 1-induction; discovers `pc[5:4]` ≡ 0 and that registers r3–r5 are never read |
| TinyCPU LUT mapping | 3/4/5/6-LUT: 390 / 283 / 196 / 180 LUTs, depth 22 / 15 / 10 / 9 (all SAT-verified) |
| Redundant MAC pipeline | 67 → 46 flops: duplicate operand registers merged, stuck `sticky` flag removed, `prod[0]`/`acc[0]` proved constant (the datapath computes 2·a·b) |
| Ripple-carry vs Kogge-Stone adder | proved equivalent; buggy adder refuted with the unique corner case `a=255 b=0 cin=1` |
| Combination lock | BMC recovers the 4-digit code; two invariants proved by induction |
| One-hot vs binary FSM, two mod-10 counters | proved equivalent **for all time** (22 / 16 mined invariants) |
| Mod-20 vs mod-21 counter | bounded check finds the cycle-20 divergence; induction correctly refuses to prove them equal |
| `a*b ≡ b*a` | 8 bits ≈ 1 s; 10 bits ≈ 1 min (SAT is the limit; beyond `-conflicts` the answer is INCONCLUSIVE) |

## Why I built this today

The ledger already holds a SAT solver, a SQL engine, a Prolog, a compiler middle-end, a CPU simulator and a
Game Boy — but nothing that goes from *hardware description text* down to *gates*, and nothing where the
tool's output is itself formally checked. Logic synthesis is the one domain where all of those threads meet:
a parser and elaborator, graph rewriting, SAT as the engine of both optimisation (FRAIG) and verification
(miters, BMC, induction), and a visible payoff (a CPU shrinking by 63 % *with a proof*). The build was
also a chance to do something I rarely get to in one sitting: make the verification layer adversarial — the
optimiser fuzzer found a real soundness bug in my own removal bookkeeping within minutes.

## Where a human could take this next

* **Better SAT**: LBD-based clause deletion, recursive minimisation, inprocessing — the 10-bit multiplier
  miter would drop from a minute to seconds; or plug in a DRAT proof logger so proofs are independently checkable.
* **Stronger sequential equivalence**: IC3/PDR instead of mined-clause Houdini; signal-correspondence
  (`scorr`) to merge equivalent registers across designs automatically.
* **Language**: `generate`, functions, memories (RAM inference), signed arithmetic, async reset, multi-clock
  domains with proper CDC handling.
* **Back end**: real technology mapping with a cell library and delays (Liberty), carry-chain inference,
  retiming, a placer for the LUT netlist.
* **Tooling**: an LSP / editor integration over the diagnostics, a VCD-diff command, SystemVerilog assertions
  with temporal operators (`##1`, `|=>`) compiled to monitors, hierarchical waveforms in the HTML viewer
  with search by value.
