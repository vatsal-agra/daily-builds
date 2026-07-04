# Graft

A version control system built from scratch in pure Python — no `dulwich`,
no `pygit2`, no shelling out to real `git` for any of the actual logic.
Content-addressable object store, a staging area, a commit DAG, a from-scratch
Myers diff engine, three-way merge with conflict markers, and a custom
packfile format with delta compression.

The twist: real `git` is installed on the box this was built on, so Graft's
object encoding is **differentially verified against it** — `git cat-file`
can read Graft's raw loose objects directly, `git write-tree` on an
identical file layout produces the exact same SHA-1 Graft computes, and a
1,000-trial fuzzer checks Graft's three-way merge against real
`git merge-file` with zero mismatches.

## What it is

- **Object store** (`objecthash.py`) — blobs/trees/commits hashed with
  SHA-1 and zlib-deflated to disk in git's own loose-object layout
  (`objects/xx/yyyy...`), byte-identical to real git for the same content.
- **Staging area** (`index.py`, `worktree.py`) — `add`/`rm`/`status` with a
  real index file and three-way working-tree/index/HEAD comparison.
- **History** (`repository.py`) — branches, HEAD (attached and detached),
  parent-chain traversal, safe checkout that refuses to clobber
  uncommitted work.
- **Diff** (`diffalgo.py`) — a from-scratch Myers O(ND) diff producing a
  provably minimal edit script, formatted as git-style unified diffs with
  the same context-trimming/hunk-grouping algorithm as Python's `difflib`.
- **Merge** (`merge.py`) — BFS merge-base, fast-forward detection, and a
  line-level three-way content merge with `<<<<<<<`/`=======`/`>>>>>>>`
  conflict markers, matching real git's "touching hunks conflict, disjoint
  hunks with an unchanged line between them merge cleanly" semantics.
- **Packfiles** (`packfile.py`) — `graft gc` compacts loose objects into a
  single pack with copy/insert delta compression against a same-type
  anchor object, verifying every object round-trips before deleting the
  loose copies.
- **Visualizer** (`viz.py`) — `graft viz` renders a self-contained,
  clickable HTML commit graph with a per-commit diff view.

## How to run it

```sh
cd your-project
python3 /path/to/graft/bin/graft init .
python3 /path/to/graft/bin/graft add somefile.txt
python3 /path/to/graft/bin/graft commit -m "message"
python3 /path/to/graft/bin/graft log
```

Full command list: `init`, `hash-object [-w]`, `cat-file [-t|-s]`, `add`,
`rm [--cached]`, `status`, `commit -m`, `log [rev]`,
`branch [name] [start] [-d name]`, `checkout <target> [-f]`,
`diff [--cached]`, `merge <branch>`, `gc`, `viz [-o out.html]`.

### Testing

```sh
python3 -m unittest discover -s tests -p "test_*.py"   # 71 tests, all green
./demo.sh                                               # runnable walkthrough of every feature
```

## Full feature list

**Required (all shipped):**
1. Content-addressable object store, byte-identical to real git.
2. Staging area + status + commit, building real tree objects.
3. History graph: log/branch/checkout, attached & detached HEAD.
4. Myers diff engine with unified-diff output.

**Stretch (all shipped):**
5. Branching + three-way merge with conflict markers, `MERGE_HEAD` tracking
   so a post-conflict commit correctly gets two parents.
6. Packfiles with delta compression + `graft gc`, self-verifying before
   deleting loose objects.
7. *(bonus)* Interactive HTML commit-graph + diff visualizer (`graft viz`).

## Why this today

Nearly every developer uses git daily and almost nobody has built it. Under
the porcelain it's a small, elegant set of ideas — a Merkle DAG of immutable
objects, a minimal-edit-script diff algorithm, and a three-way merge — that
was meaty enough for a full day without repeating this repo's prior SAT
solvers, path tracers, or synths. It also came with a built-in oracle: real
`git` on the same machine, which turned "does this look right" into "is
this byte-identical to / does this exactly match real git," a much higher
bar than self-consistency. That oracle earned its keep — adversarial review
found and fixed 6 real issues (see [REVIEW.md](REVIEW.md)), including a
three-way-merge conflict-detection bug caught only by fuzzing against real
`git merge-file`, not by hand-written test cases (which had encoded a wrong
assumption about git's own behavior).

## Where a human could take this next

- **Binary index format** matching git's actual `.git/index` (currently a
  simple newline-delimited file — functionally complete but not
  byte-compatible with git tooling the way objects are).
- **Remote protocol** — a `clone`/`fetch`/`push` implementation of the
  smart HTTP or SSH git protocol, so two Graft repos (or Graft ↔ real git)
  could actually sync.
- **Rename detection** in diff/merge (currently a rename is a delete+add).
- **Multiple merge bases / recursive merge** for criss-cross histories
  (current BFS merge-base picks a single nearest common ancestor, which
  covers the common cases but not pathological octopus histories).
- **Delta chains** in the packfile format (currently one level only, all
  deltas point at a same-type anchor) and a real sliding-window match
  finder for better ratios on large repos.
- **Interactive rebase / cherry-pick**, built on the diff/merge primitives
  that already exist.
