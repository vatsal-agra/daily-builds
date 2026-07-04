# Strata

A version control system built from scratch in pure Python (stdlib
only, zero dependencies) — a real Git-like VCS with a content-addressable
object store, a proper Myers O(ND) diff engine, merge-base discovery over
an arbitrary commit DAG, a three-way (diff3-style) merge with real
conflict markers, and an interactive HTML commit-graph visualizer.

## What it is

Every prior daily build in this repo has been "implement a classic
algorithm from scratch" — SAT solvers, path tracers, a SQL engine, a
bytecode VM, a compression toolkit, music synthesizers. None of them
built the tool that manages *this repository's own history*: a version
control system. Strata fills that gap. It's not a toy that only handles
the happy path — it implements the actual algorithms that make a VCS
trustworthy, and every one of them is verified against an independent
oracle or a real adversarial-review pass (see [REVIEW.md](./REVIEW.md)):

- **Content-addressable object store**: blobs/trees/commits hashed by
  SHA-256 over a self-describing frame, zlib-deflated on disk, with
  integrity checking on every read (a single flipped bit is detected,
  not silently returned).
- **Myers O(ND) diff**: the real shortest-edit-script algorithm (not a
  naive O(n²) LCS table), verified to be truly minimal against a
  brute-force DP oracle across 12,000+ random cases, and its unified-diff
  rendering verified byte-for-byte identical to Python's own
  `difflib.unified_diff` across 2,000+ cases.
- **Merge-base discovery** over a real commit DAG (ancestor-set BFS,
  handles multi-parent merge commits).
- **Three-way merge**: a two-pointer synchronized walk over both sides'
  diffs against the common ancestor, producing real `<<<<<<<`/`=======`/
  `>>>>>>>` conflict markers only where changes genuinely overlap —
  verified with 1,000+ property-based fuzz cases (disjoint edits always
  merge silently, identical edits never conflict, same-line edits always
  conflict, nothing is ever silently dropped).

## How to run it

No install step — pure stdlib, just point `PYTHONPATH` at this folder:

```bash
cd 2026-07-03-strata
export PYTHONPATH="$PWD:$PYTHONPATH"

python3 -m strata init myrepo && cd myrepo
python3 -m strata config user.name "Your Name"
python3 -m strata config user.email "you@example.com"

echo "hello" > a.txt
python3 -m strata add a.txt
python3 -m strata commit -m "Initial commit"

python3 -m strata branch feature
python3 -m strata checkout feature
echo "world" >> a.txt && python3 -m strata add a.txt && python3 -m strata commit -m "Edit"

python3 -m strata checkout main
python3 -m strata diff main feature      # Myers-engine unified diff
python3 -m strata merge feature          # fast-forward or 3-way merge

python3 -m strata viz -o graph.html      # interactive commit-graph visualizer
```

Run the test suite (98 tests) or the end-to-end demo:

```bash
python3 -m unittest discover -s tests -v
./demo.sh
```

## Full feature list

**Required (all four implemented, verified end-to-end — see PLAN.md):**

1. Content-addressable object store (`init`, integrity-checked reads)
2. Staging + committing: `add` (incl. staged deletions), `status`,
   `commit`, `log`
3. Branching & checkout, including detached HEAD and safety checks that
   refuse to silently clobber uncommitted *or* untracked work
4. Real Myers-algorithm diffing with unified-diff rendering

**Stretch (both implemented):**

5. Three-way merge with real conflict markers, `MERGE_HEAD` tracking
   (so a resolved conflict produces a proper 2-parent merge commit, not
   a history-losing single-parent one)
6. Interactive self-contained HTML commit-graph visualizer (`strata
   viz`) — SVG DAG with per-branch lanes (simplified `git log --graph`-
   style layout), branch/HEAD chips, click-to-inspect commits with
   metadata and a per-commit unified diff against its first parent,
   dark/light mode aware, verified rendering in a real headless browser

**Extra, beyond the plan:**

- `strata config` (user.name/user.email, used as commit author)
- `strata show` (inspect a commit + its diff)
- Clean, traceback-free error handling on corrupt objects, bad refs,
  and invalid input
- Two path-traversal vulnerabilities found and fixed during adversarial
  review (malicious branch names, `add` reaching outside the repo, and
  tree objects with `/`-containing entry names) — see REVIEW.md

## Why I chose this today

Looking at `LEDGER.md`, this repo has built five SAT solvers, three path
tracers, two chess engines, two music synthesizers — all genuinely
different implementations of well-trodden "from scratch" algorithms, but
clustered in the same territory (numerical/graph algorithms rendered to
an HTML visualizer). A version control system is a different kind of
system entirely: it's about a Merkle DAG as the source of truth, content
addressing for integrity and dedup, and the two hardest correctness
problems in the space — diffing and merging — both of which have crisp,
checkable correctness properties (minimality, no silent data loss) that
made rigorous verification possible rather than just plausible. It's
also the one category of tool every other daily build in this repo
implicitly depends on but has never itself been the subject.

## Where a human could take this next

- **Networked clone/push/fetch**: a smart-HTTP-ish protocol so two
  Strata repos can actually sync, turning this from a local tool into a
  real distributed VCS.
- **Packfiles**: the object store is one loose file per object today;
  a delta-compressed pack format would cut repo size dramatically on
  real-world histories.
- **A general LCA algorithm** for `merge_base()`: the current
  most-recent-common-ancestor heuristic is right in every case tested
  but isn't a formally general lowest-common-ancestor-with-redundant-
  base-pruning algorithm (see the "accepted limitation" in REVIEW.md).
- **Rename detection** in the diff/merge engines (currently a renamed
  file shows as a full delete + full add).
- **`.strataignore` glob patterns** are supported for `add`/`status`,
  but there's no `strata rm --cached`, partial-file staging (`add -p`),
  or stash — the porcelain commands a daily user would eventually want.
- **Submodules / worktrees** for the truly ambitious.
