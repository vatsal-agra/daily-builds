//! QUAST-lite assembly evaluation against a known truth sequence.
//!
//! Each contig is cut into 500-bp chunks which are mapped with the read mapper. Chunks that map
//! uniquely (MAPQ >= 1) are chained: consecutive chunks on the same contig must keep the same
//! contig, strand and diagonal (within 50 bp, which absorbs real indels). A break in that chain is
//! a misassembly (relocation, inversion or inter-chromosomal join). Unaligned stretches, genome
//! fraction, per-100kb mismatch / indel rates and an NGA50 (N50 of the aligned blocks measured
//! against the truth length) complete the report.

use crate::dbg::{n_stats, Contig};
use crate::fm::FmIndex;
use crate::mapper::MapParams;
use crate::seq::Fastq;

const CHUNK: usize = 500;
const OVERLAP: usize = 100;
const DIAG_TOL: i64 = 50;

#[derive(Debug, Clone, Default)]
pub struct AsmEval {
    pub contigs: usize,
    pub assembly_len: usize,
    pub truth_len: usize,
    pub aligned_bases: usize,
    pub unaligned_bases: usize,
    pub genome_fraction: f64,
    pub misassemblies: usize,
    pub mismatches_per_100kb: f64,
    pub indels_per_100kb: f64,
    pub nga50: usize,
    pub duplication_ratio: f64,
    pub per_contig: Vec<ContigEval>,
}

#[derive(Debug, Clone, Default)]
pub struct ContigEval {
    pub len: usize,
    pub blocks: usize,
    pub misassemblies: usize,
    pub unaligned: usize,
}

struct Anchor {
    rid: usize,
    reverse: bool,
    diag: i64,
}

