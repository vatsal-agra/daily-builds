# Palimpsest — a version control system built from scratch

## Concept

A from-scratch implementation of Git's core model — content-addressable
objects, a staging index, commits, branches, diffing, and merging — in pure
Python, with **no dependency on the `git` binary at runtime**. The twist that
makes it verifiable rather than "trust me": every low-level primitive (blob
hashing, tree hashing, commit hashing, tree sort order) is byte-identical to
real Git's object format, so we can differentially test it *against the real
`git` binary* — same inputs, same `GIT_AUTHOR_DATE`/`GIT_COMMITTER_DATE`, same
SHA-1 out. If our SHA doesn't match git's SHA for the same tree, we have a bug,
full stop. That's a much stronger oracle than "does it look right."

## Why this is interesting

Every previous daily build in this repo touched physics, ray tracing, audio
synthesis, SAT solving, compression, or language runtimes. Version control is
a different kind of system: it's a Merkle DAG (content-addressable storage +
hash-linked history), a set of classic string algorithms (Myers diff, 3-way
merge / diff3), and a graph algorithm (lowest common ancestor for merge base)
— all wired together into a tool a human actually uses daily, that can be
checked against a real, deployed, battle-tested implementation (`git` itself)
byte-for-byte. It's also a nice showcase of "worse is better" precision: the
object model looks simple but has exact formatting rules (mode strings, tree
entry sort order, null-byte framing) that are easy to get subtly wrong, which
is exactly the kind of thing this repo's adversarial-review phase is good at
catching.

## Architecture

```
palimpsest/
  objects.py     # Blob/Tree/Commit encode+decode, sha1, zlib store/load
  repository.py  # .git-like ".plm" dir, index/staging, add/status/commit,
                 # branches/refs, HEAD, checkout/switch, log/history walk
  diffalgo.py    # Myers O(ND) shortest-edit-script diff + unified diff format
  merge.py       # merge-base (LCA over parent DAG), 3-way line merge w/
                 # conflict markers
  cli.py         # argparse subcommands mirroring git's UX
  viz.py         # generates a self-contained interactive HTML commit-graph
                 # + diff viewer for a repo
tests/
  test_objects.py     # differential vs `git hash-object` / `git write-tree`
  test_diff.py        # Myers vs brute-force LCS oracle + vs difflib
  test_merge.py       # merge-base vs `git merge-base`, 3-way merge cases
  test_repository.py  # end-to-end add/commit/branch/checkout/log
  test_cli.py          # CLI smoke tests
demo.sh
README.md
```

Storage format: a `.plm/` directory shaped like Git's `.git/` — `objects/xx/*`
(zlib-deflated, sha1-addressed), `refs/heads/*`, `HEAD` (symbolic ref),
`index` (staging area, JSON-encoded path -> blob sha + mode). Object encoding
is intentionally identical to real Git so hashes match.

## Feature list

**Required (4):**
1. **Content-addressable object store** — blob/tree/commit objects encoded in
   Git's exact byte format, SHA-1 addressed, zlib-compressed on disk;
   `hash-object` / `cat-file` CLI; verified byte-identical to `git
   hash-object` / `git write-tree` / `git commit-tree` for the same content
   and timestamps.
2. **Staging + commit workflow** — an index (staging area) tracking
   path -> blob sha/mode; `add`, `status` (untracked/modified/staged
   three-way diff against HEAD tree + working dir + index), `commit` building
   a real tree object from the index and a commit object with parent
   pointers.
3. **Branches, HEAD, checkout/log** — `branch`, `switch`/`checkout <ref>`
   (updates working directory + HEAD, detects uncommitted-change conflicts),
   `log` (commit graph walk, topological + first-parent), symbolic HEAD.
4. **Myers diff engine** — real O(ND) shortest-edit-script algorithm over
   lines, unified-diff output (`diff` command comparing working tree /
   index / commits / two commits); verified against a brute-force LCS
   oracle for minimality and against `difflib`/`diff -u` for output
   correctness.

**Stretch (2+):**
5. **Three-way merge** — lowest-common-ancestor merge-base search over the
   commit parent DAG, line-based 3-way merge (like `diff3`) producing
   `<<<<<<<`/`=======`/`>>>>>>>` conflict markers on real conflicts and clean
   auto-merges otherwise; `merge <branch>` CLI command.
6. **Interactive HTML commit-graph visualizer** — self-contained single-file
   HTML rendering the commit DAG (SVG graph, branch colors, HEAD pointer)
   with a click-through unified diff viewer per commit.
7. *(bonus, time permitting)* **Local clone/remote simulation** — `clone`
   between two on-disk `.plm` repos (object transfer + ref update), a minimal
   stand-in for push/pull/fetch.

## Verification strategy

Real `git` is installed in this environment and is used purely as an
oracle in tests (never as a runtime dependency of Palimpsest itself):
object hashes are compared 1:1 against `git hash-object`/`git write-tree`/
`git commit-tree` under pinned `GIT_AUTHOR_DATE`/`GIT_COMMITTER_DATE`/
identity env vars so the byte streams — and therefore the SHA-1s — must
match exactly. Diff minimality is checked against a brute-force LCS. Merge
base is checked against `git merge-base`.
