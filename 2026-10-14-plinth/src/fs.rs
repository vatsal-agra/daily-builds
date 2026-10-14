//! The filesystem proper: allocators, block mapping, directories, path resolution and the
//! transactional operation wrappers. Every mutating public call is exactly one journal
//! transaction (or, for very large writes, a sequence of independently atomic 32 KiB chunks).
use crate::dev::BlockDev;
use crate::error::{FsError, Result};
use crate::journal::{self, Bug};
use crate::layout::*;
use crate::vfs::{assign_groups, Dump, DumpNode, Vfs};
use std::collections::{BTreeMap, VecDeque};

pub const WRITE_CHUNK: usize = 32 * BS;
const MAX_SYMLINK_HOPS: u32 = 8;
const MAX_SYMLINK_LEN: usize = BS;

pub struct MkfsOpts {
    pub ninodes: u32,
    pub journal_len: u32,
}

impl Default for MkfsOpts {
    fn default() -> Self {
        MkfsOpts { ninodes: 1024, journal_len: 128 }
    }
}

#[derive(Debug, Clone)]
pub struct Stat {
    pub ino: u32,
    pub kind: Kind,
    pub perm: u16,
    pub nlink: u16,
    pub size: u64,
    pub mtime: u64,
    /// Blocks allocated to the inode, including indirect blocks.
    pub blocks: u32,
}

#[derive(Debug, Clone)]
pub struct StatFs {
    pub nblocks: u32,
    pub free_blocks: u32,
    pub ninodes: u32,
    pub free_inodes: u32,
    pub journal_len: u32,
    pub clock: u64,
}

type TxMap = BTreeMap<u32, Box<Block>>;

pub struct Fs<D: BlockDev> {
    pub dev: D,
    pub sb: Superblock,
    pub bug: Bug,
    /// Blocks re-applied from the journal by the last `mount`.
    pub replayed: Option<usize>,
    tx: Option<TxMap>,
    hint: u32,
}

impl<D: BlockDev> Fs<D> {
    // ---------------------------------------------------------------- mkfs / mount

    pub fn mkfs(mut dev: D, opts: &MkfsOpts) -> Result<Fs<D>> {
        let sb = Superblock::geometry(dev.nblocks(), opts.ninodes, opts.journal_len).map_err(FsError::Invalid)?;
        // wipe all metadata areas so stale bytes from a previous image cannot leak in
        for b in 0..sb.data_start {
            dev.write(b, &ZERO)?;
        }
        let mut sb = sb;
        // block bitmap: metadata + root directory block
        let root_blk = sb.data_start;
        for bi in 0..sb.bbm_len {
            let mut bm = ZERO;
            for bit in 0..BITS_PER_BLOCK {
                let blk = bi * BITS_PER_BLOCK + bit;
                if blk <= root_blk && blk < sb.nblocks {
                    bit_set(&mut bm, bit as usize, true);
                }
            }
            dev.write(sb.bbm_start + bi, &bm)?;
        }
        sb.free_blocks -= 1;
        // inode bitmap: reserved 0 + root
        let mut im = ZERO;
        bit_set(&mut im, 0, true);
        bit_set(&mut im, ROOT_INO as usize, true);
        dev.write(sb.ibm_start, &im)?;
        sb.free_inodes -= 2; // slot 0 is reserved, slot 1 is root
        // root inode
        let mut root = Inode::new(Kind::Dir, 0o755, 0);
        root.nlink = 2;
        root.size = BS as u64;
        root.direct[0] = root_blk;
        let mut ib = ZERO;
        root.encode(&mut ib[(ROOT_INO as usize % IPB) * INODE_SIZE..]);
        dev.write(sb.itable_start + ROOT_INO / IPB as u32, &ib)?;
        let mut rd = ZERO;
        dirent_write(&mut rd, 0, ROOT_INO, ".");
        dirent_write(&mut rd, 1, ROOT_INO, "..");
        dev.write(root_blk, &rd)?;
        dev.write(0, &sb.encode())?;
        dev.flush()?;
        Ok(Fs { dev, sb, bug: Bug::None, replayed: None, tx: None, hint: root_blk + 1 })
    }

    pub fn mount(dev: D) -> Result<Fs<D>> {
        Fs::mount_with(dev, Bug::None)
    }

    pub fn mount_with(mut dev: D, bug: Bug) -> Result<Fs<D>> {
        let mut b = ZERO;
        dev.read(0, &mut b)?;
        let sb = Superblock::decode(&b).map_err(FsError::Corrupt)?;
        if dev.nblocks() < sb.nblocks {
            return Err(FsError::Corrupt("image is smaller than its superblock claims".into()));
        }
        let mut replayed = None;
        let mut sb = sb;
        if bug != Bug::SkipReplay {
            replayed = journal::replay(&mut dev, &sb, bug)?;
            if replayed.is_some() {
                dev.read(0, &mut b)?;
                sb = Superblock::decode(&b).map_err(FsError::Corrupt)?;
            }
        }
        let hint = sb.data_start;
        Ok(Fs { dev, sb, bug, replayed, tx: None, hint })
    }

