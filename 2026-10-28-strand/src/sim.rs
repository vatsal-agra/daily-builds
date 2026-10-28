//! Ground-truth simulator: a reference genome with repeat families and microsatellites,
//! a sample derived from it with known SNPs and indels (haploid or diploid, het/hom),
//! and Illumina-like reads with position-dependent substitution errors and honest quality
//! strings. Every downstream stage can be graded against what this module wrote down.

use crate::rng::Rng;
use crate::seq::Fastq;
use crate::vcf::{normalize, Variant};

#[derive(Clone, Debug)]
pub struct SimParams {
    pub length: usize,
    pub chroms: usize,
    pub seed: u64,
    pub coverage: f64,
    pub read_len: usize,
    pub snp_rate: f64,
    pub indel_rate: f64,
    pub ploidy: usize,
    pub het_frac: f64,
    pub error_scale: f64,
    pub repeat_frac: f64,
    pub gc: f64,
}

impl Default for SimParams {
    fn default() -> SimParams {
        SimParams {
            length: 200_000,
            chroms: 2,
            seed: 1,
            coverage: 30.0,
            read_len: 100,
            snp_rate: 1.0 / 800.0,
            indel_rate: 1.0 / 5000.0,
            ploidy: 2,
            het_frac: 0.6,
            error_scale: 1.0,
            repeat_frac: 0.08,
            gc: 0.45,
        }
    }
}

impl SimParams {
    pub fn validate(&self) -> Result<(), String> {
        if self.length < 1000 {
            return Err("genome length must be at least 1000".into());
        }
        if self.chroms == 0 || self.length / self.chroms < 500 {
            return Err("each chromosome needs at least 500 bases; reduce --chroms".into());
        }
        if self.ploidy != 1 && self.ploidy != 2 {
            return Err("ploidy must be 1 or 2".into());
        }
        if self.read_len < 30 || self.read_len > 1000 {
            return Err("read length must be within 30..=1000".into());
        }
        if self.length / self.chroms < 2 * self.read_len {
            return Err("chromosomes must be at least twice the read length".into());
        }
        if !(self.coverage > 0.0) || self.coverage > 1000.0 {
            return Err("coverage must be in (0, 1000]".into());
        }
        for (n, v) in [("snp-rate", self.snp_rate), ("indel-rate", self.indel_rate), ("het-frac", self.het_frac), ("repeat-frac", self.repeat_frac)] {
            if !(0.0..=1.0).contains(&v) {
                return Err(format!("--{} must be within [0,1]", n));
            }
        }
        if self.snp_rate + self.indel_rate > 0.05 {
            return Err("combined variant rate above 5% is unrealistic for this simulator".into());
        }
        if !(0.1..=0.9).contains(&self.gc) {
            return Err("gc must be within [0.1, 0.9]".into());
        }
        if self.error_scale < 0.0 || self.error_scale > 50.0 {
            return Err("error-scale must be within [0, 50]".into());
        }
        Ok(())
    }
}

pub struct SimChrom {
    pub name: String,
    pub reference: Vec<u8>,
    pub haplotypes: Vec<Vec<u8>>,
}

pub struct SimOutput {
    pub chroms: Vec<SimChrom>,
    pub truth: Vec<Variant>,
    pub reads: Vec<Fastq>,
}

fn random_base(rng: &mut Rng, gc: f64) -> u8 {
    if rng.chance(gc) {
        if rng.chance(0.5) {
            b'C'
        } else {
            b'G'
        }
    } else if rng.chance(0.5) {
        b'A'
    } else {
        b'T'
    }
}

fn transition(b: u8) -> u8 {
    match b {
        b'A' => b'G',
        b'G' => b'A',
        b'C' => b'T',
        _ => b'C',
    }
}

fn transversion(rng: &mut Rng, b: u8) -> u8 {
    let opts: &[u8] = match b {
        b'A' | b'G' => b"CT",
        _ => b"AG",
    };
    opts[rng.below(2)]
}

