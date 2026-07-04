# Palimpsest

A version control system built from scratch in pure Python — Git's object
model, a staging area, branching, a real Myers diff engine, three-way merge,
and an interactive HTML commit-graph visualizer. It has **no runtime
dependency on the real `git` binary** — `git` is used only in the test suite,
as an oracle to verify Palimpsest's own hashes and merge-base logic are
byte-identical to the real thing.

## What it is

Under the hood, Palimpsest stores a repository exactly the way Git does:
content-addressable blob/tree/commit objects, SHA-1 addressed and
zlib-compressed, in a `.plm/` directory shaped like `.git/`. A file's
contents become a blob; a directory listing becomes a tree (with the same
"directories sort as if they had a trailing `/`" quirk real Git has, and the
same "directory mode is `40000`, not `040000`" gotcha that first-time
from-scratch implementers reliably get wrong); a snapshot plus parent
pointers becomes a commit. Branches are just named pointers into that
commit DAG, `HEAD` is a symbolic ref, and `checkout` rewrites the working
tree to match whatever tree a ref resolves to.

On top of that object model sit three classic algorithms, each implemented
from scratch and independently verified:

- **Myers' O(ND) diff algorithm** — the actual shortest-edit-script
  algorithm behind real `diff`/`git diff`, not a naive line-by-line
  comparison. Formats results as a real unified diff (`@@ hunk @@` headers,
  bounded context, binary-file detection).
- **Lowest-common-ancestor merge-base search** over the commit parent DAG.
- **Three-way (diff3-style) line merge** — anchors two Myers diffs (base→ours,
  base→theirs) on the common base, merges non-overlapping edits
  automatically, and emits real `<<<<<<<`/`=======`/`>>>>>>>` conflict
  markers only when both sides actually touch the same lines differently.

## How to run it

```bash
cd 2026-07-04-palimpsest
python3 -m palimpsest.cli init myrepo
cd myrepo
echo "hello" > a.txt
python3 -m palimpsest.cli add a.txt
python3 -m palimpsest.cli commit -m "first commit"
python3 -m palimpsest.cli log
```

Or just run the full guided walkthrough:

```bash
./demo.sh
```

Run the test suite directly:

```bash
python3 -m unittest discover tests -v
```

## Full feature list

**Required:**
1. **Content-addressable object store** — `init` / `hash-object` / `cat-file`;
   blob/tree/commit encoding byte-identical to real Git (differentially
   tested against `git hash-object` / `git mktree` / `git commit-tree`).
2. **Staging + commit workflow** — `add` / `status` / `commit`; the index
   tracks path → (mode, blob sha); `add` also correctly stages *deletions*
   of tracked files and correctly stores symlinks as their link-target text
   (not the dereferenced file they point to).
3. **Branches, HEAD, checkout, log** — `branch` / `checkout` (also aliased
   `switch`) / `log`; detached-HEAD checkout by sha prefix; refuses to
   clobber uncommitted changes unless forced.
4. **Myers diff engine** — `diff` (worktree ↔ index ↔ any commit, or commit
   ↔ commit), real unified-diff output, binary-file detection.

**Stretch:**
5. **Three-way merge** — `merge <branch>`; fast-forward detection,
   automatic merge-base search, clean auto-merge of non-conflicting edits,
   real conflict markers otherwise.
6. **Interactive HTML commit-graph visualizer** — `viz`; a self-contained
   single-file HTML app (no external assets, dark-mode aware) that lists
   every reachable commit with its branch labels, and shows a live unified
   diff for whichever commit you click.

## Why I chose this today

Every previous entry in this repo's ledger is a physics engine, ray tracer,
audio synthesizer, SAT solver, compression codec, or language runtime.
Version control is a different shape of problem — a Merkle DAG plus a
handful of classic string/graph algorithms — but more importantly, it's a
system with a **canonical, deployed, already-correct reference
implementation sitting right there in `$PATH`**. That turns "does this look
right?" into "is this SHA-1 the same as `git`'s?" — a much sharper bar. It
paid off immediately: the differential test against `git mktree` caught a
real bug during core build (Git writes directory tree-entries as mode
`"40000"`, not the `"040000"` almost everyone assumes), and the same
philosophy — verify against something authoritative rather than eyeballing
the output — carried into the diff engine (checked against a brute-force
LCS oracle and against the real `patch(1)` command applying 500 generated
diffs) and the merge engine (merge-base checked against `git merge-base`).

## Where a human could take this next

- **Packfiles** — real Git compacts loose objects into delta-compressed
  packfiles; Palimpsest still writes one zlib blob per object.
- **A real network protocol** — `clone`/`push`/`fetch` between two
  repositories over an actual transport, not just local filesystem access.
- **Rebase** — replaying a commit range onto a new base, reusing the same
  three-way merge machinery already built here.
- **Index performance** — the index is a flat JSON file re-read/re-hashed on
  every `status`; fine at this scale, would want a real binary index +
  mtime-based skip logic for large trees.
- **Octopus merges / full merge-base ALL** — the merge-base search returns
  *a* correct common ancestor via BFS, not the complete "best common
  ancestors" set real Git computes for pathological criss-cross histories.
- **Rename detection** in diffs and merges (similarity-based, like
  `git diff -M`), which Palimpsest doesn't attempt — a deleted+added pair
  today just shows up as a delete and an add.

See `PLAN.md` for the original design doc and `REVIEW.md` for the full
adversarial-review writeup (10 real issues found and fixed, including two
critical ones: deletions could never be committed at all, and symlinks were
silently corrupted into the content they pointed at).