    pub fn into_dev(self) -> D {
        self.dev
    }

    pub fn statfs(&self) -> StatFs {
        StatFs {
            nblocks: self.sb.nblocks,
            free_blocks: self.sb.free_blocks,
            ninodes: self.sb.ninodes,
            free_inodes: self.sb.free_inodes,
            journal_len: self.sb.journal_len,
            clock: self.sb.clock,
        }
    }

    // ---------------------------------------------------------------- transactions

    fn txn<T>(&mut self, f: impl FnOnce(&mut Self) -> Result<T>) -> Result<T> {
        assert!(self.tx.is_none(), "nested transaction");
        self.tx = Some(BTreeMap::new());
        match f(self) {
            Ok(v) => {
                self.commit()?;
                Ok(v)
            }
            Err(e) => {
                self.abort();
                Err(e)
            }
        }
    }

    fn abort(&mut self) {
        self.tx = None;
        let mut b = ZERO;
        if self.dev.read(0, &mut b).is_ok() {
            if let Ok(sb) = Superblock::decode(&b) {
                self.sb = sb;
            }
        }
    }

    fn commit(&mut self) -> Result<()> {
        let mut dirty = self.tx.take().expect("commit without tx");
        if dirty.is_empty() {
            return Ok(());
        }
        self.sb.clock += 1;
        dirty.insert(0, Box::new(self.sb.encode()));
        if dirty.len() > journal::max_tx_blocks(&self.sb) {
            self.abort();
            return Err(FsError::TxTooLarge);
        }
        let seq = self.sb.clock;
        if let Err(e) = journal::commit(&mut self.dev, &self.sb, &dirty, seq, self.bug) {
            self.abort();
            return Err(e.into());
        }
        Ok(())
    }

    fn rd(&mut self, b: u32) -> Result<Block> {
        if let Some(tx) = &self.tx {
            if let Some(x) = tx.get(&b) {
                return Ok(**x);
            }
        }
        if b >= self.sb.nblocks {
            return Err(FsError::Corrupt(format!("block {b} out of range")));
        }
        let mut buf = ZERO;
        self.dev.read(b, &mut buf)?;
        Ok(buf)
    }

    fn wr(&mut self, b: u32, blk: &Block) -> Result<()> {
        let limit = journal::max_tx_blocks(&self.sb) - 1; // slot for the superblock
        let tx = self.tx.as_mut().expect("write outside transaction");
        tx.insert(b, Box::new(*blk));
        if tx.len() > limit {
            return Err(FsError::TxTooLarge);
        }
        Ok(())
    }

    // ---------------------------------------------------------------- allocators

    fn alloc_block(&mut self) -> Result<u32> {
        if self.sb.free_blocks == 0 {
            return Err(FsError::NoSpace);
        }
        let (ds, n) = (self.sb.data_start, self.sb.nblocks);
        let start = if self.hint >= ds && self.hint < n { self.hint } else { ds };
        let span = n - ds;
        let mut cached: Option<(u32, Block)> = None;
        for i in 0..span {
            let b = ds + (start - ds + i) % span;
            let bi = b / BITS_PER_BLOCK;
            if cached.as_ref().map(|c| c.0) != Some(bi) {
                let blk = self.rd(self.sb.bbm_start + bi)?;
                cached = Some((bi, blk));
            }
            let (_, blk) = cached.as_mut().unwrap();
            let bit = (b % BITS_PER_BLOCK) as usize;
            if !bit_get(blk, bit) {
                bit_set(blk, bit, true);
                let copy = *blk;
                self.wr(self.sb.bbm_start + bi, &copy)?;
                self.wr(b, &ZERO)?;
                self.sb.free_blocks -= 1;
                self.hint = b + 1;
                return Ok(b);
            }
        }
        Err(FsError::Corrupt("free block counter says space exists but bitmap is full".into()))
    }

    fn free_block(&mut self, b: u32) -> Result<()> {
        if b < self.sb.data_start || b >= self.sb.nblocks {
            return Err(FsError::Corrupt(format!("freeing block {b} outside the data area")));
        }
        let bi = b / BITS_PER_BLOCK;
        let mut blk = self.rd(self.sb.bbm_start + bi)?;
        let bit = (b % BITS_PER_BLOCK) as usize;
        if !bit_get(&blk, bit) {
            return Err(FsError::Corrupt(format!("double free of block {b}")));
        }
        bit_set(&mut blk, bit, false);
        self.wr(self.sb.bbm_start + bi, &blk)?;
        self.sb.free_blocks += 1;
        Ok(())
    }

    fn alloc_inode(&mut self) -> Result<u32> {
        if self.sb.free_inodes == 0 {
            return Err(FsError::NoInodes);
        }
        let mut im = self.rd(self.sb.ibm_start)?;
        for i in 1..self.sb.ninodes as usize {
            if !bit_get(&im, i) {
                bit_set(&mut im, i, true);
                self.wr(self.sb.ibm_start, &im)?;
                self.sb.free_inodes -= 1;
                return Ok(i as u32);
            }
        }
        Err(FsError::Corrupt("free inode counter says space exists but bitmap is full".into()))
    }

