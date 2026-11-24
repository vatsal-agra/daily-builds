# Spillway
Register-allocation laboratory (Go, stdlib only).

**Status: Phase 3 — adversarial review done** (see REVIEW.md; 9 findings fixed, 7/8 harness mutants killed, 1 proven equivalent).

Implemented so far: IR parser/validator/interpreter, liveness + loop depth, Chaitin–Briggs graph colouring with coalescing, Poletto linear scan, naive baseline, K-register VM with cost model, differential verifier, independent interference checker, post-allocation spill clean-up (forwarding / dead stores / slot sharing), random program generator and differential fuzzer (library).

```
go build -o spillway ./cmd/spillway
./spillway compare examples/pressure.ir -k 6 -args 20
./spillway run examples/collatz.ir -k 5 -args 30
./spillway sweep examples/pressure.ir -kmax 14 -args 20
./spillway live examples/sumsq.ir
```
See PLAN.md for the plan.
