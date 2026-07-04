# Adversarial Review

Conducted by attacking the Phase 2/4 implementation as a hostile reviewer:
running real workflows end-to-end, stress-testing edge cases by hand, and
fuzzing the two algorithmically subtle pieces (Myers diff, 3-way merge)
against independent oracles.

## Issues found and fixed

1. **CRITICAL — `graft add`/`graft rm` broken from a subdirectory.**
   Paths given on the command line were joined directly onto the repo root
   (`os.path.join(repo.worktree, p)`), ignoring the actual current working
   directory. Running `graft add foo.txt` from inside `sub/` looked for
   `<repo-root>/foo.txt` instead of `<repo-root>/sub/foo.txt` and failed with
   a bogus "pathspec did not match" error — real git resolves pathspecs
   relative to cwd. Fixed with `_to_repo_relpath()`, which resolves a
   user-supplied path against `os.getcwd()` first and rejects paths outside
   the worktree. Verified: `cd sub && graft add nested.txt` now stages
   `sub/nested.txt`.

2. **CRITICAL — 3-way merge falsely conflicted on non-overlapping edits.**
   The first merge implementation built "anchors" by intersecting the
   equal-block coverage of base→ours and base→theirs, and treated *every*
   gap between anchors as one atomic chunk to compare. Two people editing
   *different, non-adjacent* lines (ours changes line 2, theirs changes
   line 3) got merged into a single comparison chunk spanning both edits,
   which never matched either side and always conflicted. Rewrote the
   algorithm to operate on the two sides' independent *changed intervals*
   in base coordinates, only grouping (and thus only conflicting on)
   intervals that genuinely *overlap*; adjacent-but-disjoint intervals stay
   separate and both apply cleanly. Verified against real git behavior on
   the same scenario (clean merge, no markers) and fuzzed 500 random
   base/ours/theirs triples — 0 anomalies (see `tests/test_merge.py`).

3. **HIGH — same rewrite, second-order bug: single-sided regions still
   compared against reconstructed content.** After fix #2, a region touched
   by only one side was still reconstructed for *both* sides and compared
   for equality — but the untouched side's "reconstruction" fell back to
   *base* content, which never equals the touched side's new content, so
   every single-sided edit conflicted with itself. Fixed by skipping the
   comparison entirely when only one side has a change in the group (no
   conflict is possible when the other side didn't touch it at all).

3b. **HIGH — third-order bug in the same area: "non-overlapping" was too
   permissive.** Having fixed #2/#3, a unit test asserting that two
   *directly adjacent* single-line edits (no unchanged line between them)
   should merge cleanly turned out to encode a wrong assumption. Checked
   empirically against real `git merge`: editing two immediately-adjacent
   lines **does** conflict in real git (it only merges cleanly with at
   least one unchanged line of separation between the two edits — real
   git's merge is conservative about *touching* hunks, not just
   *overlapping* ones), and two insertions at the exact same zero-width
   position also conflict. Changed the interval-grouping condition from
   strict overlap (`s < group_end`) to touching-or-overlap (`s <=
   group_end`), and replaced the hand-written assumption with an automated
   differential fuzzer (`tests/test_merge_git_compat.py`) that shells out
   to `git merge-file` — the real 3-way file merge — as an oracle. Ran
   1,000 random base/ours/theirs triples: 0 conflict-detection mismatches
   and 0 content mismatches on the triples both sides resolved cleanly.

4. **MEDIUM — binary files produced a garbled, misleading text diff.**
   Both `graft diff` and the merge's content-merge path decoded arbitrary
   bytes with `errors="replace"` and ran the *line* diff/merge machinery
   over the resulting mush (readable garbage, silently-wrong hunks, and for
   merge: line-based conflict markers spliced into binary data, corrupting
   it). Added `diffalgo.is_binary()` (git's own heuristic: a NUL byte in the
   first 8000 bytes); `graft diff` now prints `Binary files a/x and b/x
   differ`, and merge treats a binary-vs-binary difference as a whole-file
   conflict (keeps `ours`, flags the path) instead of attempting a line
   merge.

5. **LOW — `graft log | head` crashed with an unhandled `BrokenPipeError`.**
   Piping output into a command that closes the pipe early (`head`, `less
   -F` quitting, etc.) raised a raw traceback. `main()` now catches
   `BrokenPipeError` and exits 0 quietly, matching real git/coreutils
   behavior.

6. **Demo-script bug (not a product bug), caught by running the demo, not
   just reading it.** `demo.sh`'s conflict-detection check piped `graft
   merge` into `grep -q` and read `$?` afterward — but the script also sets
   `pipefail`, so `$?` reflected `graft merge`'s own exit code (1, correct
   for a real conflict) rather than `grep`'s. The check always failed
   regardless of whether the conflict message was actually present,
   turning a *correct* product feature into a *failing* demo step. Fixed
   by capturing `graft merge`'s stdout via command substitution first and
   grepping that captured string, sidestepping the pipefail interaction
   entirely.

## Things checked and found correct (no fix needed)

- Blob/tree/commit loose-object bytes are **byte-identical to real git**
  for the same content (verified via subprocess `git hash-object`/`git
  cat-file`/`git write-tree` in `tests/test_git_compat.py`), including the
  git-specific tree sort order quirk (directories sort as if they had a
  trailing `/`, so `lib.py` sorts before the directory `lib`).
- Myers diff edit-distance and reconstructed opcodes checked against a
  brute-force O(NM) DP edit-distance oracle over 3,000 random string pairs
  — 0 mismatches.
- Fast-forward, already-up-to-date, and genuine-conflict merge paths all
  produce the expected result end-to-end (checked manually and in
  `tests/test_merge.py`); merge conflict/clean-content behavior matches
  real `git merge-file` on 1,000 random fuzz trials with 0 mismatches
  (`tests/test_merge_git_compat.py`).
- `graft gc` round-trips every object (loose bytes deleted only after an
  independent re-read of every packed object matches byte-for-byte) and is
  idempotent (running it twice with nothing new packs 0 objects, no
  errors). Compression ratio is >1x on realistic near-duplicate text files
  (2.1x in testing) but can be <1x on a handful of tiny (few-byte) test
  fixtures — expected and consistent with any container format's per-entry
  overhead dominating at that scale (real git has the same property), not
  a bug in the delta logic itself.
- Detached-HEAD commits, checkout back to a branch, and symlink
  (mode `120000`) add/commit/checkout all round-trip correctly.
- Repo-not-found, missing-pathspec, and empty-history `log`/`commit`
  errors all produce clean messages on stderr with exit code 1 rather than
  a traceback.
