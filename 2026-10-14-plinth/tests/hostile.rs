//! Adversarial tests written during the phase-3 review. Each targets a suspected weakness.
use plinth::dev::*;
use plinth::error::FsError;
use plinth::fs::*;
use plinth::fsck;
use plinth::layout::*;
use plinth::rng::Rng;

fn fresh(nblocks: u32, ninodes: u32) -> Fs<MemDev> {
    Fs::mkfs(MemDev::new(nblocks), &MkfsOpts { ninodes, journal_len: 64 }).unwrap()
}
fn assert_clean(fs: &mut Fs<MemDev>) {
    let a = fsck::analyze(&mut fs.dev);
    assert!(a.issues.is_empty(), "fsck: {:?}", a.issues);
}

#[test]
fn enospc_rolls_back_and_space_is_reusable() {
    let mut fs = fresh(256, 64);
    let before = fs.statfs().free_blocks;
    fs.create("/big").unwrap();
    let data = vec![0xABu8; 400 * 1024];
    let err = fs.write("/big", 0, &data).unwrap_err();
    assert_eq!(err.kind(), "ENOSPC", "{err}");
    assert_clean(&mut fs);
    // chunks already committed stay (documented), the rest rolled back; free space is exactly consistent
    fs.unlink("/big").unwrap();
    assert_eq!(fs.statfs().free_blocks, before);
    fs.create("/small").unwrap();
    fs.write("/small", 0, &[7u8; 5000]).unwrap();
    assert_eq!(fs.read_all("/small").unwrap(), vec![7u8; 5000]);
    assert_clean(&mut fs);
}

#[test]
fn out_of_inodes_is_clean() {
    let mut fs = fresh(512, 16);
    let mut made = 0;
    loop {
        match fs.create(&format!("/f{made}")) {
            Ok(()) => made += 1,
            Err(e) => {
                assert_eq!(e.kind(), "ENOINODES");
                break;
            }
        }
    }
    assert_eq!(made, 14); // 16 slots - reserved 0 - root
    assert_clean(&mut fs);
    fs.unlink("/f3").unwrap();
    fs.mkdir("/d").unwrap();
    assert_clean(&mut fs);
}

#[test]
fn huge_directory_spills_into_indirect_blocks() {
    let mut fs = fresh(2048, 512);
    fs.mkdir("/d").unwrap();
    let n = 400;
    for i in 0..n {
        fs.create(&format!("/d/{}{i}", "x".repeat(50))).unwrap();
    }
    let st = fs.stat("/d", true).unwrap();
    assert!(st.size / BS as u64 > 20, "dir should span >12 blocks, got {}", st.size / BS as u64);
    assert_eq!(fs.readdir("/d").unwrap().len(), n + 2);
    for i in (0..n).step_by(2) {
        fs.unlink(&format!("/d/{}{i}", "x".repeat(50))).unwrap();
    }
    assert_eq!(fs.readdir("/d").unwrap().len(), n / 2 + 2);
    // freed slots are reused instead of growing the directory
    let size_before = fs.stat("/d", true).unwrap().size;
    for i in 0..n / 2 {
        fs.create(&format!("/d/r{i}")).unwrap();
    }
    assert_eq!(fs.stat("/d", true).unwrap().size, size_before);
    assert_clean(&mut fs);
}

