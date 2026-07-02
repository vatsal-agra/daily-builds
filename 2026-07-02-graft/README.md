# Graft

A version control system built from scratch in pure Python — content-addressable
object store, staging area, commit DAG, Myers diff, three-way merge and a
custom packfile format.

**Status: Phase 4 (stretch + polish) complete.** All 4 required features plus
all 3 stretch features (merge, packfiles/gc, HTML visualizer) work end-to-end.
Adversarial review (see [REVIEW.md](REVIEW.md)) found and fixed 5 real bugs.
See [PLAN.md](PLAN.md) for the full architecture.

## Quick start

```sh
cd your-project
python3 /path/to/graft/bin/graft init .
python3 /path/to/graft/bin/graft add somefile.txt
python3 /path/to/graft/bin/graft commit -m "message"
python3 /path/to/graft/bin/graft log
```

Blob/tree/commit objects are byte-identical to real Git (verified via
subprocess differential tests against `git hash-object`/`git write-tree`).

## Commands

`init`, `hash-object`, `cat-file`, `add`, `rm [--cached]`, `status`,
`commit -m`, `log [rev]`, `branch [name] [start] [-d name]`,
`checkout <target> [-f]`, `diff [--cached]`, `merge <branch>`, `gc`,
`viz [-o out.html]`.

Next: full test suite + demo script (Phase 5), then final ship (Phase 6).
