//! FM-index over a DNA reference: BWT with rank checkpoints, backward search
//! and `locate` through a sampled suffix array walked with LF-mapping.
//!
//! Text layout: codes 1..4 followed by one sentinel 0. Records of a multi-FASTA
//! reference are simply concatenated; hits that straddle a record boundary are
//! filtered by callers via `Reference::locate`.

use crate::sais;
use crate::seq::Reference;
use std::io::{Read, Write};

const CHECK: usize = 64; // occ checkpoint interval
const MAGIC: &[u8; 8] = b"STRANDFM";
const VERSION: u32 = 1;

pub struct FmIndex {
    pub reference: Reference,
    n: usize,             // text length including sentinel
    bwt: Vec<u8>,         // 0..=4
    c: [usize; 6],        // c[x] = number of symbols < x ; c[5] = n
    occ: Vec<[u32; 4]>,   // occ[i] = counts of codes 1..4 in bwt[0..i*CHECK]
    sa_rate: usize,
    sa_samples: Vec<u32>, // SA[row] for rows divisible by sa_rate
}

/// Half-open row interval [lo,hi) in the suffix array.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Range {
    pub lo: usize,
    pub hi: usize,
}

impl Range {
    pub fn len(&self) -> usize {
        self.hi.saturating_sub(self.lo)
    }
    pub fn is_empty(&self) -> bool {
        self.hi <= self.lo
    }
}

impl FmIndex {
    pub fn build(reference: Reference, sa_rate: usize) -> FmIndex {
        assert!(sa_rate >= 1);
        let mut text: Vec<u32> = reference.codes.iter().map(|&c| c as u32).collect();
        text.push(0);
        let n = text.len();
        assert!(n < u32::MAX as usize, "reference too large for 32-bit positions");
        let sa = sais::suffix_array(&text, 5);
        let mut bwt = vec![0u8; n];
        for (i, &p) in sa.iter().enumerate() {
            bwt[i] = if p == 0 { 0 } else { text[p - 1] as u8 };
        }
        let sa_samples: Vec<u32> = sa.iter().step_by(sa_rate).map(|&p| p as u32).collect();
        Self::assemble(reference, n, bwt, sa_rate, sa_samples)
    }

    fn assemble(reference: Reference, n: usize, bwt: Vec<u8>, sa_rate: usize, sa_samples: Vec<u32>) -> FmIndex {
        let mut cnt = [0usize; 5];
        let mut occ = Vec::with_capacity(n / CHECK + 2);
        let mut run = [0u32; 4];
        for (i, &b) in bwt.iter().enumerate() {
            if i % CHECK == 0 {
                occ.push(run);
            }
            cnt[b as usize] += 1;
            if b != 0 {
                run[b as usize - 1] += 1;
            }
        }
        if n % CHECK == 0 {
            occ.push(run); // checkpoint for rank at i == n
        }
        let mut c = [0usize; 6];
        for x in 0..5 {
            c[x + 1] = c[x] + cnt[x];
        }
        FmIndex { reference, n, bwt, c, occ, sa_rate, sa_samples }
    }

    pub fn text_len(&self) -> usize {
        self.n - 1
    }

    /// Number of occurrences of code `x` (1..=4) in bwt[0..i).
    #[inline]
    pub fn rank(&self, x: u8, i: usize) -> usize {
        let blk = i / CHECK;
        let mut r = self.occ[blk][x as usize - 1] as usize;
        for &b in &self.bwt[blk * CHECK..i] {
            r += (b == x) as usize;
        }
        r
    }

    pub fn full_range(&self) -> Range {
        Range { lo: 0, hi: self.n }
    }

    /// One backward-search step: prepend code `x` to the pattern matched by `r`.
    #[inline]
    pub fn extend(&self, r: Range, x: u8) -> Range {
        Range { lo: self.c[x as usize] + self.rank(x, r.lo), hi: self.c[x as usize] + self.rank(x, r.hi) }
    }

    /// Rows matching `pattern` (codes 1..4). Empty pattern matches every row.
    pub fn search(&self, pattern: &[u8]) -> Range {
        let mut r = self.full_range();
        for &x in pattern.iter().rev() {
            if !(1..=4).contains(&x) {
                return Range { lo: 0, hi: 0 };
            }
            r = self.extend(r, x);
            if r.is_empty() {
                break;
            }
        }
        r
    }

    pub fn count(&self, pattern: &[u8]) -> usize {
        self.search(pattern).len()
    }

    /// Text position of suffix-array row `row`, via LF walking to a sampled row.
    pub fn locate_row(&self, mut row: usize) -> usize {
        let mut steps = 0;
        loop {
            if row % self.sa_rate == 0 {
                return self.sa_samples[row / self.sa_rate] as usize + steps;
            }
            let b = self.bwt[row];
            if b == 0 {
                // this row's suffix starts at text position 0
                return steps;
            }
            row = self.c[b as usize] + self.rank(b, row);
            steps += 1;
        }
    }

