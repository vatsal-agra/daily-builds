use plinth::dev::*;
use plinth::fs::*;
use plinth::fsck;
use plinth::fuzz::*;
use plinth::layout::*;
use plinth::model::Model;
use plinth::repair::*;
use plinth::rng::Rng;

/// Build a populated filesystem by running a random workload.
fn populated(seed: u64, nops: usize) -> (Fs<MemDev>, Model) {
    let mut fs = Fs::mkfs(MemDev::new(2048), &MkfsOpts { ninodes: 256, journal_len: 64 }).unwrap();
    let mut model = Model::new();
    let mut rng = Rng::new(seed);
    let cfg = GenCfg { max_write: 20 * 1024, max_off: 60 * 1024 };
    for _ in 0..nops {
        let op = gen_op(&mut rng, &model, &cfg);
        let _ = apply(&mut fs, &op);
        let _ = apply(&mut model, &op);
    }
    (fs, model)
}

#[test]
fn every_corruption_kind_is_detected() {
    for kind in 0..CORRUPTION_KINDS {
        let mut hits = 0;
        for seed in 0..40u64 {
            let (fs, _) = populated(seed, 120);
            let mut dev = fs.into_dev();
            assert!(fsck::analyze(&mut dev).issues.is_empty());
            let mut rng = Rng::new(seed * 31 + kind as u64);
            if let Some(desc) = inject(&mut dev.data, kind, &mut rng) {
                let a = fsck::analyze(&mut dev);
                assert!(!a.issues.is_empty(), "kind {kind} ({desc}) went undetected by fsck");
                hits += 1;
            }
        }
        assert!(hits >= 5, "corruption kind {kind} was almost never applicable ({hits})");
    }
}

#[test]
fn benign_damage_is_repaired_losslessly() {
    let mut total = 0;
    for kind in (0..CORRUPTION_KINDS).filter(|&k| is_benign(k)) {
        for seed in 0..25u64 {
            let (mut fs, _) = populated(seed + 100, 150);
            let before = fs.tree_dump().unwrap();
            let mut dev = fs.into_dev();
            let mut rng = Rng::new(seed);
            let desc = match inject(&mut dev.data, kind, &mut rng) {
                Some(d) => d,
                None => continue,
            };
            let (dev, rep) = repair(dev).unwrap();
            assert!(rep.after.is_empty(), "kind {kind} ({desc}) seed {seed}: still broken: {:?}\nactions: {:?}", rep.after, rep.actions);
            let mut fs = Fs::mount(dev).unwrap();
            assert_eq!(fs.tree_dump().unwrap(), before, "kind {kind} ({desc}) seed {seed}: repair changed the file tree\nactions: {:?}", rep.actions);
            total += 1;
        }
    }
    assert!(total > 60, "only {total} benign repairs exercised");
}

#[test]
fn destructive_damage_ends_clean_and_usable() {
    let mut total = 0;
    let mut reconnected = 0;
    for seed in 0..120u64 {
        let (fs, _) = populated(seed + 500, 150);
        let mut dev = fs.into_dev();
        let mut rng = Rng::new(seed ^ 0xABCD);
        let mut descs = vec![];
        for _ in 0..rng.range(1, 4) {
            let kind = rng.below(CORRUPTION_KINDS as u64) as usize;
            if let Some(d) = inject(&mut dev.data, kind, &mut rng) {
                descs.push(d);
            }
        }
        if descs.is_empty() {
            continue;
        }
        let (dev, rep) = match repair(dev) {
            Ok(x) => x,
            Err(e) => panic!("seed {seed}: repair failed: {e} after {descs:?}"),
        };
        assert!(rep.after.is_empty(), "seed {seed}: damage {descs:?}\nleft: {:?}\nactions: {:?}", rep.after, rep.actions);
        reconnected += rep.actions.iter().filter(|a| a.contains("reconnected")).count();
        // a second repair is a no-op
        let (dev, rep2) = repair(dev).unwrap();
        assert!(rep2.before.is_empty() && rep2.actions.is_empty(), "seed {seed}: repair not idempotent: {:?}", rep2.actions);
        // the repaired filesystem is fully functional
        let mut fs = Fs::mount(dev).unwrap();
        let dump = fs.tree_dump().unwrap_or_else(|e| panic!("seed {seed}: walking repaired tree: {e}"));
        assert!(dump.contains_key("/"));
        fs.mkdir("/after-repair").unwrap();
        fs.create("/after-repair/f").unwrap();
        fs.write("/after-repair/f", 0, &[3u8; 20_000]).unwrap();
        let a = fsck::analyze(&mut fs.dev);
        assert!(a.issues.is_empty(), "seed {seed}: {:?}", a.issues);
        total += 1;
    }
    assert!(total > 80);
    assert!(reconnected > 0, "no orphan was ever reconnected; the orphan path is untested");
}

#[test]
fn orphans_land_in_lost_and_found_with_contents_intact() {
    let mut fs = Fs::mkfs(MemDev::new(512), &MkfsOpts { ninodes: 64, journal_len: 64 }).unwrap();
    fs.mkdir("/proj").unwrap();
    fs.mkdir("/proj/src").unwrap();
    fs.create("/proj/src/main.rs").unwrap();
    fs.write("/proj/src/main.rs", 0, b"fn main() {}").unwrap();
    fs.create("/proj/notes").unwrap();
    fs.write("/proj/notes", 0, b"remember the milk").unwrap();
    let sb = fs.sb.clone();
    let proj = fs.ino_of("/proj").unwrap();
    let mut dev = fs.into_dev();
    // erase the entry "proj" from the root directory -> whole subtree becomes an orphan
    let mut ib = ZERO;
    dev.read(sb.itable_start, &mut ib).unwrap();
    let root = Inode::decode(&ib[ROOT_INO as usize * INODE_SIZE..]);
    let mut rb = ZERO;
    dev.read(root.direct[0], &mut rb).unwrap();
    for s in 0..DPB {
        if dirent_read(&rb, s).1.as_deref() == Some("proj") {
            dirent_clear(&mut rb, s);
        }
    }
    dev.write(root.direct[0], &rb).unwrap();
    let a = fsck::analyze(&mut dev);
    assert!(a.issues.iter().any(|i| i.code == "orphan-inode"));
    let (dev, rep) = repair(dev).unwrap();
    assert!(rep.after.is_empty(), "{:?} / {:?}", rep.after, rep.actions);
    let mut fs = Fs::mount(dev).unwrap();
    let new = format!("/lost+found/#{proj}");
    assert_eq!(fs.read_all(&format!("{new}/src/main.rs")).unwrap(), b"fn main() {}");
    assert_eq!(fs.read_all(&format!("{new}/notes")).unwrap(), b"remember the milk");
    assert_eq!(fs.stat(&new, true).unwrap().nlink, 3); // entry + '.' + child '..'
}

#[test]
fn unusable_superblock_cannot_be_repaired() {
    let (fs, _) = populated(1, 20);
    let mut dev = fs.into_dev();
    dev.data[3] ^= 0xFF;
    assert!(repair(dev).is_err());
}