    fn free_inode_slot(&mut self, ino: u32) -> Result<()> {
        let mut im = self.rd(self.sb.ibm_start)?;
        if !bit_get(&im, ino as usize) {
            return Err(FsError::Corrupt(format!("double free of inode {ino}")));
        }
        bit_set(&mut im, ino as usize, false);
        self.wr(self.sb.ibm_start, &im)?;
        self.sb.free_inodes += 1;
        let blank = Inode::default();
        self.put_inode(ino, &blank)
    }

    // ---------------------------------------------------------------- inodes

    fn inode_loc(&self, ino: u32) -> Result<(u32, usize)> {
        if ino < 1 || ino >= self.sb.ninodes {
            return Err(FsError::Corrupt(format!("inode number {ino} out of range")));
        }
        Ok((self.sb.itable_start + ino / IPB as u32, (ino as usize % IPB) * INODE_SIZE))
    }

    pub fn get_inode(&mut self, ino: u32) -> Result<Inode> {
        let (blk, off) = self.inode_loc(ino)?;
        let b = self.rd(blk)?;
        Ok(Inode::decode(&b[off..off + INODE_SIZE]))
    }

    fn put_inode(&mut self, ino: u32, inode: &Inode) -> Result<()> {
        let (blk, off) = self.inode_loc(ino)?;
        let mut b = self.rd(blk)?;
        inode.encode(&mut b[off..off + INODE_SIZE]);
        self.wr(blk, &b)
    }

    fn live_inode(&mut self, ino: u32) -> Result<Inode> {
        let i = self.get_inode(ino)?;
        if i.kind().is_none() {
            return Err(FsError::Corrupt(format!("inode {ino} is free but referenced")));
        }
        Ok(i)
    }

    fn now(&self) -> u64 {
        self.sb.clock + 1
    }

    // ---------------------------------------------------------------- block mapping

    fn check_ptr(&self, p: u32) -> Result<u32> {
        if p != 0 && (p < self.sb.data_start || p >= self.sb.nblocks) {
            return Err(FsError::Corrupt(format!("block pointer {p} outside the data area")));
        }
        Ok(p)
    }

    fn ptr_slot(&mut self, blk: u32, idx: usize, alloc: bool) -> Result<u32> {
        let mut b = self.rd(blk)?;
        let p = self.check_ptr(get_u32(&b, idx * 4))?;
        if p != 0 || !alloc {
            return Ok(p);
        }
        let n = self.alloc_block()?;
        put_u32(&mut b, idx * 4, n);
        self.wr(blk, &b)?;
        Ok(n)
    }

    /// Map logical block `lbn` of `inode` to a physical block (0 = hole when `alloc` is false).
    /// May modify `inode`'s pointers; the caller persists the inode.
    fn bmap(&mut self, inode: &mut Inode, lbn: u64, alloc: bool) -> Result<u32> {
        if lbn >= MAX_FILE_BLOCKS {
            return Err(FsError::TooBig);
        }
        let lbn = lbn as usize;
        if lbn < NDIRECT {
            let p = self.check_ptr(inode.direct[lbn])?;
            if p == 0 && alloc {
                inode.direct[lbn] = self.alloc_block()?;
            }
            return Ok(inode.direct[lbn]);
        }
        let l = lbn - NDIRECT;
        if l < PPB {
            if self.check_ptr(inode.ind)? == 0 {
                if !alloc {
                    return Ok(0);
                }
                inode.ind = self.alloc_block()?;
            }
            return self.ptr_slot(inode.ind, l, alloc);
        }
        let l2 = l - PPB;
        if self.check_ptr(inode.dind)? == 0 {
            if !alloc {
                return Ok(0);
            }
            inode.dind = self.alloc_block()?;
        }
        let mid = self.ptr_slot(inode.dind, l2 / PPB, alloc)?;
        if mid == 0 {
            return Ok(0);
        }
        self.ptr_slot(mid, l2 % PPB, alloc)
    }

    /// Free every data block of the subtree at `blk` whose index is >= `keep`.
    /// Returns true when `blk` itself was freed.
    fn free_tree(&mut self, blk: u32, level: u32, keep: u64) -> Result<bool> {
        if level == 0 {
            if keep == 0 {
                self.free_block(blk)?;
                return Ok(true);
            }
            return Ok(false);
        }
        let mut b = self.rd(blk)?;
        let span = (PPB as u64).pow(level - 1);
        let mut changed = false;
        for i in 0..PPB {
            let p = self.check_ptr(get_u32(&b, i * 4))?;
            if p == 0 {
                continue;
            }
            let start = i as u64 * span;
            if start >= keep {
                self.free_tree(p, level - 1, 0)?;
                put_u32(&mut b, i * 4, 0);
                changed = true;
            } else if keep < start + span {
                self.free_tree(p, level - 1, keep - start)?;
            }
        }
        if keep == 0 {
            self.free_block(blk)?;
            return Ok(true);
        }
        if changed {
            self.wr(blk, &b)?;
        }
        Ok(false)
    }