    /// All text positions of `pattern`, sorted ascending.
    pub fn locate(&self, pattern: &[u8]) -> Vec<usize> {
        let r = self.search(pattern);
        let mut v: Vec<usize> = (r.lo..r.hi).map(|row| self.locate_row(row)).collect();
        v.sort_unstable();
        v
    }

    /// Reconstruct the text from the BWT alone (inverse BWT) — proves the index is lossless.
    pub fn invert(&self) -> Vec<u8> {
        let mut out = vec![0u8; self.n - 1];
        let mut row = 0; // row 0 is the sentinel suffix; its BWT symbol is the last text char
        for i in (0..self.n - 1).rev() {
            let b = self.bwt[row];
            out[i] = b;
            row = self.c[b as usize] + self.rank(b, row);
        }
        out
    }

    // ---- persistence -----------------------------------------------------------------

    pub fn save(&self, path: &str) -> Result<(), String> {
        let f = std::fs::File::create(path).map_err(|e| format!("{}: {}", path, e))?;
        let mut w = std::io::BufWriter::new(f);
        self.write_to(&mut w).map_err(|e| format!("{}: {}", path, e))
    }

    fn write_to<W: Write>(&self, w: &mut W) -> std::io::Result<()> {
        w.write_all(MAGIC)?;
        w.write_all(&VERSION.to_le_bytes())?;
        w.write_all(&(self.sa_rate as u32).to_le_bytes())?;
        w.write_all(&(self.reference.names.len() as u32).to_le_bytes())?;
        for i in 0..self.reference.names.len() {
            let nm = self.reference.names[i].as_bytes();
            w.write_all(&(nm.len() as u32).to_le_bytes())?;
            w.write_all(nm)?;
            w.write_all(&(self.reference.lens[i] as u64).to_le_bytes())?;
        }
        w.write_all(&(self.reference.ambiguous as u64).to_le_bytes())?;
        w.write_all(&(self.n as u64).to_le_bytes())?;
        w.write_all(&self.bwt)?;
        for &s in &self.sa_samples {
            w.write_all(&s.to_le_bytes())?;
        }
        let mut sum = checksum(&self.bwt);
        for &s in &self.sa_samples {
            sum = sum.rotate_left(5) ^ s as u64;
        }
        for nm in &self.reference.names {
            sum = sum.rotate_left(5) ^ checksum(nm.as_bytes());
        }
        w.write_all(&sum.to_le_bytes())?;
        w.flush()
    }

    pub fn load(path: &str) -> Result<FmIndex, String> {
        let mut f = std::fs::File::open(path).map_err(|e| format!("{}: {}", path, e))?;
        let mut buf = Vec::new();
        f.read_to_end(&mut buf).map_err(|e| format!("{}: {}", path, e))?;
        Self::from_bytes(&buf).map_err(|e| format!("{}: {}", path, e))
    }

    pub fn from_bytes(buf: &[u8]) -> Result<FmIndex, String> {
        let mut p = 0usize;
        let mut take = |k: usize| -> Result<&[u8], String> {
            if k > buf.len() - p {
                return Err("truncated index file".into());
            }
            let s = &buf[p..p + k];
            p += k;
            Ok(s)
        };
        if take(8)? != MAGIC {
            return Err("not a Strand index (bad magic)".into());
        }
        let u32le = |b: &[u8]| u32::from_le_bytes(b.try_into().unwrap());
        let u64le = |b: &[u8]| u64::from_le_bytes(b.try_into().unwrap());
        let ver = u32le(take(4)?);
        if ver != VERSION {
            return Err(format!("unsupported index version {}", ver));
        }
        let sa_rate = u32le(take(4)?) as usize;
        if sa_rate == 0 {
            return Err("corrupt index (sa_rate 0)".into());
        }
        let nrec = u32le(take(4)?) as usize;
        let mut names = vec![];
        let mut lens = vec![];
        for _ in 0..nrec {
            let l = u32le(take(4)?) as usize;
            names.push(String::from_utf8(take(l)?.to_vec()).map_err(|_| "corrupt record name".to_string())?);
            lens.push(u64le(take(8)?) as usize);
        }
        let ambiguous = u64le(take(8)?) as usize;
        let n = u64le(take(8)?) as usize;
        if lens.iter().sum::<usize>() + 1 != n {
            return Err("corrupt index (lengths disagree)".into());
        }
        let bwt = take(n)?.to_vec();
        if bwt.iter().any(|&b| b > 4) {
            return Err("corrupt index (bad BWT symbol)".into());
        }
        let ns = (n + sa_rate - 1) / sa_rate;
        let mut sa_samples = Vec::with_capacity(ns);
        for _ in 0..ns {
            sa_samples.push(u32le(take(4)?));
        }
        let sum = u64le(take(8)?);
        let mut want = checksum(&bwt);
        for &s in &sa_samples {
            want = want.rotate_left(5) ^ s as u64;
        }
        for nm in &names {
            want = want.rotate_left(5) ^ checksum(nm.as_bytes());
        }
        if sum != want {
            return Err("index checksum mismatch (file is corrupt)".into());
        }
        if p != buf.len() {
            return Err("trailing bytes after index data".into());
        }
        if sa_samples.iter().any(|&s| s as usize >= n) {
            return Err("corrupt index (suffix-array sample out of range)".into());
        }
        let mut offsets = vec![];
        let mut o = 0;
        for &l in &lens {
            offsets.push(o);
            o += l;
        }
        let mut idx = Self::assemble(Reference { names, offsets, lens, codes: vec![], ambiguous }, n, bwt, sa_rate, sa_samples);
        // The reference codes are recovered from the BWT itself.
        idx.reference.codes = idx.invert();
        Ok(idx)
    }
}

