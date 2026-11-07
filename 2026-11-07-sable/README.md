# Sable

An SSA-based **optimizing compiler with register allocation**, written from scratch in Go (stdlib only).

> Status: **Phase 4 complete** (inlining, graph-colouring allocator, fuzzer + pass bisection, HTML report added; see REVIEW.md). Earlier: **Phase 2** — the four required features work end to end:
> 1. frontend + AST oracle interpreter, 2. SSA construction + verifier, 3. optimiser (SCCP, instcombine, GVN, LICM, DCE, SimplifyCFG),
> 4. backend with linear-scan allocation, calling convention and a poisoning register VM.
> See `PLAN.md`. Review, stretch features, tests and the full README follow in later phases.

```
go build -o sable ./cmd/sable
./sable check examples/fib.sb      # every executor vs the oracle
./sable asm   examples/primes.sb -k 4
./sable stats examples/mandel.sb
```
