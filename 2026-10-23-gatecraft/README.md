# Gatecraft (work in progress)

> Phase 3 (adversarial review) done — see [REVIEW.md](REVIEW.md): 10 findings fixed, each with a regression test.

Verilog-subset hardware compiler, simulator, optimiser and formal checker. See [PLAN.md](PLAN.md).

## Status
* Phase 1 — plan: done.
* Phase 2 — core build: the four required features work end-to-end:
  1. Verilog frontend + elaborator → AIG (`gatecraft elab`)
  2. Cycle-accurate simulator, testbench scripts, VCD (`gatecraft sim`)
  3. AIG optimiser with per-pass SAT verification (`gatecraft opt`)
  4. SAT-based equivalence checking with replayed counterexamples (`gatecraft equiv`)
  (Property checking `gatecraft check`, emit formats are also already in place.)

```
go build -o gatecraft ./cmd/gatecraft
./gatecraft sim examples/counter.v -tb examples/counter.tb -vcd counter.vcd
./gatecraft opt examples/counter.v
./gatecraft equiv examples/adder_rtl.v examples/adder_kogge.v
```
