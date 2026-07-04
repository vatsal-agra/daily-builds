# Graft — a version control system from scratch

## Concept

Git is the piece of software nearly every developer uses every day and
almost nobody has actually built. Underneath the porcelain it's a small,
elegant set of ideas: content-addressable storage, a Merkle DAG of
immutable objects, a three-way merge algorithm, and a diff algorithm that
finds a minimal edit script. **Graft** is a real implementation of all of
that from scratch in pure Python — no `dulwich`, no `pygit2`, no shelling
out to `git` for the actual logic.

The fun part: real `git` is installed on this machine, so Graft's object
encoding can be **differentially verified against real git** — we can
`git hash-object` and `git cat-file` the exact same bytes Graft writes and
assert byte-identical SHA-1s and zlib streams. That's a much stronger
correctness bar than "our own tests pass" — it means Graft's repositories
are (for loose objects) genuinely readable by real git tooling.

## Why this is interesting

- It's a DAG + hashing + diff + merge problem, which is meaty enough to
  fill a full day without being another SAT solver / path tracer / synth.
- It has a built-in oracle for differential testing (real `git`), which
  earlier builds in this repo had to construct by hand (brute-force SAT,
  finite differences, etc.) — here it already exists on disk.
- Three-way merge and Myers diff are genuinely subtle algorithms with
  real edge cases (renames, conflicting hunks, criss-cross merges) that
  reward an adversarial-review pass.

## Architecture

```
graft/
  objecthash.py   sha1 + zlib loose-object encode/decode (blob/tree/commit/tag)
  repository.py   .graft/ layout: objects/, refs/heads/, HEAD, config
  index.py        staging area (index file: path -> (mode, sha, size, mtime))
  diffalgo.py     Myers O(ND) diff -> unified diff hunks; tree diff
  merge.py        merge-base (BFS lowest common ancestor over commit DAG),
                   recursive tree merge, 3-way line-level content merge
                   with git-style <<<<<<< conflict markers
  packfile.py     custom pack format: object table + zlib + simple
                   copy/insert delta encoding against a similar-size base
  cli.py          `graft` command dispatch
  viz.py          static HTML commit-graph + diff visualizer
```

Object model mirrors git's: blobs are raw file bytes, trees are sorted
`mode name\0<20-byte-sha1>` entries, commits are text records
(tree/parent/author/committer/message) — all wrapped in a
`"<type> <size>\0<content>"` header and zlib-deflated to disk at
`objects/xx/yyyy...`, exactly like real git, so real `git cat-file -p`
can read a Graft object and `git hash-object` produces the identical SHA.

## Feature list

**Required (core, must fully work end-to-end):**
1. **Content-addressable object store** — `graft hash-object`/`cat-file`
   for blob/tree/commit objects; SHA-1 + zlib loose-object format
   differentially verified byte-for-byte against real `git`.
2. **Staging area + status/commit** — `graft add/rm/status/commit` with a
   real index file, working-tree vs. index vs. HEAD three-way status,
   and commits that build real tree objects from the index.
3. **History graph** — `graft log/branch/checkout` — parent-chain
   traversal, branch refs, HEAD (attached + detached), safe checkout
   that refuses to clobber uncommitted changes.
4. **Diff engine** — Myers O(ND) minimal-edit-script diff, unified-diff
   output for working-tree/index/commit-to-commit, verified against
   Python's own `difflib` oracle and against real `git diff`.

**Stretch:**
5. **Branching + three-way merge** — BFS merge-base, recursive tree
   merge, line-level 3-way content merge, conflict markers on real
   conflicts, clean fast-forward detection.
6. **Packfiles + gc** — `graft gc` packs loose objects into a custom
   pack file with copy/insert delta compression against a similar
   object, then unpacks losslessly; reports compression ratio.
7. *(bonus if time permits)* interactive HTML commit-graph + diff
   visualizer (`graft viz`) rendering the DAG and a colorized diff.

## Verification strategy

- Differential test every object hash/zlib stream against real `git
  hash-object -w` / `git cat-file` run via subprocess.
- Differential test diff output against Python `difflib` (edit-script
  minimality: total ops) and against `git diff --no-index`.
- Scripted merge scenarios: fast-forward, clean 3-way, and a real
  conflicting merge, checked against what real git produces in a
  throwaway repo.
- Round-trip packfile: pack N objects, delete loose copies, unpack,
  byte-compare content to originals.
