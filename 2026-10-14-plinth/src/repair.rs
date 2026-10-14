//! fsck --repair: rebuilds a consistent filesystem from a damaged one, plus a corruption injector
//! used to prove the repair works. Repair is offline and works on an in-memory copy of the image;
//! only changed blocks are written back, followed by a flush.
use crate::dev::BlockDev;
use crate::error::{FsError, Result};
use crate::fs::Fs;
use crate::fsck::{analyze, analyze_image, Issue, Owner};
use crate::layout::*;
use crate::rng::Rng;
use std::collections::{BTreeSet, HashSet};

pub struct RepairReport {
    pub before: Vec<Issue>,
    pub actions: Vec<String>,
    pub after: Vec<Issue>,
}

#[derive(Clone, Copy, Debug)]
enum Slot {
    Direct(u32, usize),
    InBlock(u32, usize),
}

struct Repairer {
    sb: Superblock,
    img: Vec<u8>,
    dirty: BTreeSet<u32>,
    owner: Vec<Owner>,
    actions: Vec<String>,
}

fn valid_data_ptr(sb: &Superblock, p: u32) -> bool {
    p >= sb.data_start && p < sb.nblocks
}

impl Repairer {
    fn blk(&self, b: u32) -> &[u8] {
        &self.img[b as usize * BS..(b as usize + 1) * BS]
    }
    fn blk_mut(&mut self, b: u32) -> &mut [u8] {
        self.dirty.insert(b);
        &mut self.img[b as usize * BS..(b as usize + 1) * BS]
    }
    fn act(&mut self, s: String) {
        self.actions.push(s);
    }
    fn get_inode(&self, ino: u32) -> Inode {
        let b = self.sb.itable_start + ino / IPB as u32;
        let o = (ino as usize % IPB) * INODE_SIZE;
        Inode::decode(&self.blk(b)[o..o + INODE_SIZE])
    }
    fn put_inode(&mut self, ino: u32, i: &Inode) {
        let b = self.sb.itable_start + ino / IPB as u32;
        let o = (ino as usize % IPB) * INODE_SIZE;
        i.encode(&mut self.blk_mut(b)[o..o + INODE_SIZE]);
    }
    fn alloc_block(&mut self) -> Option<u32> {
        let b = (self.sb.data_start..self.sb.nblocks).find(|&b| self.owner[b as usize] == Owner::Free)?;
        self.owner[b as usize] = Owner::Data(0);
        for x in self.blk_mut(b).iter_mut() {
            *x = 0;
        }
        Some(b)
    }
    fn alloc_inode(&mut self) -> Option<u32> {
        (2..self.sb.ninodes).find(|&i| self.get_inode(i).kind == 0)
    }

    fn set_slot(&mut self, slot: Slot, v: u32) {
        match slot {
            Slot::Direct(ino, i) => {
                let mut n = self.get_inode(ino);
                n.direct[i] = v;
                self.put_inode(ino, &n);
            }
            Slot::InBlock(b, idx) => put_u32(self.blk_mut(b), idx * 4, v),
        }
    }

