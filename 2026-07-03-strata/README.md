# Strata

A version control system built from scratch in pure Python (stdlib only) —
a real Git-like VCS with a content-addressable object store, a proper
Myers O(ND) diff engine, merge-base discovery over a commit DAG, and a
three-way (diff3-style) merge with real conflict markers.

**Status: Phase 5 — verification complete.** 98 automated tests
(`tests/`, `python3 -m unittest discover -s tests`) and a 9-step
end-to-end `demo.sh` walkthrough all pass, covering every required and
stretch feature — see [PLAN.md](./PLAN.md) for the feature list and
[REVIEW.md](./REVIEW.md) for the adversarial-review findings. Final
ship (this README + LEDGER) next.

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
