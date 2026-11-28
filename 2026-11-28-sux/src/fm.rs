//! FM-index: a compressed full-text index built on the Burrows–Wheeler transform.
//!
//! * BWT lives in a wavelet matrix over a compacted alphabet (rank = LF-mapping).
//! * Every `sample_rate`-th text position has its suffix-array row sampled (locate);
//!   the inverse mapping is sampled the same way (extract).
//! * Newline offsets are stored as an Elias–Fano sequence, so `grep` can print line
//!   numbers and whole lines from the index alone — the original file is not needed.
use crate::bitvec::{BitVec, RankSelect};
use crate::ef::EliasFano;
use crate::sais::suffix_array;
use crate::util::*;
use crate::wavelet::WaveletMatrix;

const MAGIC: &[u8; 4] = b"SUXF";

#[derive(Debug)]
pub struct FmIndex {
    n: usize,              // text length (without sentinel)
    sample_rate: usize,
    alphabet: Vec<u8>,     // alphabet[k-1] = byte for compact symbol k
    c: Vec<usize>,         // c[k] = number of BWT symbols < k
    bwt: WaveletMatrix,
    sa_marked: RankSelect, // row has a sampled SA value
    sa_samples: Vec<u32>,  // SA values of marked rows, in row order, stored / sample_rate
    isa_samples: Vec<u32>, // row of the suffix starting at text position j*sample_rate
    newlines: EliasFano,   // text offsets of '\n'
}

/// One matching line.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LineHit {
    pub line: usize, // 1-based
    pub text: Vec<u8>,
    /// Offsets (relative to line start) where the pattern occurs.
    pub columns: Vec<usize>,
}

impl FmIndex {
    pub fn build(text: &[u8], sample_rate: usize) -> Result<Self> {
        Self::build_with(text, sample_rate, false)
    }

    /// `compressed` stores the BWT's wavelet levels as RRR bitvectors (smaller, slower).
    pub fn build_with(text: &[u8], sample_rate: usize, compressed: bool) -> Result<Self> {
        if sample_rate == 0 || sample_rate > 4096 {
            return Err(Error::Invalid("sample rate must be in 1..=4096".into()));
        }
        if text.len() >= u32::MAX as usize - 1 {
            return Err(Error::Invalid("text too large (limit 4 GiB - 2)".into()));
        }
        let n = text.len();
        // Compact alphabet: 0 = sentinel, then used bytes in order.
        let mut used = [false; 256];
        for &b in text {
            used[b as usize] = true;
        }
        let alphabet: Vec<u8> = (0..=255u8).filter(|&b| used[b as usize]).collect();
        let mut map = [0usize; 256];
        for (k, &b) in alphabet.iter().enumerate() {
            map[b as usize] = k + 1;
        }
        let sigma = alphabet.len() + 1;
        let mut s: Vec<usize> = text.iter().map(|&b| map[b as usize]).collect();
        s.push(0);
        let sa = suffix_array(&s, sigma - 1);
        debug_assert_eq!(sa[0], n);

        let mut bwt_syms = Vec::with_capacity(n + 1);
        let mut c = vec![0usize; sigma + 1];
        for &x in &s {
            c[x + 1] += 1;
        }
        for k in 0..sigma {
            c[k + 1] += c[k];
        }
        let mut marked = BitVec::new();
        let mut sa_samples = Vec::new();
        let mut isa_samples = vec![0u32; n.div_ceil(sample_rate).max(1)];
        for (row, &p) in sa.iter().enumerate() {
            bwt_syms.push(if p == 0 { 0 } else { s[p - 1] as u32 });
            if p % sample_rate == 0 {
                marked.push(true);
                sa_samples.push((p / sample_rate) as u32);
                if p < n {
                    isa_samples[p / sample_rate] = row as u32;
                }
            } else {
                marked.push(false);
            }
        }
        let nl: Vec<u64> = text.iter().enumerate().filter(|(_, &b)| b == b'\n').map(|(i, _)| i as u64).collect();
        let newlines = EliasFano::with_universe(&nl, n as u64 + 1)?;
        Ok(FmIndex {
            n,
            sample_rate,
            alphabet,
            c,
            bwt: if compressed { WaveletMatrix::new_compressed(&bwt_syms) } else { WaveletMatrix::new(&bwt_syms) },
            sa_marked: RankSelect::new(marked),
            sa_samples,
            isa_samples,
            newlines,
        })
    }

