//! On-disk format: constants, superblock, inode and directory-entry codecs, CRC32.

pub const BS: usize = 1024;
pub type Block = [u8; BS];
pub const ZERO: Block = [0u8; BS];

pub const MAGIC: &[u8; 8] = b"PLINTH01";
pub const INODE_SIZE: usize = 128;
pub const IPB: usize = BS / INODE_SIZE;
pub const NDIRECT: usize = 12;
pub const PPB: usize = BS / 4;
pub const DIRENT_SIZE: usize = 64;
pub const DPB: usize = BS / DIRENT_SIZE;
pub const MAX_NAME: usize = 59;
pub const ROOT_INO: u32 = 1;
pub const MAX_FILE_BLOCKS: u64 = (NDIRECT + PPB + PPB * PPB) as u64;
pub const MAX_FILE_SIZE: u64 = MAX_FILE_BLOCKS * BS as u64;
pub const BITS_PER_BLOCK: u32 = (BS * 8) as u32;
pub const MAX_LINKS: u16 = 60000;

pub const JDESC_MAGIC: &[u8; 8] = b"PLJDESC1";
pub const JCOMMIT_MAGIC: &[u8; 8] = b"PLJCOMT1";
/// Max data blocks one transaction can carry (descriptor holds 250 target numbers).
pub const JDESC_CAP: usize = (BS - 24) / 4;

pub fn get_u16(b: &[u8], o: usize) -> u16 {
    u16::from_le_bytes([b[o], b[o + 1]])
}
pub fn get_u32(b: &[u8], o: usize) -> u32 {
    u32::from_le_bytes([b[o], b[o + 1], b[o + 2], b[o + 3]])
}
pub fn get_u64(b: &[u8], o: usize) -> u64 {
    let mut a = [0u8; 8];
    a.copy_from_slice(&b[o..o + 8]);
    u64::from_le_bytes(a)
}
pub fn put_u16(b: &mut [u8], o: usize, v: u16) {
    b[o..o + 2].copy_from_slice(&v.to_le_bytes());
}
pub fn put_u32(b: &mut [u8], o: usize, v: u32) {
    b[o..o + 4].copy_from_slice(&v.to_le_bytes());
}
pub fn put_u64(b: &mut [u8], o: usize, v: u64) {
    b[o..o + 8].copy_from_slice(&v.to_le_bytes());
}

pub struct Crc32(u32);
fn table() -> &'static [u32; 256] {
    static T: std::sync::OnceLock<[u32; 256]> = std::sync::OnceLock::new();
    T.get_or_init(|| {
        let mut t = [0u32; 256];
        for i in 0..256u32 {
            let mut c = i;
            for _ in 0..8 {
                c = if c & 1 != 0 { 0xEDB8_8320 ^ (c >> 1) } else { c >> 1 };
            }
            t[i as usize] = c;
        }
        t
    })
}
impl Crc32 {
    pub fn new() -> Crc32 {
        Crc32(0xFFFF_FFFF)
    }
    pub fn update(&mut self, data: &[u8]) {
        let t = table();
        for &b in data {
            self.0 = t[((self.0 ^ b as u32) & 0xFF) as usize] ^ (self.0 >> 8);
        }
    }
    pub fn finish(&self) -> u32 {
        !self.0
    }
}
/// FNV-1a. Used for the superblock's embedded checksum rather than CRC32: a block that carries its own
/// CRC32 has a *constant* CRC32 over the whole block (the CRC residue property), which silently
/// blinds the journal's transaction checksum to any change in that block.
pub fn fnv32(data: &[u8]) -> u32 {
    let mut h: u32 = 0x811C_9DC5;
    for &b in data {
        h ^= b as u32;
        h = h.wrapping_mul(0x0100_0193);
    }
    h
}
pub fn crc32(data: &[u8]) -> u32 {
    let mut c = Crc32::new();
    c.update(data);
    c.finish()
}

