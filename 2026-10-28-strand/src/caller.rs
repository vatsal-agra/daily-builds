//! Pileup-based SNP / indel caller with a Bayesian genotype model.
//!
//! * SNPs: per-site allele counts come from a pileup; sites with enough non-reference
//!   evidence are re-walked to collect (base, Phred quality, strand) for every read, and the
//!   genotype posterior over {ref/ref, ref/alt, alt/alt} (or {ref, alt} for haploid samples)
//!   is computed from per-base error probabilities.
//! * Indels: read-level events are read straight off the CIGARs, left-normalised against the
//!   reference so every read that sees the same indel agrees on its representation, and
//!   genotyped with an error rate that grows with the length of the surrounding repeat
//!   (homopolymers and tandem repeats are where sequencers and aligners slip).
//! * A Fisher-exact strand-bias filter flags artefacts supported by a single read orientation.

use crate::mapper::SamFile;
use crate::vcf::{normalize, Variant};
use std::collections::HashMap;

#[derive(Clone, Debug)]
pub struct CallParams {
    pub min_mapq: u8,
    pub min_baseq: u8,
    pub min_depth: u32,
    pub min_alt: u32,
    pub min_qual: f64,
    pub ploidy: u8,
    pub keep_filtered: bool,
}

impl Default for CallParams {
    fn default() -> CallParams {
        CallParams { min_mapq: 20, min_baseq: 10, min_depth: 6, min_alt: 3, min_qual: 20.0, ploidy: 2, keep_filtered: false }
    }
}

impl CallParams {
    pub fn validate(&self) -> Result<(), String> {
        if self.ploidy != 1 && self.ploidy != 2 {
            return Err("ploidy must be 1 or 2".into());
        }
        if self.min_alt == 0 {
            return Err("min-alt must be at least 1".into());
        }
        if !(self.min_qual >= 0.0) {
            return Err("min-qual must be >= 0".into());
        }
        Ok(())
    }
}

#[derive(Default, Debug, Clone)]
pub struct CallStats {
    pub reads_total: usize,
    pub reads_used: usize,
    pub reads_unmapped: usize,
    pub reads_low_mapq: usize,
    pub snp_sites_examined: usize,
    pub indel_events_examined: usize,
    pub filtered: usize,
}

pub struct CallResult {
    pub variants: Vec<Variant>,
    pub coverage: Vec<Vec<u16>>, // per contig, depth of bases passing the quality filter
    pub stats: CallStats,
}

#[derive(Default, Clone)]
struct EventAgg {
    fwd: u32,
    rev: u32,
}

fn base_idx(b: u8) -> Option<usize> {
    match b {
        b'A' => Some(0),
        b'C' => Some(1),
        b'G' => Some(2),
        b'T' => Some(3),
        _ => None,
    }
}

fn phred_err(q: u8) -> f64 {
    10f64.powf(-((q.saturating_sub(33)) as f64) / 10.0).clamp(1e-4, 0.5)
}

fn log_sum_exp(v: &[f64]) -> f64 {
    let m = v.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
    if m == f64::NEG_INFINITY {
        return m;
    }
    m + v.iter().map(|x| (x - m).exp()).sum::<f64>().ln()
}

fn phred(p: f64) -> f64 {
    (-10.0 * p.max(1e-300).log10()).clamp(0.0, 999.0)
}

/// Posterior over genotypes. `ll[g]` are log-likelihoods for g = 0 (ref), 1 (het/…), 2 (hom alt).
/// Returns (best genotype index, QUAL = Phred(P(ref genotype)), GQ).
fn genotype_posterior(ll: &[f64], ploidy: u8) -> (usize, f64, f64) {
    let (het, hom) = (1e-3f64, 5e-4f64);
    let priors: Vec<f64> = if ploidy == 2 { vec![1.0 - het - hom, het, hom] } else { vec![1.0 - 1.5e-3, 1.5e-3] };
    let lp: Vec<f64> = ll.iter().zip(&priors).map(|(l, p)| l + p.ln()).collect();
    let z = log_sum_exp(&lp);
    let post: Vec<f64> = lp.iter().map(|x| (x - z).exp()).collect();
    let best = post.iter().enumerate().max_by(|a, b| a.1.partial_cmp(b.1).unwrap()).unwrap().0;
    let qual = phred(post[0]);
    let gq = phred(1.0 - post[best]).min(99.0);
    (best, qual, gq)
}

