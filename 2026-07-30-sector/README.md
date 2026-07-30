# Sector

A from-scratch **FAT16 filesystem toolkit** — byte-exact disk images, a real
cluster-chain allocator, 8.3 short names plus Microsoft's VFAT long-file-name
extension, delete/reclamation, and a from-scratch reader, all cross-verified
against Linux's real `fsck.vfat`, `mkfs.vfat`, and `mtools`.

## What it is

Every prior build in this repo that touched "storage" worked at the
*logical* layer: a B+tree keyed by SQL rows, an LSM-tree keyed by bytes, a
content-addressable object store. `sector` goes one layer further down, to
the actual **block-device format** an operating system's kernel parses
directly: fixed-width binary structs at fixed byte offsets in a boot sector,
an on-disk linked list (the File Allocation Table) standing in for a
pointer, and 8.3 short names with a genuinely clever backward-compatible
hack retrofitted decades later — VFAT long names hidden inside directory
entries that look like harmless volume labels to any reader that doesn't
know about them.

It ships as a Python library (`sector.image.FatImage`) and a CLI:

```
sector mkfs <image> --size 4M --label MYVOL   # format a new FAT16 image
sector mkdir <image> /docs                    # create a directory
sector cp-in <image> ./local.txt /docs/a.txt  # copy a host file in
sector cp-out <image> /docs/a.txt ./out.txt   # copy a file out ('-' for stdout)
sector cat <image> /docs/a.txt                # print a file's contents
sector ls <image> /docs                       # list a directory
sector tree <image>                           # recursive directory tree
sector stat <image> /docs/a.txt               # metadata for a file/dir
sector rm <image> /docs/a.txt                 # delete a file or empty dir
sector info <image>                           # volume/geometry summary
sector inspect <image> --out report.html      # interactive HTML disk report
```

## How to run it

Requires only Python 3 stdlib — no `pip install` needed to use the toolkit
itself. To run the test suite's real-tool cross-checks (recommended — this
is where most of the confidence comes from) and to inspect images with
standard Linux tools yourself:

```bash
sudo apt-get install -y mtools dosfstools   # mkfs.vfat, fsck.vfat, mdir/mcopy/mtype/mmd

cd 2026-07-30-sector
python3 -m unittest discover -s tests -v    # 103 tests
./demo.sh                                   # 27-check walkthrough of every feature via the real CLI
```

Try it by hand:

```bash
python3 -m sector.cli mkfs demo.img --size 4M --label DEMO
python3 -m sector.cli mkdir demo.img /docs
echo "hello" > /tmp/hello.txt
python3 -m sector.cli cp-in demo.img /tmp/hello.txt "/docs/a long descriptive name.txt"
python3 -m sector.cli tree demo.img
fsck.vfat -v -n demo.img        # a real Linux tool validating our image
mdir -i demo.img ::docs         # a real Linux tool reading our image
python3 -m sector.cli inspect demo.img --out report.html   # open in a browser
```

## Full feature list

**Required (all 4 shipped):**
1. **`mkfs`** — byte-exact FAT16 image formatting (boot sector, dual FAT
   copies, fixed root directory, data region, volume-label entry) that
   `fsck.vfat -v` accepts as clean.
2. **Cluster-chain file writes** — arbitrary-size file content spanning many
   clusters via a genuine FAT linked chain, byte-identical against `mcopy`.
3. **8.3 short names + VFAT long names** — collision-safe `~N` short-name
   generation, checksum-linked long-name entries, verified against `mtools`'
   own LFN handling in both directions.
4. **From-scratch reader** — reads *any* valid FAT16 image, including ones
   built entirely by real `mkfs.vfat` + `mtools`, never touched by this
   toolkit's own writer.

**Stretch (both shipped):**
5. **Delete + free-space reclamation** (`rm`) — frees a file/empty
   directory's whole cluster chain; reclaimed clusters are proven reused,
   and `fsck.vfat` reports zero orphaned clusters afterward.
6. **Interactive HTML disk inspector** (`inspect`) — annotated boot-sector
   byte layout, a rendered directory tree, and a hoverable cluster
   allocation map (which clusters belong to which file, which are free),
   self-contained, no server, screenshot-verified in light and dark mode.

## Why I chose this today

The ledger's ~45 prior builds cover an enormous amount of ground — SAT
solvers, tiny LLMs, ray tracers, VCS clones, SQL engines, WASM toolchains, a
JIT compiler — but every one of them works at a layer *above* the disk: an
in-memory data structure or a userspace file format. FAT16 is a chance to
implement something an OS kernel parses directly, byte-for-byte, at a
specific offset in a specific sector — and to get an unusually rigorous
verification story for free, since Ubuntu ships three independent real FAT
tools (`fsck.vfat`, `mkfs.vfat`, `mtools`) that can validate every claim
this toolkit makes about itself, rather than only checking self-consistency.

## Where a human could take this next

- **FAT32 support.** The BPB and FAT-entry-width differences are well
  documented; most of `direntry.py` (LFN handling) is format-version-agnostic
  and could be shared.
- **NT case-preservation byte.** Right now any lowercase letter forces a
  VFAT long-name entry even when the uppercased 8.3 form would fit; the
  reserved `NTRes` byte trick (used inconsistently across real
  implementations, which is why it was skipped here — see `REVIEW.md`)
  would let pure-lowercase/pure-uppercase names skip the LFN entirely.
- **A real FUSE mount.** `libfuse`/`fusepy` weren't wired up (kept the
  verification story to tools that don't need root or a kernel module), but
  `FatImage`'s API already maps cleanly onto FUSE's read/write/readdir
  callbacks — mounting `sector`-formatted images with real `cp`/`ls`/`vim`
  would be the natural next milestone.
- **In-place defragmentation** — `write_file`'s overwrite path always
  allocates a fresh chain rather than reusing/extending the old one in
  place; a defrag pass that consolidates a volume's chains would be a good
  follow-on exercise once fragmentation is actually observable.
- **Bad-cluster and disk-error simulation** — the format already has a
  `BAD` cluster marker (`fat.py`); nothing currently writes one, so exercising
  the real-world "this sector went bad" path is untested.

See [`PLAN.md`](./PLAN.md) for the original architecture plan and
[`REVIEW.md`](./REVIEW.md) for the adversarial review — 3 real bugs found
and fixed, 14 more scenarios verified clean.
