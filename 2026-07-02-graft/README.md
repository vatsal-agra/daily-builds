# Graft

A version control system built from scratch in pure Python — content-addressable
object store, staging area, commit DAG, Myers diff, three-way merge and a
custom packfile format.

**Status: Phase 2 (core build) complete.** The 4 required features work
end-to-end: object store, staging+status+commit, log/branch/checkout, and a
from-scratch Myers diff. See [PLAN.md](PLAN.md) for the full architecture.

## Quick start

```sh
cd your-project
python3 /path/to/graft/bin/graft init .
python3 /path/to/graft/bin/graft add somefile.txt
python3 /path/to/graft/bin/graft commit -m "message"
python3 /path/to/graft/bin/graft log
```

Blob objects are byte-identical to real Git (`graft hash-object` ==
`git hash-object`), verified via subprocess differential tests.

Adversarial review and stretch features (merge, packfiles, viz) are next.
