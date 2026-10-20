# Quarry
A from-scratch memory allocator (`malloc`) in C with an `LD_PRELOAD` drop-in, a heap-debug mode, and an
allocation trace recorder / replay simulator that compares allocator designs.

**Status: phase 3 of 6 — built, attacked, fixed** (`make test`).
Full documentation arrives with the ship phase; [PLAN.md](PLAN.md) has the design.

```
make                                   # build/libquarry.so, build/qsim, build/qgen, tests
make test                              # the whole verification suite
tools/quarry -- ls -la                 # run anything on top of quarry
tools/quarry --debug -- ./myprog       # redzones, double-free, use-after-free, leak report
tools/quarry --trace app.qtr -- ./app  # record allocations ...
build/qsim compare app.qtr             # ... replay them on quarry, glibc, first-fit, buddy, bump
build/qgen mixed -n 300000 -o w.qtr    # or generate a synthetic workload
```

## Progress
| Phase | State |
|---|---|
| 1 Plan | done |
| 2 Core build (required 1-4: allocator core, LD_PRELOAD drop-in, debug mode, trace + replay simulator) | done |
| 3 Adversarial review (REVIEW.md: 15 findings, all fixed with regression guards) | done |
| 4 Stretch + polish | pending |
| 5 Verification | pending |
| 6 Ship | pending |