/// Genome with interspersed repeat families (diverged copies) and microsatellites.
pub fn make_genome(rng: &mut Rng, p: &SimParams) -> Vec<u8> {
    let mut g: Vec<u8> = (0..p.length).map(|_| random_base(rng, p.gc)).collect();
    let n_fam = (p.length / 30_000).clamp(2, 12);
    let target = (p.length as f64 * p.repeat_frac) as usize;
    let mut used = 0usize;
    while used < target {
        let unit_len = rng.range(150, 600).min(p.length / 10);
        let unit: Vec<u8> = (0..unit_len).map(|_| random_base(rng, p.gc)).collect();
        let copies = rng.range(2, 5);
        let _ = n_fam;
        for _ in 0..copies {
            let div = 0.005 + rng.f64() * 0.03;
            let mut copy = Vec::with_capacity(unit_len + 8);
            for &b in &unit {
                let r = rng.f64();
                if r < div {
                    copy.push(if rng.chance(0.66) { transition(b) } else { transversion(rng, b) });
                } else if r < div * 1.05 {
                    // deletion
                } else if r < div * 1.1 {
                    copy.push(b);
                    copy.push(random_base(rng, p.gc));
                } else {
                    copy.push(b);
                }
            }
            if rng.chance(0.5) {
                copy = crate::seq::revcomp_ascii(&copy);
            }
            if copy.len() + 2 >= g.len() {
                continue;
            }
            let at = rng.below(g.len() - copy.len());
            g[at..at + copy.len()].copy_from_slice(&copy);
            used += copy.len();
        }
    }
    // microsatellites
    let n_ms = (p.length / 4000).max(1);
    for _ in 0..n_ms {
        let ul = rng.range(1, 4);
        let unit: Vec<u8> = (0..ul).map(|_| random_base(rng, p.gc)).collect();
        let reps = rng.range(6, 16);
        let total = ul * reps;
        if total + 2 >= g.len() {
            continue;
        }
        let at = rng.below(g.len() - total);
        for k in 0..total {
            g[at + k] = unit[k % ul];
        }
    }
    g
}

struct Edit {
    pos: usize,
    r: Vec<u8>,
    a: Vec<u8>,
    mask: u8, // bit h set => haplotype h carries the allele
}

fn make_edits(rng: &mut Rng, g: &[u8], p: &SimParams) -> Vec<Edit> {
    let mut edits: Vec<Edit> = Vec::new();
    let rate = p.snp_rate + p.indel_rate;
    if rate <= 0.0 {
        return edits;
    }
    let mut pos = 40usize;
    let margin = 40usize;
    while pos + margin < g.len() {
        pos += rng.geometric(rate.min(0.999));
        if pos + margin >= g.len() {
            break;
        }
        let is_snp = rng.f64() < p.snp_rate / rate;
        let (r, a): (Vec<u8>, Vec<u8>) = if is_snp {
            let b = g[pos];
            let alt = if rng.chance(2.0 / 3.0) { transition(b) } else { transversion(rng, b) };
            (vec![b], vec![alt])
        } else {
            let len = rng.geometric(0.45).min(12);
            if rng.chance(0.5) {
                // insertion after anchor; half the time a tandem duplication of the preceding bases
                let ins: Vec<u8> = if rng.chance(0.5) && pos >= len {
                    g[pos + 1 - len..=pos].to_vec()
                } else {
                    (0..len).map(|_| random_base(rng, p.gc)).collect()
                };
                let mut a = vec![g[pos]];
                a.extend(ins);
                (vec![g[pos]], a)
            } else {
                if pos + 1 + len + margin >= g.len() {
                    continue;
                }
                (g[pos..=pos + len].to_vec(), vec![g[pos]])
            }
        };
        // normalise now so spacing is judged on canonical coordinates
        let (np, nr, na) = normalize(g, pos, r, a);
        if let Some(last) = edits.last() {
            if np < last.pos + last.r.len() + 12 {
                pos += 12;
                continue;
            }
        }
        let mask = if p.ploidy == 1 {
            1
        } else if rng.chance(p.het_frac) {
            1 << rng.below(2)
        } else {
            3
        };
        let end = np + nr.len();
        edits.push(Edit { pos: np, r: nr, a: na, mask });
        pos = end.max(pos);
    }
    edits
}

fn build_haplotype(g: &[u8], edits: &[Edit], h: usize) -> (Vec<u8>, Vec<u32>) {
    let mut seq = Vec::with_capacity(g.len() + 64);
    let mut map: Vec<u32> = Vec::with_capacity(g.len() + 64);
    let mut cur = 0usize;
    for e in edits {
        if e.mask & (1 << h) == 0 {
            continue;
        }
        while cur < e.pos {
            seq.push(g[cur]);
            map.push(cur as u32);
            cur += 1;
        }
        // emit the alt allele; every base maps to its anchor position (insertions) or its own ref position
        for (k, &b) in e.a.iter().enumerate() {
            seq.push(b);
            map.push((e.pos + k.min(e.r.len() - 1)) as u32);
        }
        cur = e.pos + e.r.len();
    }
    while cur < g.len() {
        seq.push(g[cur]);
        map.push(cur as u32);
        cur += 1;
    }
    (seq, map)
}

