# Reaper — a garbage-collector laboratory (C++17)

**Status: Phase 2 done** — required features 1–4 work end to end:

- heap core + verifier (`src/heap.*`), root-slot mutator API
- mark-sweep, mark-compact (Lisp2), Cheney copying collectors
- generational collector (nursery, write barrier, remembered set)
- differential fuzzer against a never-collecting oracle: `make && ./reaper fuzz`

Build: `make`. Try: `./reaper list`, `./reaper run generational lru-cache`, `./reaper fuzz --seeds 5`.
Full README (features, design, next steps) arrives in Phase 6. See PLAN.md.