#[test]
fn double_indirect_roundtrip_and_truncate() {
    let mut fs = fresh(4096, 64);
    fs.create("/f").unwrap();
    let off = (NDIRECT + PPB + 5) as u64 * BS as u64 + 100; // inside the double-indirect range
    let payload = Rng::new(9).bytes(5000);
    fs.write("/f", off, &payload).unwrap();
    let ino = fs.ino_of("/f").unwrap();
    assert_ne!(fs.get_inode(ino).unwrap().dind, 0);
    assert_eq!(fs.read("/f", off, 5000).unwrap(), payload);
    assert_eq!(fs.read("/f", 0, 100).unwrap(), vec![0u8; 100]); // hole reads as zeros
    let used = fs.stat("/f", true).unwrap().blocks;
    assert!(used < 20, "sparse file must not allocate the hole ({used} blocks)");
    assert_clean(&mut fs);
    // shrink back into single-indirect range then to zero: everything is returned
    let free_mid = fs.statfs().free_blocks;
    fs.truncate("/f", 20 * BS as u64).unwrap();
    assert!(fs.statfs().free_blocks > free_mid);
    assert_eq!(fs.get_inode(ino).unwrap().dind, 0);
    assert_clean(&mut fs);
    fs.truncate("/f", 0).unwrap();
    assert_eq!(fs.stat("/f", true).unwrap().blocks, 0);
    assert_clean(&mut fs);
    // extending after shrinking must expose zeros, never stale bytes
    fs.write("/f", 0, &[0xFFu8; 3000]).unwrap();
    fs.truncate("/f", 1500).unwrap();
    fs.truncate("/f", 3000).unwrap();
    let back = fs.read_all("/f").unwrap();
    assert!(back[..1500].iter().all(|&b| b == 0xFF) && back[1500..].iter().all(|&b| b == 0));
}

#[test]
fn max_file_size_limits() {
    let mut fs = fresh(512, 32);
    fs.create("/f").unwrap();
    assert_eq!(fs.write("/f", MAX_FILE_SIZE, &[1]).unwrap_err().kind(), "EFBIG");
    assert_eq!(fs.truncate("/f", MAX_FILE_SIZE + 1).unwrap_err().kind(), "EFBIG");
    fs.truncate("/f", MAX_FILE_SIZE).unwrap(); // fully sparse, allocates nothing
    assert_eq!(fs.stat("/f", true).unwrap().blocks, 0);
    fs.write("/f", MAX_FILE_SIZE - 3, &[1, 2, 3]).unwrap();
    assert_eq!(fs.read("/f", MAX_FILE_SIZE - 3, 100).unwrap(), vec![1, 2, 3]);
    assert_clean(&mut fs);
    assert_eq!(fs.write("/f", u64::MAX - 1, &[1, 2, 3]).unwrap_err().kind(), "EFBIG");
}

#[test]
fn names_and_paths() {
    let mut fs = fresh(512, 64);
    let ok = "é".repeat(29) + "x"; // 59 bytes
    assert_eq!(ok.len(), 59);
    fs.create(&format!("/{ok}")).unwrap();
    assert_eq!(fs.create(&format!("/{ok}y")).unwrap_err().kind(), "ENAMETOOLONG");
    assert_eq!(fs.create("/a/b").unwrap_err().kind(), "ENOENT");
    assert_eq!(fs.create("rel").unwrap_err().kind(), "EINVAL");
    assert_eq!(fs.create("/").unwrap_err().kind(), "EINVAL");
    assert_eq!(fs.mkdir("/.").unwrap_err().kind(), "EINVAL");
    assert_eq!(fs.mkdir("/..").unwrap_err().kind(), "EINVAL");
    fs.mkdir("/d").unwrap();
    fs.create("//d///f").unwrap(); // redundant slashes are fine
    assert!(fs.stat("/d/./../d/f", true).is_ok());
    assert_eq!(fs.rmdir("/d").unwrap_err().kind(), "ENOTEMPTY");
    assert_eq!(fs.rmdir("/d/f").unwrap_err().kind(), "ENOTDIR");
    assert_eq!(fs.unlink("/d").unwrap_err().kind(), "EISDIR");
    assert_eq!(fs.rename("/d", "/d/x").unwrap_err().kind(), "EINVAL");
    assert_eq!(fs.rename("/d", "/d/f/x").unwrap_err().kind(), "ENOTDIR");
    assert_clean(&mut fs);
}

