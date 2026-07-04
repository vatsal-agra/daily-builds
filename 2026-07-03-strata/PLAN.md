# Strata — a version control system built from scratch

## Concept

Every daily build in this repo so far has been "implement a classic
algorithm from scratch" (SAT solvers, path tracers, a SQL engine, a
bytecode VM, a compression toolkit, a music synth...). None of them has
built the tool that manages *this very repository's own history*: a
version control system. That's the gap today fills.

**Strata** is a from-scratch, dependency-free (Python 3 stdlib only)
version control system — a small but *real* Git-like VCS, not a toy
that only handles the happy path. It implements the actual algorithms
that make a VCS trustworthy:

- a **content-addressable object store** (blobs/trees/commits hashed
  by SHA-256, zlib-deflated on disk — the same core idea as Git's
  object database),
- the **Myers O(ND) diff algorithm** for real line-level diffs (the
  same algorithm `diff`/`git diff` use, not a naive LCS table),
- **merge-base discovery** over an arbitrary commit DAG (multiple
  parents, criss-cross merges) via ancestor-set BFS, and
- a **three-way merge** (diff3-style) that produces real conflict
  markers when two branches touch the same lines.

## Why this is interesting

A VCS is deceptively small on the surface ("it's just files in
folders") and deceptively deep underneath: content addressing gives
you deduplication and integrity for free, the object graph *is* a
Merkle DAG, and correct merging requires a real diff algorithm plus
correct common-ancestor discovery in a DAG that can have multiple
merge bases. Getting all of that right — and provably right, via a
brute-force diff oracle and round-trip object-store tests — is a
satisfying, self-contained systems problem, and building it teaches
you exactly what `git` is doing under the hood.

## Architecture

```
strata/
  __init__.py
  hashing.py      sha256 object ids, content framing ("<type> <size>\0<content>")
  objects.py      Blob / Tree / Commit — serialize/deserialize, zlib store I/O
  store.py        content-addressable object store on disk (.strata/objects/xx/yyyy…)
  index.py        staging area ("index") — path -> blob-hash, persisted as JSON
  diff.py         Myers O(ND) diff -> edit script -> unified diff renderer
  merge.py        merge-base (multi-parent ancestor BFS) + 3-way diff3 merge
  repository.py   high-level porcelain: init/add/commit/status/log/branch/
                   checkout/diff/merge — orchestrates the modules above
  cli.py          argparse CLI ("strata <command> ...")
  visualizer.py   renders a self-contained interactive HTML commit-graph

tests/
  test_hashing.py, test_objects_store.py, test_index.py,
  test_diff.py (incl. brute-force LCS oracle cross-check),
  test_merge.py, test_repository.py, test_cli_integration.py
demo.sh           scripted end-to-end walkthrough of every feature
```

On-disk layout under a repo's `.strata/`:
```
.strata/objects/<2-hex>/<62-hex>   zlib-deflated objects, content-addressed
.strata/refs/heads/<branch>        40/64-hex commit id the branch points at
.strata/HEAD                       "ref: refs/heads/main"  or a raw commit id (detached)
.strata/index                      JSON staging area: path -> blob hash + mode
.strata/config                     minimal repo config (user name/email)
```

## Feature list

**Required (core, must work end-to-end, no stubs):**

1. **Content-addressable object store** — `strata init`, then blobs,
   trees, and commits are hashed (SHA-256 over a Git-style
   `"<type> <len>\0<bytes>"` frame), zlib-compressed, and written to
   `.strata/objects/`. Reading an object back by hash reproduces the
   exact original bytes. Corrupting an object on disk is detected
   (hash mismatch on read).

2. **Staging + committing (add / status / commit / log)** —
   `strata add <paths>` walks the working tree, hashes changed files
   into blobs, and updates the index. `strata status` diffs
   working-tree ↔ index ↔ HEAD commit and reports
   added/modified/deleted/untracked. `strata commit -m <msg>` builds
   tree objects from the index (recursively, matching directory
   structure) and a commit object with parent linkage, author, and
   timestamp. `strata log` walks parent pointers to print history.

3. **Branching & checkout** — `strata branch <name>` creates a ref;
   `strata checkout <branch|commit>` updates the working directory to
   match the target tree (writing/removing files as needed), moves
   HEAD, and refuses to clobber uncommitted changes it would
   overwrite (matching real VCS safety behavior). Detached-HEAD
   checkout of a raw commit id also works.

4. **Real diffing (Myers algorithm)** — `strata diff` computes a
   proper shortest edit script between two blobs/trees with the
   O(ND) Myers algorithm (not naive O(n²) LCS) and renders unified
   diff output (`@@ -a,b +c,d @@`, `-`/`+`/context lines). Used by
   both `status` (working tree vs index) and `diff <ref> <ref>`
   (commit vs commit).

**Stretch:**

5. **Three-way merge with real conflict markers** — `strata merge
   <branch>` finds the merge-base via ancestor-set BFS over the
   (possibly multi-parent) commit DAG, then does a line-based diff3
   merge: non-overlapping changes merge silently, overlapping ones
   produce `<<<<<<<` / `=======` / `>>>>>>>` conflict blocks and a
   non-zero exit / merge-in-progress state, exactly like a real VCS.

6. **Interactive HTML commit-graph visualizer** — `strata viz` walks
   the full object graph and renders a single self-contained HTML
   file: commits laid out as a DAG (SVG, lanes per branch, edges to
   parents), branch/HEAD labels, and a click-a-commit panel showing
   its diff against its first parent (computed with the same Myers
   engine, rendered client-side from embedded JSON — no server
   needed).

(Time permitting, additional polish items: `.strataignore` glob
patterns, `strata show <commit>`.)
