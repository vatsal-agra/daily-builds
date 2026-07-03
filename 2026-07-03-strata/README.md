# Strata

A version control system built from scratch in pure Python (stdlib only) —
a real Git-like VCS with a content-addressable object store, a proper
Myers O(ND) diff engine, merge-base discovery over a commit DAG, and a
three-way (diff3-style) merge with real conflict markers.

**Status: Phase 4 — stretch features + polish complete.** Both stretch
features are done: a hardened three-way merge with real conflict
markers (see [REVIEW.md](./REVIEW.md) for the bugs found and fixed
during adversarial review), and an interactive, self-contained HTML
commit-graph visualizer (`strata viz`) — a real DAG layout with
per-branch lanes, click-to-inspect commits, and per-commit diffs
computed with the same Myers engine. Verified in an actual browser
(Playwright/Chromium) in both light and dark mode. Verification suite
and final ship next.

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
