# Forthwright
*Status: Phase 3 complete (adversarial review). Full README arrives in the ship phase. See [PLAN.md](PLAN.md), [REVIEW.md](REVIEW.md).*

A Forth system in dependency-free JavaScript with **static stack-effect inference**, a **time-travel tracer**,
an **IR optimizer** and a **web IDE**.

```
node cli.js run examples/demo.fth        # run a program
node cli.js effects examples/demo.fth    # inferred effect of every word
node cli.js see examples/demo.fth fact   # disassembly (post-optimization)
node cli.js trace examples/demo.fth      # step trace
node test/review.js && node test/fuzz.js # regression + analyzer soundness fuzz
open web/index.html                      # browser IDE (no build step)
```

Progress: Phase 1 plan ✔ · Phase 2 core (engine, analyzer, tracer, IDE) ✔ · Phase 3 review (11 findings fixed) ✔