    /// Release all blocks at logical index >= `keep` (and zero the tail of a partial last block).
    fn shrink_blocks(&mut self, inode: &mut Inode, new_size: u64) -> Result<()> {
        let keep = (new_size + BS as u64 - 1) / BS as u64;
        for i in (keep as usize).min(NDIRECT)..NDIRECT {
            let p = self.check_ptr(inode.direct[i])?;
            if p != 0 {
                self.free_block(p)?;
                inode.direct[i] = 0;
            }
        }
        if self.check_ptr(inode.ind)? != 0 && self.free_tree(inode.ind, 1, keep.saturating_sub(NDIRECT as u64))? {
            inode.ind = 0;
        }
        if self.check_ptr(inode.dind)? != 0
            && self.free_tree(inode.dind, 2, keep.saturating_sub((NDIRECT + PPB) as u64))?
        {
            inode.dind = 0;
        }
        let tail = (new_size % BS as u64) as usize;
        if tail != 0 {
            let p = self.bmap(inode, new_size / BS as u64, false)?;
            if p != 0 {
                let mut b = self.rd(p)?;
                for x in b[tail..].iter_mut() {
                    *x = 0;
                }
                self.wr(p, &b)?;
            }
        }
        Ok(())
    }

    fn count_blocks(&mut self, inode: &Inode) -> Result<u32> {
        let mut n = inode.direct.iter().filter(|&&p| p != 0).count() as u32;
        if inode.ind != 0 {
            n += 1;
            let b = self.rd(self.check_ptr(inode.ind)?)?;
            n += (0..PPB).filter(|&i| get_u32(&b, i * 4) != 0).count() as u32;
        }
        if inode.dind != 0 {
            n += 1;
            let d = self.rd(self.check_ptr(inode.dind)?)?;
            for i in 0..PPB {
                let m = self.check_ptr(get_u32(&d, i * 4))?;
                if m != 0 {
                    n += 1;
                    let mb = self.rd(m)?;
                    n += (0..PPB).filter(|&j| get_u32(&mb, j * 4) != 0).count() as u32;
                }
            }
        }
        Ok(n)
    }

    // ---------------------------------------------------------------- file data

    fn read_data(&mut self, inode: &Inode, off: u64, len: u64) -> Result<Vec<u8>> {
        if off >= inode.size {
            return Ok(Vec::new());
        }
        let end = inode.size.min(off.saturating_add(len));
        let mut out = Vec::with_capacity((end - off) as usize);
        let mut scratch = inode.clone();
        let mut pos = off;
        while pos < end {
            let lbn = pos / BS as u64;
            let bo = (pos % BS as u64) as usize;
            let n = ((BS - bo) as u64).min(end - pos) as usize;
            let p = self.bmap(&mut scratch, lbn, false)?;
            if p == 0 {
                out.extend(std::iter::repeat(0u8).take(n));
            } else {
                let b = self.rd(p)?;
                out.extend_from_slice(&b[bo..bo + n]);
            }
            pos += n as u64;
        }
        Ok(out)
    }

    fn write_data(&mut self, ino: u32, off: u64, data: &[u8]) -> Result<()> {
        let end = off.checked_add(data.len() as u64).ok_or(FsError::TooBig)?;
        if end > MAX_FILE_SIZE {
            return Err(FsError::TooBig);
        }
        let mut inode = self.live_inode(ino)?;
        let mut pos = off;
        while pos < end {
            let lbn = pos / BS as u64;
            let bo = (pos % BS as u64) as usize;
            let n = (BS - bo).min((end - pos) as usize);
            let existing = self.bmap(&mut inode, lbn, false)?;
            let (p, mut b) = if existing != 0 {
                (existing, self.rd(existing)?)
            } else {
                (self.bmap(&mut inode, lbn, true)?, ZERO)
            };
            let src = (pos - off) as usize;
            b[bo..bo + n].copy_from_slice(&data[src..src + n]);
            self.wr(p, &b)?;
            pos += n as u64;
        }
        if end > inode.size {
            inode.size = end;
        }
        inode.mtime = self.now();
        self.put_inode(ino, &inode)
    }

    fn set_size(&mut self, ino: u32, size: u64) -> Result<()> {
        if size > MAX_FILE_SIZE {
            return Err(FsError::TooBig);
        }
        let mut inode = self.live_inode(ino)?;
        if size < inode.size {
            self.shrink_blocks(&mut inode, size)?;
        }
        inode.size = size;
        inode.mtime = self.now();
        self.put_inode(ino, &inode)
    }

    // ---------------------------------------------------------------- directories