    /// Pass A: make every inode's block tree sane and exclusively owned.
    fn fix_inodes(&mut self) {
        let ni = self.sb.ninodes;
        self.owner = vec![Owner::Free; self.sb.nblocks as usize];
        for b in 0..self.sb.data_start as usize {
            self.owner[b] = Owner::Super; // any non-free marker for metadata
        }
        let mut maps: Vec<Vec<(u64, u32, Slot)>> = vec![Vec::new(); ni as usize];
        for ino in 1..ni {
            let mut inode = self.get_inode(ino);
            if inode.kind == 0 {
                continue;
            }
            if inode.kind().is_none() {
                self.act(format!("inode {ino}: invalid kind {}, inode cleared", inode.kind));
                self.put_inode(ino, &Inode::default());
                continue;
            }
            let mut found: Vec<(u64, u32, Slot)> = Vec::new();
            // returns true when pointer `p` is usable and now owned by `ino`
            let take = |me: &mut Repairer, p: u32, slot: Slot, own: Owner| -> bool {
                if p == 0 {
                    return false;
                }
                if !valid_data_ptr(&me.sb, p) {
                    me.act(format!("inode {ino}: pointer {p} outside the data area removed"));
                    me.set_slot(slot, 0);
                    return false;
                }
                if me.owner[p as usize] != Owner::Free {
                    me.act(format!("inode {ino}: block {p} is already owned by another inode, pointer removed"));
                    me.set_slot(slot, 0);
                    return false;
                }
                me.owner[p as usize] = own;
                true
            };
            let data_own = if inode.kind() == Some(Kind::Dir) { Owner::DirData(ino) } else { Owner::Data(ino) };
            for l in 0..NDIRECT {
                let p = inode.direct[l];
                if take(self, p, Slot::Direct(ino, l), data_own) {
                    found.push((l as u64, p, Slot::Direct(ino, l)));
                }
            }
            inode = self.get_inode(ino); // pointers may have been zeroed
            if take(self, inode.ind, Slot::Direct(ino, usize::MAX), Owner::Indirect(ino)) {
                let ib = inode.ind;
                for i in 0..PPB {
                    let p = get_u32(self.blk(ib), i * 4);
                    if take(self, p, Slot::InBlock(ib, i), data_own) {
                        found.push(((NDIRECT + i) as u64, p, Slot::InBlock(ib, i)));
                    }
                }
            } else if inode.ind != 0 {
                inode.ind = 0;
                self.put_inode(ino, &inode);
            }
            if take(self, inode.dind, Slot::Direct(ino, usize::MAX - 1), Owner::Indirect(ino)) {
                let db = inode.dind;
                for i in 0..PPB {
                    let m = get_u32(self.blk(db), i * 4);
                    if take(self, m, Slot::InBlock(db, i), Owner::Indirect(ino)) {
                        for j in 0..PPB {
                            let p = get_u32(self.blk(m), j * 4);
                            if take(self, p, Slot::InBlock(m, j), data_own) {
                                found.push(((NDIRECT + PPB + i * PPB + j) as u64, p, Slot::InBlock(m, j)));
                            }
                        }
                    }
                }
            } else if inode.dind != 0 {
                inode.dind = 0;
                self.put_inode(ino, &inode);
            }
            maps[ino as usize] = found;
        }
        // phase 2: sizes, holes, past-EOF blocks, tails
        for ino in 1..ni {
            let mut inode = self.get_inode(ino);
            let kind = match inode.kind() {
                Some(k) => k,
                None => continue,
            };
            let max_lbn = maps[ino as usize].iter().map(|x| x.0 + 1).max().unwrap_or(0);
            match kind {
                Kind::Dir => {
                    if inode.size == 0 || inode.size % BS as u64 != 0 || inode.size > MAX_FILE_SIZE {
                        let sz = max_lbn.max(1) * BS as u64;
                        self.act(format!("directory inode {ino}: size {} replaced by {sz}", inode.size));
                        inode.size = sz;
                    }
                    // every directory block within size must exist
                    for l in 0..inode.size / BS as u64 {
                        if !maps[ino as usize].iter().any(|x| x.0 == l) {
                            if l >= NDIRECT as u64 {
                                // can only patch direct slots; trim the directory instead
                                inode.size = l * BS as u64;
                                break;
                            }
                            match self.alloc_block() {
                                Some(b) => {
                                    self.owner[b as usize] = Owner::DirData(ino);
                                    inode.direct[l as usize] = b;
                                    maps[ino as usize].push((l, b, Slot::Direct(ino, l as usize)));
                                    self.act(format!("directory inode {ino}: hole at block {l} replaced by an empty block"));
                                }
                                None => {
                                    inode.size = l * BS as u64;
                                    break;
                                }
                            }
                        }
                    }
                    if inode.size == 0 {
                        if let Some(b) = self.alloc_block() {
                            self.owner[b as usize] = Owner::DirData(ino);
                            inode.direct[0] = b;
                            inode.size = BS as u64;
                            maps[ino as usize].push((0, b, Slot::Direct(ino, 0)));
                        }
                    }
                }
                Kind::Symlink => {
                    if inode.size == 0 || inode.size > 1024 {
                        self.act(format!("symlink inode {ino}: impossible size {}, inode cleared", inode.size));
                        for (_, b, _) in maps[ino as usize].clone() {
                            self.owner[b as usize] = Owner::Free;
                        }
                        self.put_inode(ino, &Inode::default());
                        continue;
                    }
                }
                Kind::File => {
                    if inode.size > MAX_FILE_SIZE {
                        let sz = max_lbn * BS as u64;
                        self.act(format!("inode {ino}: impossible size {} replaced by {sz}", inode.size));
                        inode.size = sz;
                    }
                }
            }
            let size_blocks = (inode.size + BS as u64 - 1) / BS as u64;
            for (l, b, slot) in maps[ino as usize].clone() {
                if l >= size_blocks {
                    self.act(format!("inode {ino}: block {b} beyond end of file released"));
                    self.owner[b as usize] = Owner::Free;
                    match slot {
                        Slot::Direct(_, i) => inode.direct[i] = 0,
                        Slot::InBlock(blk, idx) => put_u32(self.blk_mut(blk), idx * 4, 0),
                    }
                }
            }
            if kind != Kind::Dir && inode.size % BS as u64 != 0 {
                let l = inode.size / BS as u64;
                if let Some((_, b, _)) = maps[ino as usize].iter().find(|x| x.0 == l && inode.size > l * BS as u64) {
                    let b = *b;
                    let tail = (inode.size % BS as u64) as usize;
                    if self.blk(b)[tail..].iter().any(|&x| x != 0) {
                        self.act(format!("inode {ino}: non-zero bytes past EOF zeroed"));
                        for x in self.blk_mut(b)[tail..].iter_mut() {
                            *x = 0;
                        }
                    }
                }
            }
            if inode.mtime > self.sb.clock {
                inode.mtime = self.sb.clock;
            }
            self.put_inode(ino, &inode);
        }
    }

