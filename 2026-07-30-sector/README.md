# Sector

A from-scratch FAT16 filesystem toolkit — byte-exact disk images, a real
cluster-chain allocator, 8.3 + VFAT long-name directory entries, and a
from-scratch reader, cross-verified against Linux's real `fsck.vfat`,
`mkfs.vfat`, and `mtools`.

**Status: Phase 2 (core build) complete.** All four required features are
implemented and manually verified end-to-end against real FAT tooling:

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