    fn dir_blocks(&mut self, d: &Inode) -> Result<Vec<u32>> {
        let mut scratch = d.clone();
        let mut v = Vec::new();
        for lbn in 0..d.size / BS as u64 {
            let p = self.bmap(&mut scratch, lbn, false)?;
            if p == 0 {
                return Err(FsError::Corrupt("hole inside a directory".into()));
            }
            v.push(p);
        }
        Ok(v)
    }

    /// All live entries (including `.` and `..`) as (name, ino).
    fn dir_entries(&mut self, d: &Inode) -> Result<Vec<(String, u32)>> {
        let mut out = Vec::new();
        for p in self.dir_blocks(d)? {
            let b = self.rd(p)?;
            for s in 0..DPB {
                let (ino, name) = dirent_read(&b, s);
                if ino == 0 {
                    continue;
                }
                match name {
                    Some(n) => out.push((n, ino)),
                    None => return Err(FsError::Corrupt("directory entry with invalid name".into())),
                }
            }
        }
        Ok(out)
    }

    fn dir_find(&mut self, d: &Inode, name: &str) -> Result<Option<(u32, usize, u32)>> {
        for p in self.dir_blocks(d)? {
            let b = self.rd(p)?;
            for s in 0..DPB {
                let (ino, n) = dirent_read(&b, s);
                if ino != 0 && n.as_deref() == Some(name) {
                    return Ok(Some((p, s, ino)));
                }
            }
        }
        Ok(None)
    }

    fn lookup(&mut self, dir: u32, name: &str) -> Result<Option<u32>> {
        let d = self.live_inode(dir)?;
        if d.kind() != Some(Kind::Dir) {
            return Err(FsError::NotDir);
        }
        Ok(self.dir_find(&d, name)?.map(|x| x.2))
    }

    fn dir_add(&mut self, dino: u32, name: &str, ino: u32) -> Result<()> {
        let mut d = self.live_inode(dino)?;
        for p in self.dir_blocks(&d)? {
            let mut b = self.rd(p)?;
            for s in 0..DPB {
                if dirent_read(&b, s).0 == 0 {
                    dirent_write(&mut b, s, ino, name);
                    self.wr(p, &b)?;
                    d.mtime = self.now();
                    return self.put_inode(dino, &d);
                }
            }
        }
        let lbn = d.size / BS as u64;
        let p = self.bmap(&mut d, lbn, true)?;
        let mut b = ZERO;
        dirent_write(&mut b, 0, ino, name);
        self.wr(p, &b)?;
        d.size += BS as u64;
        d.mtime = self.now();
        self.put_inode(dino, &d)
    }

    fn dir_remove(&mut self, dino: u32, name: &str) -> Result<()> {
        let mut d = self.live_inode(dino)?;
        let (p, s, _) = self.dir_find(&d, name)?.ok_or(FsError::NotFound)?;
        let mut b = self.rd(p)?;
        dirent_clear(&mut b, s);
        self.wr(p, &b)?;
        d.mtime = self.now();
        self.put_inode(dino, &d)
    }

    fn dir_retarget(&mut self, dino: u32, name: &str, new_ino: u32) -> Result<()> {
        let d = self.live_inode(dino)?;
        let (p, s, _) = self.dir_find(&d, name)?.ok_or_else(|| FsError::Corrupt(format!("missing '{name}' entry")))?;
        let mut b = self.rd(p)?;
        dirent_write(&mut b, s, new_ino, name);
        self.wr(p, &b)
    }

    fn dir_is_empty(&mut self, d: &Inode) -> Result<bool> {
        Ok(self.dir_entries(d)?.iter().all(|(n, _)| n == "." || n == ".."))
    }

    fn adjust_nlink(&mut self, ino: u32, delta: i32) -> Result<u16> {
        let mut i = self.live_inode(ino)?;
        let n = i.nlink as i32 + delta;
        if n < 0 || n > MAX_LINKS as i32 {
            return Err(if n < 0 { FsError::Corrupt(format!("link count of inode {ino} underflow")) } else { FsError::TooManyLinks });
        }
        i.nlink = n as u16;
        self.put_inode(ino, &i)?;
        Ok(i.nlink)
    }

    /// Release an inode and all of its blocks.
    fn destroy_inode(&mut self, ino: u32) -> Result<()> {
        let mut i = self.live_inode(ino)?;
        self.shrink_blocks(&mut i, 0)?;
        self.free_inode_slot(ino)
    }

    // ---------------------------------------------------------------- path resolution

    fn split(path: &str) -> Result<VecDeque<String>> {
        if !path.starts_with('/') {
            return Err(FsError::Invalid("paths must be absolute".into()));
        }
        Ok(path.split('/').filter(|c| !c.is_empty()).map(|c| c.to_string()).collect())
    }

    fn read_link_target(&mut self, ino: u32) -> Result<String> {
        let i = self.live_inode(ino)?;
        let raw = self.read_data(&i, 0, i.size)?;
        String::from_utf8(raw).map_err(|_| FsError::Corrupt("symlink target is not UTF-8".into()))
    }

