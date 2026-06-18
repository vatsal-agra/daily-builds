# Coil

**Coil** is a small, dynamically-typed programming language with a real
**bytecode virtual machine**, written from scratch in pure Python (no third-party
dependencies). It is a complete language — not a calculator — with lexical
scoping, first-class functions, **closures that capture upvalues by reference**,
lists and maps, a native standard library, line-numbered runtime tracebacks, a
bytecode disassembler, an interactive REPL, and its own **mark-and-sweep garbage
collector** over a VM-managed object heap.

Source flows through the classic compiled-language pipeline:

```
source → Lexer → Pratt parser → AST → bytecode Compiler → Chunk → stack VM
```

## What it is

Most toy interpreters are tree-walkers. Coil instead compiles to bytecode and
executes it on a stack machine, the way CPython, Lua and the JVM do — which
forces the genuinely interesting problems into the open: upvalue capture, jump
back-patching, scope unwinding for `break`/`continue`, and a garbage collector
that has to root the live object graph correctly.

## How to run it

Requires only Python 3.8+.

```sh
# Run a program
python3 coil.py examples/closures.coil

# Interactive REPL (expressions echo their value)
python3 coil.py --repl

# Show the compiled bytecode for a file
python3 coil.py --disasm examples/fib.coil

# Dump the parsed AST
python3 coil.py --ast examples/fizzbuzz.coil

# GC controls
python3 coil.py --gc-stress program.coil   # collect before every allocation
python3 coil.py --trace-gc  program.coil   # log each collection

# Guided tour of every feature + the test suite
./demo.sh

# Tests
python3 -m unittest tests.test_coil        # 87 tests
```

## The language at a glance

```
// variables, arithmetic, strings
let name = "Ada";
print "hello, " + name;            // hello, Ada
print 1 + 2 * 3 - 4 / 2;           // 5

// control flow
for (let i = 1; i <= 5; i = i + 1) {
    if (i % 2 == 0) print str(i) + " even";
    else print str(i) + " odd";
}

// functions, recursion
fn fib(n) { if (n < 2) return n; return fib(n - 1) + fib(n - 2); }
print fib(20);                     // 6765

// closures capture by reference
fn makeCounter() {
    let count = 0;
    fn inc() { count = count + 1; return count; }
    return inc;
}
let c = makeCounter();
print c(); print c();              // 1  2

// lists & maps
let xs = [3, 1, 2];
push(xs, 0);
print xs;                          // [3, 1, 2, 0]
let person = { name: "Ada", age: 36 };
print person.name;                 // Ada  (dot is sugar for person["name"])
person.age = 37;
print keys(person);                // ["name", "age"]
```

## Feature list

**Required (all shipped):**
1. **Front end** — character lexer (line/col, string escapes, nested block
   comments) and a Pratt/precedence-climbing parser producing an AST, with
   precise syntax errors that point a caret at the offending token.
2. **Bytecode compiler + stack VM** — arithmetic, string & list `+`, comparisons,
   short-circuiting `and`/`or`, global and block-scoped local variables (slot
   resolution), `if`/`else`/`else if`, `while`, `for`, `break`/`continue` (with
   correct scope unwinding), `print`.
3. **Functions, recursion & closures** — first-class `fn` declarations and
   expressions, parameters, `return`, recursion, and closures that capture
   enclosing locals *by reference* via upvalues (counter factory; per-iteration
   loop capture; arbitrary nesting). The VM call loop is iterative, so deep Coil
   recursion never hits Python's recursion limit.
4. **Composite types + native stdlib** — `[...]` lists and `{k: v}` maps with
   literals, get/set indexing (incl. negative list indices), and ~25 native
   functions: `print len str num type push pop keys values has delete range
   slice abs floor ceil sqrt min max split join upper lower contains clock
   assert gc heap_size`.

**Stretch (all 3 shipped):**
5. **Mark-and-sweep garbage collector** over a VM-managed heap, tracing the real
   root set (value stack, globals, call frames, open upvalues). Observable via
   `gc()`/`heap_size()` builtins, `--gc-stress` (collect every allocation), and
   `--trace-gc`.
6. **Bytecode disassembler + REPL + runtime tracebacks** — `--disasm` renders
   chunks (and nested functions) with line numbers and decoded operands; the
   REPL echoes expression results and buffers incomplete multi-line input;
   runtime errors unwind into a multi-frame, source-annotated traceback.
7. **Example program suite** — `closures`, `fib`, `fizzbuzz`, `sort`
   (quicksort + in-place insertion sort), `wordcount` (split/map/maps),
   all run by the test suite.

## Architecture

| File | Responsibility |
|------|----------------|
| `coil/lexer.py` | source → tokens (line/col, escapes, nested comments) |
| `coil/ast_nodes.py` | AST node dataclasses |
| `coil/parser.py` | Pratt parser → AST |
| `coil/bytecode.py` | `Op` enum + `Chunk` (code, line table, constants) |
| `coil/objects.py` | GC-managed heap objects (`Function`, `Closure`, `Upvalue`, `List`, `Map`, `Native`) |
| `coil/compiler.py` | AST → bytecode: scope/upvalue resolution, jump patching |
| `coil/vm.py` | stack VM, call frames, native library, mark-sweep GC |
| `coil/disasm.py` | bytecode disassembler |
| `coil/errors.py` | error hierarchy + rendered diagnostics/tracebacks |
| `coil/cli.py` | CLI, REPL |
| `coil.py` | launcher |

## Adversarial review

The build's Phase-3 self-review (`REVIEW.md`) caught and fixed a **critical**
`break`/`continue` bug — they jumped without popping loop-body locals, corrupting
the value stack so later slot reads returned stale values (a probe returned
`500` instead of `800`) — and a **GC un-tracking hazard** where building a list
or map could let the collector sweep the aggregate's own elements out of the
managed heap. Both have regression tests.

## Where a human could take this next

- **`else`/`elif` are already nice, but add `match`/`switch`** and a proper
  ternary or `if`-expression.
- **More datatypes:** a string type with methods, sets, tuples; iterator
  protocol + `foreach (x in xs)` sugar (currently you index manually).
- **A real module system** (`import`) and a small standard library written *in*
  Coil.
- **Performance:** the VM dispatches via a Python `if/elif` ladder; switch to a
  dispatch table or computed-goto-style jump, intern strings, and cache global
  lookups by slot. Compile constants/locals once.
- **A generational or incremental GC**, and weak references.
- **Better tooling:** a source-level step debugger driven by the line table, and
  an HTML visualizer that animates the stack/heap as bytecode executes.
- **Self-hosting:** the lexer/parser are simple enough to re-implement in Coil
  itself once it has strings-with-methods and file I/O.

## Why I chose this today

The recent ledger is heavy on solvers and engines (six SAT solvers, a regex
engine, a SQL database, a Raft simulator, a physics engine, an autodiff engine).
None of them is a *compiled programming language with a bytecode VM and a garbage
collector* — a different and classic systems problem, and one where the
interesting bugs (upvalue capture, scope unwinding, GC rooting) are exactly the
kind a hostile review can hunt down. It felt like the most distinct, complete
thing to build in a day.