    pub fn is_compressed(&self) -> bool {
        self.bwt.is_compressed()
    }
    pub fn len(&self) -> usize {
        self.n
    }
    pub fn is_empty(&self) -> bool {
        self.n == 0
    }
    pub fn sample_rate(&self) -> usize {
        self.sample_rate
    }
    pub fn line_count(&self) -> usize {
        self.newlines.len() + usize::from(self.line_start(self.newlines.len()) < self.n)
    }

    fn sym(&self, b: u8) -> Option<usize> {
        self.alphabet.binary_search(&b).ok().map(|k| k + 1)
    }

    /// Backward search: half-open row range [lo, hi) of suffixes prefixed by `pat`.
    pub fn search(&self, pat: &[u8]) -> (usize, usize) {
        let (mut lo, mut hi) = (0usize, self.n + 1);
        for &b in pat.iter().rev() {
            let Some(k) = self.sym(b) else { return (0, 0) };
            lo = self.c[k] + self.bwt.rank(k as u32, lo);
            hi = self.c[k] + self.bwt.rank(k as u32, hi);
            if lo >= hi {
                return (0, 0);
            }
        }
        (lo, hi)
    }

    /// Number of occurrences. The empty pattern occurs at every one of the n+1 positions
    /// (including the end), so `count(b"") == len() + 1`.
    pub fn count(&self, pat: &[u8]) -> usize {
        let (lo, hi) = self.search(pat);
        hi - lo
    }

    #[inline]
    fn lf(&self, row: usize) -> usize {
        let k = self.bwt.access(row).unwrap();
        self.c[k as usize] + self.bwt.rank(k, row)
    }

    /// Text position of the suffix at `row`. In a valid index a sampled row is reached
    /// within `sample_rate` LF steps; anything longer means the index is corrupt.
    fn locate_row(&self, mut row: usize) -> Result<usize> {
        for steps in 0..self.sample_rate {
            if self.sa_marked.get(row) {
                let pos = self.sa_samples[self.sa_marked.rank1(row)] as usize * self.sample_rate + steps;
                return if pos <= self.n { Ok(pos) } else { Err(Error::Corrupt("located position beyond text".into())) };
            }
            row = self.lf(row);
        }
        Err(Error::Corrupt("suffix-array sampling inconsistent (index is corrupt)".into()))
    }

    /// All start positions of `pat` (sorted ascending). Empty pattern -> error.
    pub fn locate(&self, pat: &[u8]) -> Result<Vec<usize>> {
        if pat.is_empty() {
            return Err(Error::Invalid("empty pattern".into()));
        }
        let (lo, hi) = self.search(pat);
        let mut v = (lo..hi).map(|r| self.locate_row(r)).collect::<Result<Vec<usize>>>()?;
        v.sort_unstable();
        Ok(v)
    }

    /// Reconstruct text[start..end) from the index alone.
    pub fn extract(&self, start: usize, end: usize) -> Result<Vec<u8>> {
        if start > end {
            return Err(Error::Invalid(format!("start {start} is after end {end}")));
        }
        if end > self.n {
            return Err(Error::Invalid(format!("end {end} is beyond the text length {}", self.n)));
        }
        if start == end {
            return Ok(Vec::new());
        }
        let sr = self.sample_rate;
        let p = end.div_ceil(sr) * sr;
        let (mut pos, mut row) = if p >= self.n { (self.n, 0) } else { (p, self.isa_samples[p / sr] as usize) };
        let mut out = Vec::with_capacity(end - start);
        while pos > start {
            let k = self.bwt.access(row).unwrap();
            if k == 0 {
                return Err(Error::Corrupt("hit the sentinel while extracting (index is corrupt)".into()));
            }
            pos -= 1;
            if pos < end {
                out.push(self.alphabet[k as usize - 1]);
            }
            row = self.c[k as usize] + self.bwt.rank(k, row);
        }
        out.reverse();
        Ok(out)
    }

    /// Offset where 0-based line `i` starts (line_count() gives n or n+1 sentinel).
    fn line_start(&self, i: usize) -> usize {
        if i == 0 {
            0
        } else {
            self.newlines.get(i - 1).map_or(self.n, |p| p as usize + 1)
        }
    }
    /// 0-based line containing text offset `pos`.
    fn line_of(&self, pos: usize) -> usize {
        self.newlines.rank(pos as u64)
    }