    fn walk(&mut self, mut queue: VecDeque<String>, follow_last: bool) -> Result<u32> {
        let mut cur = ROOT_INO;
        let mut hops = 0;
        while let Some(c) = queue.pop_front() {
            if c == "." {
                continue;
            }
            if c.len() > MAX_NAME {
                return Err(FsError::NameTooLong);
            }
            let ino = self.lookup(cur, &c)?.ok_or(FsError::NotFound)?;
            let inode = self.live_inode(ino)?;
            if inode.kind() == Some(Kind::Symlink) && (follow_last || !queue.is_empty()) {
                hops += 1;
                if hops > MAX_SYMLINK_HOPS {
                    return Err(FsError::Loop);
                }
                let target = self.read_link_target(ino)?;
                if target.starts_with('/') {
                    cur = ROOT_INO;
                }
                for part in target.split('/').rev().filter(|p| !p.is_empty()) {
                    queue.push_front(part.to_string());
                }
                continue;
            }
            if !queue.is_empty() && inode.kind() != Some(Kind::Dir) {
                return Err(FsError::NotDir);
            }
            cur = ino;
        }
        Ok(cur)
    }

    fn resolve(&mut self, path: &str, follow_last: bool) -> Result<u32> {
        let q = Fs::<D>::split(path)?;
        self.walk(q, follow_last)
    }

    /// Resolve the directory that would contain `path`'s last component, plus that component.
    fn resolve_parent(&mut self, path: &str) -> Result<(u32, String)> {
        let mut q = Fs::<D>::split(path)?;
        let name = q.pop_back().ok_or_else(|| FsError::Invalid("path has no final component".into()))?;
        if name == "." || name == ".." {
            return Err(FsError::Invalid(format!("'{name}' is not allowed here")));
        }
        if name.len() > MAX_NAME {
            return Err(FsError::NameTooLong);
        }
        if !name_ok(&name) {
            return Err(FsError::Invalid("bad file name".into()));
        }
        let dir = self.walk(q, true)?;
        if self.live_inode(dir)?.kind() != Some(Kind::Dir) {
            return Err(FsError::NotDir);
        }
        Ok((dir, name))
    }

    fn new_node(&mut self, parent: u32, name: &str, kind: Kind, perm: u16) -> Result<u32> {
        if self.lookup(parent, name)?.is_some() {
            return Err(FsError::Exists);
        }
        let ino = self.alloc_inode()?;
        let mut node = Inode::new(kind, perm, self.now());
        node.nlink = 1;
        if kind == Kind::Dir {
            node.nlink = 2;
            let p = self.alloc_block()?;
            node.direct[0] = p;
            node.size = BS as u64;
            let mut b = ZERO;
            dirent_write(&mut b, 0, ino, ".");
            dirent_write(&mut b, 1, parent, "..");
            self.wr(p, &b)?;
        }
        self.put_inode(ino, &node)?;
        self.dir_add(parent, name, ino)?;
        if kind == Kind::Dir {
            self.adjust_nlink(parent, 1)?;
        }
        Ok(ino)
    }

    // ---------------------------------------------------------------- public: queries

    pub fn stat(&mut self, path: &str, follow: bool) -> Result<Stat> {
        let ino = self.resolve(path, follow)?;
        self.stat_ino(ino)
    }

    pub fn stat_ino(&mut self, ino: u32) -> Result<Stat> {
        let i = self.live_inode(ino)?;
        let blocks = self.count_blocks(&i)?;
        Ok(Stat {
            ino,
            kind: i.kind().unwrap(),
            perm: i.perm,
            nlink: i.nlink,
            size: i.size,
            mtime: i.mtime,
            blocks,
        })
    }

    pub fn readdir(&mut self, path: &str) -> Result<Vec<(String, u32, Kind)>> {
        let ino = self.resolve(path, true)?;
        let d = self.live_inode(ino)?;
        if d.kind() != Some(Kind::Dir) {
            return Err(FsError::NotDir);
        }
        let mut v = Vec::new();
        for (n, i) in self.dir_entries(&d)? {
            let k = self.live_inode(i)?.kind().unwrap();
            v.push((n, i, k));
        }
        v.sort();
        Ok(v)
    }

    pub fn read(&mut self, path: &str, off: u64, len: u64) -> Result<Vec<u8>> {
        let ino = self.resolve(path, true)?;
        let i = self.live_inode(ino)?;
        match i.kind() {
            Some(Kind::Dir) => Err(FsError::IsDir),
            _ => self.read_data(&i, off, len),
        }
    }

    pub fn read_all(&mut self, path: &str) -> Result<Vec<u8>> {
        self.read(path, 0, u64::MAX)
    }

    pub fn readlink(&mut self, path: &str) -> Result<String> {
        let ino = self.resolve(path, false)?;
        if self.live_inode(ino)?.kind() != Some(Kind::Symlink) {
            return Err(FsError::Invalid("not a symlink".into()));
        }
        self.read_link_target(ino)
    }

    // ---------------------------------------------------------------- public: mutations

