# Spillway
Register-allocation laboratory (Go, stdlib only).

**Status: Phase 2 — core build done.**

Implemented so far (required features 1–4):
1. IR text parser/validator, CFG, bitset liveness, natural-loop depth, reference interpreter
2. Chaitin–Briggs/Appel graph-colouring allocator with coalescing, freeze and optimistic spilling
3. Poletto linear-scan allocator + naive spill-everything baseline
4. K-register machine code generation, cost-model VM, differential verifier, independent interference checker

```
go build -o spillway ./cmd/spillway
./spillway compare examples/pressure.ir -k 6 -args 20
./spillway run examples/collatz.ir -k 5 -args 30
./spillway sweep examples/pressure.ir -kmax 14 -args 20
./spillway live examples/sumsq.ir
```
See PLAN.md for the full plan.
