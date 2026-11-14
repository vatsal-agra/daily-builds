# Forthwright — PLAN

## Concept
A complete Forth system in dependency-free JavaScript whose twist is **static analysis**:
Forth is untyped and stack-based, so the classic way to die is a wrong stack effect that only
shows up at runtime as garbage or underflow. Forthwright compiles words to an IR (not
threaded JS closures) and then runs an abstract interpreter over that IR to **infer every
word's stack effect**, cross-check it against the programmer's `( a b -- c )` comment, and
reject branch/loop imbalance at compile time. Execution is fully recordable and can be
scrubbed backwards in a time-travel debugger.

## Why it's interesting
- Forth's whole semantics fit in a page, yet inference over control flow (IF/ELSE joins,
  BEGIN/UNTIL back edges, DO/LOOP, recursion with declared effects) is a real dataflow problem.
- IR-based design means the same IR feeds the VM, the analyzer, the optimizer, the disassembler
  and the tracer.
- Nobody else in this repo's ledger has built a Forth.

## Architecture
```
src/forth.js     UMD. Tokenizer/outer interpreter, dictionary, IR compiler, VM (iterative,
                 explicit call stack), ~120 primitives with declared effects, byte memory.
src/analyze.js   UMD. Effect parser, CFG abstract interpreter, declared-vs-inferred check.
src/optimize.js  UMD. Constant folding + peephole + inlining over IR (stretch).
src/tracer.js    UMD. Recording run -> snapshots, profiler counters.
cli.js           run / repl / trace / see / effects / test subcommands.
web/             index.html + app.js + style.css : browser IDE (REPL, stack viz, word browser, scrubber).
test/            run.js (engine/analyzer/optimizer oracles), forth/*.fth conformance, ui.js (Playwright).
```

## Features
| # | Feature | Tier |
|---|---------|------|
| 1 | **Forth engine**: IR compiler + VM; colon defs, IF/ELSE/THEN, BEGIN/WHILE/REPEAT/UNTIL/AGAIN, DO/?DO/LOOP/+LOOP/LEAVE, RECURSE, VARIABLE/CONSTANT/CREATE/DOES>, byte memory, strings, 32-bit wraparound math | **required** |
| 2 | **Stack-effect inference**: abstract interpretation over the CFG; verifies `( -- )` comments; compile-time errors for underflow-prone/mismatched branches, unbalanced loops and return stack | **required** |
| 3 | **Time-travel tracer**: recorded run, per-step data/return stack + output; step forward/back, jump | **required** |
| 4 | **Web IDE**: editor+REPL, live stack visualisation, word browser with inferred effects, trace scrubber | **required** |
| 5 | **Optimizer + disassembler** (`see`): constant folding, peephole, inlining; differential-tested vs unoptimized | stretch |
| 6 | **Conformance suite**: `T{ ... -> ... }T` harness written in Forth, run on the engine | stretch |
| 7 | **Profiler**: per-word step counts / hot-word bars | stretch |