    pub fn mkdir(&mut self, p: &str) -> Result<()> {
        self.txn(|fs| {
            let (parent, name) = fs.resolve_parent(p)?;
            fs.new_node(parent, &name, Kind::Dir, 0o755).map(|_| ())
        })
    }

    pub fn create(&mut self, p: &str) -> Result<()> {
        self.txn(|fs| {
            let (parent, name) = fs.resolve_parent(p)?;
            fs.new_node(parent, &name, Kind::File, 0o644).map(|_| ())
        })
    }

    pub fn symlink(&mut self, target: &str, p: &str) -> Result<()> {
        if target.is_empty() || target.len() > MAX_SYMLINK_LEN {
            return Err(FsError::Invalid("symlink target must be 1..=1024 bytes".into()));
        }
        self.txn(|fs| {
            let (parent, name) = fs.resolve_parent(p)?;
            let ino = fs.new_node(parent, &name, Kind::Symlink, 0o777)?;
            fs.write_data(ino, 0, target.as_bytes())
        })
    }

    fn file_target(&mut self, p: &str) -> Result<u32> {
        let ino = self.resolve(p, true)?;
        match self.live_inode(ino)?.kind() {
            Some(Kind::Dir) => Err(FsError::IsDir),
            _ => Ok(ino),
        }
    }

    /// Write `data` at `off`. Large writes are split into 32 KiB chunks, each its own atomic transaction.
    pub fn write(&mut self, p: &str, off: u64, data: &[u8]) -> Result<()> {
        if data.is_empty() {
            self.txn(|fs| fs.file_target(p).map(|_| ()))?;
            return Ok(());
        }
        let mut done = 0usize;
        while done < data.len() {
            let n = WRITE_CHUNK.min(data.len() - done);
            let at = off.checked_add(done as u64).ok_or(FsError::TooBig)?;
            self.txn(|fs| {
                let ino = fs.file_target(p)?;
                fs.write_data(ino, at, &data[done..done + n])
            })?;
            done += n;
        }
        Ok(())
    }

    pub fn truncate(&mut self, p: &str, size: u64) -> Result<()> {
        self.txn(|fs| {
            let ino = fs.file_target(p)?;
            fs.set_size(ino, size)
        })
    }

    pub fn unlink(&mut self, p: &str) -> Result<()> {
        self.txn(|fs| {
            let (parent, name) = fs.resolve_parent(p)?;
            let ino = fs.lookup(parent, &name)?.ok_or(FsError::NotFound)?;
            if fs.live_inode(ino)?.kind() == Some(Kind::Dir) {
                return Err(FsError::IsDir);
            }
            fs.dir_remove(parent, &name)?;
            if fs.adjust_nlink(ino, -1)? == 0 {
                fs.destroy_inode(ino)?;
            }
            Ok(())
        })
    }

    pub fn rmdir(&mut self, p: &str) -> Result<()> {
        self.txn(|fs| {
            let (parent, name) = fs.resolve_parent(p)?;
            let ino = fs.lookup(parent, &name)?.ok_or(FsError::NotFound)?;
            let d = fs.live_inode(ino)?;
            if d.kind() != Some(Kind::Dir) {
                return Err(FsError::NotDir);
            }
            if !fs.dir_is_empty(&d)? {
                return Err(FsError::NotEmpty);
            }
            fs.dir_remove(parent, &name)?;
            fs.adjust_nlink(parent, -1)?;
            fs.destroy_inode(ino)
        })
    }

    pub fn link(&mut self, existing: &str, new: &str) -> Result<()> {
        self.txn(|fs| {
            let ino = fs.resolve(existing, false)?;
            if fs.live_inode(ino)?.kind() == Some(Kind::Dir) {
                return Err(FsError::IsDir);
            }
            let (parent, name) = fs.resolve_parent(new)?;
            if fs.lookup(parent, &name)?.is_some() {
                return Err(FsError::Exists);
            }
            fs.adjust_nlink(ino, 1)?;
            fs.dir_add(parent, &name, ino)
        })
    }

    pub fn chmod(&mut self, p: &str, perm: u16) -> Result<()> {
        self.txn(|fs| {
            let ino = fs.resolve(p, true)?;
            let mut i = fs.live_inode(ino)?;
            i.perm = perm & 0o7777;
            fs.put_inode(ino, &i)
        })
    }