/// Two-sided Fisher exact test on [[a,b],[c,d]].
pub fn fisher_exact(a: u32, b: u32, c: u32, d: u32) -> f64 {
    let n = (a + b + c + d) as usize;
    let mut lf = vec![0.0f64; n + 1];
    for i in 2..=n {
        lf[i] = lf[i - 1] + (i as f64).ln();
    }
    let (r1, r2, c1) = (a + b, c + d, a + c);
    let lp = |x: u32| {
        lf[r1 as usize] + lf[r2 as usize] + lf[c1 as usize] + lf[n - c1 as usize]
            - lf[n]
            - lf[x as usize]
            - lf[(r1 - x) as usize]
            - lf[(c1 - x) as usize]
            - lf[(r2 - (c1 - x)) as usize]
    };
    let lo = c1.saturating_sub(r2);
    let hi = r1.min(c1);
    let p_obs = lp(a);
    let mut p = 0.0;
    for x in lo..=hi {
        let l = lp(x);
        if l <= p_obs + 1e-9 {
            p += l.exp();
        }
    }
    p.min(1.0)
}

/// Number of whole extra copies of `unit` immediately after `pos` (a measure of repeat context).
fn repeat_copies(refseq: &[u8], mut pos: usize, unit: &[u8]) -> usize {
    let mut c = 0;
    if unit.is_empty() {
        return 0;
    }
    while pos + unit.len() <= refseq.len() && &refseq[pos..pos + unit.len()] == unit {
        c += 1;
        pos += unit.len();
        if c > 40 {
            break;
        }
    }
    c
}