    fn dir_block_list(&self, d: u32) -> Vec<u32> {
        let i = self.get_inode(d);
        let mut v = vec![];
        for l in 0..(i.size / BS as u64) as usize {
            // only direct/indirect lookups needed; re-resolve through the pointers
            let p = self.map_lbn(&i, l as u64);
            if p != 0 {
                v.push(p);
            }
        }
        v
    }

    fn map_lbn(&self, i: &Inode, l: u64) -> u32 {
        let l = l as usize;
        let ok = |p: u32| if valid_data_ptr(&self.sb, p) { p } else { 0 };
        if l < NDIRECT {
            return ok(i.direct[l]);
        }
        let l = l - NDIRECT;
        if l < PPB {
            return if ok(i.ind) == 0 { 0 } else { ok(get_u32(self.blk(i.ind), l * 4)) };
        }
        let l2 = l - PPB;
        if ok(i.dind) == 0 || l2 >= PPB * PPB {
            return 0;
        }
        let m = ok(get_u32(self.blk(i.dind), (l2 / PPB) * 4));
        if m == 0 {
            0
        } else {
            ok(get_u32(self.blk(m), (l2 % PPB) * 4))
        }
    }

    /// Insert an entry into directory `d` (free slot, else a new direct block).
    fn dir_insert(&mut self, d: u32, name: &str, ino: u32) -> bool {
        for b in self.dir_block_list(d) {
            for s in 0..DPB {
                if dirent_read(self.blk(b), s).0 == 0 {
                    dirent_write(self.blk_mut(b), s, ino, name);
                    return true;
                }
            }
        }
        let mut i = self.get_inode(d);
        let l = (i.size / BS as u64) as usize;
        if l >= NDIRECT {
            return false;
        }
        let b = match self.alloc_block() {
            Some(b) => b,
            None => return false,
        };
        self.owner[b as usize] = Owner::DirData(d);
        dirent_write(self.blk_mut(b), 0, ino, name);
        i.direct[l] = b;
        i.size += BS as u64;
        self.put_inode(d, &i);
        true
    }