    pub fn rename(&mut self, from: &str, to: &str) -> Result<()> {
        self.txn(|fs| {
            let (sp, sname) = fs.resolve_parent(from)?;
            let (dp, dname) = fs.resolve_parent(to)?;
            let sino = fs.lookup(sp, &sname)?.ok_or(FsError::NotFound)?;
            if sp == dp && sname == dname {
                return Ok(());
            }
            let skind = fs.live_inode(sino)?.kind().unwrap();
            if skind == Kind::Dir {
                // moving a directory beneath itself would orphan it
                let mut cur = dp;
                loop {
                    if cur == sino {
                        return Err(FsError::Invalid("cannot move a directory into itself".into()));
                    }
                    if cur == ROOT_INO {
                        break;
                    }
                    cur = fs.lookup(cur, "..")?.ok_or_else(|| FsError::Corrupt("directory without '..'".into()))?;
                }
            }
            if let Some(dino) = fs.lookup(dp, &dname)? {
                if dino == sino {
                    return Ok(());
                }
                let dkind = fs.live_inode(dino)?.kind().unwrap();
                match (skind == Kind::Dir, dkind == Kind::Dir) {
                    (true, false) => return Err(FsError::NotDir),
                    (false, true) => return Err(FsError::IsDir),
                    _ => {}
                }
                if dkind == Kind::Dir {
                    let d = fs.live_inode(dino)?;
                    if !fs.dir_is_empty(&d)? {
                        return Err(FsError::NotEmpty);
                    }
                    fs.dir_remove(dp, &dname)?;
                    fs.adjust_nlink(dp, -1)?;
                    fs.destroy_inode(dino)?;
                } else {
                    fs.dir_remove(dp, &dname)?;
                    if fs.adjust_nlink(dino, -1)? == 0 {
                        fs.destroy_inode(dino)?;
                    }
                }
            }
            fs.dir_add(dp, &dname, sino)?;
            fs.dir_remove(sp, &sname)?;
            if skind == Kind::Dir && sp != dp {
                fs.dir_retarget(sino, "..", dp)?;
                fs.adjust_nlink(sp, -1)?;
                fs.adjust_nlink(dp, 1)?;
            }
            Ok(())
        })
    }

    /// Link an existing (typically orphaned) inode into `dir_ino` under `name`. Used by fsck repair.
    pub fn reconnect(&mut self, dir_ino: u32, name: &str, ino: u32) -> Result<()> {
        self.txn(|fs| {
            let i = fs.live_inode(ino)?;
            fs.dir_add(dir_ino, name, ino)?;
            if i.kind() == Some(Kind::Dir) {
                fs.dir_retarget(ino, "..", dir_ino)?;
                fs.adjust_nlink(dir_ino, 1)?;
            } else {
                fs.adjust_nlink(ino, 1)?;
            }
            Ok(())
        })
    }

    /// Inode number of a path (follows symlinks).
    pub fn ino_of(&mut self, path: &str) -> Result<u32> {
        self.resolve(path, true)
    }

    // ---------------------------------------------------------------- tree dump

    pub fn tree_dump(&mut self) -> Result<Dump> {
        let mut dump = Dump::new();
        let mut ids: Vec<(String, u64)> = Vec::new();
        let mut stack = vec![("/".to_string(), ROOT_INO)];
        let mut seen_dirs = std::collections::HashSet::new();
        while let Some((path, ino)) = stack.pop() {
            let i = self.live_inode(ino)?;
            let kind = i.kind().unwrap();
            let (size, data) = match kind {
                Kind::Dir => (0, Vec::new()),
                _ => (i.size, self.read_data(&i, 0, i.size)?),
            };
            dump.insert(
                path.clone(),
                DumpNode { kind, perm: i.perm, nlink: i.nlink, size, data, group: String::new() },
            );
            ids.push((path.clone(), ino as u64));
            if kind == Kind::Dir {
                if !seen_dirs.insert(ino) {
                    return Err(FsError::Corrupt("directory cycle".into()));
                }
                for (n, c) in self.dir_entries(&i)? {
                    if n == "." || n == ".." {
                        continue;
                    }
                    let child = if path == "/" { format!("/{n}") } else { format!("{path}/{n}") };
                    stack.push((child, c));
                }
            }
        }
        assign_groups(&mut dump, &ids);
        Ok(dump)
    }
}

impl<D: BlockDev> Vfs for Fs<D> {
    fn mkdir(&mut self, p: &str) -> Result<()> {
        Fs::mkdir(self, p)
    }
    fn create(&mut self, p: &str) -> Result<()> {
        Fs::create(self, p)
    }
    fn write(&mut self, p: &str, off: u64, data: &[u8]) -> Result<()> {
        Fs::write(self, p, off, data)
    }
    fn truncate(&mut self, p: &str, size: u64) -> Result<()> {
        Fs::truncate(self, p, size)
    }
    fn unlink(&mut self, p: &str) -> Result<()> {
        Fs::unlink(self, p)
    }
    fn rmdir(&mut self, p: &str) -> Result<()> {
        Fs::rmdir(self, p)
    }
    fn rename(&mut self, from: &str, to: &str) -> Result<()> {
        Fs::rename(self, from, to)
    }
    fn link(&mut self, existing: &str, new: &str) -> Result<()> {
        Fs::link(self, existing, new)
    }
    fn symlink(&mut self, target: &str, new: &str) -> Result<()> {
        Fs::symlink(self, target, new)
    }
    fn chmod(&mut self, p: &str, perm: u16) -> Result<()> {
        Fs::chmod(self, p, perm)
    }
    fn dump(&mut self) -> Result<Dump> {
        self.tree_dump()
    }
}
