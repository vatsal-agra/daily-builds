# Strata

A version control system built from scratch in pure Python (stdlib only) —
a real Git-like VCS with a content-addressable object store, a proper
Myers O(ND) diff engine, merge-base discovery over a commit DAG, and a
three-way (diff3-style) merge with real conflict markers.

**Status: Phase 2 — core build complete.** All four required features
(object store, add/status/commit/log, branching & checkout, Myers
diffing) work end-to-end, verified by hand and by a brute-force LCS
oracle for the diff engine. Adversarial review is next.

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
