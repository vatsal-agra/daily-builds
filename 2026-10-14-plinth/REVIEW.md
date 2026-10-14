# REVIEW — adversarial pass (Phase 3)

Method: read the code as a hostile reviewer, write a test for every suspicion *first*, and only count a
finding as real if something observable broke (or, for design gaps, if a mutant could slip through).
All items below are fixed and covered by a regression test; a fresh `cargo test --release` hits none of them.

## Real defects

| # | Sev | Finding | How found | Fix | Regression test |
|---|-----|---------|-----------|-----|-----------------|
| 1 | **critical** | **The journal's CRC was blind to the superblock.** The superblock carried its own CRC32 trailer; a block that ends with its own CRC32 has a *constant* CRC32 over the whole block (CRC residue property), so the transaction checksum could not tell a stale journal copy of block 0 from the new one. After a reordered crash, replay accepted a transaction whose superblock was stale → free counters disagreed with the bitmaps. | the crash fuzzer, on the very first correct-journal run (3 failures, all `free-inodes-count`); it took tracing a CRC match across two different blocks to understand | superblock now uses FNV-1a for its embedded checksum (documented at `fnv32`) | `crash_fuzz_correct_journal_is_clean` (also: every mutant had been "killed" by this bug, which is why I did not trust the first mutant result) |
| 2 | high | A corrupted inode with `size = 2^60` made `read_data` call `Vec::with_capacity(2^60)` → **process abort** (OOM) | hostile test `absurd_inode_size_is_rejected_not_allocated` | `live_inode` rejects `size > MAX_FILE_SIZE` as corruption | same |
| 3 | high | `rename` walked `..` upward to detect "directory into itself" with no bound → **infinite loop** on an image whose `..` entries form a cycle | `dotdot_cycle_does_not_hang_rename` | step bound = inode count, then `Corrupt` | same |
| 4 | high | After an I/O error mid-checkpoint the mounted `Fs` carried on; the next transaction would overwrite the journal descriptor of a **committed but not yet checkpointed** transaction → silent loss of an acknowledged operation | reasoning about the failure path; confirmed by sweeping an injected write failure over every write of an operation | `Fs` is *poisoned* after a failed commit: all mutations return `EIO` until remount, which replays | `io_failure_during_checkpoint_poisons_then_recovers` |
| 5 | med | Replay trusted descriptor targets blindly; a (CRC-valid) descriptor naming blocks inside the journal itself would let recovery scribble on its own log | read-through | targets inside the journal region are rejected | covered by crash-fuzz + code path in `journal::replay` |
| 6 | med | Tiny journals were accepted (`>= 8`) although a single rename needs ~13 blocks, and the 32-block write chunk could never fit → every write `ETXTOOLARGE` | thought experiment, then `small_journals_are_rejected_or_work` | `MIN_JOURNAL = 24`, geometry also requires room for the bitmap blocks, chunk size derived from the journal (`chunk_bytes`) | same |
| 7 | low | `FileDev::flush` is a real `fdatasync` — a 60 MB `put` is ~6000 fsyncs and effectively unusable for demos | trying the CLI | `PLINTH_NOSYNC=1` env switch (documented as unsafe) | demo uses it |

## Weaknesses in the verification itself

| # | Finding | Fix |
|---|---------|-----|
| 8 | The crash fuzzer never crashed **during recovery**. A recovery that clears the journal before its own home writes are durable passes every single-crash test. | `nested` mode: record the events of each recovery and explore every crash prefix/subset inside it. New mutant `replay-no-flush` is killed *only* by this mode (verified: with `nested: false` it survives). |
| 9 | Torn writes were only applied to the *last* in-flight write. | The torn write is a random member of a random subset. |
| 10 | fsck did not check the invariant `truncate`-grow relies on (bytes after EOF in the last block are zero) nor impossible mtimes. | new issue codes `dirty-tail`, `bad-mtime` + test. |
| 11 | The workload generator never wrote *through* symlinks. | symlinks are now part of the file-target pool. |
| 12 | Only one mutant per protocol step was present, and no mutant targeted recovery. | 5 mutants total: `no-crc`, `no-journal-flush`, `early-clear`, `skip-replay`, `replay-no-flush`; test fails if any survives. |

## Checked and found fine (first try)

ENOSPC rollback and exact space accounting; inode exhaustion; directories spilling into indirect blocks and
slot reuse; double-indirect read/write/truncate round trips and hole semantics; stale-byte exposure after
shrink-then-grow; MAX_FILE_SIZE limits and overflow-safe offsets; 59/60-byte multibyte names; symlink loops,
dangling links, writes through relative links; link-count ceiling (fabricated via raw inode edit); 60 random
single-bit corruptions of metadata (no panic, no hang); 8 seeds × 600 ops of model-differential fuzzing.

## Accepted limitations (documented, not bugs)

* Directories are linear: lookup/insert are O(entries). Same as ext2 without htree.
* A `write` larger than one chunk (default 32 KiB) is a sequence of independently atomic transactions;
  a crash can leave a prefix of the chunks. Every individual chunk and every other operation is atomic.
* One transaction at a time (no group commit / no journal ring), so each operation pays three barriers.
* Paths are absolute, UTF-8; a trailing slash is ignored rather than asserting "is a directory".
* Timestamps are a logical per-transaction clock, not wall time (keeps images deterministic).
* No permissions enforcement (`perm` is stored, not checked) and no uid/gid.
