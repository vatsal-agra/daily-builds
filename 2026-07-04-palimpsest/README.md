# Palimpsest

A version control system built from scratch in pure Python — Git's object
model, staging area, branching, Myers diff, three-way merge, and an
interactive HTML commit-graph visualizer, with no runtime dependency on the
real `git` binary.

**Status: Phase 5 (verification) complete.** 92 unit tests + a 19-check
end-to-end `demo.sh` all green, exercising every feature through the real
CLI exactly as a user would.

## What works
- `plm init` / `hash-object` / `cat-file` — content-addressable object store
- `plm add` / `status` / `commit` — staging area + tree/commit building,
  including staging deletions and symlinks correctly
- `plm branch` / `checkout` / `log` — branches, HEAD, working-tree switching
- `plm diff` — Myers-diff-powered unified diffs (worktree/index/commits),
  with a real "Binary files differ" for non-text content
- `plm merge` — merge-base search + line-level three-way merge, fast-forward
  detection, and real conflict markers when both sides touch the same lines
- `plm viz` — self-contained interactive HTML commit-graph + diff viewer

Run `./demo.sh` for a full end-to-end walkthrough of every feature.

See `PLAN.md` for the full design and feature list, `REVIEW.md` for the
adversarial review (10 issues found and fixed across phases 3–4).
