# Sector

A from-scratch FAT16 filesystem toolkit — byte-exact disk images, a real
cluster-chain allocator, 8.3 + VFAT long-name directory entries, and a
from-scratch reader, cross-verified against Linux's real `fsck.vfat`,
`mkfs.vfat`, and `mtools`.

**Status: Phase 5 (verification) complete.** All required and stretch
features are implemented and verified:

- `sector mkfs` produces images `fsck.vfat -v` accepts as clean.
- `sector cp-in` writes files (including multi-cluster ones) that `mcopy`/`mtype`
  read back byte-identical.
- Long file names (VFAT LFN entries, checksum-linked, `~N` short-name
  collision handling) round-trip through real `mdir`.
- `sector`'s own reader correctly lists/reads a volume built **entirely** by
  real `mkfs.vfat` + `mtools` (`mmd`/`mcopy`), including nested directories
  and long names — proof it understands the format, not just its own
  writer's conventions.
- `sector rm` deletes files/empty directories and reclaims their clusters
  (verified reused, and `fsck.vfat`-clean afterward).
- `sector inspect` renders a self-contained interactive HTML disk report
  (boot-sector byte layout, directory tree, hoverable cluster-allocation
  map) — screenshot-verified in headless Chromium, zero console errors, both
  light and dark themes.

103 unit/integration tests (`python3 -m unittest discover -s tests`) plus a
27-check `./demo.sh` walking every feature through the real CLI — all green.

See [`PLAN.md`](./PLAN.md) for the architecture and feature list, and
[`REVIEW.md`](./REVIEW.md) for the adversarial review — 3 real bugs found
and fixed (two of them cluster-accounting corruption bugs: a leak on a
root-directory-full write, and free-cluster-count corruption on every image
reopen caused by FAT sector-padding being treated as real free clusters)
plus 14 other scenarios checked and confirmed correct.

Usage instructions and final results land in Phase 6.
