# Coil

A small programming language with a real **bytecode virtual machine**, written
from scratch in pure Python (no dependencies). Source flows:

```
source → Lexer → Pratt parser → AST → bytecode Compiler → Chunk → stack VM
```

**Status: Phase 3 (adversarial review) complete.** Lexer, parser, compiler and
VM all run; closures, recursion, lists/maps, control flow, a native stdlib, a
mark-sweep GC, a disassembler and a REPL work. Self-review found and fixed a
critical `break`/`continue` stack-corruption bug and a GC un-tracking hazard —
see `REVIEW.md`. Remaining phases (polish, verification, ship) follow.

## Run it

```sh
python3 coil.py examples/closures.coil     # run a program
python3 coil.py --repl                      # interactive REPL
python3 coil.py --disasm examples/fib.coil  # show bytecode
python3 coil.py --gc-stress program.coil    # collect on every allocation
python3 coil.py --trace-gc program.coil     # log each collection
```

## A taste of Coil

```
fn makeCounter() {
    let count = 0;
    fn inc() { count = count + 1; return count; }
    return inc;
}
let c = makeCounter();
print c(); print c();        // 1  2

let xs = [3, 1, 2];
push(xs, 0);
print xs;                    // [3, 1, 2, 0]

let person = {name: "Ada", age: 36};
print person.name;           // Ada
```

See `PLAN.md` for the full feature list and architecture.
