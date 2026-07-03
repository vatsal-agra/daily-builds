# Adversarial review

I went through Strata as a hostile reviewer, deliberately trying to break
each piece and find corners where the "from scratch" implementation would
diverge from a real VCS's guarantees. Every issue below was found by
actually running the scenario (not by inspection alone), and every one is
fixed and re-verified in this repo's current state.

## Correctness bugs

1. **Myers diff cross-check used the wrong oracle at first.** My initial
   fuzz harness compared against `difflib.SequenceMatcher`, which is a
   *heuristic* matcher, not a minimal-edit-distance one — it disagreed
   with the true minimum on cases like `['a'] -> ['b','b','b']`. Replaced
   the oracle with a real O(N·M) DP computation of `len(a)+len(b)-2·LCS`
   (the true minimum indel distance) and re-ran 12,000 random cases plus
   edge cases — all pass. Separately cross-checked `unified_diff()` output
   byte-for-byte against Python's own `difflib.unified_diff()` across
   2,000 random cases (identical output, including hunk headers).

2. **Hunk-header formatting was wrong for empty ranges.** A brand-new or
   fully-deleted file produced `@@ -1,0 ...@@` instead of the standard
   `@@ -0,0 ...@@` (the convention where a zero-length range is anchored
   at the position *before* it, matching GNU diff / `git diff` /
   `difflib`). Fixed in `diff.py::_hunk_header`.

3. **Three-way merge silently dropped conflicting insertions at the end
   of a file** (or any point where an insert-opcode sits exactly on the
   boundary between two "unchanged" regions). The original algorithm
   computed sync points only from the *intersection of equal ranges* and
   never gave zero-width insert opcodes their own hunk to be evaluated —
   so if both branches appended different content at EOF, one side's
   line was silently discarded instead of raising a conflict. Rewrote
   `merge.py` around a proper two-pointer walk over both diffs'
   opcode lists that explicitly drains insert opcodes at each base
   position before processing content spans. Re-verified with: an EOF
   dual-append case (now correctly conflicts), 12,000 property-based
   fuzz cases (one-side-unchanged never conflicts and reproduces the
   changed side exactly; identical changes on both sides never
   conflict; disjoint-region edits merge silently and correctly;
   same-line edits on both sides always conflict and preserve both
   texts) — 0 failures across all properties.

