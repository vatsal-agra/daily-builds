# Sector

A from-scratch FAT16 filesystem toolkit — byte-exact disk images, a real
cluster-chain allocator, 8.3 + VFAT long-name directory entries, and a
from-scratch reader, cross-verified against Linux's real `fsck.vfat`,
`mkfs.vfat`, and `mtools`.

**Status: Phase 4 (stretch + polish) complete.** Both stretch features are
shipped: `sector rm` (delete + free-space reclamation, verified to actually
reuse reclaimed clusters and stay `fsck.vfat`-clean) and `sector inspect`
(a self-contained interactive HTML disk report — annotated boot-sector byte
layout, directory tree, and a hoverable cluster-allocation map — screenshot-
verified in headless Chromium with zero console errors in both light and
dark themes).

See [`REVIEW.md`](./REVIEW.md) for the Phase 3 findings — 3 real bugs found
and fixed (two of them cluster-accounting corruption bugs: a leak on a
root-directory-full write, and free-cluster-count corruption on every
image reopen caused by FAT sector-padding being treated as real free
clusters) plus 14 other scenarios checked and confirmed correct.

All four required features are implemented and verified end-to-end against
real FAT tooling:

- `sector mkfs` produces images `fsck.vfat -v` accepts as clean.
- `sector cp-in` writes files (including multi-cluster ones) that `mcopy`/`mtype`
  read back byte-identical.
- Long file names (VFAT LFN entries, checksum-linked, `~N` short-name
  collision handling) round-trip through real `mdir`.
- `sector`'s own reader correctly lists/reads a volume built **entirely** by
  real `mkfs.vfat` + `mtools` (`mmd`/`mcopy`), including nested directories
  and long names — proof it understands the format, not just its own
  writer's conventions.

See [`PLAN.md`](./PLAN.md) for the architecture and full feature list.
Usage instructions and final results will land in Phase 6.