    /// Pass B: walk from the root repairing the directory structure. Returns (reachable, refcounts).
    fn walk_fix(&mut self) -> (Vec<bool>, Vec<u32>) {
        let ni = self.sb.ninodes as usize;
        let mut reach = vec![false; ni];
        let mut refs = vec![0u32; ni];
        if self.get_inode(ROOT_INO).kind() != Some(Kind::Dir) {
            self.act("root inode was not a directory: recreated empty".into());
            let b = self.alloc_block().expect("no space to recreate root");
            self.owner[b as usize] = Owner::DirData(ROOT_INO);
            let mut r = Inode::new(Kind::Dir, 0o755, 0);
            r.size = BS as u64;
            r.direct[0] = b;
            self.put_inode(ROOT_INO, &r);
        }
        reach[ROOT_INO as usize] = true;
        let mut stack = vec![(ROOT_INO, ROOT_INO)];
        while let Some((d, parent)) = stack.pop() {
            let mut names: HashSet<String> = HashSet::new();
            let (mut dot, mut dotdot) = (false, false);
            for b in self.dir_block_list(d) {
                for s in 0..DPB {
                    let (ino, name) = dirent_read(self.blk(b), s);
                    if ino == 0 {
                        continue;
                    }
                    let name = match name {
                        Some(n) if !n.bytes().any(|c| c == b'/' || c == 0) => n,
                        _ => {
                            self.act(format!("directory inode {d}: entry with invalid name removed"));
                            dirent_clear(self.blk_mut(b), s);
                            continue;
                        }
                    };
                    if !names.insert(name.clone()) {
                        self.act(format!("directory inode {d}: duplicate name '{name}' removed"));
                        dirent_clear(self.blk_mut(b), s);
                        continue;
                    }
                    if ino as usize >= ni || self.get_inode(ino).kind().is_none() {
                        self.act(format!("directory inode {d}: entry '{name}' pointed at unusable inode {ino}, removed"));
                        dirent_clear(self.blk_mut(b), s);
                        continue;
                    }
                    match name.as_str() {
                        "." => {
                            dot = true;
                            if ino != d {
                                self.act(format!("directory inode {d}: '.' fixed"));
                                dirent_write(self.blk_mut(b), s, d, ".");
                            }
                            refs[d as usize] += 1;
                        }
                        ".." => {
                            dotdot = true;
                            if ino != parent {
                                self.act(format!("directory inode {d}: '..' pointed at {ino}, set to {parent}"));
                                dirent_write(self.blk_mut(b), s, parent, "..");
                            }
                            refs[parent as usize] += 1;
                        }
                        _ => {
                            let is_dir = self.get_inode(ino).kind() == Some(Kind::Dir);
                            if is_dir && reach[ino as usize] {
                                self.act(format!("directory inode {d}: second link '{name}' to directory {ino} removed"));
                                dirent_clear(self.blk_mut(b), s);
                                continue;
                            }
                            refs[ino as usize] += 1;
                            if !reach[ino as usize] {
                                reach[ino as usize] = true;
                                if is_dir {
                                    stack.push((ino, d));
                                }
                            }
                        }
                    }
                }
            }
            if !dot {
                if self.dir_insert(d, ".", d) {
                    refs[d as usize] += 1;
                    self.act(format!("directory inode {d}: missing '.' restored"));
                }
            }
            if !dotdot {
                if self.dir_insert(d, "..", parent) {
                    refs[parent as usize] += 1;
                    self.act(format!("directory inode {d}: missing '..' restored"));
                }
            }
        }
        (reach, refs)
    }

