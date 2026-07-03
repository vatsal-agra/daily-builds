# Strata

A version control system built from scratch in pure Python (stdlib only) —
a real Git-like VCS with a content-addressable object store, a proper
Myers O(ND) diff engine, merge-base discovery over a commit DAG, and a
three-way (diff3-style) merge with real conflict markers.

**Status: Phase 3 — adversarial review complete.** All four required
features work end-to-end. 15 real issues were found by hostile testing
(correctness bugs in diff/merge, two path-traversal vulnerabilities,
silent data-loss risks on checkout/merge, raw tracebacks on corrupt
objects, UX gaps, dead code) and every one is fixed — see
[REVIEW.md](./REVIEW.md) for the full list and how each was verified.
Stretch features (merge conflicts + HTML visualizer — merge is already
built and hardened) and final polish are next.

See [PLAN.md](./PLAN.md) for the full design and feature list.

## Quick taste

```
$ python3 -m strata init myrepo && cd myrepo
$ echo "hello" > a.txt && python3 -m strata add a.txt
$ python3 -m strata commit -m "Initial commit"
$ python3 -m strata branch feature && python3 -m strata checkout feature
$ echo "world" >> a.txt && python3 -m strata add a.txt && python3 -m strata commit -m "Edit"
$ python3 -m strata checkout main && python3 -m strata diff main feature
```