#[test]
fn symlinks_loops_and_dangling() {
    let mut fs = fresh(512, 64);
    fs.symlink("/b", "/a").unwrap();
    fs.symlink("/a", "/b").unwrap();
    assert_eq!(fs.stat("/a", true).unwrap_err().kind(), "ELOOP");
    assert_eq!(fs.stat("/a", false).unwrap().kind, Kind::Symlink);
    fs.symlink("/nowhere", "/dangling").unwrap();
    assert_eq!(fs.write("/dangling", 0, b"x").unwrap_err().kind(), "ENOENT");
    fs.mkdir("/d").unwrap();
    fs.create("/d/real").unwrap();
    fs.symlink("d", "/rel").unwrap();
    fs.write("/rel/real", 0, b"through the link").unwrap();
    assert_eq!(fs.read_all("/d/real").unwrap(), b"through the link");
    assert_eq!(fs.readlink("/rel").unwrap(), "d");
    // unlinking a symlink removes the link, not its target
    fs.unlink("/rel").unwrap();
    assert_eq!(fs.read_all("/d/real").unwrap(), b"through the link");
    assert_clean(&mut fs);
}

#[test]
fn link_count_ceiling() {
    let mut fs = fresh(512, 64);
    fs.create("/f").unwrap();
    let ino = fs.ino_of("/f").unwrap();
    // fabricate a file that already has MAX_LINKS-1 links by editing the inode table directly
    let sb = fs.sb.clone();
    let mut dev = fs.into_dev();
    let blk = sb.itable_start + ino / IPB as u32;
    let mut b = ZERO;
    dev.read(blk, &mut b).unwrap();
    let off = (ino as usize % IPB) * INODE_SIZE;
    put_u16(&mut b, off + 4, MAX_LINKS - 1);
    dev.write(blk, &b).unwrap();
    let mut fs = Fs::mount(dev).unwrap();
    fs.link("/f", "/g").unwrap();
    assert_eq!(fs.link("/f", "/h").unwrap_err().kind(), "EMLINK");
    assert_eq!(fs.stat("/f", true).unwrap().nlink, MAX_LINKS);
    assert!(fs.stat("/h", true).is_err(), "failed link must leave no directory entry");
}

#[test]
fn remount_preserves_everything() {
    let mut fs = fresh(1024, 128);
    fs.mkdir("/a").unwrap();
    fs.write_file_for_test("/a/f", b"hello");
    let before = fs.tree_dump().unwrap();
    let mut fs = Fs::mount(fs.into_dev()).unwrap();
    assert_eq!(fs.tree_dump().unwrap(), before);
}

trait T {
    fn write_file_for_test(&mut self, p: &str, d: &[u8]);
}
impl T for Fs<MemDev> {
    fn write_file_for_test(&mut self, p: &str, d: &[u8]) {
        self.create(p).unwrap();
        self.write(p, 0, d).unwrap();
    }
}

/// Flip random bytes in metadata, then hammer the filesystem. It may return errors but must
/// never panic, hang, or allocate absurd amounts of memory.
#[test]
fn corrupted_images_never_panic() {
    for seed in 0..60u64 {
        let mut fs = fresh(1024, 128);
        let mut rng = Rng::new(seed);
        fs.mkdir("/d").unwrap();
        fs.mkdir("/d/e").unwrap();
        for i in 0..6 {
            fs.create(&format!("/d/f{i}")).unwrap();
            let n = rng.range(1, 30000) as usize;
            fs.write(&format!("/d/f{i}"), 0, &rng.bytes(n)).unwrap();
        }
        fs.symlink("/d", "/ln").unwrap();
        let sb = fs.sb.clone();
        let mut dev = fs.into_dev();
        let meta_end = sb.data_start + 40; // metadata plus the first data blocks (dirs, indirects)
        for _ in 0..rng.range(1, 12) {
            let b = rng.range(sb.ibm_start as u64, meta_end as u64) as usize;
            let o = b * BS + rng.below(BS as u64) as usize;
            dev.data[o] ^= 1 << rng.below(8);
        }
        let res = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            let mut fs = match Fs::mount(dev) {
                Ok(f) => f,
                Err(_) => return,
            };
            let _ = fs.tree_dump();
            let _ = fs.readdir("/d");
            let _ = fs.read_all("/d/f1");
            let _ = fs.read_all("/ln/f2");
            let _ = fs.create("/d/new");
            let _ = fs.write("/d/f3", 100, &[1; 4000]);
            let _ = fs.truncate("/d/f4", 10);
            let _ = fs.unlink("/d/f0");
            let _ = fs.rename("/d/e", "/x");
            let _ = fs.rename("/x", "/d/e/y");
            let _ = fs.rmdir("/d");
            let _ = fs.mkdir("/q");
            let _ = fsck::analyze(&mut fs.dev);
        }));
        assert!(res.is_ok(), "panic on corrupted image, seed {seed}");
    }
}

