# Adversarial review

Approach: two scripted attack passes (`tests/adversarial/` — reproduced here
from the ad hoc scripts used during the review, see Phase 5 for the
permanent regression suite) hammering the implementation with the kind of
inputs a hostile user or a genuinely full disk would produce, checking every
result against real `fsck.vfat` as well as internal consistency (no cluster
leaks, correct byte-for-byte content). 17 scenarios total.

## Bugs found and fixed

### 1. CRITICAL — cluster leak when the root directory is full

`FatImage._create_entry` allocated the new file's **data cluster(s) first**,
then tried to reserve directory-entry slot(s) for it. When the root
directory (a fixed 512-entry region on FAT16 — it cannot grow, unlike a
subdirectory) was already full, slot reservation correctly raised
`DirEntryError`, but the data cluster it had *already* allocated a moment
earlier was never freed: the FAT permanently marked it used, with nothing
in any directory ever pointing at it. Confirmed independently by real
`fsck.vfat`, which reported "Reclaimed 1 unused cluster" on an image where
the 512th write had been rejected as expected.

**Fix:** reorder `_create_entry` to reserve the directory slot(s) *first*
(`_alloc_slots`, which is where root-full failure is detected), and only
allocate data/subdirectory clusters after that succeeds. A failed create now
touches the FAT exactly zero times. Regression test: fill root to capacity,
attempt one more create, assert both a clean error *and* `fsck.vfat` reports
zero reclaimable clusters afterward.

### 2. CRITICAL — FAT region padding entries treated as real free clusters

`Fat.from_bytes` (used by `FatImage.open`, i.e. every time a saved image is
reopened) blindly turned the *entire* on-disk FAT region into in-memory
entries. A FAT region is sized in whole sectors, so it is almost always
padded past the last real cluster (e.g. an 8095-cluster volume's FAT region
holds 8192 entry slots — 97 are padding). Those padding slots read back as
`0x0000` (FREE), and `Fat.allocate()` happily handed them out as if they
were real data clusters. The resulting "cluster number" pointed **past the
end of the data region** — any write through it would silently corrupt
whatever comes after the volume in the image (or, for a maximally-sized
volume, run off the end of the file entirely.

Caught directly: reopening a freshly-formatted 4 MiB image reported 8180
free clusters against a volume with only 8095 clusters total — free count
*exceeding* total count is impossible and was the tell.

**Fix:** `Fat.from_bytes` now requires the real `count_of_clusters` and
trims to exactly `count_of_clusters + 2` entries (the `+2` for the two
reserved housekeeping slots), discarding sector-padding. Regression test:
open a saved image, assert `free_clusters <= count_of_clusters`, and that a
write immediately after reopening still passes `fsck.vfat`.

### 3. MODERATE — overwrite-on-disk-full could destroy the old file

`write_file`'s overwrite path freed the existing file's cluster chain
*before* allocating the replacement. If the replacement allocation then
failed with `FatFullError` (a legitimately full disk, not a bug on its own),
the directory entry on disk still pointed at the old first cluster, but the
FAT had already marked that whole chain free — so a subsequent read walked
into a cluster the FAT layer now (correctly) refuses to treat as part of a
chain, and the file's original content was unrecoverable even though the
overwrite itself never succeeded.

**Fix:** allocate and write the *new* chain first; only free the old chain
after the new one is confirmed in place. A failed overwrite now leaves the
original file exactly as it was. Regression test: fill a volume to within 2
clusters of capacity, attempt to overwrite a small file with one far larger
than remaining space, assert `FatFullError` *and* the original content is
still readable byte-for-byte afterward.

## Things checked and found correct (no bug, but worth recording)

- **12-way short-name collisions** (`identical name 0.txt` .. `identical
  name 11.txt`) each got a unique `~1`..`~12` short name with no collisions
  and correct per-file content, cross-checked against `fsck.vfat`.
- **Cluster-boundary file sizes** (`cluster_size - 1`, exactly
  `cluster_size`, `cluster_size + 1`, `2 * cluster_size`) all round-trip
  byte-for-byte — no off-by-one in the chain-length calculation.
- **Unicode/emoji long names** (Japanese, accented Latin, emoji) round-trip
  through UTF-16LE-encoded LFN entries correctly and pass `fsck.vfat`.
- **255-character long name** (VFAT's real ceiling — 20 LFN entries × 13
  chars, minus room for the NUL terminator) round-trips correctly.
- **15-level directory nesting** plus forcing a subdirectory's own cluster
  chain to grow past its first cluster (by creating more entries than fit
  in one cluster) both work; the grown chain was verified to actually be
  ≥2 clusters, not just "didn't crash".
- **Path edge cases**: case-insensitive lookup (`/sub/file.txt` finds
  `/Sub/File.TXT`), doubled slashes, and trailing slashes on directories all
  resolve correctly.
- **Illegal names** (empty, 300 characters, embedded `/`, control
  characters, leading/trailing whitespace) are all rejected with a specific
  exception, never an unhandled crash.
- **mkfs geometry boundaries**: a 32 KiB image (too small for the FAT16
  cluster-count floor) and an 8 GiB image (too large even at 64 KiB
  clusters) are both rejected by `BPBError` rather than silently producing
  a volume that's actually FAT12 or unrepresentable as FAT16; an 8 MiB
  volume in between builds correctly.
- **Garbage/truncated input to `FatImage.open`** (random bytes, a 4-byte
  buffer) raises `BPBError` instead of an unhandled `struct.error` or
  `IndexError`.
- **Save → reopen → modify → save → reopen** round-trips all data correctly
  across three separate `FatImage` instances backed by the same file — no
  bug from in-memory state not being fully captured by `save()`.
- **Every CLI error path** exercised (missing image, missing file, missing
  directory, too-small `mkfs` size) exits non-zero with a `sector: error:
  ...` message and never leaks a raw Python traceback to the user.

## Known, deliberate simplifications (not bugs)

- Any name containing a lowercase letter always gets a VFAT long-name entry,
  even when its uppercased 8.3 form would otherwise fit losslessly (e.g.
  `readme.txt` gets an LFN pointing at `README~1.TXT` rather than the
  bare-fitting `README.TXT`). This mirrors the conservative choice most
  non-Windows FAT implementations make rather than relying on the
  non-standard NT-reserved-byte case-preservation trick, which different
  operating systems interpret inconsistently. Documented, not "fixed" — it
  produces a fully spec-valid volume either way.
- Overwriting a file always allocates an entirely fresh cluster chain rather
  than reusing already-allocated clusters that could fit the new size. This
  is simpler and was deliberately kept that way after fix #3 made it safe
  (old data survives any allocation failure); it is not more space-lossy
  once the write succeeds, since the old chain is freed immediately after.
