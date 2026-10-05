# Reaper — a garbage-collector laboratory (C++17)

**Status: Phase 4 done** — all 4 required features plus all 4 stretch features work:

- required: heap core + verifier · mark-sweep / mark-compact / copying · generational (write barrier, remembered set) · differential fuzzer vs. a never-collecting oracle
- stretch: incremental tri-colour collector · benchmark harness (`reaper bench`) · mutator scripting language (`reaper script`, see `examples/`) · heap-map HTML visualiser (`reaper viz`)

Build: `make`. Try: `./reaper list`, `./reaper bench`, `./reaper fuzz`, `./reaper script examples/barrier.rpr`, `./reaper viz out.html`.
Phase 5 (tests / demo) and the full README follow. See PLAN.md and REVIEW.md.
