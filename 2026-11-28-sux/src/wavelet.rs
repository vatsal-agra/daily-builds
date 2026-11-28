//! Wavelet matrix over a sequence of u32 symbols.
//!
//! One bitvector per bit-level (MSB first). Each level stably partitions the sequence:
//! zeros first, then ones. Queries walk the levels with rank, so every operation is
//! O(log sigma) bitvector operations.
use crate::bitvec::{BitVec, RankSelect};
use crate::rrr::Rrr;
use crate::util::{bits_for, Error, Reader, Result, Ser, Writer};

/// A level's bitvector: plain (fast) or RRR-compressed (smaller on skewed levels).
#[derive(Clone, Debug)]
enum Level {
    Plain(RankSelect),
    Rrr(Rrr),
}
impl Level {
    fn get(&self, i: usize) -> bool {
        match self { Level::Plain(x) => x.get(i), Level::Rrr(x) => x.get(i) }
    }
    fn rank1(&self, i: usize) -> usize {
        match self { Level::Plain(x) => x.rank1(i), Level::Rrr(x) => x.rank1(i) }
    }
    fn rank0(&self, i: usize) -> usize {
        i - self.rank1(i)
    }
    fn select1(&self, k: usize) -> Option<usize> {
        match self { Level::Plain(x) => x.select1(k), Level::Rrr(x) => x.select1(k) }
    }
    fn select0(&self, k: usize) -> Option<usize> {
        match self { Level::Plain(x) => x.select0(k), Level::Rrr(x) => x.select0(k) }
    }
    fn len(&self) -> usize {
        match self { Level::Plain(x) => x.len(), Level::Rrr(x) => x.len() }
    }
    fn count_zeros(&self) -> usize {
        match self { Level::Plain(x) => x.count_zeros(), Level::Rrr(x) => x.count_zeros() }
    }
    fn total_bits(&self) -> usize {
        match self { Level::Plain(x) => x.total_bits(), Level::Rrr(x) => x.total_bits() }
    }
}

#[derive(Clone, Debug)]
pub struct WaveletMatrix {
    n: usize,
    bits: u32,
    levels: Vec<Level>,
    compressed: bool,
    zeros: Vec<usize>, // number of zeros at each level
}

impl WaveletMatrix {
    pub fn new(seq: &[u32]) -> Self {
        Self::build(seq, false)
    }
    /// Same structure with RRR-compressed levels.
    pub fn new_compressed(seq: &[u32]) -> Self {
        Self::build(seq, true)
    }
    fn build(seq: &[u32], compressed: bool) -> Self {
        let max = seq.iter().copied().max().unwrap_or(0);
        Self::with_bits(seq, bits_for(max as u64), compressed)
    }

    pub fn with_bits(seq: &[u32], bits: u32, compressed: bool) -> Self {
        assert!(bits >= 1 && bits <= 32);
        assert!(seq.iter().all(|&s| bits == 32 || (s as u64) < (1u64 << bits)), "symbol exceeds bit width");
        let mut cur = seq.to_vec();
        let mut levels = Vec::new();
        let mut zeros = Vec::new();
        for lvl in 0..bits {
            let shift = bits - 1 - lvl;
            let mut bv = BitVec::new();
            let (mut z, mut o) = (Vec::new(), Vec::new());
            for &s in &cur {
                let b = (s >> shift) & 1 == 1;
                bv.push(b);
                if b {
                    o.push(s)
                } else {
                    z.push(s)
                }
            }
            zeros.push(z.len());
            z.extend(o);
            cur = z;
            levels.push(if compressed { Level::Rrr(Rrr::new(&bv)) } else { Level::Plain(RankSelect::new(bv)) });
        }
        WaveletMatrix { n: seq.len(), bits, levels, zeros, compressed }
    }

    pub fn is_compressed(&self) -> bool {
        self.compressed
    }
    pub fn len(&self) -> usize {
        self.n
    }
    pub fn is_empty(&self) -> bool {
        self.n == 0
    }
    pub fn bit_width(&self) -> u32 {
        self.bits
    }
    fn fits(&self, c: u32) -> bool {
        self.bits == 32 || (c as u64) < (1u64 << self.bits)
    }

    /// The symbol at position i.
    pub fn access(&self, i: usize) -> Option<u32> {
        if i >= self.n {
            return None;
        }
        let (mut pos, mut sym) = (i, 0u32);
        for (l, bv) in self.levels.iter().enumerate() {
            if bv.get(pos) {
                sym |= 1 << (self.bits - 1 - l as u32);
                pos = self.zeros[l] + bv.rank1(pos);
            } else {
                pos = bv.rank0(pos);
            }
        }
        Some(sym)
    }

