# Delve

**A symbolic execution engine with its own SMT solver — pure Python 3, standard library only.**

Delve runs programs on *all* inputs at once. Inputs are symbolic fixed-width integers; each `if`/`while` forks the
state and records a path condition; a bit-vector solver (hash-consed terms → bit-blasting → CNF → incremental CDCL SAT,
all written from scratch here) decides which paths are feasible. The result: one generated test per path, and a
**concrete, replay-confirmed counterexample** for every reachable assertion failure, division by zero, signed
overflow or invalid shift. No Z3, no external solver.

```
$ python3 -m delve analyze examples/sorted3.dl -q
BUGS FOUND: 1
  [assertion failure] line 6: assert(a <= b);
      triggered by: a=0, b=-1, c=-2   (replay-confirmed; reached on 2 paths)
```

## Run it
```bash
python3 -m delve analyze examples/triage.dl            # bugs + generated tests + coverage
python3 -m delve analyze examples/triage.dl --html report.html --tests tests.json
python3 -m delve replay examples/triage.dl tests.json  # re-run generated tests concretely
python3 -m delve run examples/abs.dl -i n=-128         # concrete interpreter
python3 -m delve equiv examples/equiv/clamp_a.dl examples/equiv/clamp_buggy.dl
python3 -m delve solve 'x*3 + y == 42 && x < y' -n 3   # raw formula solving
python3 -m delve solve '(x ^ y) + 2*(x & y) == x + y' --prove --width 12
./demo.sh                                               # CLI-level verification of every feature
python3 tests/run_all.py                                # 54 unit/differential/fuzz tests
```
Options: `--width N` (2–32 bit signed ints, default 8), `--loop-bound`, `--max-paths`, `--timeout`, `--solver-budget`,
`--no-overflow`. Exit codes: `0` clean/equivalent, `1` bugs/different, `2` internal inconsistency, `3` unknown, `64` usage/parse error.

## DelveLang
C-like, one integer type (W-bit two's complement). `let x = input();` / `input(lo, hi)` makes a symbolic input named
after the variable (`v`, `v#2`… inside loops). Statements: `let`, assignment, `if/else if/else`, `while`, `assert`,
`assume`, `print`, `return`, `fn` with recursion. Operators: `+ - * / % & | ^ ~ ! << >> >>>`, signed comparisons,
`&& || ?:` (short-circuit). Division truncates toward zero; `>>` is arithmetic, `>>>` logical. Decimal literals must fit the signed range (hex may use the full pattern).
Function calls inside expressions are hoisted ahead of the statement (so are evaluated eagerly; they are rejected in `while` conditions and the right side of `&&`/`||`).
Traps: assertion failure, division by zero, signed overflow (`+ - * /` and unary `-`), invalid shift (count outside `0..W-1`).

## Features shipped
1. **Language + concrete interpreter** — lexer, Pratt parser with block scoping, exact W-bit semantics, trap detection, step/recursion budgets.
2. **Bit-vector SMT solver** — hash-consed term DAG with constant folding; bit-blaster for add/sub/mul, signed and unsigned div/rem, barrel shifters, all comparisons; CDCL SAT solver (2-watched literals, 1-UIP + minimization, VSIDS, phase saving, Luby restarts, LBD clause-DB reduction, assumptions + unsat cores) used incrementally across all queries.
3. **Symbolic executor** — path forking with free feasibility checks (the current model witnesses one side of every branch), loop/call bounds, calls and recursion, assume/ranges, short-circuit-aware checks, one minimized (closest-to-zero) test per path.
4. **Bug finder** — every trap kind; each witness is replayed on the concrete interpreter and marked *replay-confirmed*; generated tests are verified against symbolic predictions of return values and prints.
5. **Equivalence checker** (`equiv`) — pairs up paths of two programs and proves identical behaviour (result, prints, traps) or returns a confirmed distinguishing input.
6. **HTML report** — dark/light, source coverage heat, bug cards, path table.
7. **Solver instrumentation** — query cache, SAT-call/conflict stats, conflict budget with honest "unknown" reporting.
8. **`solve`** — satisfiability / validity / model enumeration of bit-vector formulas.

## How it is verified
* SAT solver vs brute force on 300 random CNFs, pigeonhole, assumptions.
* Bit-blaster vs the concrete operator semantics for every operator at widths 4, 5, 8, 12.
* **Path-partition fuzzing:** for random programs and *every* input pair at 5 bits, exactly one generated path matches and its predicted outcome equals the interpreter's.
* `REVIEW.md`: 13 findings from an adversarial pass, each reproduced, fixed and regression-tested.

## Why I chose this today
Nothing in the ledger touched symbolic execution or SMT solving, and it is the technique behind KLEE/angr/SAGE-style bug hunting. It also stitches together the repo's earlier ground (SAT solving, compilers, interpreters) into a tool whose answers can be *checked*: the concrete interpreter is an independent oracle for the symbolic engine.

## Where a human could take this next
* Memory: symbolic arrays/pointers (theory of arrays, or an object-based memory model) and strings.
* Performance: constraint independence slicing, state merging, better search heuristics (coverage-guided, random-path), word-level preprocessing before bit-blasting, learned-clause sharing across paths, a faster (C/Rust) SAT core.
* Language: unsigned types, structs, a C or WebAssembly front end instead of DelveLang.
* Hybrid concolic mode, loop-invariant inference to remove the loop bound, and test-suite export to pytest/JUnit.
