//! Plain bit vector with an O(1) rank directory (Vigna's "rank9") and sampled select.
use crate::util::{Error, Reader, Result, Ser, Writer};

/// Mutable bit container used to build things.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct BitVec {
    pub words: Vec<u64>,
    pub len: usize,
}

impl BitVec {
    pub fn new() -> Self {
        Self::default()
    }
    pub fn zeros(len: usize) -> Self {
        BitVec { words: vec![0; len.div_ceil(64)], len }
    }
    pub fn from_bools(b: &[bool]) -> Self {
        let mut v = BitVec::new();
        for &x in b {
            v.push(x);
        }
        v
    }
    pub fn push(&mut self, bit: bool) {
        if self.len % 64 == 0 {
            self.words.push(0);
        }
        if bit {
            self.words[self.len / 64] |= 1 << (self.len % 64);
        }
        self.len += 1;
    }
    /// Append the low `width` bits of `value`, least-significant first.
    pub fn push_bits(&mut self, value: u64, width: u32) {
        for i in 0..width {
            self.push((value >> i) & 1 == 1);
        }
    }
    pub fn set(&mut self, i: usize, bit: bool) {
        assert!(i < self.len, "BitVec::set out of range");
        if bit {
            self.words[i / 64] |= 1 << (i % 64);
        } else {
            self.words[i / 64] &= !(1 << (i % 64));
        }
    }
    pub fn get(&self, i: usize) -> bool {
        assert!(i < self.len, "BitVec::get out of range");
        (self.words[i / 64] >> (i % 64)) & 1 == 1
    }
    /// Read `width` (<=64) bits starting at bit `pos`.
    pub fn get_bits(&self, pos: usize, width: u32) -> u64 {
        if width == 0 {
            return 0;
        }
        debug_assert!(pos + width as usize <= self.len);
        let (w, o) = (pos / 64, (pos % 64) as u32);
        let mut v = self.words[w] >> o;
        if o + width > 64 {
            v |= self.words[w + 1] << (64 - o);
        }
        if width < 64 {
            v &= (1u64 << width) - 1;
        }
        v
    }
    pub fn count_ones(&self) -> usize {
        self.words.iter().map(|w| w.count_ones() as usize).sum()
    }
}

/// Position of the `k`-th (0-based) set bit inside a word. Requires k < popcount(w).
#[inline]
pub fn select_in_word(mut w: u64, k: u32) -> u32 {
    debug_assert!(k < w.count_ones());
    // Byte-wise skip, then bit-wise within the byte.
    let mut base = 0;
    let mut k = k;
    loop {
        let c = (w & 0xFF).count_ones();
        if k < c {
            break;
        }
        k -= c;
        w >>= 8;
        base += 8;
    }
    for _ in 0..k {
        w &= w - 1;
    }
    base + w.trailing_zeros()
}

const SB_WORDS: usize = 8; // 512 bits per superblock
const SEL_SAMPLE: usize = 2048; // one sample per this many ones/zeros

/// Immutable bit vector with constant-time rank and fast select.
///
/// Directory layout (rank9): for each 512-bit superblock two u64s —
/// the absolute number of ones before it, and seven 9-bit counters giving
/// ones before each of words 1..7 inside the block. Overhead: 25% of n.
#[derive(Clone, Debug)]
pub struct RankSelect {
    bits: BitVec,
    dir: Vec<u64>,
    ones: usize,
    sel1: Vec<u32>, // superblock containing every SEL_SAMPLE-th one
    sel0: Vec<u32>, // ... zero
}

impl RankSelect {
    pub fn new(bits: BitVec) -> Self {
        let mut bits = bits;
        let nsb = bits.len / (SB_WORDS * 64) + 1; // +1 so rank(len) always has a block
        bits.words.resize(nsb * SB_WORDS, 0);
        let mut dir = Vec::with_capacity(nsb * 2);
        let mut total = 0u64;
        for sb in 0..nsb {
            dir.push(total);
            let mut packed = 0u64;
            let mut inner = 0u64;
            for j in 0..SB_WORDS {
                if j > 0 {
                    packed |= inner << (9 * (j - 1));
                }
                inner += bits.words[sb * SB_WORDS + j].count_ones() as u64;
            }
            dir.push(packed);
            total += inner;
        }
        let ones = total as usize;
        let zeros = bits.len - ones;
        let mut sel1 = Vec::new();
        let mut sel0 = Vec::new();
        // sample[k] = superblock holding the (k*SEL_SAMPLE)-th one/zero.
        let (mut next1, mut next0) = (0usize, 0usize);
        for sb in 0..nsb {
            let end_bit = ((sb + 1) * SB_WORDS * 64).min(bits.len);
            let ones_after = if sb + 1 < nsb { dir[(sb + 1) * 2] as usize } else { ones };
            let zeros_after = end_bit - ones_after.min(end_bit);
            while next1 < ones_after && next1 < ones {
                sel1.push(sb as u32);
                next1 += SEL_SAMPLE;
            }
            while next0 < zeros_after && next0 < zeros {
                sel0.push(sb as u32);
                next0 += SEL_SAMPLE;
            }
        }
        sel1.push(nsb as u32 - 1);
        sel0.push(nsb as u32 - 1);
        RankSelect { bits, dir, ones, sel1, sel0 }
    }

