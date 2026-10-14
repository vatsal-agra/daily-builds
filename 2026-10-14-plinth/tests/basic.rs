//! Feature-level tests: one per documented behaviour.
use plinth::dev::*;
use plinth::fs::*;
use plinth::fsck;
use plinth::fuzz::*;
use plinth::journal::{self, Bug};
use plinth::layout::*;

fn fresh() -> Fs<MemDev> {
    Fs::mkfs(MemDev::new(1024), &MkfsOpts { ninodes: 128, journal_len: 64 }).unwrap()
}
fn clean(fs: &mut Fs<MemDev>) {
    let a = fsck::analyze(&mut fs.dev);
    assert!(a.issues.is_empty(), "{:?}", a.issues);
}

#[test]
fn mkfs_produces_a_clean_empty_volume() {
    let mut fs = fresh();
    clean(&mut fs);
    let s = fs.statfs();
    assert_eq!(s.free_inodes, 126);
    let root = fs.stat("/", true).unwrap();
    assert_eq!((root.kind, root.nlink, root.ino), (Kind::Dir, 2, 1));
    assert_eq!(fs.readdir("/").unwrap().len(), 2); // . and ..
    assert!(Superblock::geometry(100, 5000_00, 64).is_err());
}

#[test]
fn files_roundtrip_across_block_boundaries() {
    let mut fs = fresh();
    fs.create("/f").unwrap();
    for len in [0usize, 1, 1023, 1024, 1025, 5000, 13 * 1024, 40_000] {
        let data: Vec<u8> = (0..len).map(|i| (i * 7 % 251) as u8).collect();
        fs.truncate("/f", 0).unwrap();
        fs.write("/f", 0, &data).unwrap();
        assert_eq!(fs.read_all("/f").unwrap(), data, "len {len}");
        assert_eq!(fs.stat("/f", true).unwrap().size, len as u64);
    }
    // overwrite in the middle, append, partial reads
    fs.write("/f", 100, b"HELLO").unwrap();
    assert_eq!(fs.read("/f", 98, 9).unwrap()[2..7], *b"HELLO");
    assert_eq!(fs.read("/f", 39_990, 100).unwrap().len(), 10);
    assert!(fs.read("/f", 50_000, 10).unwrap().is_empty());
    clean(&mut fs);
}

#[test]
fn hard_links_share_data_and_free_on_last_unlink() {
    let mut fs = fresh();
    let baseline = fs.statfs().free_blocks;
    fs.create("/a").unwrap();
    fs.write("/a", 0, &[1u8; 4000]).unwrap();
    fs.link("/a", "/b").unwrap();
    assert_eq!(fs.stat("/a", true).unwrap().nlink, 2);
    fs.write("/b", 0, b"X").unwrap();
    assert_eq!(fs.read("/a", 0, 1).unwrap(), b"X");
    fs.unlink("/a").unwrap();
    assert_eq!(fs.read("/b", 1, 1).unwrap(), [1]);
    assert_eq!(fs.stat("/b", true).unwrap().nlink, 1);
    fs.unlink("/b").unwrap();
    assert_eq!(fs.statfs().free_blocks, baseline);
    assert_eq!(fs.link("/", "/x").unwrap_err().kind(), "EISDIR");
    clean(&mut fs);
}

#[test]
fn rename_semantics() {
    let mut fs = fresh();
    fs.mkdir("/a").unwrap();
    fs.mkdir("/a/sub").unwrap();
    fs.mkdir("/b").unwrap();
    fs.create("/a/f").unwrap();
    fs.write("/a/f", 0, b"data").unwrap();
    // file over file replaces it
    fs.create("/b/g").unwrap();
    fs.rename("/a/f", "/b/g").unwrap();
    assert_eq!(fs.read_all("/b/g").unwrap(), b"data");
    assert!(fs.stat("/a/f", true).is_err());
    // directory move updates '..' and both parents' link counts
    assert_eq!(fs.stat("/a", true).unwrap().nlink, 3);
    fs.rename("/a/sub", "/b/sub").unwrap();
    assert_eq!(fs.stat("/a", true).unwrap().nlink, 2);
    assert_eq!(fs.stat("/b", true).unwrap().nlink, 3);
    assert_eq!(fs.ino_of("/b/sub/..").unwrap(), fs.ino_of("/b").unwrap());
    // dir over non-empty dir fails, over empty dir works, file over dir / dir over file fail
    fs.mkdir("/c").unwrap();
    fs.create("/c/x").unwrap();
    assert_eq!(fs.rename("/b/sub", "/c").unwrap_err().kind(), "ENOTEMPTY");
    assert_eq!(fs.rename("/b/g", "/c").unwrap_err().kind(), "EISDIR");
    assert_eq!(fs.rename("/c", "/b/g").unwrap_err().kind(), "ENOTDIR");
    fs.mkdir("/empty").unwrap();
    fs.rename("/b/sub", "/empty").unwrap();
    // renaming onto itself or onto a hard link of itself is a no-op
    fs.link("/b/g", "/b/g2").unwrap();
    fs.rename("/b/g", "/b/g2").unwrap();
    assert!(fs.stat("/b/g", true).is_ok() && fs.stat("/b/g2", true).is_ok());
    fs.rename("/b/g", "/b/g").unwrap();
    clean(&mut fs);
}