fn phred_char(p: f64) -> u8 {
    let q = (-10.0 * p.max(1e-6).log10()).round().clamp(2.0, 41.0) as u8;
    q + 33
}

fn make_read(rng: &mut Rng, hap: &[u8], start: usize, len: usize, reverse: bool, scale: f64) -> (Vec<u8>, Vec<u8>) {
    let mut s = hap[start..start + len].to_vec();
    if reverse {
        s = crate::seq::revcomp_ascii(&s);
    }
    let mut out = Vec::with_capacity(len + 2);
    let mut qual = Vec::with_capacity(len + 2);
    for (i, &b) in s.iter().enumerate() {
        let frac = i as f64 / len as f64;
        let p = ((0.0008 + 0.010 * frac.powi(3)) * scale).min(0.5);
        // the reported quality is a noisy estimate of the true error probability
        let est = (p * (0.35 * rng.normal()).exp()).clamp(1e-4, 0.75);
        if rng.chance(p) {
            let mut nb = b;
            while nb == b {
                nb = b"ACGT"[rng.below(4)];
            }
            out.push(nb);
        } else {
            out.push(b);
        }
        qual.push(phred_char(est));
    }
    // rare sequencing indels
    let indel_p = 0.00004 * scale;
    if scale > 0.0 && rng.chance(indel_p * len as f64) {
        let at = rng.range(5, len.saturating_sub(5).max(6) - 1);
        if at < out.len() {
            if rng.chance(0.5) {
                out.remove(at);
                qual.remove(at);
            } else {
                out.insert(at, b"ACGT"[rng.below(4)]);
                qual.insert(at, b'#' + 5);
            }
        }
    }
    (out, qual)
}

