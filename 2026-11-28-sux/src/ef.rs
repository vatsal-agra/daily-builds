//! Elias–Fano encoding of a non-decreasing integer sequence.
//!
//! n values in universe [0, u): each value is split into `l = floor(log2(u/n))` low
//! bits (stored packed) and a high part stored in unary in a bitvector of n + (u >> l) bits.
//! Space is about n * (2 + log2(u/n)) bits, within half a bit of the information-theoretic bound.
use crate::bitvec::{BitVec, RankSelect};
use crate::util::{Error, Reader, Result, Ser, Writer};

#[derive(Clone, Debug)]
pub struct EliasFano {
    n: usize,
    universe: u64, // all values < universe
    l: u32,
    low: BitVec,
    high: RankSelect,
}

impl EliasFano {
    /// Build from a non-decreasing sequence. Duplicates are allowed.
    pub fn new(values: &[u64]) -> Result<Self> {
        for w in values.windows(2) {
            if w[0] > w[1] {
                return Err(Error::Invalid(format!("sequence not non-decreasing: {} then {}", w[0], w[1])));
            }
        }
        let universe = values.last().map_or(0, |&m| m.checked_add(1).unwrap_or(m));
        Self::with_universe(values, universe)
    }

    pub fn with_universe(values: &[u64], universe: u64) -> Result<Self> {
        let n = values.len();
        if let Some(&m) = values.last() {
            if m >= universe {
                return Err(Error::Invalid(format!("value {m} not below universe {universe}")));
            }
        }
        let l = if n == 0 || universe <= n as u64 { 0 } else { 63 - (universe / n as u64).leading_zeros() };
        let mut low = BitVec::new();
        let hi_len = n + (universe >> l) as usize + 1;
        let mut high = BitVec::zeros(hi_len);
        for (i, &v) in values.iter().enumerate() {
            low.push_bits(v & ((1u64 << l) - 1), l);
            high.set((v >> l) as usize + i, true);
        }
        Ok(EliasFano { n, universe, l, low, high: RankSelect::new(high) })
    }

    pub fn len(&self) -> usize {
        self.n
    }
    pub fn is_empty(&self) -> bool {
        self.n == 0
    }
    pub fn universe(&self) -> u64 {
        self.universe
    }

    /// The i-th value.
    pub fn get(&self, i: usize) -> Option<u64> {
        if i >= self.n {
            return None;
        }
        let h = self.high.select1(i)? - i;
        Some(((h as u64) << self.l) | self.low.get_bits(i * self.l as usize, self.l))
    }

    /// Index range [lo, hi) of elements whose high part equals `h`.
    fn bucket(&self, h: u64) -> (usize, usize) {
        let h = h as usize;
        let start = if h == 0 { 0 } else { self.high.select0(h - 1).map_or(self.n, |p| p + 1 - h) };
        let end = self.high.select0(h).map_or(self.n, |p| p - h);
        (start, end.max(start))
    }

    /// Number of elements strictly less than `x`.
    pub fn rank(&self, x: u64) -> usize {
        if self.n == 0 || x == 0 {
            return 0;
        }
        if x >= self.universe {
            return self.n;
        }
        let h = x >> self.l;
        let (mut lo, mut hi) = self.bucket(h);
        let xl = x & ((1u64 << self.l) - 1);
        // Binary search the bucket's low parts (non-decreasing inside a bucket).
        let start = lo;
        while lo < hi {
            let mid = (lo + hi) / 2;
            if self.low.get_bits(mid * self.l as usize, self.l) < xl {
                lo = mid + 1;
            } else {
                hi = mid;
            }
        }
        debug_assert!(lo >= start);
        lo
    }

    /// Smallest element >= x, with its index.
    pub fn successor(&self, x: u64) -> Option<(usize, u64)> {
        let i = self.rank(x);
        self.get(i).map(|v| (i, v))
    }

    /// Largest element <= x, with its index.
    pub fn predecessor(&self, x: u64) -> Option<(usize, u64)> {
        let r = if x == u64::MAX { self.n } else { self.rank(x + 1) };
        if r == 0 {
            None
        } else {
            self.get(r - 1).map(|v| (r - 1, v))
        }
    }

    pub fn contains(&self, x: u64) -> bool {
        matches!(self.successor(x), Some((_, v)) if v == x)
    }

    pub fn iter(&self) -> impl Iterator<Item = u64> + '_ {
        (0..self.n).map(move |i| self.get(i).unwrap())
    }

    /// Bits used by the encoded data (low part + high part, excluding the select directory).
    pub fn payload_bits(&self) -> usize {
        self.low.len + self.high.len()
    }
    pub fn total_bits(&self) -> usize {
        self.low.len + self.high.total_bits()
    }
}

impl Ser for EliasFano {
    fn write(&self, w: &mut Writer) {
        w.usize(self.n);
        w.u64(self.universe);
        w.u8(self.l as u8);
        w.usize(self.low.len);
        w.words(&self.low.words);
        self.high.write(w);
    }
    fn read(r: &mut Reader) -> Result<Self> {
        let n = r.usize()?;
        let universe = r.u64()?;
        let l = r.u8()? as u32;
        if l > 63 {
            return Err(Error::Corrupt("elias-fano low width".into()));
        }
        let low_len = r.usize()?;
        if low_len != n.checked_mul(l as usize).ok_or_else(|| Error::Corrupt("ef size".into()))? {
            return Err(Error::Corrupt("elias-fano low length inconsistent".into()));
        }
        let low = BitVec { words: r.words_exact(low_len.div_ceil(64))?, len: low_len };
        let high = RankSelect::read(r)?;
        if high.count_ones() != n || high.len() != n + (universe >> l) as usize + 1 {
            return Err(Error::Corrupt("elias-fano high part inconsistent".into()));
        }
        Ok(EliasFano { n, universe, l, low, high })
    }
}