fn checksum(b: &[u8]) -> u64 {
    // FNV-1a
    let mut h = 0xcbf29ce484222325u64;
    for &x in b {
        h ^= x as u64;
        h = h.wrapping_mul(0x100000001b3);
    }
    h
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::rng::Rng;
    use crate::seq::{parse_fasta, Reference};

    fn random_ref(seed: u64, n: usize) -> Reference {
        let mut r = Rng::new(seed);
        let s: String = (0..n).map(|_| b"ACGT"[r.below(4)] as char).collect();
        Reference::from_fasta(&parse_fasta(&format!(">x\n{}\n", s)).unwrap()).unwrap()
    }

    fn naive_locate(text: &[u8], pat: &[u8]) -> Vec<usize> {
        (0..text.len().saturating_sub(pat.len() - 1)).filter(|&i| &text[i..i + pat.len()] == pat).collect()
    }

    #[test]
    fn count_and_locate_match_naive() {
        for (seed, n, rate) in [(1u64, 500usize, 1usize), (2, 777, 4), (3, 64, 8), (4, 1000, 16), (5, 127, 3)] {
            let r = random_ref(seed, n);
            let text = r.codes.clone();
            let fm = FmIndex::build(r, rate);
            let mut rng = Rng::new(seed + 100);
            for _ in 0..300 {
                let len = 1 + rng.below(8);
                let pat: Vec<u8> = if rng.chance(0.7) {
                    let st = rng.below(n - len);
                    text[st..st + len].to_vec()
                } else {
                    (0..len).map(|_| 1 + rng.below(4) as u8).collect()
                };
                let want = naive_locate(&text, &pat);
                assert_eq!(fm.count(&pat), want.len());
                assert_eq!(fm.locate(&pat), want, "pattern {:?}", pat);
            }
        }
    }

    #[test]
    fn invert_recovers_text() {
        for n in [1usize, 2, 63, 64, 65, 1234] {
            let r = random_ref(9 + n as u64, n);
            let text = r.codes.clone();
            let fm = FmIndex::build(r, 8);
            assert_eq!(fm.invert(), text, "n={}", n);
        }
    }

    #[test]
    fn periodic_text_many_hits() {
        let r = Reference::from_fasta(&parse_fasta(&format!(">p\n{}\n", "ACGT".repeat(300))).unwrap()).unwrap();
        let fm = FmIndex::build(r, 8);
        assert_eq!(fm.count(&[1, 2, 3, 4]), 300);
        assert_eq!(fm.locate(&[1, 2, 3, 4, 1, 2]).len(), 299);
        assert_eq!(fm.count(&[4, 4]), 0);
    }

    #[test]
    fn save_load_roundtrip_and_corruption() {
        let f = parse_fasta(">a\nACGTACGGTCAGT\n>b\nTTGACCA\n").unwrap();
        let r = Reference::from_fasta(&f).unwrap();
        let fm = FmIndex::build(r, 4);
        let dir = std::env::temp_dir().join(format!("strand_fm_test_{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("t.fm");
        fm.save(path.to_str().unwrap()).unwrap();
        let fm2 = FmIndex::load(path.to_str().unwrap()).unwrap();
        assert_eq!(fm2.reference.names, vec!["a", "b"]);
        assert_eq!(fm2.reference.codes, fm.reference.codes);
        assert_eq!(fm2.locate(&[2, 3]), fm.locate(&[2, 3]));
        let mut bytes = std::fs::read(&path).unwrap();
        let mid = bytes.len() / 2;
        bytes[mid] = (bytes[mid] + 1) % 5;
        assert!(FmIndex::from_bytes(&bytes).is_err());
        assert!(FmIndex::from_bytes(&bytes[..20]).is_err());
        assert!(FmIndex::from_bytes(b"NOTANINDEXFILE__").is_err());
        std::fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn invalid_pattern_symbols() {
        let fm = FmIndex::build(random_ref(5, 100), 4);
        assert_eq!(fm.count(&[0]), 0);
        assert_eq!(fm.count(&[9]), 0);
    }
}
