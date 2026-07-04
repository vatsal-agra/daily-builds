# Adversarial review

Hunting my own work as a hostile reviewer. Each finding was reproduced first,
then fixed; "Fix" describes what actually changed.

## 1. CRITICAL — no way to ever commit a file deletion

`repo.add(path)` raised `RepoError` whenever the given path did not exist on
disk, even if it was currently tracked. Real Git treats `git add <path>` on a
path that used to be tracked but is now missing as *staging the removal*.
Without this, Palimpsest could stage and commit new/changed files but a
removed file could **never** be committed as removed — a hole in the single
most basic VCS operation ("staging + commit workflow" is a required feature).

Repro:
```
plm init; echo hi > a.txt; plm add a.txt; plm commit -m "add a"
rm a.txt
plm add a.txt   # -> "plm: error: pathspec did not match any files: 'a.txt'"
```

**Fix:** `add()` now checks, for every requested path that no longer exists
on disk, whether it (or, for a requested directory, anything under it) is
still present in the index; if so, it stages the removal instead of
erroring. Added `test_add_stages_deletion_of_tracked_file` and
`test_add_directory_stages_deletions_within_it` and a CLI test exercising the
full delete → add → commit → log round trip.

## 2. CRITICAL — symlinks silently corrupted (wrong content, wrong checkout)

`add()` used `open(path, "rb")` unconditionally, which **dereferences**
symlinks — a tracked symlink's blob ended up containing the *target file's
content*, not the symlink's own target string, even though `mode_for_path`
correctly tagged it `120000`. On the way back out, `checkout()` never
special-cased `MODE_SYMLINK` either, so even correctly-stored symlink blobs
would be checked out as a plain regular file containing the path text
instead of a real symlink.

Repro: track `a.txt` and a symlink `link_to_a -> a.txt`; the blob sha stored
for `link_to_a` came out **identical** to `a.txt`'s blob sha (content
duplication) instead of a tiny blob containing the six bytes `a.txt`.

**Fix:** `add()` now reads `os.readlink()` for symlink entries instead of
opening the file, and `checkout()` now calls `os.symlink()` for
`MODE_SYMLINK` entries instead of writing file bytes. Added
`test_symlink_stores_link_target_not_referent_content` and
`test_checkout_recreates_symlink`.

## 3. HIGH — file/directory path collision crashes with a raw traceback

Staging a path that collides with an existing tracked directory prefix (or
vice versa — e.g. committing `conf/settings.txt`, then later replacing the
whole `conf` directory with a plain file named `conf` and committing that)
crashed `_build_tree` with `TypeError: 'tuple' object does not support item
assignment` — a raw Python traceback shown straight to the user instead of a
clean, actionable error.

**Fix:** `_build_tree` now detects the collision while walking the index and
raises a `RepoError` naming the conflicting path
(`"'conf' cannot be both a file and a directory — remove the old entries
first"`). Added `test_file_directory_path_collision_raises_clean_error`.

## 4. MEDIUM — binary diffs produced garbled, misleading output

`diff` decoded every file as UTF-8 with `errors="replace"`, so a changed
binary file produced a nonsensical line-level diff full of replacement
characters and embedded NUL bytes dumped straight to the terminal, instead
of the standard `Binary files a and b differ` real diff/git tools print.

**Fix:** `_read_side`/`cmd_diff` now sniff for a NUL byte (the standard
binary heuristic real Git itself uses) and, when either side is binary,
emit `Binary files <label_a> and <label_b> differ` instead of attempting a
line diff. Added `test_diff_binary_file_reports_differ_not_garbage`.

## 5. LOW — dead `mtime`/`size` fields on `IndexEntry`

`IndexEntry` carried `mtime`/`size` fields that were always written as `0`/
`0.0` and never read anywhere — a vestigial leftover from an earlier design
that suggested a stat-cache optimization that was never actually built.
Since `status()` always re-hashes tracked files from disk (correct, simple,
and fast enough at this scale), keeping unused fields around is exactly the
kind of "half-finished implementation" this review is supposed to catch.

**Fix:** removed both fields; `IndexEntry` now only carries `path`, `mode`,
`sha`.

## 6. LOW — commit log printed a raw unix timestamp

`plm log` printed `Date:   1783131742 +0000` instead of a human-readable
date, which is a real usability wart for the one command users read output
from most.

**Fix:** formats via `email.utils.formatdate`-style rendering
(`time.strftime` on the stored epoch/timezone) to print e.g.
`Date:   Wed Jul 4 09:22:22 2026 +0000`.

## 7. LOW — checkout walked the entire object store every time

`_prune_empty_dirs` used `os.walk(root, topdown=False)`, which — unlike
`topdown=True` — cannot prune `dirnames` to skip descending into `.plm/`;
it silently declined to *delete* anything under `.plm/` but still walked
the whole object store (every `objects/xx/*` shard) on every single
`checkout`. Harmless today, but pointless work that gets worse every commit.

**Fix:** switched to `topdown=True` with `.plm` pruned from `dirnames`
before descending, and collects candidate directories bottom-up from the
already-restricted walk for removal.

## 8. LOW — corrupt/malformed objects raised low-level exceptions

A corrupted `.plm/objects/xx/yyyy...` file (truncated zlib stream, or valid
zlib but missing the `<type> <size>\0` header) surfaced a bare `zlib.error`
or `ValueError: not enough values to unpack` instead of a clear message.

**Fix:** `ObjectStore.read_raw` now catches `zlib.error` and malformed-header
cases and re-raises as a `ValueError` with the offending sha in the message.

## What I checked and did *not* change

- Myers diff / unified diff: already differentially verified against a
  brute-force LCS oracle (2000 cases) and against real `patch(1)` applying
  500 random generated diffs byte-for-byte — no issues found.
- Blob/tree/commit hashing: differentially verified byte-identical against
  real `git hash-object`/`git mktree`/`git commit-tree` (this *did* catch a
  real bug during core build — directory tree-entry mode must be `"40000"`,
  not `"040000"`, fixed before this review phase and covered by
  `test_matches_real_git_mktree`).
- `checkout`'s "refuse if dirty" safety check is intentionally coarser than
  real Git's (real Git only blocks when the *specific* file differs between
  current and target trees; we block on *any* dirty tracked file). This is
  a deliberate, documented simplification, not a bug — it is strictly safer
  (never silently discards changes), just occasionally more conservative.
