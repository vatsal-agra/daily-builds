# Argus (work in progress)

Explicit-state model checker for concurrent systems — see PLAN.md.

## Status
* Phase 1 (plan) ✓
* Phase 2 (core build) ✓ — language + compiler, safety BFS, LTL/Büchi liveness with fairness,
  trace rendering + independent replay validator
* Phase 3 (adversarial review) ✓ — 14 findings in REVIEW.md, all fixed with regression tests
* Phase 4 (stretch + polish) ✓ — partial-order reduction, simulator, Graphviz export, `verify`
  regression runner, interactive HTML report (`--html`), colour output, input hardening

```
python3 -m argus check models/philosophers.arg --html report.html
python3 -m argus verify models
```