    pub fn len(&self) -> usize {
        self.bits.len
    }
    pub fn is_empty(&self) -> bool {
        self.bits.len == 0
    }
    pub fn count_ones(&self) -> usize {
        self.ones
    }
    pub fn count_zeros(&self) -> usize {
        self.bits.len - self.ones
    }
    pub fn get(&self, i: usize) -> bool {
        self.bits.get(i)
    }
    pub fn bits(&self) -> &BitVec {
        &self.bits
    }

    /// Number of ones in `[0, i)`. `i` may equal `len`.
    #[inline]
    pub fn rank1(&self, i: usize) -> usize {
        assert!(i <= self.bits.len, "rank1 position {} out of range (len {})", i, self.bits.len);
        let sb = i / (SB_WORDS * 64);
        let w = (i / 64) % SB_WORDS;
        let mut r = self.dir[sb * 2] as usize;
        if w > 0 {
            r += ((self.dir[sb * 2 + 1] >> (9 * (w - 1))) & 0x1FF) as usize;
        }
        let rem = i % 64;
        if rem > 0 {
            r += (self.bits.words[sb * SB_WORDS + w] & ((1u64 << rem) - 1)).count_ones() as usize;
        }
        r
    }
    #[inline]
    pub fn rank0(&self, i: usize) -> usize {
        i - self.rank1(i)
    }

    /// Ones strictly before superblock `sb` (zeros likewise).
    #[inline]
    fn ones_before_sb(&self, sb: usize) -> usize {
        self.dir[sb * 2] as usize
    }

    /// Position of the `k`-th (0-based) one, or None if k >= count_ones.
    pub fn select1(&self, k: usize) -> Option<usize> {
        if k >= self.ones {
            return None;
        }
        let (mut lo, mut hi) = (self.sel1[k / SEL_SAMPLE] as usize, self.sel1[k / SEL_SAMPLE + 1] as usize);
        // Last superblock in [lo, hi] whose preceding count is <= k.
        while lo < hi {
            let mid = (lo + hi + 1) / 2;
            if self.ones_before_sb(mid) <= k {
                lo = mid;
            } else {
                hi = mid - 1;
            }
        }
        let mut need = k - self.ones_before_sb(lo);
        let base = lo * SB_WORDS;
        for j in 0..SB_WORDS {
            let c = self.bits.words[base + j].count_ones() as usize;
            if need < c {
                return Some((base + j) * 64 + select_in_word(self.bits.words[base + j], need as u32) as usize);
            }
            need -= c;
        }
        unreachable!("select1 directory inconsistent")
    }

    /// Position of the `k`-th (0-based) zero, or None.
    pub fn select0(&self, k: usize) -> Option<usize> {
        if k >= self.count_zeros() {
            return None;
        }
        let zeros_before = |sb: usize| sb * SB_WORDS * 64 - self.ones_before_sb(sb);
        let (mut lo, mut hi) = (self.sel0[k / SEL_SAMPLE] as usize, self.sel0[k / SEL_SAMPLE + 1] as usize);
        while lo < hi {
            let mid = (lo + hi + 1) / 2;
            if zeros_before(mid) <= k {
                lo = mid;
            } else {
                hi = mid - 1;
            }
        }
        let mut need = k - zeros_before(lo);
        let base = lo * SB_WORDS;
        for j in 0..SB_WORDS {
            let wi = base + j;
            // Padding bits past `len` must not count as zeros.
            let valid = self.bits.len.saturating_sub(wi * 64).min(64);
            let mask = if valid == 64 { u64::MAX } else { (1u64 << valid) - 1 };
            let z = !self.bits.words[wi] & mask;
            let c = z.count_ones() as usize;
            if need < c {
                return Some(wi * 64 + select_in_word(z, need as u32) as usize);
            }
            need -= c;
        }
        unreachable!("select0 directory inconsistent")
    }

    /// Size of the directory + samples in bits (the "extra" cost beyond the raw bits).
    pub fn overhead_bits(&self) -> usize {
        (self.dir.len() * 64) + (self.sel1.len() + self.sel0.len()) * 32
    }
    pub fn total_bits(&self) -> usize {
        self.bits.words.len() * 64 + self.overhead_bits()
    }
}

/// Only the raw bits are stored; the directory is rebuilt on load.
impl Ser for RankSelect {
    fn write(&self, w: &mut Writer) {
        w.usize(self.bits.len);
        let n = self.bits.len.div_ceil(64);
        w.usize(n);
        for i in 0..n {
            w.u64(self.bits.words[i]);
        }
    }
    fn read(r: &mut Reader) -> Result<Self> {
        let len = r.usize()?;
        let words = r.words_exact(len.div_ceil(64))?;
        let mut bv = BitVec { words, len };
        // Stray bits beyond len would corrupt select0/rank; reject rather than mask silently.
        if len % 64 != 0 {
            if let Some(&last) = bv.words.last() {
                if last >> (len % 64) != 0 {
                    return Err(Error::Corrupt("bits set beyond bitvector length".into()));
                }
            }
        }
        bv.len = len;
        Ok(RankSelect::new(bv))
    }
}