    fn orphan_pass(&mut self) {
        let ni = self.sb.ninodes as usize;
        let mut lf: Option<u32> = None;
        loop {
            let (reach, _) = self.walk_fix();
            let unreachable: Vec<u32> =
                (1..ni as u32).filter(|&i| !reach[i as usize] && self.get_inode(i).kind().is_some()).collect();
            if unreachable.is_empty() {
                break;
            }
            // prefer inodes no other orphan directory points at: they are subtree roots
            let mut referenced: HashSet<u32> = HashSet::new();
            for &u in &unreachable {
                if self.get_inode(u).kind() == Some(Kind::Dir) {
                    for b in self.dir_block_list(u) {
                        for s in 0..DPB {
                            let (c, n) = dirent_read(self.blk(b), s);
                            if c != 0 && n.as_deref() != Some(".") && n.as_deref() != Some("..") {
                                referenced.insert(c);
                            }
                        }
                    }
                }
            }
            let pick = unreachable.iter().copied().find(|u| !referenced.contains(u)).unwrap_or(unreachable[0]);
            let lf_ino = match lf {
                Some(l) => l,
                None => {
                    let l = self.ensure_lost_found();
                    match l {
                        Some(l) => {
                            lf = Some(l);
                            l
                        }
                        None => return,
                    }
                }
            };
            let name = format!("#{pick}");
            if !self.dir_insert(lf_ino, &name, pick) {
                self.act("lost+found is full; cannot reconnect more orphans".into());
                return;
            }
            self.act(format!("orphan inode {pick} reconnected as /lost+found/{name}"));
            if self.get_inode(pick).kind() == Some(Kind::Dir) {
                // '..' is corrected by the next walk
            }
        }
    }

    fn ensure_lost_found(&mut self) -> Option<u32> {
        for b in self.dir_block_list(ROOT_INO) {
            for s in 0..DPB {
                let (c, n) = dirent_read(self.blk(b), s);
                if c != 0 && n.as_deref() == Some("lost+found") && self.get_inode(c).kind() == Some(Kind::Dir) {
                    return Some(c);
                }
            }
        }
        let name = {
            let existing: HashSet<String> = self
                .dir_block_list(ROOT_INO)
                .into_iter()
                .flat_map(|b| (0..DPB).filter_map(move |s| Some((b, s))).collect::<Vec<_>>())
                .filter_map(|(b, s)| dirent_read(self.blk(b), s).1)
                .collect();
            if !existing.contains("lost+found") {
                "lost+found".to_string()
            } else {
                (1..).map(|n| format!("lost+found.{n}")).find(|c| !existing.contains(c)).unwrap()
            }
        };
        let ino = self.alloc_inode()?;
        let b = self.alloc_block()?;
        self.owner[b as usize] = Owner::DirData(ino);
        let mut node = Inode::new(Kind::Dir, 0o700, self.sb.clock);
        node.size = BS as u64;
        node.direct[0] = b;
        node.nlink = 2;
        dirent_write(self.blk_mut(b), 0, ino, ".");
        dirent_write(self.blk_mut(b), 1, ROOT_INO, "..");
        self.put_inode(ino, &node);
        if !self.dir_insert(ROOT_INO, &name, ino) {
            return None;
        }
        self.act(format!("created /{name} (inode {ino}) for orphans"));
        Some(ino)
    }