pub fn evaluate_assembly(fm: &FmIndex, contigs: &[Contig], threads: usize) -> Result<AsmEval, String> {
    if contigs.is_empty() {
        return Err("assembly has no contigs".into());
    }
    // clip_penalty is huge on purpose: chunks must align end to end, otherwise a base error within a
    // few bases of a chunk boundary would be clipped away and silently not counted as an error
    let params = MapParams { threads: threads.max(1), min_score: 60, clip_penalty: 100_000, ..MapParams::default() };
    params.validate()?;
    let mut ev = AsmEval { contigs: contigs.len(), truth_len: fm.reference.lens.iter().sum(), ..Default::default() };
    let (mut mism, mut indel, mut aligned_cols) = (0usize, 0usize, 0usize);
    let mut covered: Vec<Vec<(usize, usize)>> = vec![vec![]; fm.reference.names.len()];
    let mut block_lens: Vec<usize> = Vec::new();

    for c in contigs {
        let len = c.seq.len();
        ev.assembly_len += len;
        // Chunks overlap by OVERLAP bases but each error is only counted in the chunk's "core"
        // (the first CHUNK bases), so an indel on a chunk boundary is seen exactly once.
        // (start, core_end, chunk_end); a short tail is folded into the previous chunk.
        let mut bounds: Vec<(usize, usize, usize)> = Vec::new();
        let mut s = 0;
        while s < len {
            let core_end = (s + CHUNK).min(len);
            if core_end - s < 150 && !bounds.is_empty() {
                let last = bounds.last_mut().unwrap();
                last.1 = core_end;
                last.2 = core_end;
            } else {
                bounds.push((s, core_end, (core_end + OVERLAP).min(len)));
            }
            s = core_end;
        }
        let reads: Vec<Fastq> =
            bounds.iter().enumerate().map(|(i, &(s, _, e))| Fastq { name: format!("chunk{}", i), seq: c.seq[s..e].to_vec(), qual: vec![b'I'; e - s] }).collect();
        let results = crate::mapper::map_all(fm, &params, &reads)?;
        let mut ce = ContigEval { len, ..Default::default() };
        let mut prev: Option<Anchor> = None;
        let mut block_start = 0usize;
        let mut last_end = 0usize;
        for (i, r) in results.iter().enumerate() {
            let (s, core_end, _) = bounds[i];
            let core = core_end - s;
            match &r.hit {
                None => ce.unaligned += core,
                Some(h) => {
                    let al = &h.aln;
                    // walk the alignment in query coordinates, counting only events inside the core
                    let mut q = al.q_start;
                    let mut aligned_core = 0usize;
                    let mut cols = 0usize;
                    for &(op, n) in &al.ops {
                        for _ in 0..n {
                            let inside = q < core;
                            match op {
                                b'=' | b'X' => {
                                    if inside {
                                        aligned_core += 1;
                                        cols += 1;
                                        if op == b'X' {
                                            mism += 1;
                                        }
                                    }
                                    q += 1;
                                }
                                b'I' => {
                                    if inside {
                                        indel += 1;
                                        cols += 1;
                                    }
                                    q += 1;
                                }
                                _ => {
                                    // a deletion sits *between* query bases; one exactly on the core
                                    // boundary belongs to this chunk (the next chunk cannot start with it)
                                    if q <= core {
                                        indel += 1;
                                        cols += 1;
                                    }
                                }
                            }
                        }
                    }
                    aligned_cols += cols;
                    ev.aligned_bases += aligned_core;
                    ce.unaligned += core - aligned_core;
                    covered[h.rid].push((h.pos, h.pos + al.ref_span()));
                    if h.mapq >= 1 {
                        let diag = if h.reverse { (h.pos + al.ref_span()) as i64 + s as i64 } else { h.pos as i64 - s as i64 };
                        let a = Anchor { rid: h.rid, reverse: h.reverse, diag };
                        if let Some(p) = &prev {
                            if p.rid != a.rid || p.reverse != a.reverse || (p.diag - a.diag).abs() > DIAG_TOL {
                                ce.misassemblies += 1;
                                block_lens.push(last_end - block_start);
                                block_start = s;
                            }
                        }
                        prev = Some(a);
                        last_end = core_end;
                    }
                }
            }
        }
        block_lens.push(last_end.saturating_sub(block_start).max(if prev.is_none() { 0 } else { 1 }));
        ce.blocks = ce.misassemblies + 1;
        ev.misassemblies += ce.misassemblies;
        ev.per_contig.push(ce);
    }
    ev.unaligned_bases = ev.per_contig.iter().map(|c| c.unaligned).sum();
    // union of covered truth intervals
    let mut union_len = 0usize;
    for iv in covered.iter_mut() {
        iv.sort_unstable();
        let mut cur: Option<(usize, usize)> = None;
        for &(s, e) in iv.iter() {
            match cur {
                Some((cs, ce)) if s <= ce => cur = Some((cs, ce.max(e))),
                Some((cs, ce)) => {
                    union_len += ce - cs;
                    cur = Some((s, e));
                }
                None => cur = Some((s, e)),
            }
        }
        if let Some((cs, ce)) = cur {
            union_len += ce - cs;
        }
    }
    ev.genome_fraction = union_len as f64 / ev.truth_len.max(1) as f64;
    ev.duplication_ratio = if union_len == 0 { 0.0 } else { ev.aligned_bases as f64 / union_len as f64 };
    ev.mismatches_per_100kb = 1e5 * mism as f64 / aligned_cols.max(1) as f64;
    ev.indels_per_100kb = 1e5 * indel as f64 / aligned_cols.max(1) as f64;
    ev.nga50 = n_stats(&block_lens, 0.5, ev.truth_len).0;
    Ok(ev)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::rng::Rng;
    use crate::seq::{parse_fasta, Reference};

    fn rand_dna(rng: &mut Rng, n: usize) -> Vec<u8> {
        (0..n).map(|_| b"ACGT"[rng.below(4)]).collect()
    }

    fn index(g: &[u8]) -> FmIndex {
        let f = parse_fasta(&format!(">t\n{}\n", String::from_utf8_lossy(g))).unwrap();
        FmIndex::build(Reference::from_fasta(&f).unwrap(), 8)
    }

    fn contig(s: &[u8]) -> Contig {
        Contig { seq: s.to_vec(), cov: 30.0 }
    }

    #[test]
    fn perfect_contig_has_no_errors() {
        let mut rng = Rng::new(1);
        let g = rand_dna(&mut rng, 10_000);
        let fm = index(&g);
        let ev = evaluate_assembly(&fm, &[contig(&g[1000..9000])], 1).unwrap();
        assert_eq!(ev.misassemblies, 0);
        assert_eq!(ev.unaligned_bases, 0);
        assert!((ev.genome_fraction - 0.8).abs() < 0.01, "{}", ev.genome_fraction);
        assert_eq!(ev.mismatches_per_100kb, 0.0);
        assert!(ev.nga50 == 0 || ev.nga50 >= 7000 || ev.genome_fraction < 0.5);
    }

    #[test]
    fn reverse_strand_contig_is_recognised() {
        let mut rng = Rng::new(2);
        let g = rand_dna(&mut rng, 8000);
        let fm = index(&g);
        let ev = evaluate_assembly(&fm, &[contig(&crate::seq::revcomp_ascii(&g[500..7500]))], 1).unwrap();
        assert_eq!(ev.misassemblies, 0, "{:?}", ev);
        assert!(ev.genome_fraction > 0.85);
    }

    #[test]
    fn chimeric_contig_counts_a_misassembly() {
        let mut rng = Rng::new(3);
        let g = rand_dna(&mut rng, 20_000);
        let fm = index(&g);
        let mut chim = g[1000..4000].to_vec();
        chim.extend_from_slice(&g[12_000..15_000]); // relocation
        let ev = evaluate_assembly(&fm, &[contig(&chim)], 1).unwrap();
        assert_eq!(ev.misassemblies, 1, "{:?}", ev.per_contig);
        let mut inv = g[1000..4000].to_vec();
        inv.extend(crate::seq::revcomp_ascii(&g[4000..7000])); // inversion
        let ev = evaluate_assembly(&fm, &[contig(&inv)], 1).unwrap();
        assert_eq!(ev.misassemblies, 1, "{:?}", ev.per_contig);
    }

    #[test]
    fn snps_and_indels_are_counted_per_100kb() {
        let mut rng = Rng::new(4);
        let g = rand_dna(&mut rng, 12_000);
        let fm = index(&g);
        let mut c = g[1000..11_000].to_vec();
        for p in [2000usize, 4000, 6000, 8000] {
            c[p] = if c[p] == b'A' { b'T' } else { b'A' };
        }
        c.remove(5000);
        let ev = evaluate_assembly(&fm, &[contig(&c)], 1).unwrap();
        assert_eq!(ev.misassemblies, 0);
        // 4 mismatches in ~10,000 aligned columns = 40 / 100kb, 1 indel = 10 / 100kb
        assert!((ev.mismatches_per_100kb - 40.0).abs() < 8.0, "{}", ev.mismatches_per_100kb);
        assert!((ev.indels_per_100kb - 10.0).abs() < 6.0, "{}", ev.indels_per_100kb);
    }

    #[test]
    fn foreign_contig_is_unaligned() {
        let mut rng = Rng::new(5);
        let g = rand_dna(&mut rng, 8000);
        let fm = index(&g);
        let junk = rand_dna(&mut rng, 3000);
        let ev = evaluate_assembly(&fm, &[contig(&junk)], 1).unwrap();
        assert!(ev.unaligned_bases >= 2900);
        assert_eq!(ev.genome_fraction, 0.0);
        assert!(evaluate_assembly(&fm, &[], 1).is_err());
    }
}