    /// Full text of 1-based line number (without trailing newline).
    pub fn line(&self, number: usize) -> Result<Vec<u8>> {
        if number == 0 || number > self.line_count() {
            return Err(Error::Invalid(format!("line {number} out of range 1..={}", self.line_count())));
        }
        let s = self.line_start(number - 1);
        let e = self.newlines.get(number - 1).map_or(self.n, |p| p as usize);
        self.extract(s, e)
    }

    /// Lines containing `pat` (patterns containing '\n' can never match inside one line).
    pub fn grep(&self, pat: &[u8]) -> Result<Vec<LineHit>> {
        if pat.contains(&b'\n') {
            return Err(Error::Invalid("pattern may not contain a newline".into()));
        }
        let positions = self.locate(pat)?;
        let mut hits: Vec<LineHit> = Vec::new();
        for p in positions {
            let ln = self.line_of(p);
            let col = p - self.line_start(ln);
            match hits.last_mut() {
                Some(h) if h.line == ln + 1 => h.columns.push(col),
                _ => hits.push(LineHit { line: ln + 1, text: self.line(ln + 1)?, columns: vec![col] }),
            }
        }
        Ok(hits)
    }

    pub fn total_bits(&self) -> usize {
        self.bwt.total_bits()
            + self.sa_marked.total_bits()
            + self.sa_samples.len() * 32
            + self.isa_samples.len() * 32
            + self.newlines.total_bits()
    }

    pub fn save_bytes(&self) -> Vec<u8> {
        let mut w = Writer::new();
        self.write(&mut w);
        seal(MAGIC, &w.buf)
    }
    pub fn load_bytes(data: &[u8]) -> Result<Self> {
        let payload = unseal(MAGIC, data)?;
        let mut r = Reader::new(payload);
        let fm = Self::read(&mut r)?;
        if r.remaining() != 0 {
            return Err(Error::Corrupt("trailing bytes".into()));
        }
        Ok(fm)
    }
}

impl Ser for FmIndex {
    fn write(&self, w: &mut Writer) {
        w.usize(self.n);
        w.usize(self.sample_rate);
        w.bytes(&self.alphabet);
        self.bwt.write(w);
        self.sa_marked.write(w);
        w.u32s(&self.sa_samples);
        w.u32s(&self.isa_samples);
        self.newlines.write(w);
    }
    fn read(r: &mut Reader) -> Result<Self> {
        let n = r.usize()?;
        let sample_rate = r.usize()?;
        if sample_rate == 0 || sample_rate > 4096 {
            return Err(Error::Corrupt("sample rate".into()));
        }
        let alphabet = r.bytes()?;
        if alphabet.windows(2).any(|w| w[0] >= w[1]) {
            return Err(Error::Corrupt("alphabet not strictly increasing".into()));
        }
        let sigma = alphabet.len() + 1;
        let bwt = WaveletMatrix::read(r)?;
        if bwt.len() != n + 1 {
            return Err(Error::Corrupt("bwt length".into()));
        }
        // Derive C[] from the BWT itself so it can never disagree with it.
        let mut c = vec![0usize; sigma + 1];
        for k in 0..sigma {
            c[k + 1] = c[k] + bwt.rank(k as u32, n + 1);
        }
        if c[sigma] != n + 1 {
            return Err(Error::Corrupt("bwt contains symbols outside the alphabet".into()));
        }
        let sa_marked = RankSelect::read(r)?;
        if sa_marked.len() != n + 1 {
            return Err(Error::Corrupt("marker length".into()));
        }
        let sa_samples = r.u32s()?;
        if sa_samples.len() != sa_marked.count_ones() || sa_samples.iter().any(|&v| v as usize * sample_rate > n) {
            return Err(Error::Corrupt("sa samples".into()));
        }
        let isa_samples = r.u32s()?;
        if isa_samples.len() != n.div_ceil(sample_rate).max(1) || isa_samples.iter().any(|&v| v as usize > n) {
            return Err(Error::Corrupt("isa samples".into()));
        }
        let newlines = EliasFano::read(r)?;
        if newlines.universe() != n as u64 + 1 {
            return Err(Error::Corrupt("newline universe".into()));
        }
        Ok(FmIndex { n, sample_rate, alphabet, c, bwt, sa_marked, sa_samples, isa_samples, newlines })
    }
}
