# Plinth — a journaling filesystem and the lab that proves it survives power loss

Plinth is an ext2-style filesystem written from scratch in Rust (zero dependencies, ~4,000 lines of library +
~1,600 lines of tests), living in an ordinary image file, with a write-ahead journal and — the real point — the
tooling to *demonstrate* crash safety instead of asserting it: a crash-state fuzzer that rebuilds every disk state
a real device is allowed to expose after power loss, an fsck that can repair vandalised images, and a set of
deliberately broken journals the fuzzer is required to catch.

```
$ plinth crashtest --seed 7 --ops 40
seed 7: 40 ops → 472 device events (366 writes, 66 flushes)
  explored 2669 crash states (366 with a torn write); 1192 needed journal replay; 11304 further states explored by crashing inside recovery itself
  every recovered state passed fsck and equals the state before or after the interrupted operation
$ plinth crashtest --seed 1 --bug no-journal-flush
  5 FAILURE(S) — mutant 'no-journal-flush' killed:
```

## Run it

```bash
cd 2026-10-14-plinth
cargo build --release                      # binary: target/release/plinth
./demo.sh                                  # 9-step guided tour (CLI, crash fuzz, mutants, repair, HTML map)
./verify.sh                                # everything: tests + extra fuzz seeds + mutants + Chromium check (~1.5 min)
cargo test --release                       # just the test suites
```

```
plinth mkfs img --size-mb 8                 plinth put img host.txt /docs/a.txt     plinth fsck img [--repair]
plinth tree img                             plinth get img /docs/a.txt out.txt      plinth map img map.html
plinth ls|cat|stat|mkdir|rm|rmdir|mv|ln|ln-s|truncate ...                           plinth df | journal img
plinth crashtest [--seed N --ops N --variants N --bug NAME --no-nested]             plinth difftest [--seed N --ops N]
plinth corrupt img <kind 0-15> [--seed N]   plinth bugs
```
Set `PLINTH_NOSYNC=1` to skip `fsync` (fast demos; defeats durability). Paths inside an image are absolute.

## Design

* **Layout** (1 KiB blocks): `[super][journal][inode bitmap][block bitmap][inode table][data…]`; 128-byte inodes with
  12 direct + single + double indirect pointers (max file 64.3 MiB, sparse files supported); 64-byte fixed directory
  entries with real `.`/`..`; files, directories, symlinks (loop-limited resolution), hard links.
* **Transactions**: every mutating call builds its block updates in an in-memory overlay and commits them as *one*
  journal transaction (full data journaling). Failed operations roll back without touching the disk. Writes bigger than a
  chunk (≤32 KiB, sized from the journal) are a sequence of individually atomic chunks.
* **Commit protocol**: write descriptor + data + commit block → **flush** → checkpoint to home locations → **flush** →
  retire the descriptor → **flush**. A CRC32 over sequence number, targets and every data block makes a torn or
  half-persisted journal detectable; replay is idempotent and itself crash-safe. After an I/O error mid-commit the mount
  turns read-only until a remount replays the journal.
* **Crash model**: `MemDev` records every `write`/`flush`. For *every* prefix of that event stream the fuzzer builds the
  durable image plus a none / all / random-subset (shuffled order) of the in-flight writes, plus one variant where a
  random write is torn at 512-byte sector granularity, then mounts (replaying), runs `fsck`, and demands the tree equal
  the reference model's state either before or after the interrupted operation (atomicity + durability of completed
  ops). For a sample of states it also **crashes again inside recovery** (double fault), and probes that the recovered
  filesystem still accepts writes.
* **Oracle**: `model.rs` is an independent, naive in-memory filesystem with identical error semantics; a differential
  fuzzer compares every result and the whole tree (contents, link groups, link counts, permissions) after random operations.

## Features

| | Feature | Status |
|-|---------|--------|
| R1 | Filesystem core: mkfs/mount, allocators, direct/indirect/double-indirect mapping, directories (growing past 12 blocks), files, symlinks, hard links, rename (dir moves, cycle check, replace rules), truncate, sparse files | ✅ |
| R2 | Write-ahead journal with CRC, 3-barrier commit, idempotent replay, rollback, poison-on-I/O-error | ✅ |
| R3 | fsck: 28 issue codes — bitmaps both ways, link counts, double-claimed/out-of-range/past-EOF blocks, orphans, dangling/duplicate entries, `.`/`..`, multi-parent dirs, sizes, dirty EOF tail, mtimes, free counters | ✅ |
| R4 | Crash-consistency fuzzer (record/replay, subsets, torn writes, double faults) + model-differential fuzzer | ✅ |
| S1 | `fsck --repair`: fixes bitmaps/counters/nlink/pointers/dup blocks/dangling entries/`..`; reconnects orphans (whole subtrees) into `/lost+found`; idempotent; verified against a 16-kind corruption injector | ✅ |
| S2 | Mutation self-test: 5 injectable journal bugs, all must be killed (`replay-no-flush` only dies to the double-fault mode) | ✅ |
| S3 | `plinth map`: self-contained HTML block-ownership map (hover, click-to-highlight extents, filters, fsck verdict), checked in headless Chromium | ✅ |
| S4 | Full CLI (22 commands) with clear errors and exit codes | ✅ |

## Verification evidence

`./verify.sh` runs: 12 feature tests, 17 hostile tests, 5 repair tests, 3 CLI tests, model-differential fuzz
(8 seeds × 600 ops in the suite + 6 × 2,500 ops through the CLI, each with remounts and fsck), crash fuzz
(3 seeds in the suite + 5 × 60 ops, ≈3,000 crash states and ≈10,000 double-fault states each, **0 failures**), the
5-mutant kill test, the demo, and a Chromium load of the HTML map. [REVIEW.md](REVIEW.md) lists what the adversarial
pass found — including a critical bug the crash fuzzer caught in the project's own journal on its first run (the CRC
residue property made the transaction checksum blind to the superblock).

## Why this, today

The ledger is full of things that sit *on top of* a filesystem (databases, a VCS, a KV store, a time-series DB) and of
protocol/compiler work, but nothing about the layer that decides whether "write, then lose power" is survivable. It is
also a project where being wrong is silent: a journal with a missing barrier passes every happy-path test. That made
"build the verifier at the same time as the system, and verify the verifier with mutants" the natural shape.

## Where a human could take this next

* **Real I/O reordering fidelity**: model per-sector atomicity options and `FUA`/write-cache semantics; replay traces
  captured from a real block device (dm-log-writes) through the same checker.
* **Performance work the correctness base now makes safe**: group commit / a journal ring with multiple in-flight
  transactions, directory hashing (htree), extents instead of block maps, a block cache.
* **Metadata-only (ordered) journaling** with the fuzzer extended to check data-ordering guarantees.
* **FUSE front end** so the image can be mounted and attacked with `fsstress`/`xfstests`.
* Checksums on all metadata (not only the journal) and online scrub; snapshots via copy-on-write.
* Feed the fuzzer's failing traces into a delta-debugger to shrink them to a minimal operation sequence.