    /// Occurrences of `c` in positions [0, i).
    pub fn rank(&self, c: u32, i: usize) -> usize {
        let i = i.min(self.n);
        if !self.fits(c) {
            return 0;
        }
        let (mut s, mut e) = (0usize, i);
        for (l, bv) in self.levels.iter().enumerate() {
            if (c >> (self.bits - 1 - l as u32)) & 1 == 1 {
                s = self.zeros[l] + bv.rank1(s);
                e = self.zeros[l] + bv.rank1(e);
            } else {
                s = bv.rank0(s);
                e = bv.rank0(e);
            }
        }
        e - s
    }

    /// Position of the k-th (0-based) occurrence of `c`.
    pub fn select(&self, c: u32, k: usize) -> Option<usize> {
        if !self.fits(c) {
            return None;
        }
        let mut s = 0usize;
        for (l, bv) in self.levels.iter().enumerate() {
            s = if (c >> (self.bits - 1 - l as u32)) & 1 == 1 { self.zeros[l] + bv.rank1(s) } else { bv.rank0(s) };
        }
        // s is where c's block starts at the bottom level; the block has `rank(c, n)` entries.
        if k >= self.rank(c, self.n) {
            return None;
        }
        let mut pos = s + k;
        for l in (0..self.bits as usize).rev() {
            let bv = &self.levels[l];
            pos = if (c >> (self.bits - 1 - l as u32)) & 1 == 1 {
                bv.select1(pos - self.zeros[l])?
            } else {
                bv.select0(pos)?
            };
        }
        Some(pos)
    }

    /// The k-th smallest (0-based) symbol in positions [l, r).
    pub fn quantile(&self, l: usize, r: usize, k: usize) -> Option<u32> {
        if l > r || r > self.n || k >= r - l {
            return None;
        }
        let (mut s, mut e, mut k, mut sym) = (l, r, k, 0u32);
        for (lv, bv) in self.levels.iter().enumerate() {
            let (s0, e0) = (bv.rank0(s), bv.rank0(e));
            let nz = e0 - s0;
            if k < nz {
                s = s0;
                e = e0;
            } else {
                k -= nz;
                sym |= 1 << (self.bits - 1 - lv as u32);
                s = self.zeros[lv] + (s - s0);
                e = self.zeros[lv] + (e - e0);
            }
        }
        Some(sym)
    }

    /// Number of positions in [l, r) whose symbol is < c.
    pub fn count_less(&self, l: usize, r: usize, c: u32) -> usize {
        if l >= r || r > self.n {
            return 0;
        }
        if !self.fits(c) {
            return r - l;
        }
        let (mut s, mut e, mut cnt) = (l, r, 0usize);
        for (lv, bv) in self.levels.iter().enumerate() {
            let (s0, e0) = (bv.rank0(s), bv.rank0(e));
            if (c >> (self.bits - 1 - lv as u32)) & 1 == 1 {
                cnt += e0 - s0;
                s = self.zeros[lv] + (s - s0);
                e = self.zeros[lv] + (e - e0);
            } else {
                s = s0;
                e = e0;
            }
        }
        cnt
    }

    /// Number of positions in [l, r) whose symbol lies in [lo, hi).
    pub fn count_range(&self, l: usize, r: usize, lo: u32, hi: u32) -> usize {
        if lo >= hi {
            return 0;
        }
        self.count_less(l, r, hi) - self.count_less(l, r, lo)
    }

    /// Smallest symbol >= c that occurs in [l, r).
    pub fn next_value(&self, l: usize, r: usize, c: u32) -> Option<u32> {
        let below = self.count_less(l, r, c);
        self.quantile(l, r, below)
    }

    pub fn total_bits(&self) -> usize {
        self.levels.iter().map(|l| l.total_bits()).sum()
    }
    pub fn payload_bits(&self) -> usize {
        self.levels.iter().map(|l| l.len()).sum()
    }
}

impl Ser for WaveletMatrix {
    fn write(&self, w: &mut Writer) {
        w.usize(self.n);
        w.u8(self.bits as u8);
        w.u8(self.compressed as u8);
        for l in &self.levels {
            match l {
                Level::Plain(x) => x.write(w),
                Level::Rrr(x) => x.write(w),
            }
        }
    }
    fn read(r: &mut Reader) -> Result<Self> {
        let n = r.usize()?;
        let bits = r.u8()? as u32;
        if bits == 0 || bits > 32 {
            return Err(Error::Corrupt("wavelet bit width".into()));
        }
        let compressed = match r.u8()? {
            0 => false,
            1 => true,
            _ => return Err(Error::Corrupt("wavelet level kind".into())),
        };
        let mut levels = Vec::new();
        let mut zeros = Vec::new();
        for _ in 0..bits {
            let l = if compressed { Level::Rrr(Rrr::read(r)?) } else { Level::Plain(RankSelect::read(r)?) };
            if l.len() != n {
                return Err(Error::Corrupt("wavelet level length".into()));
            }
            zeros.push(l.count_zeros());
            levels.push(l);
        }
        Ok(WaveletMatrix { n, bits, levels, zeros, compressed })
    }
}