#[test]
fn garbage_is_not_mounted() {
    let mut d = MemDev::new(64);
    for (i, b) in d.data.iter_mut().enumerate() {
        *b = (i * 31 % 251) as u8;
    }
    assert!(matches!(Fs::mount(d), Err(FsError::Corrupt(_))));
    assert!(Fs::mount(MemDev::new(64)).is_err());
}

fn poke_inode(fs: Fs<MemDev>, ino: u32, f: impl FnOnce(&mut Inode)) -> Fs<MemDev> {
    let sb = fs.sb.clone();
    let mut dev = fs.into_dev();
    let blk = sb.itable_start + ino / IPB as u32;
    let mut b = ZERO;
    dev.read(blk, &mut b).unwrap();
    let off = (ino as usize % IPB) * INODE_SIZE;
    let mut i = Inode::decode(&b[off..off + INODE_SIZE]);
    f(&mut i);
    i.encode(&mut b[off..off + INODE_SIZE]);
    dev.write(blk, &b).unwrap();
    Fs::mount(dev).unwrap()
}

#[test]
fn absurd_inode_size_is_rejected_not_allocated() {
    let mut fs = fresh(512, 32);
    fs.create("/f").unwrap();
    fs.write("/f", 0, b"data").unwrap();
    let ino = fs.ino_of("/f").unwrap();
    let mut fs = poke_inode(fs, ino, |i| i.size = 1 << 60);
    assert!(fs.read_all("/f").is_err());
    assert!(fs.stat("/f", true).is_err());
    assert!(fs.tree_dump().is_err());
    let a = fsck::analyze(&mut fs.dev);
    assert!(a.issues.iter().any(|i| i.code == "bad-size"));
}

#[test]
fn dotdot_cycle_does_not_hang_rename() {
    let mut fs = fresh(512, 32);
    fs.mkdir("/a").unwrap();
    fs.mkdir("/a/b").unwrap();
    let a = fs.ino_of("/a").unwrap();
    let b = fs.ino_of("/a/b").unwrap();
    // make a's '..' point at b and b's '..' at a: an unreachable-from-root cycle for upward walks
    let sb = fs.sb.clone();
    let mut dev = fs.into_dev();
    for (d, target) in [(a, b), (b, a)] {
        let mut ib = ZERO;
        dev.read(sb.itable_start + d / IPB as u32, &mut ib).unwrap();
        let inode = Inode::decode(&ib[(d as usize % IPB) * INODE_SIZE..]);
        let mut blk = ZERO;
        dev.read(inode.direct[0], &mut blk).unwrap();
        dirent_write(&mut blk, 1, target, "..");
        dev.write(inode.direct[0], &blk).unwrap();
    }
    let mut fs = Fs::mount(dev).unwrap();
    fs.mkdir("/c").unwrap();
    let r = fs.rename("/c", "/a/b/c2"); // must terminate with some answer
    let _ = r;
    let a = fsck::analyze(&mut fs.dev);
    assert!(a.issues.iter().any(|i| i.code == "bad-dotdot"));
}

#[test]
fn directory_loop_is_reported_not_followed() {
    let mut fs = fresh(512, 32);
    fs.mkdir("/a").unwrap();
    fs.mkdir("/a/b").unwrap();
    let a = fs.ino_of("/a").unwrap();
    let b = fs.ino_of("/a/b").unwrap();
    let sb = fs.sb.clone();
    let mut dev = fs.into_dev();
    // add an entry "loop" in b pointing back at a
    let mut ib = ZERO;
    dev.read(sb.itable_start + b / IPB as u32, &mut ib).unwrap();
    let inode = Inode::decode(&ib[(b as usize % IPB) * INODE_SIZE..]);
    let mut blk = ZERO;
    dev.read(inode.direct[0], &mut blk).unwrap();
    dirent_write(&mut blk, 2, a, "loop");
    dev.write(inode.direct[0], &blk).unwrap();
    let mut fs = Fs::mount(dev).unwrap();
    assert!(fs.tree_dump().is_err());
    let rep = fsck::analyze(&mut fs.dev);
    assert!(rep.issues.iter().any(|i| i.code == "dir-multi-parent"), "{:?}", rep.issues);
}

