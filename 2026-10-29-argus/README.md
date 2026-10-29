# Argus (work in progress)

Explicit-state model checker for concurrent systems — see PLAN.md.

## Status
* Phase 1 (plan) ✓
* Phase 3 (adversarial review) ✓ — 14 findings in REVIEW.md, all fixed with regression tests
* Phase 2 (core build) ✓ — language + compiler, safety BFS, LTL/Büchi liveness with fairness,
  trace rendering + independent replay validator, 15 models in `models/`.

```
python3 -m argus check models/philosophers.arg
python3 -m argus verify models
```
