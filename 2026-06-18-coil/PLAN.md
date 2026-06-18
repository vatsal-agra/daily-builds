# Coil — PLAN

## Concept
**Coil** is a complete, from-scratch programming language implemented in pure
Python: a dynamically-typed scripting language with a C/Lua-flavoured syntax that
runs on a real **bytecode virtual machine**. Source text flows through a classic
pipeline:

```
source → Lexer → Pratt parser → AST → bytecode Compiler → Chunk → stack VM
```

It is a full language, not a calculator: it has lexical scoping, first-class
functions, **closures with upvalues**, recursion, lists & maps, a native standard
library, line-numbered runtime stack traces, a bytecode disassembler, a REPL, and
its own **mark-and-sweep garbage collector** running over a VM-managed object heap.

## Why it's interesting
Most "toy interpreters" are tree-walkers. Coil instead compiles to bytecode and
runs a stack machine the way CPython/Lua/the JVM do, which forces the genuinely
hard problems into the open:
- **Upvalues / closures** — capturing a still-live local by reference and keeping
  it alive after the enclosing frame returns (the classic loop-counter trap).
- **A real GC** — Python already manages memory, so to make GC *mean* something we
  run our own heap of Coil objects and mark-sweep over the actual VM root set
  (stack, frames, globals, open upvalues). The collector's effect is observable.
- **Honest error reporting** — every byte of bytecode carries a source line, so a
  runtime error unwinds the call stack into a real traceback.

It's also distinct from everything in the ledger (SAT solvers, regex engine, SQL
DB, Raft, physics, autodiff, world-gen): none of those is a compiled language with
a VM and GC.

## Architecture
- `coil/lexer.py` — character scanner → tokens with line/col; positioned errors.
- `coil/ast_nodes.py` — typed AST node dataclasses.
- `coil/parser.py` — Pratt (precedence-climbing) parser → AST.
- `coil/bytecode.py` — `OpCode` enum + `Chunk` (code, constants, line table).
- `coil/objects.py` — runtime heap objects (Function, Closure, Upvalue, List, Map,
  String, Native) — every one GC-managed.
- `coil/compiler.py` — AST → Chunk; scope/local resolution, upvalue capture,
  jump back-patching.
- `coil/vm.py` — the stack VM, call frames, native dispatch, **mark-sweep GC**.
- `coil/disasm.py` — bytecode disassembler.
- `coil/errors.py` — `CoilError` hierarchy (syntax/compile/runtime) + tracebacks.
- `coil/__init__.py` — `run_source`, `Interpreter` facade.
- `coil.py` — CLI: run a file, `--repl`, `--disasm`, `--gc-stress`, `--ast`.
- `examples/*.coil` — real programs.
- `tests/test_coil.py` — full unittest suite. `demo.sh` — guided tour.

## Feature list

### Required (4)
1. **Front end — lexer + Pratt parser + AST** with precise, line/column syntax
   errors that point at the offending token. Full operator precedence, unary,
   grouping, all literals.
2. **Bytecode compiler + stack VM** executing the core language: arithmetic &
   string ops, comparisons, `print`, global + block-scoped local variables,
   `if`/`else`, `while`, `for`, and short-circuiting `and`/`or` — compiled to
   bytecode and run on the VM.
3. **Functions, recursion & closures with upvalues** — first-class `fn`
   declarations and expressions, parameters, `return`, recursion (fib), and
   correct closures that capture enclosing locals *by reference* (counter
   factory; loop-capture).
4. **Composite types + native stdlib** — `[...]` list and `{k: v}` map literals,
   indexing get/set (`a[i]`, `m["k"]`), and native functions (`print`, `len`,
   `str`, `num`, `type`, `push`, `pop`, `keys`, `clock`, `abs`, `floor`, ...).

### Stretch (3 — target ≥1)
5. **Mark-and-sweep garbage collector** over a VM-managed heap with observable
   stats: a `gc()` builtin returns bytes/objects reclaimed, and `--gc-stress`
   collects on every allocation, proving unreachable cycles/objects are freed
   while live ones survive.
6. **Bytecode disassembler + REPL + runtime tracebacks** — `--disasm` prints
   human-readable bytecode with line numbers; `--repl` gives an interactive shell
   that prints expression values; runtime errors produce a multi-frame stack
   trace with source lines.
7. **Example program suite** — fibonacci, closure counter, FizzBuzz, recursive
   sort, a map/list data-munging program, all shipped as `.coil` files and run by
   the test suite & demo.

## Done means
All 4 required features demonstrably work end-to-end; ≥1 stretch shipped (target
all 3); adversarial review done and every issue fixed; a green test suite that
runs every feature including the example programs; README + LEDGER updated.