4. **Merge commits lost their second parent.** After a merge stopped for
   conflicts, resolving and running `strata commit` produced an ordinary
   single-parent commit — the graph edge back to the other branch was
   gone, even though the file content had in fact been merged. Added a
   `MERGE_HEAD` file (same idea as Git's), written when `merge()` hits a
   conflict and consumed by the next `commit()` to build a proper
   2-parent merge commit; cleared on success. Also guards against
   starting a second merge while one is unresolved.

5. **`commit()` refused to record a legitimate deletion.** Committing
   "delete the only tracked file" left the index empty, and `commit()`
   had a blanket `if not self.index.entries: raise ...` guard that
   rejected it — even though an empty tree is a perfectly valid commit
   (all files deleted). Removed the blanket guard; the existing
   "identical to parent" check still correctly rejects genuine no-op
   commits.

6. **`strata add <deleted-file>` had no effect.** There was no path from
   "I deleted a tracked file" to "commit records the deletion" — `add()`
   only hashed files that still existed, so a real `rm` could never be
   committed. Added deletion staging: if a given path (file or directory)
   no longer exists but matches tracked index entries, those entries are
   dropped from the index instead of erroring.

## Security-relevant bugs (path traversal)

7. **Branch names weren't validated against path separators.**
   `strata branch '../../evil'` passed the (incomplete) character
   blocklist and would have written a ref file outside
   `.strata/refs/heads/` via unsanitized `os.path.join`. Fixed by
   centralizing validation in `_branch_ref_path()`: reject any segment
   equal to `""`, `"."`, or `".."`, and additionally verify the
   resolved path is still inside `refs_dir` before ever touching the
   filesystem. Verified the attack no longer escapes and no longer
   creates any file outside the repo.

8. **`strata add` could ingest files from outside the repository.**
   `strata add ../secret.txt` (or any path resolving above `root`) was
   accepted, silently pulling outside content into the object store
   under a nonsensical `../`-prefixed index path, only to fail later
   with a confusing "illegal tree entry name" at commit time. Now
   rejected immediately, with a clear error, at `add()` time.

9. **Tree entry names weren't validated on the read path, and the write
   path missed `/`.** `encode_tree()` blocked tab/newline/NUL and
   `.`/`..`, but not a name containing `/` or `\` — and `decode_tree()`
   (the path that actually matters, since it's what interprets objects
   *read back from disk* during checkout) did no name validation at
   all. A hand-crafted or corrupted tree object with an entry named
   e.g. `../../../etc/passwd` would have had that path joined directly
   onto the working directory root during checkout — a path-traversal
   write. Added a shared `_validate_entry_name()` enforced on both
   `encode_tree()` and `decode_tree()`, and confirmed by hand-crafting
   malicious tree bytes and checking `decode_tree` now rejects them.

## Safety / data-loss bugs

10. **`checkout` and fast-forward `merge` could silently clobber
    untracked files.** The dirty-worktree check before checkout only
    looked at *tracked* changes (staged/unstaged); an untracked file
    that happened to collide with a path in the target commit's tree
    got overwritten with no warning — a real "I just lost work" trap
    that real VCSes explicitly guard against. Added an untracked-vs-
    target-tree collision check to `checkout()`, switched the internal
    fast-forward-merge checkout call from `force=True` to `force=False`
    so it goes through the same guard, and added an analogous
    untracked-collision check to the real 3-way `merge()` path. Verified
    all three refuse with a clear message instead of overwriting.

## Robustness (no raw tracebacks on bad input)

11. **Object-store corruption surfaced as a raw Python traceback.** A
    previous project in this repo's history called out exactly this
    anti-pattern as its worst adversarial-review finding, so I checked
    for it here too: `ObjectNotFound`/`CorruptObject` (from `store.py`)
    and `InvalidObject` (from `objects.py`) aren't subclasses of
    `RepositoryError`, so the CLI's existing exception handling didn't
    catch them. Hand-corrupted a real object file on disk (flipped a
    byte in a stored commit) and confirmed `strata log`/`strata status`
    crashed with a full traceback. Added a second `except` clause in
    `cli.main()` for this exception family, producing a clean one-line
    `strata: fatal: object store error: ...` message instead. Re-ran the
    corruption scenario — now exits cleanly with a readable message.

## UX gaps

12. **`strata diff <ref>` (a single ref, no second one) silently ignored
    the ref and fell back to `diff_worktree()`** — genuinely confusing,
    since real `git diff <commit>` compares that commit to the working
    tree. Added `Repository.diff_ref_worktree()` and wired the CLI to
    use it when exactly one ref is given.

13. **PLAN.md's architecture section promised a `.strata/config` file
    for user name/email, but nothing read or wrote it** — every commit
    used a hardcoded author string with no way to change it. Rather than
    quietly drop the promised feature, implemented it: `strata config
    <key> [value]` gets/sets `user.name`/`user.email`, and `commit()`
    now builds the author string from config when both are set.

## Dead / vestigial code removed

14. `Repository.unstage_missing()` was an empty stub (docstring, no
    body) left over from an earlier draft — deleted; its actual job is
    now done by `add()`'s deletion-staging (see #6).
15. `cmd_add`'s `if not args.paths: ...` guard was unreachable —
    argparse's `nargs="+"` on the `paths` argument already refuses to
    parse a `strata add` with zero paths (verified: exits via argparse's
    own usage error before `cmd_add` ever runs). Removed.

## What a fresh run-through now hits

Re-ran the full set of scenarios above after fixes (path traversal via
`add`/`branch`, untracked-file collision on `checkout`/`merge`, EOF merge
conflict, deletion commit/staging, corrupted object, single-ref diff,
config-driven author, nested-directory checkout with empty-dir pruning,
detached HEAD, empty commit message, unknown ref) — zero of the listed
issues reproduce.

## Accepted design limitation (not a bug, flagged for honesty)

`merge_base()` picks the common ancestor with the greatest commit
timestamp when there are multiple candidates. For most histories
(including every criss-cross-merge scenario I tried) this picks the
same "best" base a full lowest-common-ancestor algorithm would, but it
isn't a formal proof of optimality the way the diff engine's oracle-
verified minimality is. A fully general LCA-with-redundant-base-pruning
algorithm was judged out of scope for a from-scratch VCS built in a
day; this is called out here rather than silently shipped as if it were
airtight.
