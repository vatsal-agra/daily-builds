# Sector

## Concept

A from-scratch **FAT16 filesystem toolkit**: a byte-exact implementation of the
FAT16 on-disk format (BIOS Parameter Block, dual FAT tables, fixed-size root
directory, cluster-chain data allocation, 8.3 short names, and Microsoft's
VFAT long-file-name extension) — the same format that lives on every USB
stick, SD card, and EFI system partition. Not a wrapper around the OS's own
filesystem calls: `sector` builds the disk image byte-by-byte, walks cluster
chains by hand, and writes directory entries at the exact offsets the FAT
spec requires.

## Why it's interesting

Every prior build in this repo that touches "storage" has worked at the
*logical* layer: a B+tree keyed by SQL rows (PicoSQL), an LSM-tree keyed by
bytes (Strata), a content-addressable object store (three VCS builds). None
of them has gone one layer further down, to the actual **block-device
format** an operating system's kernel parses directly — fixed-width binary
structs at fixed byte offsets, a on-disk linked list (the FAT chain) instead
of a pointer, and a legacy 8.3-name scheme retrofitted decades later with a
genuinely clever backward-compatible hack (VFAT long names hidden inside
directory entries that look deleted to any reader that doesn't understand
them).

It also comes with an unusually strong verification story. Ubuntu ships
independent, real-world FAT tooling: `mkfs.vfat` (format), `fsck.vfat`
(structural validator used by every Linux box that's ever fscked a USB
drive), and `mtools` (`mdir`/`mcopy`/`mtype`/`minfo` — read/write FAT images
without root or a loopback mount). That means **three independent real
oracles**, not just self-consistency:
- images `sector` formats must pass `fsck.vfat -v` clean
- files `sector` writes must be byte-identical when read back by `mcopy`/`mtype`
- files written into an image by real `mcopy` must be byte-identical when
  read back by `sector`'s own from-scratch reader (round-trip in both
  directions, on both sides of the format)

## Architecture

```
sector/
  bpb.py       # boot sector / BIOS Parameter Block: pack/unpack, validation
  fat.py       # the FAT table itself: 16-bit entry get/set, chain walk,
               # chain allocation, free-cluster bitmap, chain free
  direntry.py  # 8.3 short directory entries + VFAT long-name entries
               # (encode/decode, short-name checksum, LFN <-> short pairing)
  image.py     # FatImage: the high-level object every command uses —
               # mkfs / mkdir / write_file / read_file / list_dir / unlink /
               # stat / tree, built entirely from bpb+fat+direntry
  cli.py       # `sector` command-line tool
  inspector.py # builds the self-contained HTML disk visualizer
tests/
  test_bpb.py, test_fat.py, test_direntry.py, test_image.py
  test_oracle.py   # cross-checks against real fsck.vfat / mtools
demo.sh
```

Data flow for "write a file": `image.py` walks the root directory (or a
subdirectory's cluster chain) for a free 32-byte slot, allocates a cluster
chain in `fat.py` sized to the file, writes the content into those clusters,
and writes a short 8.3 entry (+ VFAT long-name entries if the name needs
them) pointing at the first cluster. Reading reverses exactly that: find the
entry, follow its start cluster through the FAT chain, concatenate cluster
bytes, truncate to the stored file size.

## Feature list

**Required:**
1. **`mkfs`** — format a byte-exact FAT16 image from scratch (boot sector,
   two identical FAT copies, fixed root directory region, data region) that
   `fsck.vfat -v` accepts as a valid, clean filesystem, and that real
   `mdir`/`minfo` (mtools) can list and inspect.
2. **File write with real cluster-chain allocation** — write file content of
   arbitrary size (spanning many clusters) by allocating a genuine FAT
   linked chain (not a contiguous-only shortcut), terminated with the
   correct end-of-chain marker, verified byte-identical against `mcopy`
   pulling the same file back out.
3. **Directory entries: 8.3 short names + VFAT long names** — create files
   and directories with correct short-name generation (`~1` collision
   suffixes), attributes, and timestamps, *and* full VFAT long-file-name
   entries (UTF-16LE, checksum-linked to the short entry, `~1`-style
   fallback short name) for names that don't fit 8.3 — verified against
   `mtools`' own LFN handling in both directions.
4. **From-scratch reader** — given *any* valid FAT16 image, including ones
   built entirely by the real `mkfs.vfat` + `mcopy` (never touched by
   `sector`'s own writer), list directories recursively and read file
   contents byte-for-byte correctly — the acid test that the reader
   actually understands the format rather than only its own writer's
   conventions.

**Stretch:**
5. **Delete + free-space reclamation** — unlink a file or empty directory,
   free its whole cluster chain in the FAT, and prove reclaimed clusters get
   reused (write a new file after deleting an old one; `fsck.vfat` still
   reports the image clean, no orphaned chains, no lost clusters).
6. **Interactive HTML disk inspector** — a self-contained visualizer built
   from a real image: annotated boot-sector byte layout, a rendered
   directory tree, and a cluster-allocation map (which clusters belong to
   which file, which are free) — the same category of "what does this
   binary format actually look like" view `xxd`/`ncdu` give separately, but
   for one FAT image, over HTTP-free static HTML.

Both stretch features are planned; the required four are the hard gate for
Phase 2.
