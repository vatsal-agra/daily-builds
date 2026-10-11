# Delve (in progress)
Symbolic execution engine with a from-scratch bit-vector SMT solver (own CDCL SAT solver, bit-blaster, term layer).

Status after Phase 4: required features 1–4 plus stretch features (equivalence checker, formula solver, HTML report, solver stats/caching) are done; see PLAN.md / REVIEW.md.
Try: `python3 -m delve analyze examples/triage.dl` · `python3 -m delve equiv examples/equiv/clamp_a.dl examples/equiv/clamp_b.dl` · tests: `python3 tests/run_all.py`