#[derive(Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Debug)]
pub enum Kind {
    File,
    Dir,
    Symlink,
}
impl Kind {
    pub fn code(self) -> u8 {
        match self {
            Kind::File => 1,
            Kind::Dir => 2,
            Kind::Symlink => 3,
        }
    }
    pub fn from_code(c: u8) -> Option<Kind> {
        match c {
            1 => Some(Kind::File),
            2 => Some(Kind::Dir),
            3 => Some(Kind::Symlink),
            _ => None,
        }
    }
    pub fn name(self) -> &'static str {
        match self {
            Kind::File => "file",
            Kind::Dir => "dir",
            Kind::Symlink => "symlink",
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Superblock {
    pub nblocks: u32,
    pub ninodes: u32,
    pub journal_start: u32,
    pub journal_len: u32,
    pub ibm_start: u32,
    pub bbm_start: u32,
    pub bbm_len: u32,
    pub itable_start: u32,
    pub itable_len: u32,
    pub data_start: u32,
    pub free_blocks: u32,
    pub free_inodes: u32,
    pub clock: u64,
}

impl Superblock {
    pub fn encode(&self) -> Block {
        let mut b = ZERO;
        b[0..8].copy_from_slice(MAGIC);
        put_u32(&mut b, 8, BS as u32);
        let f = [
            self.nblocks,
            self.ninodes,
            self.journal_start,
            self.journal_len,
            self.ibm_start,
            self.bbm_start,
            self.bbm_len,
            self.itable_start,
            self.itable_len,
            self.data_start,
            self.free_blocks,
            self.free_inodes,
        ];
        for (i, v) in f.iter().enumerate() {
            put_u32(&mut b, 12 + i * 4, *v);
        }
        put_u64(&mut b, 60, self.clock);
        let c = fnv32(&b[0..68]);
        put_u32(&mut b, 68, c);
        b
    }
    pub fn decode(b: &Block) -> Result<Superblock, String> {
        if &b[0..8] != MAGIC {
            return Err("bad magic (not a plinth image)".into());
        }
        if get_u32(b, 8) as usize != BS {
            return Err("unsupported block size".into());
        }
        if get_u32(b, 68) != fnv32(&b[0..68]) {
            return Err("superblock checksum mismatch".into());
        }
        let g = |i: usize| get_u32(b, 12 + i * 4);
        let sb = Superblock {
            nblocks: g(0),
            ninodes: g(1),
            journal_start: g(2),
            journal_len: g(3),
            ibm_start: g(4),
            bbm_start: g(5),
            bbm_len: g(6),
            itable_start: g(7),
            itable_len: g(8),
            data_start: g(9),
            free_blocks: g(10),
            free_inodes: g(11),
            clock: get_u64(b, 60),
        };
        sb.validate()?;
        Ok(sb)
    }
    /// Geometry for a fresh filesystem.
    pub fn geometry(nblocks: u32, ninodes: u32, journal_len: u32) -> Result<Superblock, String> {
        if ninodes < 2 || ninodes > BITS_PER_BLOCK {
            return Err(format!("inode count must be in 2..={}", BITS_PER_BLOCK));
        }
        if journal_len < 8 || journal_len as usize > JDESC_CAP + 2 {
            return Err(format!("journal length must be in 8..={}", JDESC_CAP + 2));
        }
        let bbm_len = (nblocks + BITS_PER_BLOCK - 1) / BITS_PER_BLOCK;
        let itable_len = (ninodes + IPB as u32 - 1) / IPB as u32;
        let journal_start = 1;
        let ibm_start = journal_start + journal_len;
        let bbm_start = ibm_start + 1;
        let itable_start = bbm_start + bbm_len;
        let data_start = itable_start + itable_len;
        if data_start + 8 > nblocks {
            return Err("image too small for this geometry".into());
        }
        Ok(Superblock {
            nblocks,
            ninodes,
            journal_start,
            journal_len,
            ibm_start,
            bbm_start,
            bbm_len,
            itable_start,
            itable_len,
            data_start,
            free_blocks: nblocks - data_start,
            free_inodes: ninodes,
            clock: 0,
        })
    }
    pub fn validate(&self) -> Result<(), String> {
        let g = Superblock::geometry(self.nblocks, self.ninodes, self.journal_len)
            .map_err(|e| format!("inconsistent superblock: {e}"))?;
        if g.journal_start != self.journal_start
            || g.ibm_start != self.ibm_start
            || g.bbm_start != self.bbm_start
            || g.bbm_len != self.bbm_len
            || g.itable_start != self.itable_start
            || g.itable_len != self.itable_len
            || g.data_start != self.data_start
        {
            return Err("inconsistent superblock: geometry does not match counts".into());
        }
        if self.free_blocks > self.nblocks - self.data_start || self.free_inodes > self.ninodes {
            return Err("inconsistent superblock: free counters out of range".into());
        }
        Ok(())
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Default)]
pub struct Inode {
    /// 0 = free, otherwise `Kind::code`.
    pub kind: u8,
    pub perm: u16,
    pub nlink: u16,
    pub size: u64,
    pub mtime: u64,
    pub direct: [u32; NDIRECT],
    pub ind: u32,
    pub dind: u32,
}

impl Inode {
    pub fn new(kind: Kind, perm: u16, now: u64) -> Inode {
        Inode { kind: kind.code(), perm, nlink: 0, size: 0, mtime: now, ..Default::default() }
    }
    pub fn kind(&self) -> Option<Kind> {
        Kind::from_code(self.kind)
    }
    pub fn encode(&self, out: &mut [u8]) {
        for x in out[..INODE_SIZE].iter_mut() {
            *x = 0;
        }
        out[0] = self.kind;
        put_u16(out, 2, self.perm);
        put_u16(out, 4, self.nlink);
        put_u64(out, 8, self.size);
        put_u64(out, 16, self.mtime);
        for i in 0..NDIRECT {
            put_u32(out, 24 + i * 4, self.direct[i]);
        }
        put_u32(out, 72, self.ind);
        put_u32(out, 76, self.dind);
    }
    pub fn decode(b: &[u8]) -> Inode {
        let mut direct = [0u32; NDIRECT];
        for i in 0..NDIRECT {
            direct[i] = get_u32(b, 24 + i * 4);
        }
        Inode {
            kind: b[0],
            perm: get_u16(b, 2),
            nlink: get_u16(b, 4),
            size: get_u64(b, 8),
            mtime: get_u64(b, 16),
            direct,
            ind: get_u32(b, 72),
            dind: get_u32(b, 76),
        }
    }
}

/// Valid file name: non-empty, <= MAX_NAME bytes, no '/' or NUL.
pub fn name_ok(name: &str) -> bool {
    !name.is_empty() && name.len() <= MAX_NAME && !name.bytes().any(|c| c == b'/' || c == 0)
}

pub fn dirent_read(b: &[u8], slot: usize) -> (u32, Option<String>) {
    let o = slot * DIRENT_SIZE;
    let ino = get_u32(b, o);
    let n = b[o + 4] as usize;
    if n == 0 || n > MAX_NAME {
        return (ino, None);
    }
    (ino, std::str::from_utf8(&b[o + 5..o + 5 + n]).ok().map(|s| s.to_string()))
}
pub fn dirent_write(b: &mut [u8], slot: usize, ino: u32, name: &str) {
    let o = slot * DIRENT_SIZE;
    for x in b[o..o + DIRENT_SIZE].iter_mut() {
        *x = 0;
    }
    put_u32(b, o, ino);
    b[o + 4] = name.len() as u8;
    b[o + 5..o + 5 + name.len()].copy_from_slice(name.as_bytes());
}
pub fn dirent_clear(b: &mut [u8], slot: usize) {
    let o = slot * DIRENT_SIZE;
    for x in b[o..o + DIRENT_SIZE].iter_mut() {
        *x = 0;
    }
}

pub fn bit_get(b: &[u8], i: usize) -> bool {
    b[i / 8] & (1 << (i % 8)) != 0
}
pub fn bit_set(b: &mut [u8], i: usize, v: bool) {
    if v {
        b[i / 8] |= 1 << (i % 8);
    } else {
        b[i / 8] &= !(1 << (i % 8));
    }
}