    /// Final pass: link counts, bitmaps, free counters.
    fn rebuild_metadata(&mut self, refs: &[u32], reach: &[bool]) {
        let ni = self.sb.ninodes as usize;
        for ino in 1..ni as u32 {
            let mut i = self.get_inode(ino);
            if i.kind().is_some() && reach[ino as usize] {
                let want = refs[ino as usize].min(u16::MAX as u32) as u16;
                if i.nlink != want {
                    self.act(format!("inode {ino}: link count {} corrected to {want}", i.nlink));
                    i.nlink = want;
                    self.put_inode(ino, &i);
                }
            }
        }
        // inode bitmap
        let mut im = [0u8; BS];
        bit_set(&mut im, 0, true);
        let mut free_i = 0;
        for ino in 1..ni {
            let used = self.get_inode(ino as u32).kind().is_some();
            bit_set(&mut im, ino, used);
            if !used {
                free_i += 1;
            }
        }
        if self.blk(self.sb.ibm_start) != &im[..] {
            self.act("inode bitmap rebuilt".into());
            self.blk_mut(self.sb.ibm_start).copy_from_slice(&im);
        }
        // block bitmap
        let mut free_b = 0;
        for bi in 0..self.sb.bbm_len {
            let mut bm = [0u8; BS];
            for bit in 0..BITS_PER_BLOCK {
                let b = bi * BITS_PER_BLOCK + bit;
                if b >= self.sb.nblocks {
                    break;
                }
                let used = b < self.sb.data_start || self.owner[b as usize] != Owner::Free;
                bit_set(&mut bm, bit as usize, used);
                if !used {
                    free_b += 1;
                }
            }
            let at = self.sb.bbm_start + bi;
            if self.blk(at) != &bm[..] {
                self.act(format!("block bitmap block {bi} rebuilt"));
                self.blk_mut(at).copy_from_slice(&bm);
            }
        }
        if self.sb.free_blocks != free_b || self.sb.free_inodes != free_i {
            self.act(format!(
                "superblock counters corrected (free blocks {} -> {free_b}, free inodes {} -> {free_i})",
                self.sb.free_blocks, self.sb.free_inodes
            ));
            self.sb.free_blocks = free_b;
            self.sb.free_inodes = free_i;
        }
        let e = self.sb.encode();
        self.blk_mut(0).copy_from_slice(&e);
    }
}

/// Repair `dev`. The journal is replayed first (mounting does that). Returns the device back.
pub fn repair<D: BlockDev>(dev: D) -> Result<(D, RepairReport)> {
    let fs = Fs::mount(dev)?;
    let mut dev = fs.into_dev();
    let an = analyze(&mut dev);
    let before = an.issues.clone();
    let sb = an.sb.clone().ok_or_else(|| FsError::Corrupt("superblock is unusable; nothing to repair from".into()))?;
    if before.is_empty() {
        return Ok((dev, RepairReport { before, actions: vec![], after: vec![] }));
    }
    let mut r = Repairer { sb, img: an.image, dirty: BTreeSet::new(), owner: vec![], actions: vec![] };
    r.fix_inodes();
    r.orphan_pass();
    let (reach, refs) = r.walk_fix();
    r.rebuild_metadata(&refs, &reach);
    for &b in r.dirty.iter() {
        let mut blk = ZERO;
        blk.copy_from_slice(r.blk(b));
        dev.write(b, &blk)?;
    }
    dev.flush()?;
    let after = analyze_image(r.img.clone()).issues;
    Ok((dev, RepairReport { before, actions: r.actions, after }))
}

// ------------------------------------------------------------------------------------------
// corruption injector
// ------------------------------------------------------------------------------------------

pub const CORRUPTION_KINDS: usize = 16;

/// Whether repairing this kind of damage can be lossless (the file tree must come back unchanged).
pub fn is_benign(kind: usize) -> bool {
    matches!(kind, 0 | 1 | 2 | 7 | 14 | 15)
}

