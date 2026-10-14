# Plinth — PLAN

## Concept
**Plinth** is a from-scratch, ext2-style **journaling filesystem** written in Rust (zero dependencies),
living inside an ordinary image file (or RAM), together with the tooling that proves it is crash-safe:

* a block-device abstraction whose in-memory implementation can **record every write and flush** and later
  rebuild *any* post-crash disk state the hardware is allowed to produce (writes between two flushes may land
  in any subset, any order, even torn at sector granularity);
* a **crash-consistency fuzzer** (in the spirit of CrashMonkey / ALICE) that crashes a random workload at every
  event, recovers, runs `fsck`, and compares the result with an in-memory reference model;
* an **fsck** that can also *repair* hand-corrupted images.

## Why it's interesting
Every earlier build in this repo sits *above* a filesystem (databases, VCS, KV stores, TSDB). Nothing models the
layer that makes "write then crash" safe. The interesting part is not "store files in blocks" — it is the
ordering protocol (journal → flush → checkpoint → flush → clear → flush) and *demonstrating* that each barrier is
load-bearing: the fuzzer must catch a deliberately broken journal (mutants) or it is worthless.

## Architecture
```
 CLI (plinth)  ──►  Fs<D: BlockDev>  ──►  Tx overlay (BTreeMap<blk,Block>)  ──►  Journal  ──►  BlockDev
                        │                                                         (desc + data + commit, CRC32)
   model.rs (oracle) ◄──┤ same Vfs trait                                       FileDev | MemDev(record/replay)
   fuzz.rs (diff + crash) ┘
   fsck.rs: analyze(image) → Issues → repair()   report.rs: HTML block map
```
On-disk layout (1 KiB blocks): `[super][journal][inode bitmap][block bitmap][inode table][data…]`,
128-byte inodes with 12 direct + 1 single + 1 double indirect pointer, 64-byte fixed directory entries
(`.`/`..` stored for real), file / dir / symlink, hard links, sparse files, full data journaling.

## Features
Required (core):
1. **R1 Filesystem core** — mkfs/mount, inode + bitmap allocators, indirect mapping, directories, files, symlinks
   (resolution with loop limit), hard links, rename (incl. dir moves, cycle check), truncate, sparse files.
2. **R2 Write-ahead journal** — every operation is one atomic transaction; CRC-protected descriptor/commit,
   three-barrier commit protocol, idempotent replay on mount, rollback of failed operations.
3. **R3 fsck** — full structural analysis (bitmaps, link counts, double-claimed blocks, orphans, dir tree,
   `.`/`..`, size vs. blocks, free counters) with precise issue codes.
4. **R4 Crash-consistency fuzzer + differential fuzzer** — reference model oracle; record/replay of device
   events; crash at every event with adversarial persistence subsets and torn writes; recover + fsck + state ∈ {S_c, S_c+1}.

Stretch:
5. **S1 fsck repair** — fix corrupted images (bit-flipped bitmaps, bad nlink, out-of-range / duplicated pointers,
   dangling entries, wrong `..`), reconnect orphans into `/lost+found`; verified by a corruption injector.
6. **S2 Mutation self-test** — injectable journal bugs (no CRC check, missing barrier, early clear, skip replay);
   the fuzzer must kill every one.
7. **S3 HTML block map** — self-contained visualisation of the image: who owns every block, per-file extents.
8. **S4 CLI** — `mkfs ls tree cat put get mkdir rm mv ln stat truncate df fsck map crashtest difftest corrupt`.

## Done means
`./verify.sh` green: unit tests, differential fuzz over several seeds, crash fuzz over several seeds with zero
failures, all mutants killed, repair fuzz, CLI end-to-end demo, HTML map rendered and checked in Chromium.
