//! Offline consistency checker. `analyze` loads the whole image, cross-checks every structure
//! against every other one, and also yields the block-ownership map used by the HTML report.
use crate::dev::BlockDev;
use crate::layout::*;
use std::collections::{HashMap, HashSet};
use std::fmt;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Issue {
    pub code: &'static str,
    pub msg: String,
    /// Inode the issue is about (0 = none).
    pub ino: u32,
}

impl fmt::Display for Issue {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        write!(f, "[{}] {}", self.code, self.msg)
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Owner {
    Free,
    Super,
    Journal,
    InodeBitmap,
    BlockBitmap,
    InodeTable,
    Data(u32),
    Indirect(u32),
    DirData(u32),
}

#[derive(Debug, Default, Clone)]
pub struct Stats {
    pub files: u32,
    pub dirs: u32,
    pub symlinks: u32,
    pub data_blocks_used: u32,
    pub sparse_holes: u64,
}

pub struct Analysis {
    pub sb: Option<Superblock>,
    pub issues: Vec<Issue>,
    pub inodes: Vec<Inode>,
    pub owner: Vec<Owner>,
    /// Physical blocks of each inode by logical index (0 = hole / invalid pointer).
    pub maps: Vec<Vec<u32>>,
    pub paths: HashMap<u32, String>,
    pub refs: Vec<u32>,
    pub reachable: Vec<bool>,
    pub imap: Vec<bool>,
    pub bmap: Vec<bool>,
    pub stats: Stats,
    pub journal_pending: bool,
    pub image: Vec<u8>,
}

impl Analysis {
    pub fn ok(&self) -> bool {
        self.issues.is_empty()
    }
    fn blk(&self, b: u32) -> &[u8] {
        &self.image[b as usize * BS..b as usize * BS + BS]
    }
}

fn load<D: BlockDev>(dev: &mut D) -> Vec<u8> {
    let n = dev.nblocks();
    let mut img = vec![0u8; n as usize * BS];
    let mut b = ZERO;
    for i in 0..n {
        if dev.read(i, &mut b).is_ok() {
            img[i as usize * BS..(i as usize + 1) * BS].copy_from_slice(&b);
        }
    }
    img
}

pub fn analyze<D: BlockDev>(dev: &mut D) -> Analysis {
    let image = load(dev);
    analyze_image(image)
}

pub fn analyze_image(image: Vec<u8>) -> Analysis {
    let mut a = Analysis {
        sb: None,
        issues: vec![],
        inodes: vec![],
        owner: vec![],
        maps: vec![],
        paths: HashMap::new(),
        refs: vec![],
        reachable: vec![],
        imap: vec![],
        bmap: vec![],
        stats: Stats::default(),
        journal_pending: false,
        image,
    };
    let mut b0 = ZERO;
    b0.copy_from_slice(&a.image[0..BS]);
    let sb = match Superblock::decode(&b0) {
        Ok(sb) => sb,
        Err(e) => {
            a.issues.push(Issue { code: "bad-super", msg: e, ino: 0 });
            return a;
        }
    };
    if (a.image.len() / BS) < sb.nblocks as usize {
        a.issues.push(Issue { code: "bad-super", msg: "image shorter than superblock claims".into(), ino: 0 });
        return a;
    }
    let (nb, ni) = (sb.nblocks as usize, sb.ninodes as usize);
    macro_rules! issue {
        ($code:expr, $ino:expr, $($arg:tt)*) => { a.issues.push(Issue { code: $code, msg: format!($($arg)*), ino: $ino }) };
    }

    // journal state (informational)
    {
        let d = a.blk(sb.journal_start);
        a.journal_pending = &d[0..8] == JDESC_MAGIC;
    }
    // bitmaps
    a.imap = (0..ni).map(|i| bit_get(a.blk(sb.ibm_start), i)).collect();
    a.bmap = (0..nb)
        .map(|i| bit_get(a.blk(sb.bbm_start + i as u32 / BITS_PER_BLOCK), i % BITS_PER_BLOCK as usize))
        .collect();
    // inode table
    a.inodes = (0..ni)
        .map(|i| {
            let blk = sb.itable_start + i as u32 / IPB as u32;
            let off = (i % IPB) * INODE_SIZE;
            Inode::decode(&a.blk(blk)[off..off + INODE_SIZE])
        })
        .collect();
    // metadata ownership
    a.owner = vec![Owner::Free; nb];
    a.owner[0] = Owner::Super;
    for b in sb.journal_start..sb.journal_start + sb.journal_len {
        a.owner[b as usize] = Owner::Journal;
    }
    a.owner[sb.ibm_start as usize] = Owner::InodeBitmap;
    for b in sb.bbm_start..sb.bbm_start + sb.bbm_len {
        a.owner[b as usize] = Owner::BlockBitmap;
    }
    for b in sb.itable_start..sb.itable_start + sb.itable_len {
        a.owner[b as usize] = Owner::InodeTable;
    }
    for b in 0..sb.data_start as usize {
        if !a.bmap[b] {
            issue!("meta-unmarked", 0, "metadata block {b} is not marked used in the block bitmap");
        }
    }
    if !a.imap[0] {
        issue!("meta-unmarked", 0, "reserved inode 0 is not marked used");
    }

    // per-inode block enumeration
    a.maps = vec![Vec::new(); ni];
    for ino in 1..ni {
        let inode = a.inodes[ino].clone();
        if inode.kind == 0 {
            if a.imap[ino] {
                issue!("inode-marked-free", ino as u32, "inode {ino} is marked allocated but its kind is free");
            }
            continue;
        }
        let kind = match inode.kind() {
            Some(k) => k,
            None => {
                issue!("bad-kind", ino as u32, "inode {ino} has invalid kind {}", inode.kind);
                continue;
            }
        };
        if !a.imap[ino] {
            issue!("inode-unmarked", ino as u32, "inode {ino} is in use but not marked in the inode bitmap");
        }
        match kind {
            Kind::File => a.stats.files += 1,
            Kind::Dir => a.stats.dirs += 1,
            Kind::Symlink => a.stats.symlinks += 1,
        }
        if inode.size > MAX_FILE_SIZE {
            issue!("bad-size", ino as u32, "inode {ino} size {} exceeds the maximum", inode.size);
        }
        match kind {
            Kind::Dir if inode.size == 0 || inode.size % BS as u64 != 0 => {
                issue!("bad-dir-size", ino as u32, "directory inode {ino} has size {} (not a positive multiple of {BS})", inode.size)
            }
            Kind::Symlink if inode.size == 0 || inode.size > 1024 => {
                issue!("bad-size", ino as u32, "symlink inode {ino} has size {}", inode.size)
            }
            _ => {}
        }
        let size_blocks = (inode.size.min(MAX_FILE_SIZE) + BS as u64 - 1) / BS as u64;
        let data_owner = |i: u32| if kind == Kind::Dir { Owner::DirData(i) } else { Owner::Data(i) };
        let mut map: Vec<u32> = Vec::new();
        {
            // claim helper: returns true when the pointer is usable
            let claim = |a: &mut Analysis, p: u32, own: Owner, lbn: Option<u64>| -> bool {
                if p == 0 {
                    return false;
                }
                if p < sb.data_start || p as usize >= nb {
                    a.issues.push(Issue { code: "bad-pointer", msg: format!("inode {ino} points at block {p}, outside the data area"), ino: ino as u32 });
                    return false;
                }
                if a.owner[p as usize] != Owner::Free {
                    a.issues.push(Issue { code: "dup-block", msg: format!("block {p} claimed by inode {ino} and already owned by {:?}", a.owner[p as usize]), ino: ino as u32 });
                    return false;
                }
                if let Some(l) = lbn {
                    if l >= size_blocks {
                        a.issues.push(Issue { code: "block-past-eof", msg: format!("inode {ino} maps block {p} at index {l}, beyond its size"), ino: ino as u32 });
                    }
                }
                a.owner[p as usize] = own;
                true
            };
            let set = |map: &mut Vec<u32>, l: u64, p: u32| {
                let l = l as usize;
                if map.len() <= l {
                    map.resize(l + 1, 0);
                }
                map[l] = p;
            };
            for l in 0..NDIRECT {
                let p = inode.direct[l];
                if claim(&mut a, p, data_owner(ino as u32), Some(l as u64)) {
                    set(&mut map, l as u64, p);
                }
            }
            if claim(&mut a, inode.ind, Owner::Indirect(ino as u32), None) {
                let ib = a.blk(inode.ind).to_vec();
                for i in 0..PPB {
                    let p = get_u32(&ib, i * 4);
                    let l = (NDIRECT + i) as u64;
                    if claim(&mut a, p, data_owner(ino as u32), Some(l)) {
                        set(&mut map, l, p);
                    }
                }
            }
            if claim(&mut a, inode.dind, Owner::Indirect(ino as u32), None) {
                let db = a.blk(inode.dind).to_vec();
                for i in 0..PPB {
                    let m = get_u32(&db, i * 4);
                    if claim(&mut a, m, Owner::Indirect(ino as u32), None) {
                        let mb = a.blk(m).to_vec();
                        for j in 0..PPB {
                            let p = get_u32(&mb, j * 4);
                            let l = (NDIRECT + PPB + i * PPB + j) as u64;
                            if claim(&mut a, p, data_owner(ino as u32), Some(l)) {
                                set(&mut map, l, p);
                            }
                        }
                    }
                }
            }
        }
        if inode.mtime > sb.clock {
            issue!("bad-mtime", ino as u32, "inode {ino} has modification time {} from the future (clock {})", inode.mtime, sb.clock);
        }
        if kind != Kind::Dir && inode.size % BS as u64 != 0 {
            let l = (inode.size / BS as u64) as usize;
            if let Some(&p) = map.get(l) {
                if p != 0 && a.blk(p)[(inode.size % BS as u64) as usize..].iter().any(|&x| x != 0) {
                    issue!("dirty-tail", ino as u32, "inode {ino} has non-zero bytes past its end in its last block (would reappear when the file grows)");
                }
            }
        }
        if kind != Kind::Dir {
            let holes = (0..size_blocks as usize).filter(|&l| map.get(l).copied().unwrap_or(0) == 0).count();
            a.stats.sparse_holes += holes as u64;
        }
        a.maps[ino] = map;
    }

    // directory tree
    a.refs = vec![0; ni];
    a.reachable = vec![false; ni];
    let root_ok = a.inodes[ROOT_INO as usize].kind() == Some(Kind::Dir);
    if !root_ok {
        issue!("bad-root", ROOT_INO, "root inode is not a directory");
    } else {
        a.reachable[ROOT_INO as usize] = true;
        a.paths.insert(ROOT_INO, "/".into());
        let mut stack: Vec<(u32, u32)> = vec![(ROOT_INO, ROOT_INO)];
        while let Some((d, parent)) = stack.pop() {
            let dsize = a.inodes[d as usize].size / BS as u64;
            let dpath = a.paths[&d].clone();
            let mut names: HashSet<String> = HashSet::new();
            let (mut saw_dot, mut saw_dotdot) = (false, false);
            for lbn in 0..dsize as usize {
                let p = a.maps[d as usize].get(lbn).copied().unwrap_or(0);
                if p == 0 {
                    issue!("dir-hole", d, "directory {dpath} has an unmapped block at index {lbn}");
                    continue;
                }
                let blk = a.blk(p).to_vec();
                for s in 0..DPB {
                    let (ino, name) = dirent_read(&blk, s);
                    if ino == 0 {
                        continue;
                    }
                    let name = match name {
                        Some(n) if !n.bytes().any(|c| c == b'/' || c == 0) => n,
                        _ => {
                            issue!("bad-dirent-name", d, "directory {dpath} slot {lbn}.{s} has an invalid name");
                            continue;
                        }
                    };
                    if !names.insert(name.clone()) {
                        issue!("dup-name", d, "directory {dpath} lists '{name}' twice");
                        continue;
                    }
                    if ino as usize >= ni || a.inodes[ino as usize].kind().is_none() {
                        issue!("dangling-entry", d, "{dpath}/{name} points at unusable inode {ino}");
                        continue;
                    }
                    a.refs[ino as usize] += 1;
                    match name.as_str() {
                        "." => {
                            saw_dot = true;
                            if ino != d {
                                issue!("bad-dot", d, "'.' of {dpath} points at inode {ino}, expected {d}");
                            }
                        }
                        ".." => {
                            saw_dotdot = true;
                            if ino != parent {
                                issue!("bad-dotdot", d, "'..' of {dpath} points at inode {ino}, expected {parent}");
                            }
                        }
                        _ => {
                            let child = ino;
                            let cpath = if dpath == "/" { format!("/{name}") } else { format!("{dpath}/{name}") };
                            let is_dir = a.inodes[child as usize].kind() == Some(Kind::Dir);
                            if is_dir {
                                if a.reachable[child as usize] {
                                    issue!("dir-multi-parent", child, "directory inode {child} is linked at {cpath} and at {}", a.paths[&child]);
                                    continue;
                                }
                                a.reachable[child as usize] = true;
                                a.paths.insert(child, cpath);
                                stack.push((child, d));
                            } else if !a.reachable[child as usize] {
                                a.reachable[child as usize] = true;
                                a.paths.insert(child, cpath);
                            }
                        }
                    }
                }
            }
            if !saw_dot {
                issue!("missing-dot", d, "directory {dpath} has no '.' entry");
            }
            if !saw_dotdot {
                issue!("missing-dotdot", d, "directory {dpath} has no '..' entry");
            }
        }
    }
    for ino in 1..ni {
        if a.inodes[ino].kind().is_none() {
            continue;
        }
        if !a.reachable[ino] {
            issue!("orphan-inode", ino as u32, "inode {ino} ({}) is allocated but unreachable from the root", a.inodes[ino].kind().unwrap().name());
        } else if a.refs[ino] != a.inodes[ino].nlink as u32 {
            issue!("bad-nlink", ino as u32, "inode {ino} ({}) has link count {} but {} directory references", a.paths[&(ino as u32)], a.inodes[ino].nlink, a.refs[ino]);
        }
    }

    // block bitmap vs ownership, free counters
    let mut free_b = 0u32;
    for b in sb.data_start as usize..nb {
        let used = a.owner[b] != Owner::Free;
        if used {
            a.stats.data_blocks_used += 1;
        }
        if !a.bmap[b] {
            free_b += 1;
        }
        if used && !a.bmap[b] {
            issue!("block-unmarked", 0, "block {b} is in use ({:?}) but marked free", a.owner[b]);
        } else if !used && a.bmap[b] {
            issue!("block-leaked", 0, "block {b} is marked used but nothing owns it");
        }
    }
    let free_i = (1..ni).filter(|&i| !a.imap[i]).count() as u32;
    if free_b != sb.free_blocks {
        issue!("free-blocks-count", 0, "superblock says {} free blocks, bitmap has {}", sb.free_blocks, free_b);
    }
    if free_i != sb.free_inodes {
        issue!("free-inodes-count", 0, "superblock says {} free inodes, bitmap has {}", sb.free_inodes, free_i);
    }
    a.sb = Some(sb);
    a
}
