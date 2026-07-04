# Palimpsest

A version control system built from scratch in pure Python — Git's object
model, staging area, branching, Myers diff, and (soon) three-way merge, with
no runtime dependency on the real `git` binary.

**Status: Phase 2 (core build) complete.** All 4 required features work
end-to-end and are covered by 55 passing tests, including differential tests
against the real `git` binary (blob/tree/commit hashes are byte-identical).

## What works so far
- `plm init` / `hash-object` / `cat-file` — content-addressable object store
- `plm add` / `status` / `commit` — staging area + tree/commit building
- `plm branch` / `checkout` / `log` — branches, HEAD, working-tree switching
- `plm diff` — Myers-diff-powered unified diffs (worktree/index/commits)

See `PLAN.md` for the full design and feature list. `REVIEW.md` (adversarial
review) and stretch features (merge, HTML visualizer) still to come.
