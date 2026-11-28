//! RRR (Raman–Raman–Rao) entropy-compressed bit vector.
//!
//! Bits are cut into 15-bit blocks. Each block is stored as its *class* (popcount, 4 bits)
//! plus its *offset* — the index of the block among all C(15, class) blocks of that class,
//! in ceil(log2 C(15, class)) bits (the combinatorial number system). Sparse or dense
//! vectors therefore shrink toward n·H0(p); all-zero/all-one blocks cost only their class.
use crate::bitvec::{select_in_word, BitVec};
use crate::util::{Error, Reader, Result, Ser, Writer};

const B: usize = 15;
const SB_BLOCKS: usize = 64; // blocks per sampled superblock (960 bits)

/// Pascal's triangle up to row 15.
const fn binom_table() -> [[u16; 16]; 16] {
    let mut t = [[0u16; 16]; 16];
    let mut n = 0;
    while n < 16 {
        t[n][0] = 1;
        let mut k = 1;
        while k <= n {
            t[n][k] = t[n - 1][k - 1] + if k <= n - 1 { t[n - 1][k] } else { 0 };
            k += 1;
        }
        n += 1;
    }
    t
}
const C: [[u16; 16]; 16] = binom_table();

/// Offset width in bits for each class.
const fn width_table() -> [u8; 16] {
    let mut w = [0u8; 16];
    let mut c = 0;
    while c < 16 {
        let v = C[15][c] as u32;
        let mut bits = 0;
        while (1u32 << bits) < v {
            bits += 1;
        }
        w[c] = bits as u8;
        c += 1;
    }
    w
}
const WIDTH: [u8; 16] = width_table();

fn encode_block(block: u16) -> (u8, u16) {
    let class = block.count_ones() as usize;
    let mut k = class;
    let mut off = 0u16;
    for p in (0..B).rev() {
        if (block >> p) & 1 == 1 {
            off += C[p][k];
            k -= 1;
        }
    }
    (class as u8, off)
}

fn decode_block(class: u8, mut off: u16) -> u16 {
    let mut k = class as usize;
    let mut block = 0u16;
    for p in (0..B).rev() {
        if k > 0 && off >= C[p][k] {
            block |= 1 << p;
            off -= C[p][k];
            k -= 1;
        }
    }
    block
}

#[derive(Clone, Debug)]
pub struct Rrr {
    len: usize,
    ones: usize,
    classes: BitVec, // 4 bits per block
    offsets: BitVec, // variable width
    sb_rank: Vec<u32>, // ones before each superblock
    sb_off: Vec<u64>,  // offset-bit position at each superblock start
}

impl Rrr {
    pub fn new(bits: &BitVec) -> Self {
        let nblocks = bits.len.div_ceil(B);
        let mut classes = BitVec::new();
        let mut offsets = BitVec::new();
        let (mut sb_rank, mut sb_off) = (Vec::new(), Vec::new());
        let mut ones = 0usize;
        for b in 0..nblocks {
            if b % SB_BLOCKS == 0 {
                sb_rank.push(ones as u32);
                sb_off.push(offsets.len as u64);
            }
            let start = b * B;
            let w = B.min(bits.len - start) as u32;
            let block = bits.get_bits(start, w) as u16;
            let (class, off) = encode_block(block);
            classes.push_bits(class as u64, 4);
            offsets.push_bits(off as u64, WIDTH[class as usize] as u32);
            ones += class as usize;
        }
        if nblocks % SB_BLOCKS == 0 {
            sb_rank.push(ones as u32);
            sb_off.push(offsets.len as u64);
        }
        Rrr { len: bits.len, ones, classes, offsets, sb_rank, sb_off }
    }

    pub fn from_bools(b: &[bool]) -> Self {
        Self::new(&BitVec::from_bools(b))
    }
    pub fn len(&self) -> usize {
        self.len
    }
    pub fn is_empty(&self) -> bool {
        self.len == 0
    }
    pub fn count_ones(&self) -> usize {
        self.ones
    }
    pub fn count_zeros(&self) -> usize {
        self.len - self.ones
    }
    #[inline]
    fn class(&self, b: usize) -> u8 {
        self.classes.get_bits(b * 4, 4) as u8
    }
    #[inline]
    fn block_at(&self, class: u8, off_pos: u64) -> u16 {
        decode_block(class, self.offsets.get_bits(off_pos as usize, WIDTH[class as usize] as u32) as u16)
    }