#[test]
fn sparse_files_allocate_only_what_is_written() {
    let mut fs = fresh();
    fs.create("/s").unwrap();
    fs.write("/s", 500_000, b"end").unwrap();
    let st = fs.stat("/s", true).unwrap();
    assert_eq!(st.size, 500_003);
    assert!(st.blocks <= 4, "{} blocks", st.blocks);
    assert!(fs.read("/s", 0, 4096).unwrap().iter().all(|&b| b == 0));
    clean(&mut fs);
}

#[test]
fn failed_operations_leave_no_trace() {
    let mut fs = fresh();
    fs.mkdir("/d").unwrap();
    let before = fs.tree_dump().unwrap();
    let (free_b, free_i, clock) = (fs.statfs().free_blocks, fs.statfs().free_inodes, fs.statfs().clock);
    assert!(fs.create("/d").is_err());
    assert!(fs.mkdir("/nope/x").is_err());
    assert!(fs.rmdir("/zzz").is_err());
    assert!(fs.rename("/d", "/d/inner").is_err());
    assert!(fs.write("/d", 0, b"x").is_err());
    assert_eq!(fs.tree_dump().unwrap(), before);
    let s = fs.statfs();
    assert_eq!((s.free_blocks, s.free_inodes, s.clock), (free_b, free_i, clock), "failed ops must not even commit a transaction");
}

#[test]
fn every_operation_is_one_transaction_with_three_barriers() {
    let mut fs = fresh();
    fs.dev.flushes = 0;
    fs.mkdir("/d").unwrap();
    assert_eq!(fs.dev.flushes, 3);
    fs.create("/d/f").unwrap();
    assert_eq!(fs.dev.flushes, 6);
    let _ = fs.read_all("/d/f").unwrap();
    assert_eq!(fs.dev.flushes, 6, "reads never touch the journal");
}

/// Hand-built crash: a committed transaction sits in the journal, nothing was checkpointed.
#[test]
fn committed_but_unapplied_transaction_is_replayed_on_mount() {
    let mut fs = fresh();
    fs.create("/keep").unwrap();
    let base = fs.dev.data.clone();
    fs.dev.start_recording();
    fs.mkdir("/new").unwrap();
    let ev = fs.dev.log.take().unwrap();
    // keep only the journal-write phase (up to and including the first flush)
    let mut img = base;
    for e in &ev {
        match e {
            Event::Write(b, d) => img[*b as usize * BS..(*b as usize + 1) * BS].copy_from_slice(&d[..]),
            Event::Flush => break,
            _ => {}
        }
    }
    let mut dev = MemDev::from_bytes(img.clone());
    let mut b = ZERO;
    dev.read(0, &mut b).unwrap();
    let sb = Superblock::decode(&b).unwrap();
    assert!(matches!(journal::peek(&mut dev, &sb).unwrap(), Some((_, _, true))));
    let mut fs2 = Fs::mount(MemDev::from_bytes(img.clone())).unwrap();
    assert!(fs2.replayed.is_some());
    assert!(fs2.stat("/new", true).is_ok(), "committed transaction must survive");
    clean(&mut fs2);
    // the same image mounted with recovery disabled shows the lost operation and an inconsistent disk
    let mut broken = Fs::mount_with(MemDev::from_bytes(img), Bug::SkipReplay).unwrap();
    assert!(broken.stat("/new", true).is_err());
}