pub fn call_variants(refs: &[(String, Vec<u8>)], sam: &SamFile, p: &CallParams) -> Result<CallResult, String> {
    p.validate()?;
    let idx: HashMap<&str, usize> = refs.iter().enumerate().map(|(i, (n, _))| (n.as_str(), i)).collect();
    for (n, l) in &sam.contigs {
        match idx.get(n.as_str()) {
            None => return Err(format!("SAM header contig {} is not in the reference FASTA", n)),
            Some(&i) if refs[i].1.len() != *l => {
                return Err(format!("contig {} has length {} in the SAM header but {} in the FASTA — wrong reference?", n, l, refs[i].1.len()))
            }
            _ => {}
        }
    }
    let mut stats = CallStats { reads_total: sam.records.len(), ..Default::default() };
    let mut counts: Vec<Vec<[u16; 4]>> = refs.iter().map(|(_, s)| vec![[0u16; 4]; s.len()]).collect();
    let mut events: HashMap<(usize, usize, Vec<u8>, Vec<u8>), EventAgg> = HashMap::new();

    let usable = |r: &crate::mapper::SamRecord| -> bool { r.is_mapped() && r.flag & (256 | 2048 | 1024) == 0 && r.mapq >= p.min_mapq };

    // ---- pass 1: pileup counts and indel events ----
    for r in &sam.records {
        if !r.is_mapped() {
            stats.reads_unmapped += 1;
        } else if r.flag & (256 | 2048 | 1024) == 0 && r.mapq < p.min_mapq {
            stats.reads_low_mapq += 1;
        }
        if !usable(r) {
            continue;
        }
        let ci = *idx.get(r.rname.as_str()).ok_or_else(|| format!("read {} maps to unknown contig {}", r.name, r.rname))?;
        let refseq = &refs[ci].1;
        if r.pos + r.ref_len() > refseq.len() {
            return Err(format!("read {} extends past the end of {} — SAM does not match this reference", r.name, r.rname));
        }
        stats.reads_used += 1;
        let rev = r.flag & 16 != 0;
        let (mut rp, mut qp) = (r.pos, 0usize);
        let mut seen_aligned = false;
        let n_ops = r.cigar.len();
        for (oi, &(op, n)) in r.cigar.iter().enumerate() {
            match op {
                b'M' | b'=' | b'X' => {
                    for k in 0..n {
                        if let Some(b) = base_idx(r.seq[qp + k]) {
                            if r.qual[qp + k].saturating_sub(33) >= p.min_baseq {
                                let c = &mut counts[ci][rp + k][b];
                                *c = c.saturating_add(1);
                            }
                        }
                    }
                    rp += n;
                    qp += n;
                    seen_aligned = true;
                }
                b'I' => {
                    if seen_aligned && oi + 1 < n_ops && matches!(r.cigar[oi + 1].0, b'M' | b'=' | b'X') {
                        let anchor = rp - 1;
                        let ins = &r.seq[qp..qp + n];
                        if ins.iter().all(|&b| base_idx(b).is_some()) {
                            let mut alt = vec![refseq[anchor]];
                            alt.extend_from_slice(ins);
                            let (np, nr, na) = normalize(refseq, anchor, vec![refseq[anchor]], alt);
                            let e = events.entry((ci, np, nr, na)).or_default();
                            if rev {
                                e.rev += 1
                            } else {
                                e.fwd += 1
                            }
                        }
                    }
                    qp += n;
                }
                b'D' => {
                    if seen_aligned && oi + 1 < n_ops && matches!(r.cigar[oi + 1].0, b'M' | b'=' | b'X') {
                        let anchor = rp - 1;
                        let reff = refseq[anchor..=rp + n - 1].to_vec();
                        let (np, nr, na) = normalize(refseq, anchor, reff, vec![refseq[anchor]]);
                        let e = events.entry((ci, np, nr, na)).or_default();
                        if rev {
                            e.rev += 1
                        } else {
                            e.fwd += 1
                        }
                    }
                    rp += n;
                }
                b'N' => rp += n,
                b'S' => qp += n,
                _ => {}
            }
        }
    }

    let coverage: Vec<Vec<u16>> = counts.iter().map(|c| c.iter().map(|x| x.iter().fold(0u16, |a, &b| a.saturating_add(b))).collect()).collect();

    // ---- candidate SNP sites ----
    let mut cand: HashMap<(usize, usize), Vec<(u8, u8, bool)>> = HashMap::new();
    for (ci, (_, s)) in refs.iter().enumerate() {
        for (pos, c) in counts[ci].iter().enumerate() {
            let Some(rb) = base_idx(s[pos]) else { continue };
            let depth: u32 = c.iter().map(|&x| x as u32).sum();
            let alt_max = (0..4).filter(|&b| b != rb).map(|b| c[b] as u32).max().unwrap_or(0);
            if depth >= p.min_depth.min(p.min_alt) && alt_max >= p.min_alt {
                cand.insert((ci, pos), Vec::new());
            }
        }
    }
    stats.snp_sites_examined = cand.len();

    // ---- pass 2: gather qualities at candidate sites ----
    if !cand.is_empty() {
        for r in &sam.records {
            if !usable(r) {
                continue;
            }
            let ci = idx[r.rname.as_str()];
            let rev = r.flag & 16 != 0;
            let (mut rp, mut qp) = (r.pos, 0usize);
            for &(op, n) in &r.cigar {
                match op {
                    b'M' | b'=' | b'X' => {
                        for k in 0..n {
                            if let Some(v) = cand.get_mut(&(ci, rp + k)) {
                                if base_idx(r.seq[qp + k]).is_some() && r.qual[qp + k].saturating_sub(33) >= p.min_baseq {
                                    v.push((r.seq[qp + k], r.qual[qp + k], rev));
                                }
                            }
                        }
                        rp += n;
                        qp += n;
                    }
                    b'I' | b'S' => qp += n,
                    b'D' | b'N' => rp += n,
                    _ => {}
                }
            }
        }
    }

    let mut out: Vec<Variant> = Vec::new();

    // ---- SNP genotyping ----
    for ((ci, pos), reads) in &cand {
        let (name, s) = &refs[*ci];
        let rbase = s[*pos];
        let rb = base_idx(rbase).unwrap();
        let c = &counts[*ci][*pos];
        let alt_idx = (0..4).filter(|&b| b != rb).max_by_key(|&b| c[b]).unwrap();
        let alt = b"ACGT"[alt_idx];
        let ll = |x: u8, y: Option<u8>| -> f64 {
            reads
                .iter()
                .filter(|(b, _, _)| *b == rbase || *b == alt)
                .map(|&(b, q, _)| {
                    let e = phred_err(q);
                    let pr = |al: u8| if b == al { 1.0 - e } else { e / 3.0 };
                    match y {
                        Some(y) => (0.5 * pr(x) + 0.5 * pr(y)).ln(),
                        None => pr(x).ln(),
                    }
                })
                .sum()
        };
        let lls: Vec<f64> = if p.ploidy == 2 { vec![ll(rbase, Some(rbase)), ll(rbase, Some(alt)), ll(alt, Some(alt))] } else { vec![ll(rbase, None), ll(alt, None)] };
        let (g, qual, gq) = genotype_posterior(&lls, p.ploidy);
        let n_ref = reads.iter().filter(|r| r.0 == rbase).count() as u32;
        let n_alt = reads.iter().filter(|r| r.0 == alt).count() as u32;
        let depth: u32 = c.iter().map(|&x| x as u32).sum();
        if g == 0 {
            continue;
        }
        let mut v = Variant::new(name, *pos, &[rbase], &[alt]);
        v.qual = qual;
        v.depth = depth;
        v.ad = (n_ref, n_alt);
        v.gt = Some(match (p.ploidy, g) {
            (1, _) => (1, 1),
            (_, 1) => (0, 1),
            _ => (1, 1),
        });
        let _ = gq;
        let alt_f = reads.iter().filter(|r| r.0 == alt && !r.2).count() as u32;
        let alt_r = n_alt - alt_f;
        let ref_f = reads.iter().filter(|r| r.0 == rbase && !r.2).count() as u32;
        let ref_r = n_ref - ref_f;
        v.filter = filter_for(depth, n_alt, qual, (ref_f, ref_r, alt_f, alt_r), p);
        out.push(v);
    }

    // ---- indel genotyping ----
    stats.indel_events_examined = events.len();
    let mut ev_list: Vec<(usize, usize, Vec<u8>, Vec<u8>, EventAgg)> =
        events.into_iter().filter(|(_, a)| a.fwd + a.rev >= p.min_alt).map(|((ci, pos, r, a), agg)| (ci, pos, r, a, agg)).collect();
    ev_list.sort_by(|a, b| (a.0, a.1, &a.2, &a.3).cmp(&(b.0, b.1, &b.2, &b.3)));
    // Reads count as evidence for the reference allele only if one unbroken aligned block covers
    // the event plus FLANK bases either side; a read that is clipped or ends at the indel says nothing.
    const FLANK: usize = 5;
    let mut ref_support = vec![(0u32, 0u32); ev_list.len()];
    if !ev_list.is_empty() {
        for r in &sam.records {
            if !usable(r) {
                continue;
            }
            let ci = idx[r.rname.as_str()];
            let rev = r.flag & 16 != 0;
            let mut rp = r.pos;
            for &(op, n) in &r.cigar {
                match op {
                    b'M' | b'=' | b'X' => {
                        let (bs, be) = (rp, rp + n);
                        rp += n;
                        if be < bs + 2 * FLANK + 2 {
                            continue;
                        }
                        let (lo_pos, hi_pos) = (bs + FLANK - 1, be - FLANK - 1);
                        let first = ev_list.partition_point(|e| (e.0, e.1) < (ci, lo_pos));
                        for k in first..ev_list.len() {
                            let e = &ev_list[k];
                            if e.0 != ci || e.1 > hi_pos {
                                break;
                            }
                            if e.1 + 1 >= bs + FLANK && e.1 + e.2.len() + FLANK <= be {
                                if rev {
                                    ref_support[k].1 += 1
                                } else {
                                    ref_support[k].0 += 1
                                }
                            }
                        }
                    }
                    b'D' | b'N' => rp += n,
                    _ => {}
                }
            }
        }
    }
    for (k, (ci, pos, r, a, agg)) in ev_list.iter().enumerate() {
        let (name, s) = &refs[*ci];
        let alt_n = agg.fwd + agg.rev;
        let (ref_f, ref_r) = ref_support[k];
        let ref_n = ref_f + ref_r;
        let depth = ref_n + alt_n;
        // repeat context: how many copies of the inserted / deleted unit follow the anchor
        let (unit, copies) = if a.len() > r.len() {
            let u = a[1..].to_vec();
            let c = repeat_copies(s, pos + 1, &u);
            (u, c)
        } else {
            let u = r[1..].to_vec();
            let c = repeat_copies(s, pos + 1, &u).saturating_sub(1);
            (u, c)
        };
        let _ = unit;
        let eps = (0.004 * (1.0 + copies as f64)).min(0.15);
        let ll = |x_alt: bool, y_alt: Option<bool>| -> f64 {
            let pr_alt = |al: bool| if al { 1.0 - eps } else { eps };
            let pr_ref = |al: bool| if al { eps } else { 1.0 - eps };
            let one = |f: &dyn Fn(bool) -> f64| match y_alt {
                Some(y) => (0.5 * f(x_alt) + 0.5 * f(y)).ln(),
                None => f(x_alt).ln(),
            };
            alt_n as f64 * one(&pr_alt) + ref_n as f64 * one(&pr_ref)
        };
        let lls: Vec<f64> = if p.ploidy == 2 { vec![ll(false, Some(false)), ll(false, Some(true)), ll(true, Some(true))] } else { vec![ll(false, None), ll(true, None)] };
        let (g, qual, _gq) = genotype_posterior(&lls, p.ploidy);
        if g == 0 {
            continue;
        }
        let mut v = Variant::new(name, *pos, r, a);
        v.qual = qual;
        v.depth = depth;
        v.ad = (ref_n, alt_n);
        v.gt = Some(match (p.ploidy, g) {
            (1, _) => (1, 1),
            (_, 1) => (0, 1),
            _ => (1, 1),
        });
        v.filter = filter_for(depth, alt_n, qual, (ref_f, ref_r, agg.fwd, agg.rev), p);
        out.push(v);
    }

    out.sort_by(|a, b| (idx[a.chrom.as_str()], a.pos, &a.ref_a, &a.alt).cmp(&(idx[b.chrom.as_str()], b.pos, &b.ref_a, &b.alt)));
    stats.filtered = out.iter().filter(|v| v.filter != "PASS").count();
    if !p.keep_filtered {
        out.retain(|v| v.filter == "PASS");
    }
    Ok(CallResult { variants: out, coverage, stats })
}