    /// Ones in [0, i) for i in 0..=len.
    pub fn rank1(&self, i: usize) -> usize {
        assert!(i <= self.len, "rank1 position {} out of range (len {})", i, self.len);
        let (blk, rem) = (i / B, i % B);
        let sb = blk / SB_BLOCKS;
        if blk >= self.len.div_ceil(B) {
            return self.ones; // i == len on a block boundary
        }
        let mut r = self.sb_rank[sb] as usize;
        let mut pos = self.sb_off[sb];
        for b in sb * SB_BLOCKS..blk {
            let c = self.class(b);
            r += c as usize;
            pos += WIDTH[c as usize] as u64;
        }
        if rem > 0 {
            let c = self.class(blk);
            let block = self.block_at(c, pos);
            r += (block & ((1u16 << rem) - 1)).count_ones() as usize;
        }
        r
    }
    pub fn rank0(&self, i: usize) -> usize {
        i - self.rank1(i)
    }

    pub fn get(&self, i: usize) -> bool {
        assert!(i < self.len, "Rrr::get out of range");
        let blk = i / B;
        let sb = blk / SB_BLOCKS;
        let mut pos = self.sb_off[sb];
        for b in sb * SB_BLOCKS..blk {
            pos += WIDTH[self.class(b) as usize] as u64;
        }
        (self.block_at(self.class(blk), pos) >> (i % B)) & 1 == 1
    }

    fn select_generic(&self, k: usize, ones: bool) -> Option<usize> {
        let total = if ones { self.ones } else { self.count_zeros() };
        if k >= total {
            return None;
        }
        let before = |sb: usize| -> usize {
            let r = self.sb_rank[sb] as usize;
            if ones {
                r
            } else {
                sb * SB_BLOCKS * B - r
            }
        };
        // Last superblock whose preceding count <= k.
        let (mut lo, mut hi) = (0usize, self.sb_rank.len() - 1);
        while lo < hi {
            let mid = (lo + hi + 1) / 2;
            if before(mid) <= k {
                lo = mid;
            } else {
                hi = mid - 1;
            }
        }
        let mut need = k - before(lo);
        let mut pos = self.sb_off[lo];
        let nblocks = self.len.div_ceil(B);
        for b in lo * SB_BLOCKS..nblocks {
            let c = self.class(b);
            let valid = B.min(self.len - b * B);
            let cnt = if ones { c as usize } else { valid - c as usize };
            if need < cnt {
                let block = self.block_at(c, pos) as u64;
                let w = if ones { block } else { !block & ((1u64 << valid) - 1) };
                return Some(b * B + select_in_word(w, need as u32) as usize);
            }
            need -= cnt;
            pos += WIDTH[c as usize] as u64;
        }
        None
    }
    pub fn select1(&self, k: usize) -> Option<usize> {
        self.select_generic(k, true)
    }
    pub fn select0(&self, k: usize) -> Option<usize> {
        self.select_generic(k, false)
    }

    /// Total bits including superblock samples.
    pub fn total_bits(&self) -> usize {
        self.classes.len + self.offsets.len + self.sb_rank.len() * 32 + self.sb_off.len() * 32
    }
}

impl Ser for Rrr {
    fn write(&self, w: &mut Writer) {
        w.usize(self.len);
        w.usize(self.classes.len);
        w.words(&self.classes.words);
        w.usize(self.offsets.len);
        w.words(&self.offsets.words);
    }
    fn read(r: &mut Reader) -> Result<Self> {
        let len = r.usize()?;
        let nblocks = len.div_ceil(B);
        let cl = r.usize()?;
        if cl != nblocks.checked_mul(4).ok_or_else(|| Error::Corrupt("rrr size".into()))? {
            return Err(Error::Corrupt("rrr class length".into()));
        }
        let classes = BitVec { words: r.words_exact(cl.div_ceil(64))?, len: cl };
        let ol = r.usize()?;
        let offsets = BitVec { words: r.words_exact(ol.div_ceil(64))?, len: ol };
        // Validate every block while rebuilding the sample tables.
        let (mut sb_rank, mut sb_off) = (Vec::new(), Vec::new());
        let (mut ones, mut pos) = (0usize, 0usize);
        for b in 0..nblocks {
            if b % SB_BLOCKS == 0 {
                sb_rank.push(ones as u32);
                sb_off.push(pos as u64);
            }
            let c = classes.get_bits(b * 4, 4) as usize;
            let wd = WIDTH[c] as usize;
            if pos + wd > ol {
                return Err(Error::Corrupt("rrr offsets truncated".into()));
            }
            let off = offsets.get_bits(pos, wd as u32);
            if off >= C[15][c] as u64 {
                return Err(Error::Corrupt("rrr offset out of range for class".into()));
            }
            let valid = B.min(len - b * B);
            let block = decode_block(c as u8, off as u16);
            if valid < B && block >> valid != 0 {
                return Err(Error::Corrupt("rrr bits beyond length".into()));
            }
            ones += c;
            pos += wd;
        }
        if nblocks % SB_BLOCKS == 0 {
            sb_rank.push(ones as u32);
            sb_off.push(pos as u64);
        }
        if pos != ol {
            return Err(Error::Corrupt("rrr offsets length mismatch".into()));
        }
        Ok(Rrr { len, ones, classes, offsets, sb_rank, sb_off })
    }
}