/// An I/O error while checkpointing must (a) poison the mount so a later write cannot clobber the
/// still-needed journal entry, and (b) lose nothing: remount replays the committed transaction.
#[test]
fn io_failure_during_checkpoint_poisons_then_recovers() {
    // sweep the failure point across every write of one `create` + `write` and check the invariant
    for fail_at in 1..=14u64 {
        let base = fresh(512, 64);
        let mut fs = {
            let dev = FaultDev::new(base.into_dev());
            Fs::mount(dev).unwrap()
        };
        fs.mkdir("/d").unwrap();
        fs.dev.writes = 0;
        fs.dev.fail_at = Some(fail_at);
        let r = fs.create("/d/f");
        let failed = r.is_err();
        if failed {
            // every later mutation is refused, reads of the in-memory view stay safe
            assert_eq!(fs.mkdir("/other").unwrap_err().kind(), "EIO", "fail_at={fail_at}");
        }
        let mut dev = fs.into_dev().inner;
        let mut fs2 = Fs::mount(std::mem::replace(&mut dev, MemDev::new(1))).unwrap();
        let exists = fs2.stat("/d/f", true).is_ok();
        // journal phase = desc + data + commit = first (n+2) writes: failing there means "not committed".
        // Either outcome is legal, but it must be all-or-nothing and structurally clean.
        let a = fsck::analyze(&mut fs2.dev);
        assert!(a.issues.is_empty(), "fail_at={fail_at}: {:?}", a.issues);
        if !failed {
            assert!(exists, "fail_at={fail_at}: successful create vanished");
        }
        if failed && exists {
            assert!(fs2.replayed.is_some(), "fail_at={fail_at}: a committed op may only reappear through replay");
        }
    }
}

#[test]
fn fsck_flags_dirty_tail_and_future_mtime() {
    let mut fs = fresh(512, 32);
    fs.create("/f").unwrap();
    fs.write("/f", 0, &[1u8; 100]).unwrap();
    let ino = fs.ino_of("/f").unwrap();
    let blk = fs.get_inode(ino).unwrap().direct[0];
    let sb = fs.sb.clone();
    let mut dev = fs.into_dev();
    dev.data[blk as usize * BS + 500] = 9; // garbage after EOF
    let mut ib = ZERO;
    dev.read(sb.itable_start + ino / IPB as u32, &mut ib).unwrap();
    put_u64(&mut ib, (ino as usize % IPB) * INODE_SIZE + 16, 1 << 40); // mtime
    dev.write(sb.itable_start + ino / IPB as u32, &ib).unwrap();
    let a = fsck::analyze(&mut dev);
    let codes: Vec<_> = a.issues.iter().map(|i| i.code).collect();
    assert!(codes.contains(&"dirty-tail") && codes.contains(&"bad-mtime"), "{codes:?}");
}

#[test]
fn small_journals_are_rejected_or_work() {
    assert!(Fs::mkfs(MemDev::new(512), &MkfsOpts { ninodes: 32, journal_len: 8 }).is_err());
    let mut fs = Fs::mkfs(MemDev::new(512), &MkfsOpts { ninodes: 32, journal_len: MIN_JOURNAL }).unwrap();
    assert!(fs.chunk_bytes() >= BS);
    fs.mkdir("/a").unwrap();
    fs.mkdir("/b").unwrap();
    fs.create("/a/f").unwrap();
    fs.write("/a/f", 0, &vec![5u8; 100_000]).unwrap(); // many small chunks through a tiny journal
    fs.rename("/a", "/b/a").unwrap();
    assert_eq!(fs.read_all("/b/a/f").unwrap().len(), 100_000);
    assert_clean(&mut fs);
}