pub fn simulate(p: &SimParams) -> Result<SimOutput, String> {
    p.validate()?;
    let mut rng = Rng::new(p.seed);
    let genome = make_genome(&mut rng, p);
    // uneven chromosome lengths
    let mut cuts: Vec<f64> = (0..p.chroms).map(|_| 0.6 + rng.f64()).collect();
    let tot: f64 = cuts.iter().sum();
    let mut lens: Vec<usize> = cuts.iter_mut().map(|c| ((*c / tot) * p.length as f64) as usize).collect();
    let sum: usize = lens.iter().sum();
    *lens.last_mut().unwrap() += p.length - sum;
    let mut out = SimOutput { chroms: vec![], truth: vec![], reads: vec![] };
    let mut off = 0;
    let mut read_id = 0usize;
    for (ci, &l) in lens.iter().enumerate() {
        let name = format!("chr{}", ci + 1);
        let g = genome[off..off + l].to_vec();
        off += l;
        let edits = make_edits(&mut rng, &g, p);
        let mut haps = vec![];
        let mut maps = vec![];
        for h in 0..p.ploidy {
            let (s, m) = build_haplotype(&g, &edits, h);
            haps.push(s);
            maps.push(m);
        }
        for e in &edits {
            let mut v = Variant::new(&name, e.pos, &e.r, &e.a);
            v.gt = Some(match (p.ploidy, e.mask) {
                (1, _) => (1, 1),
                (_, 1) => (1, 0),
                (_, 2) => (0, 1),
                _ => (1, 1),
            });
            v.phased = true;
            out.truth.push(v);
        }
        let n_reads = ((p.coverage * l as f64) / p.read_len as f64).round() as usize;
        for _ in 0..n_reads {
            let h = rng.below(p.ploidy);
            let hap = &haps[h];
            if hap.len() <= p.read_len {
                continue;
            }
            let start = rng.below(hap.len() - p.read_len);
            let reverse = rng.chance(0.5);
            let (seq, qual) = make_read(&mut rng, hap, start, p.read_len, reverse, p.error_scale);
            let tpos = maps[h][start] as usize + 1;
            out.reads.push(Fastq {
                name: format!("{}:{}:{}:{}", name, tpos, if reverse { '-' } else { '+' }, read_id),
                seq,
                qual,
            });
            read_id += 1;
        }
        out.chroms.push(SimChrom { name, reference: g, haplotypes: haps });
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn small() -> SimParams {
        SimParams { length: 30_000, chroms: 2, coverage: 5.0, seed: 4, ..SimParams::default() }
    }

    #[test]
    fn deterministic_for_a_seed() {
        let a = simulate(&small()).unwrap();
        let b = simulate(&small()).unwrap();
        assert_eq!(a.reads, b.reads);
        assert_eq!(a.truth, b.truth);
        let mut p = small();
        p.seed = 5;
        let c = simulate(&p).unwrap();
        assert_ne!(a.chroms[0].reference, c.chroms[0].reference);
    }

    #[test]
    fn truth_variants_are_consistent_with_the_reference_and_haplotypes() {
        let o = simulate(&small()).unwrap();
        assert!(o.truth.len() > 10);
        for v in &o.truth {
            let c = o.chroms.iter().find(|c| c.name == v.chrom).unwrap();
            assert_eq!(&c.reference[v.pos..v.pos + v.ref_a.len()], &v.ref_a[..], "REF allele must match the reference");
            assert!(v.ref_a != v.alt);
            // normalised already
            let (p, r, a) = normalize(&c.reference, v.pos, v.ref_a.clone(), v.alt.clone());
            assert_eq!((p, r, a), (v.pos, v.ref_a.clone(), v.alt.clone()));
        }
        // sorted, non-overlapping, per chromosome
        for w in o.truth.windows(2) {
            if w[0].chrom == w[1].chrom {
                assert!(w[1].pos >= w[0].pos + w[0].ref_a.len());
            }
        }
    }

    #[test]
    fn haplotype_lengths_reflect_indels() {
        let o = simulate(&small()).unwrap();
        for c in &o.chroms {
            for (h, hap) in c.haplotypes.iter().enumerate() {
                let delta: i64 = o
                    .truth
                    .iter()
                    .filter(|v| v.chrom == c.name)
                    .filter(|v| {
                        let (a, b) = v.gt.unwrap();
                        if h == 0 {
                            a == 1
                        } else {
                            b == 1
                        }
                    })
                    .map(|v| v.alt.len() as i64 - v.ref_a.len() as i64)
                    .sum();
                assert_eq!(hap.len() as i64, c.reference.len() as i64 + delta);
            }
        }
    }

    #[test]
    fn reads_have_requested_shape() {
        let o = simulate(&small()).unwrap();
        let total: usize = o.reads.iter().map(|r| r.seq.len()).sum();
        let cov = total as f64 / 30_000.0;
        assert!((cov - 5.0).abs() < 0.6, "coverage {}", cov);
        for r in &o.reads {
            assert_eq!(r.seq.len(), r.qual.len());
            assert!(r.seq.len() >= 95 && r.seq.len() <= 105);
            assert!(r.seq.iter().all(|b| b"ACGT".contains(b)));
        }
    }

    #[test]
    fn error_scale_zero_gives_perfect_reads() {
        let mut p = small();
        p.error_scale = 0.0;
        p.snp_rate = 0.0;
        p.indel_rate = 0.0;
        p.ploidy = 1;
        let o = simulate(&p).unwrap();
        assert!(o.truth.is_empty());
        let g = &o.chroms[0].reference;
        let r = o.reads.iter().find(|r| r.name.starts_with("chr1")).unwrap();
        let parts: Vec<&str> = r.name.split(':').collect();
        let pos: usize = parts[1].parse::<usize>().unwrap() - 1;
        let s = if parts[2] == "-" { crate::seq::revcomp_ascii(&r.seq) } else { r.seq.clone() };
        assert_eq!(&g[pos..pos + s.len()], &s[..]);
    }

    #[test]
    fn rejects_bad_params() {
        let mut p = small();
        p.ploidy = 3;
        assert!(simulate(&p).is_err());
        let mut p = small();
        p.length = 10;
        assert!(simulate(&p).is_err());
        let mut p = small();
        p.snp_rate = 2.0;
        assert!(simulate(&p).is_err());
        let mut p = small();
        p.chroms = 0;
        assert!(simulate(&p).is_err());
        let mut p = small();
        p.coverage = f64::NAN;
        assert!(simulate(&p).is_err());
    }

    #[test]
    fn quality_tracks_true_error_rate() {
        // with large error scale the reported Phred must be lower on average
        let mut lo = small();
        lo.error_scale = 0.5;
        let mut hi = small();
        hi.error_scale = 8.0;
        let mean_q = |p: &SimParams| {
            let o = simulate(p).unwrap();
            let (mut s, mut n) = (0f64, 0f64);
            for r in &o.reads {
                for &q in &r.qual {
                    s += (q - 33) as f64;
                    n += 1.0;
                }
            }
            s / n
        };
        assert!(mean_q(&lo) > mean_q(&hi) + 3.0);
    }
}
