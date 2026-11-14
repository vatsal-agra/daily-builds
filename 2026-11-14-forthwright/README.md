# Forthwright
*Status: Phase 2 complete (core build). Full README arrives in the ship phase. See [PLAN.md](PLAN.md).*

A Forth system in dependency-free JavaScript with **static stack-effect inference**, a **time-travel tracer**
and a **web IDE**.

## Try it now
```
node cli.js run examples/demo.fth        # run a program
node cli.js effects examples/demo.fth    # inferred effect of every word
node cli.js see examples/demo.fth fact   # disassembly (post-optimization)
node cli.js trace examples/demo.fth      # step trace
open web/index.html                      # browser IDE (no build step)
```

## Built so far
- [x] Forth engine (IR compiler + VM, ~130 words, CREATE/DOES>, CASE, VALUE/TO, strings, byte memory)
- [x] Stack-effect inference + declared-comment verification + branch/loop/return-stack checks
- [x] Recording tracer with step/scrub (CLI + UI) and profiler
- [x] Web IDE
- [x] (stretch groundwork) IR optimizer