fn filter_for(depth: u32, n_alt: u32, qual: f64, strand: (u32, u32, u32, u32), p: &CallParams) -> String {
    if depth < p.min_depth {
        return "LowDepth".into();
    }
    if n_alt < p.min_alt {
        return "LowAlt".into();
    }
    if qual < p.min_qual {
        return "LowQual".into();
    }
    let (rf, rr, af, ar) = strand;
    let alt_tot = af + ar;
    if alt_tot >= 6 && (af == 0 || ar == 0) && rf > 0 && rr > 0 && fisher_exact(rf, rr, af, ar) < 1e-3 {
        return "StrandBias".into();
    }
    "PASS".into()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::fm::FmIndex;
    use crate::mapper::{map_all, parse_sam, write_sam, MapParams};
    use crate::rng::Rng;
    use crate::seq::{parse_fasta, Fastq, Reference};

    #[test]
    fn fisher_matches_known_values() {
        // classic tea-tasting table: p = 0.4857 two-sided
        let p = fisher_exact(3, 1, 1, 3);
        assert!((p - 0.4857).abs() < 1e-3, "{}", p);
        assert!(fisher_exact(10, 0, 0, 10) < 1e-4);
        assert!((fisher_exact(5, 5, 5, 5) - 1.0).abs() < 1e-9);
    }

    #[test]
    fn genotype_posterior_prefers_het_for_balanced_evidence() {
        // 10 ref + 10 alt reads at Q30 -> het
        let reads: Vec<(bool, f64)> = (0..20).map(|i| (i < 10, 0.001)).collect();
        let ll = |a: f64, b: f64| -> f64 {
            reads
                .iter()
                .map(|&(is_ref, e)| {
                    let pr = |al_ref: bool| if al_ref == is_ref { 1.0 - e } else { e / 3.0 };
                    (0.5 * pr(a > 0.5) + 0.5 * pr(b > 0.5)).ln()
                })
                .sum()
        };
        let lls = vec![ll(1.0, 1.0), ll(1.0, 0.0), ll(0.0, 0.0)];
        let (g, q, _) = genotype_posterior(&lls, 2);
        assert_eq!(g, 1);
        assert!(q > 100.0);
    }

    fn pipeline(g: &str, sample: &str, cov: usize, seed: u64) -> (Vec<(String, Vec<u8>)>, SamFile) {
        let fm = FmIndex::build(Reference::from_fasta(&parse_fasta(&format!(">c\n{}\n", g)).unwrap()).unwrap(), 4);
        let mut rng = Rng::new(seed);
        let n = sample.len();
        let reads: Vec<Fastq> = (0..(cov * n / 100))
            .map(|i| {
                let st = rng.below(n - 100);
                let mut s = sample.as_bytes()[st..st + 100].to_vec();
                if rng.chance(0.5) {
                    s = crate::seq::revcomp_ascii(&s);
                }
                Fastq { name: format!("c:{}:+:{}", st + 1, i), seq: s, qual: vec![b'5'; 100] }
            })
            .collect();
        let res = map_all(&fm, &MapParams::default(), &reads).unwrap();
        let mut buf = Vec::new();
        write_sam(&mut buf, &fm, &res, true, "t").unwrap();
        let sam = parse_sam(&String::from_utf8(buf).unwrap()).unwrap();
        (vec![("c".to_string(), g.as_bytes().to_vec())], sam)
    }

    fn rand_dna(rng: &mut Rng, n: usize) -> String {
        (0..n).map(|_| b"ACGT"[rng.below(4)] as char).collect()
    }

    #[test]
    fn calls_homozygous_snp_and_indels_and_nothing_else() {
        let mut rng = Rng::new(3);
        let g = rand_dna(&mut rng, 4000);
        let mut s = g.clone().into_bytes();
        s[1000] = if s[1000] == b'A' { b'C' } else { b'A' };
        s.drain(2000..2003); // 3-base deletion
        s.splice(3000..3000, *b"TTAC"); // 4-base insertion
        let (refs, sam) = pipeline(&g, std::str::from_utf8(&s).unwrap(), 30, 1);
        let r = call_variants(&refs, &sam, &CallParams::default()).unwrap();
        assert_eq!(r.variants.len(), 3, "{:?}", r.variants);
        let snp = r.variants.iter().find(|v| v.pos == 1000).unwrap();
        assert_eq!(snp.gt, Some((1, 1)));
        assert!(snp.qual > 50.0);
        let del = r.variants.iter().find(|v| v.ref_a.len() == 4).unwrap();
        assert_eq!(del.alt.len(), 1);
        let ins = r.variants.iter().find(|v| v.alt.len() == 5).unwrap();
        assert_eq!(&ins.alt[1..], b"TTAC");
    }

    #[test]
    fn heterozygous_site_gets_het_genotype() {
        let mut rng = Rng::new(4);
        let g = rand_dna(&mut rng, 3000);
        let mut alt = g.clone().into_bytes();
        alt[1500] = if alt[1500] == b'G' { b'T' } else { b'G' };
        // half the reads from each haplotype: build by mixing two samples' reads
        let (refs, sam1) = pipeline(&g, &g, 20, 5);
        let (_, sam2) = pipeline(&g, std::str::from_utf8(&alt).unwrap(), 20, 6);
        let mut records = sam1.records;
        records.extend(sam2.records);
        let sam = SamFile { contigs: sam1.contigs, records };
        let r = call_variants(&refs, &sam, &CallParams::default()).unwrap();
        let v = r.variants.iter().find(|v| v.pos == 1500).expect("het SNP missed");
        assert_eq!(v.gt, Some((0, 1)));
        assert!(v.ad.0 > 5 && v.ad.1 > 5);
    }

    #[test]
    fn error_only_pileups_produce_no_calls() {
        let mut rng = Rng::new(7);
        let g = rand_dna(&mut rng, 3000);
        let (refs, mut sam) = pipeline(&g, &g, 40, 8);
        // sprinkle a few single-read errors at low quality
        for (i, r) in sam.records.iter_mut().enumerate().step_by(37) {
            let k = (i * 7) % r.seq.len();
            r.seq[k] = if r.seq[k] == b'A' { b'T' } else { b'A' };
            r.qual[k] = b'+';
        }
        let r = call_variants(&refs, &sam, &CallParams::default()).unwrap();
        assert!(r.variants.is_empty(), "{:?}", r.variants);
    }

    #[test]
    fn haploid_mode_calls_alt_allele() {
        let mut rng = Rng::new(9);
        let g = rand_dna(&mut rng, 3000);
        let mut s = g.clone().into_bytes();
        s[700] = if s[700] == b'A' { b'G' } else { b'A' };
        let (refs, sam) = pipeline(&g, std::str::from_utf8(&s).unwrap(), 25, 10);
        let r = call_variants(&refs, &sam, &CallParams { ploidy: 1, ..CallParams::default() }).unwrap();
        assert_eq!(r.variants.len(), 1);
        assert_eq!(r.variants[0].gt, Some((1, 1)));
    }

    #[test]
    fn low_depth_site_is_filtered_not_called() {
        let mut rng = Rng::new(11);
        let g = rand_dna(&mut rng, 3000);
        let mut s = g.clone().into_bytes();
        s[1200] = if s[1200] == b'A' { b'G' } else { b'A' };
        let (refs, sam) = pipeline(&g, std::str::from_utf8(&s).unwrap(), 2, 12);
        let r = call_variants(&refs, &sam, &CallParams::default()).unwrap();
        assert!(r.variants.iter().all(|v| v.pos != 1200));
        let r = call_variants(&refs, &sam, &CallParams { keep_filtered: true, ..CallParams::default() }).unwrap();
        for v in &r.variants {
            assert_ne!(v.filter, "PASS");
        }
    }

    #[test]
    fn mismatched_reference_is_rejected() {
        let mut rng = Rng::new(13);
        let g = rand_dna(&mut rng, 3000);
        let (_, sam) = pipeline(&g, &g, 5, 14);
        let wrong = vec![("c".to_string(), g.as_bytes()[..2000].to_vec())];
        assert!(call_variants(&wrong, &sam, &CallParams::default()).is_err());
        let renamed = vec![("zzz".to_string(), g.as_bytes().to_vec())];
        assert!(call_variants(&renamed, &sam, &CallParams::default()).is_err());
        assert!(call_variants(&wrong, &sam, &CallParams { ploidy: 3, ..CallParams::default() }).is_err());
    }

    fn rec(name: &str, pos: usize, cigar: &str, seq: &[u8], flag: u16) -> crate::mapper::SamRecord {
        crate::mapper::SamRecord {
            name: name.into(),
            flag,
            rname: "c".into(),
            pos,
            mapq: 60,
            cigar: crate::mapper::parse_cigar(cigar).unwrap(),
            seq: seq.to_vec(),
            qual: vec![b'I'; seq.len()],
        }
    }

    #[test]
    fn reads_clipped_at_an_indel_are_not_reference_evidence() {
        // 200-bp random reference; every informative read carries a 2-bp insertion after position 100.
        let mut rng = Rng::new(31);
        let g = rand_dna(&mut rng, 200).into_bytes();
        let mut records = vec![];
        for i in 0..12 {
            let st = 40 + i % 3;
            let mut s = g[st..101].to_vec();
            s.extend_from_slice(b"TG");
            s.extend_from_slice(&g[101..141]);
            let cig = format!("{}M2I40M", 101 - st);
            records.push(rec(&format!("alt{}", i), st, &cig, &s, if i % 2 == 0 { 0 } else { 16 }));
        }
        for i in 0..14 {
            // reads that stop exactly at the anchor: they cover base 100 but say nothing about the allele
            let st = 60 + i % 3;
            let s = g[st..101].to_vec();
            records.push(rec(&format!("clip{}", i), st, &format!("{}M", 101 - st), &s, if i % 2 == 0 { 0 } else { 16 }));
        }
        let sam = SamFile { contigs: vec![("c".into(), 200)], records };
        let refs = vec![("c".to_string(), g.clone())];
        let r = call_variants(&refs, &sam, &CallParams::default()).unwrap();
        let v = r.variants.iter().find(|v| v.kind() == crate::vcf::Kind::Ins).expect("insertion not called");
        assert_eq!(v.ad.0, 0, "clipped reads must not count as reference support");
        assert_eq!(v.gt, Some((1, 1)));
    }

    #[test]
    fn homopolymer_indels_need_more_evidence_than_unique_ones() {
        let mut rng = Rng::new(32);
        let mut g = rand_dna(&mut rng, 200).into_bytes();
        g[90] = b'C';
        for b in g.iter_mut().take(103).skip(91) {
            *b = b'A';
        }
        g[103] = b'G';
        let build = |alt: usize, reference: usize, g: &Vec<u8>| {
            let mut records = vec![];
            for i in 0..alt {
                let mut s = g[50..95].to_vec();
                s.extend_from_slice(&g[96..150]);
                records.push(rec(&format!("a{}", i), 50, "45M1D54M", &s, (i % 2) as u16 * 16));
            }
            for i in 0..reference {
                records.push(rec(&format!("r{}", i), 50, "100M", &g[50..150], (i % 2) as u16 * 16));
            }
            SamFile { contigs: vec![("c".into(), 200)], records }
        };
        let refs = vec![("c".to_string(), g.clone())];
        let r = call_variants(&refs, &build(5, 10, &g), &CallParams::default()).unwrap();
        assert!(r.variants.is_empty(), "5/15 reads in a 12-A homopolymer is within slippage error: {:?}", r.variants);
        // same counts in a unique context are a real heterozygous deletion
        let mut u = rand_dna(&mut rng, 200).into_bytes();
        u[95] = b'T';
        u[96] = b'C';
        let ru = vec![("c".to_string(), u.clone())];
        let r = call_variants(&ru, &build(5, 10, &u), &CallParams::default()).unwrap();
        assert!(r.variants.iter().any(|v| v.kind() == crate::vcf::Kind::Del && v.gt == Some((0, 1))), "{:?}", r.variants);
    }

    #[test]
    fn empty_sam_gives_empty_calls() {
        let refs = vec![("c".to_string(), b"ACGTACGT".to_vec())];
        let sam = SamFile { contigs: vec![("c".into(), 8)], records: vec![] };
        let r = call_variants(&refs, &sam, &CallParams::default()).unwrap();
        assert!(r.variants.is_empty());
        assert_eq!(r.coverage[0], vec![0; 8]);
    }
}