#[test]
fn incomplete_transaction_is_discarded() {
    let mut fs = fresh();
    let base = fs.dev.data.clone();
    fs.dev.start_recording();
    fs.mkdir("/new").unwrap();
    let ev = fs.dev.log.take().unwrap();
    // keep the journal-phase writes (everything before the first barrier) except the last, the commit block
    let jw: Vec<(u32, &Box<Block>)> = ev
        .iter()
        .take_while(|e| !matches!(e, Event::Flush))
        .filter_map(|e| match e {
            Event::Write(b, d) => Some((*b, d)),
            _ => None,
        })
        .collect();
    let mut img = base;
    for (b, d) in &jw[..jw.len() - 1] {
        img[*b as usize * BS..(*b as usize + 1) * BS].copy_from_slice(&d[..]);
    }
    let mut dev = MemDev::from_bytes(img.clone());
    let mut b = ZERO;
    dev.read(0, &mut b).unwrap();
    let sb = Superblock::decode(&b).unwrap();
    let desc_n = match journal::peek(&mut dev, &sb).unwrap() {
        Some((_, n, committed)) => {
            assert!(!committed);
            n
        }
        None => panic!("descriptor should be present"),
    };
    assert!(desc_n >= 2);
    let mut fs2 = Fs::mount(MemDev::from_bytes(img)).unwrap();
    assert!(fs2.replayed.is_none());
    assert!(fs2.stat("/new", true).is_err());
    clean(&mut fs2);
}

#[test]
fn fsck_reports_each_class_of_damage() {
    use plinth::repair::{inject, CORRUPTION_KINDS};
    use plinth::rng::Rng;
    let mut seen = std::collections::BTreeSet::new();
    for seed in 0..30u64 {
        let mut fs = fresh();
        let mut m = plinth::model::Model::new();
        let mut rng = Rng::new(seed);
        for _ in 0..80 {
            let op = gen_op(&mut rng, &m, &GenCfg { max_write: 8000, max_off: 20000 });
            let _ = apply(&mut fs, &op);
            let _ = apply(&mut m, &op);
        }
        for kind in 0..CORRUPTION_KINDS {
            let mut dev = fs.dev.clone();
            if inject(&mut dev.data, kind, &mut rng).is_some() {
                for i in fsck::analyze(&mut dev).issues {
                    seen.insert(i.code);
                }
            }
        }
    }
    for code in [
        "block-leaked", "block-unmarked", "inode-marked-free", "inode-unmarked", "bad-nlink", "bad-pointer", "dup-block",
        "orphan-inode", "dangling-entry", "free-blocks-count", "free-inodes-count", "bad-dotdot", "bad-size", "bad-dir-size",
        "missing-dot", "bad-kind", "dup-name", "dir-multi-parent", "dirty-tail", "bad-mtime",
    ] {
        assert!(seen.contains(code), "fsck never produced '{code}' (saw {seen:?})");
    }
}

#[test]
fn nested_recovery_crashes_are_what_catch_replay_no_flush() {
    // with single-fault exploration only, this mutant is invisible: that is why `nested` exists
    let mut survived_single = true;
    let mut killed_nested = false;
    for seed in 1..=3 {
        let o = CrashOpts { seed, ops: 40, bug: Bug::ReplayNoFlush, nested: false, ..Default::default() };
        if !crash_fuzz(&o).failures.is_empty() {
            survived_single = false;
        }
        let o = CrashOpts { seed, ops: 40, bug: Bug::ReplayNoFlush, nested: true, ..Default::default() };
        if !crash_fuzz(&o).failures.is_empty() {
            killed_nested = true;
            break;
        }
    }
    assert!(survived_single, "replay-no-flush is now caught by single-fault testing; update REVIEW.md");
    assert!(killed_nested, "nested recovery crashes failed to kill replay-no-flush");
}

#[test]
fn diff_fuzz_reaches_every_block_mapping_tier() {
    // the generator must exercise direct, single-indirect and double-indirect files
    let mut fs = Fs::mkfs(MemDev::new(4096), &MkfsOpts { ninodes: 512, journal_len: 128 }).unwrap();
    let mut model = plinth::model::Model::new();
    let mut rng = plinth::rng::Rng::new(11);
    let cfg = GenCfg { max_write: 40 * 1024, max_off: 400 * 1024 };
    let (mut ind, mut dind) = (false, false);
    for _ in 0..1500 {
        let op = gen_op(&mut rng, &model, &cfg);
        let _ = apply(&mut fs, &op);
        let _ = apply(&mut model, &op);
        let a = fsck::analyze(&mut fs.dev);
        for i in a.inodes.iter().filter(|i| i.kind != 0) {
            ind |= i.ind != 0;
            dind |= i.dind != 0;
        }
        if ind && dind {
            break;
        }
    }
    assert!(ind && dind, "workload never reached indirect={ind} double-indirect={dind}");
}