/// Damage the image in a specific way. Returns a description, or None if not applicable here.
pub fn inject(img: &mut Vec<u8>, kind: usize, rng: &mut Rng) -> Option<String> {
    let a = analyze_image(img.clone());
    let sb = a.sb.clone()?;
    let ni = sb.ninodes as usize;
    let live: Vec<u32> = (1..ni as u32).filter(|&i| a.inodes[i as usize].kind().is_some()).collect();
    let files: Vec<u32> = live.iter().copied().filter(|&i| a.inodes[i as usize].kind() == Some(Kind::File) && !a.maps[i as usize].is_empty()).collect();
    let dirs: Vec<u32> = live.iter().copied().filter(|&i| a.inodes[i as usize].kind() == Some(Kind::Dir)).collect();
    let subdirs: Vec<u32> = dirs.iter().copied().filter(|&d| d != ROOT_INO).collect();
    let put_inode = |img: &mut Vec<u8>, ino: u32, f: &dyn Fn(&mut Inode)| {
        let o = (sb.itable_start + ino / IPB as u32) as usize * BS + (ino as usize % IPB) * INODE_SIZE;
        let mut i = Inode::decode(&img[o..o + INODE_SIZE]);
        f(&mut i);
        i.encode(&mut img[o..o + INODE_SIZE]);
    };
    // all (dir, block, slot, name, ino) real entries
    let mut entries: Vec<(u32, u32, usize, String, u32)> = vec![];
    for &d in &dirs {
        for &b in a.maps[d as usize].iter().filter(|&&b| b != 0) {
            for s in 0..DPB {
                let (c, n) = dirent_read(&img[b as usize * BS..(b as usize + 1) * BS], s);
                if let (true, Some(n)) = (c != 0, n) {
                    entries.push((d, b, s, n, c));
                }
            }
        }
    }
    let real: Vec<&(u32, u32, usize, String, u32)> = entries.iter().filter(|e| e.3 != "." && e.3 != "..").collect();
    let sub_entries: Vec<&(u32, u32, usize, String, u32)> =
        entries.iter().filter(|e| e.3 == ".." && e.0 != ROOT_INO).collect();
    match kind {
        0 => {
            let i = rng.range(2, ni as u64 - 1) as usize;
            let o = sb.ibm_start as usize * BS;
            let cur = bit_get(&img[o..o + BS], i);
            bit_set(&mut img[o..o + BS], i, !cur);
            Some(format!("flipped inode bitmap bit {i}"))
        }
        1 => {
            let b = rng.range(sb.data_start as u64, sb.nblocks as u64 - 1) as usize;
            let o = (sb.bbm_start as usize + b / BITS_PER_BLOCK as usize) * BS;
            let bit = b % BITS_PER_BLOCK as usize;
            let cur = bit_get(&img[o..o + BS], bit);
            bit_set(&mut img[o..o + BS], bit, !cur);
            Some(format!("flipped block bitmap bit {b}"))
        }
        2 => {
            let ino = *rng.pick(&live);
            let delta = if rng.chance(50) { 3 } else { 0xFFFF };
            put_inode(img, ino, &|i| i.nlink = i.nlink.wrapping_add(delta));
            Some(format!("link count of inode {ino} changed"))
        }
        3 => {
            let ino = *files.first().map(|_| rng.pick(&files))?;
            let bad = if rng.chance(50) { sb.nblocks + 7 } else { 3 };
            put_inode(img, ino, &|i| i.direct[0] = bad);
            Some(format!("inode {ino} direct[0] -> {bad}"))
        }
        4 => {
            if files.len() < 2 {
                return None;
            }
            let (x, y) = (*rng.pick(&files), *rng.pick(&files));
            if x == y {
                return None;
            }
            let victim = a.maps[y as usize][0];
            put_inode(img, x, &|i| i.direct[0] = victim);
            Some(format!("inode {x} now shares block {victim} with inode {y}"))
        }
        5 => {
            let e = (**rng.pick(&real)).clone();
            let off = e.1 as usize * BS + e.2 * DIRENT_SIZE;
            img[off..off + 4].copy_from_slice(&0u32.to_le_bytes());
            Some(format!("directory entry '{}' in inode {} erased (orphans '{}')", e.3, e.0, e.4))
        }
        6 => {
            let e = (**rng.pick(&real)).clone();
            let free = (1..ni as u32).find(|&i| a.inodes[i as usize].kind().is_none());
            let tgt = if rng.chance(50) { sb.ninodes + 9 } else { free? };
            let off = e.1 as usize * BS + e.2 * DIRENT_SIZE;
            img[off..off + 4].copy_from_slice(&tgt.to_le_bytes());
            Some(format!("entry '{}' now points at inode {tgt}", e.3))
        }
        7 => {
            let mut sb2 = sb.clone();
            sb2.free_blocks = sb.free_blocks / 2 + 1;
            sb2.free_inodes = sb.free_inodes.saturating_sub(5);
            img[0..BS].copy_from_slice(&sb2.encode());
            Some("superblock free counters scrambled".into())
        }
        8 => {
            let e = (**rng.pick(&sub_entries)).clone();
            let wrong = *rng.pick(&dirs);
            if wrong == e.4 {
                return None;
            }
            let off = e.1 as usize * BS + e.2 * DIRENT_SIZE;
            img[off..off + 4].copy_from_slice(&wrong.to_le_bytes());
            Some(format!("'..' of inode {} now points at {wrong}", e.0))
        }
        9 => {
            let ino = *rng.pick(&live);
            let big = 1u64 << 50;
            if a.inodes[ino as usize].kind() == Some(Kind::Dir) {
                put_inode(img, ino, &|i| i.size = 777);
            } else {
                put_inode(img, ino, &|i| i.size = big);
            }
            Some(format!("size of inode {ino} corrupted"))
        }
        10 => {
            let e = entries.iter().filter(|e| e.3 == ".").nth(rng.below(dirs.len() as u64) as usize)?;
            let off = e.1 as usize * BS + e.2 * DIRENT_SIZE;
            img[off..off + 4].copy_from_slice(&0u32.to_le_bytes());
            Some(format!("'.' of directory {} erased", e.0))
        }
        11 => {
            let ino = *rng.pick(&live);
            if ino == ROOT_INO {
                return None;
            }
            put_inode(img, ino, &|i| i.kind = 9);
            Some(format!("inode {ino} given invalid kind"))
        }
        12 => {
            let e = (**rng.pick(&real)).clone();
            let other = real.iter().find(|x| x.1 == e.1 && x.2 != e.2)?;
            let off = other.1 as usize * BS + other.2 * DIRENT_SIZE;
            let name = e.3.clone();
            let mut tmp = [0u8; BS];
            tmp.copy_from_slice(&img[off - other.2 * DIRENT_SIZE..off - other.2 * DIRENT_SIZE + BS]);
            dirent_write(&mut tmp, other.2, other.4, &name);
            img[off - other.2 * DIRENT_SIZE..off - other.2 * DIRENT_SIZE + BS].copy_from_slice(&tmp);
            Some(format!("duplicate name '{}' created in directory {}", e.3, e.0))
        }
        13 => {
            // hard-link a subdirectory into a second place (also a possible cycle)
            if subdirs.is_empty() {
                return None;
            }
            let target = *rng.pick(&subdirs);
            let host = *rng.pick(&dirs);
            let b = *a.maps[host as usize].iter().find(|&&b| b != 0)?;
            for s in 0..DPB {
                let off = b as usize * BS + s * DIRENT_SIZE;
                if get_u32(&img[off..], 0) == 0 {
                    let mut tmp = [0u8; BS];
                    tmp.copy_from_slice(&img[b as usize * BS..(b as usize + 1) * BS]);
                    dirent_write(&mut tmp, s, target, "evil-link");
                    img[b as usize * BS..(b as usize + 1) * BS].copy_from_slice(&tmp);
                    return Some(format!("directory {target} hard-linked into directory {host}"));
                }
            }
            None
        }
        14 => {
            let ino = *files.first().map(|_| rng.pick(&files))?;
            let size = a.inodes[ino as usize].size;
            if size % BS as u64 == 0 {
                return None;
            }
            let l = (size / BS as u64) as usize;
            let b = *a.maps[ino as usize].get(l)?;
            if b == 0 {
                return None;
            }
            img[b as usize * BS + BS - 1] = 0xEE;
            Some(format!("garbage written after EOF of inode {ino}"))
        }
        15 => {
            let ino = *rng.pick(&live);
            put_inode(img, ino, &|i| i.mtime = u64::MAX / 2);
            Some(format!("mtime of inode {ino} set far in the future"))
        }
        _ => None,
    }
}
