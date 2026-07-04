# Palimpsest

A version control system built from scratch in pure Python — Git's object
model, staging area, branching, Myers diff, and (soon) three-way merge, with
no runtime dependency on the real `git` binary.

**Status: Phase 3 (adversarial review) complete.** 8 real issues found and
fixed (2 critical: deletions could never be committed, symlinks were
silently corrupted). See `REVIEW.md`. 65 tests green.

## What works so far
- `plm init` / `hash-object` / `cat-file` — content-addressable object store
- `plm add` / `status` / `commit` — staging area + tree/commit building,
  including staging deletions and symlinks correctly
- `plm branch` / `checkout` / `log` — branches, HEAD, working-tree switching
- `plm diff` — Myers-diff-powered unified diffs (worktree/index/commits),
  with a real "Binary files differ" for non-text content

See `PLAN.md` for the full design and feature list. Stretch features (merge,
HTML visualizer) still to come.
