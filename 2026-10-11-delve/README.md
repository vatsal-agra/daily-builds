# Delve (in progress)
Symbolic execution engine with a from-scratch bit-vector SMT solver (own CDCL SAT solver, bit-blaster, term layer).

Status after Phase 3 (adversarial review):
- Phase 1 — PLAN.md written
- Phase 2 — required features 1–4 working: DelveLang + interpreter, SMT/CDCL solver, symbolic executor, bug finder with replay-confirmed counterexamples
- Phase 3 — REVIEW.md: 9 findings reproduced and fixed, regression tests in `tests/test_review.py`

Try: `python3 -m delve analyze examples/triage.dl` · tests: `python3 tests/run_all.py`
