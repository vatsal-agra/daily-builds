//! Seed-and-extend short-read mapper over the FM-index.
//!
//! 1. *Seeds*: for each strand, exact matches found by backward search from the right
//!    end of the read; a failing base is skipped and the search restarts, giving
//!    non-overlapping maximal exact matches (fallback to shorter seeds if none).
//! 2. *Chains*: seed hits are located through the sampled suffix array, converted to
//!    diagonals and clustered; the best clusters become candidate loci.
//! 3. *Extension*: banded affine-gap alignment of the whole read against a reference
//!    window. Semi-global (end to end) is preferred unless local clipping wins by more
//!    than the clip penalty, exactly the trade-off BWA-MEM makes.
//! 4. *MAPQ* from the gap between the best and second-best locus.

use crate::align::{align, Alignment, Mode, Scoring};
use crate::fm::FmIndex;
use crate::seq::{revcomp_ascii, revcomp_codes, Fastq};
use std::io::Write;

#[derive(Clone, Debug)]
pub struct MapParams {
    pub min_seed: usize,
    pub fallback_seed: usize,
    pub max_occ: usize,
    pub band: usize,
    pub max_cands: usize,
    pub clip_penalty: i32,
    pub min_score: i32,
    pub scoring: Scoring,
    pub threads: usize,
}

impl Default for MapParams {
    fn default() -> MapParams {
        MapParams {
            min_seed: 19,
            fallback_seed: 13,
            max_occ: 40,
            band: 24,
            max_cands: 6,
            clip_penalty: 5,
            min_score: 30,
            scoring: Scoring::default(),
            threads: 1,
        }
    }
}

impl MapParams {
    pub fn validate(&self) -> Result<(), String> {
        self.scoring.validate()?;
        if self.fallback_seed < 8 || self.min_seed < self.fallback_seed {
            return Err("seed lengths must satisfy 8 <= fallback <= min_seed".into());
        }
        if self.threads == 0 || self.threads > 256 {
            return Err("threads must be within 1..=256".into());
        }
        if self.max_occ == 0 || self.max_cands == 0 || self.band == 0 {
            return Err("max_occ, max_cands and band must be positive".into());
        }
        Ok(())
    }
}

#[derive(Clone, Debug)]
pub struct Mapped {
    pub rid: usize,
    pub pos: usize, // 0-based within the record
    pub reverse: bool,
    pub aln: Alignment,
    pub mapq: u8,
    pub second: i32,
}

#[derive(Clone, Debug)]
pub struct MapResult {
    pub read: Fastq,
    pub hit: Option<Mapped>,
}

struct Seed {
    qs: usize,
    len: usize,
    lo: usize,
    hi: usize,
}

fn read_codes(seq: &[u8]) -> Vec<u8> {
    seq.iter().map(|&b| crate::seq::encode(b).unwrap_or(0)).collect()
}

fn find_seeds(fm: &FmIndex, read: &[u8], min_len: usize) -> Vec<Seed> {
    let mut out = Vec::new();
    let mut e = read.len();
    while e >= min_len {
        let mut r = fm.full_range();
        let mut s = e;
        while s > 0 {
            let x = read[s - 1];
            if !(1..=4).contains(&x) {
                break;
            }
            let r2 = fm.extend(r, x);
            if r2.is_empty() {
                break;
            }
            r = r2;
            s -= 1;
        }
        let len = e - s;
        if len >= min_len {
            out.push(Seed { qs: s, len, lo: r.lo, hi: r.hi });
        }
        if s == 0 {
            break;
        }
        e = s - 1;
    }
    out
}

struct Cand {
    reverse: bool,
    diag: i64,
    weight: usize,
    repetitive: bool,
}

fn candidates(fm: &FmIndex, p: &MapParams, orient: [&[u8]; 2]) -> Vec<Cand> {
    // (reverse, diag, seed length, repetitive)
    let mut hits: Vec<(bool, i64, usize, bool)> = Vec::new();
    for (rev, read) in orient.iter().enumerate() {
        let mut seeds = find_seeds(fm, read, p.min_seed);
        if seeds.is_empty() {
            seeds = find_seeds(fm, read, p.fallback_seed);
        }
        for sd in seeds {
            let occ = sd.hi - sd.lo;
            let take = occ.min(p.max_occ);
            for row in sd.lo..sd.lo + take {
                let tp = fm.locate_row(row) as i64;
                hits.push((rev == 1, tp - sd.qs as i64, sd.len, occ > p.max_occ));
            }
        }
    }
    hits.sort_unstable_by_key(|h| (h.0, h.1));
    let mut cands: Vec<Cand> = Vec::new();
    let mut last_diag = i64::MIN;
    let mut best_len = 0usize;
    for &(rev, diag, len, rep) in &hits {
        let new = match cands.last() {
            Some(c) => c.reverse != rev || diag - last_diag > p.band as i64,
            None => true,
        };
        if new {
            cands.push(Cand { reverse: rev, diag, weight: 0, repetitive: false });
            best_len = 0;
        }
        let c = cands.last_mut().unwrap();
        c.weight += len;
        c.repetitive |= rep;
        if len > best_len {
            best_len = len;
            c.diag = diag;
        }
        last_diag = diag;
    }
    cands.sort_by(|a, b| b.weight.cmp(&a.weight));
    cands.truncate(p.max_cands);
    cands
}

struct Extended {
    rid: usize,
    pos: usize,
    reverse: bool,
    aln: Alignment,
    repetitive: bool,
}

fn extend_candidate(fm: &FmIndex, p: &MapParams, q: &[u8], c: &Cand) -> Option<Extended> {
    let rf = &fm.reference;
    let total = rf.codes.len() as i64;
    let qlen = q.len() as i64;
    let center = (c.diag + qlen / 2).clamp(0, total - 1) as usize;
    let (rid, _) = rf.locate(center)?;
    let rs = rf.offsets[rid] as i64;
    let re = rs + rf.lens[rid] as i64;
    let pad = p.band as i64;
    let ws = (c.diag - pad).max(rs);
    let we = (c.diag + qlen + pad).min(re);
    if we <= ws {
        return None;
    }
    let target = &rf.codes[ws as usize..we as usize];
    let cd = c.diag - ws;
    let band = Some((cd - pad, cd + pad));
    // End-to-end alignment can be impossible when the read hangs off the record: then clip.
    let sg = align(q, target, Mode::SemiGlobal, &p.scoring, band).ok()?;
    let lo = align(q, target, Mode::Local, &p.scoring, band).ok()??;
    let aln = match sg {
        Some(sg) if sg.score + p.clip_penalty >= lo.score => sg,
        _ => lo,
    };
    if aln.score < p.min_score || aln.ops.is_empty() {
        return None;
    }
    let pos = (ws - rs) as usize + aln.t_start;
    Some(Extended { rid, pos, reverse: c.reverse, aln, repetitive: c.repetitive })
}

pub fn mapq_from_scores(best: i32, second: i32, qlen: usize, matched: i32, repetitive: bool) -> u8 {
    if best <= 0 || repetitive {
        return 0;
    }
    let max_score = (qlen as i32 * matched).max(1);
    let gap = (best - second.max(0)) as f64 / best as f64;
    let quality = ((best as f64 / max_score as f64) / 0.85).min(1.0);
    (60.0 * gap * quality).floor().clamp(0.0, 60.0) as u8
}

pub fn map_read(fm: &FmIndex, p: &MapParams, read: &Fastq) -> MapResult {
    let fwd = read_codes(&read.seq);
    if fwd.len() < p.fallback_seed {
        return MapResult { read: read.clone(), hit: None };
    }
    let rev = revcomp_codes_with_n(&fwd);
    let cands = candidates(fm, p, [&fwd, &rev]);
    let mut exts: Vec<Extended> = Vec::new();
    for c in &cands {
        let q = if c.reverse { &rev } else { &fwd };
        if let Some(e) = extend_candidate(fm, p, q, c) {
            // drop duplicate loci produced by neighbouring clusters
            let dup = exts.iter().any(|x| {
                x.rid == e.rid && x.reverse == e.reverse && (x.pos as i64 - e.pos as i64).abs() <= p.band as i64
            });
            if !dup {
                exts.push(e);
            }
        }
    }
    if exts.is_empty() {
        return MapResult { read: read.clone(), hit: None };
    }
    exts.sort_by(|a, b| b.aln.score.cmp(&a.aln.score));
    let second = exts.get(1).map(|e| e.aln.score).unwrap_or(0);
    let best = exts.swap_remove(0);
    let mapq = mapq_from_scores(best.aln.score, second, fwd.len(), p.scoring.matched, best.repetitive);
    MapResult {
        read: read.clone(),
        hit: Some(Mapped { rid: best.rid, pos: best.pos, reverse: best.reverse, aln: best.aln, mapq, second }),
    }
}

fn revcomp_codes_with_n(c: &[u8]) -> Vec<u8> {
    // like revcomp_codes but keeps ambiguous (0) as 0
    c.iter().rev().map(|&x| if x == 0 { 0 } else { 5 - x }).collect()
}

pub fn map_all(fm: &FmIndex, p: &MapParams, reads: &[Fastq]) -> Result<Vec<MapResult>, String> {
    p.validate()?;
    let _ = revcomp_codes(&[]); // keep the plain helper linked for doc purposes
    if p.threads <= 1 || reads.len() < 64 {
        return Ok(reads.iter().map(|r| map_read(fm, p, r)).collect());
    }
    let chunk = (reads.len() + p.threads - 1) / p.threads;
    let mut out: Vec<Vec<MapResult>> = Vec::new();
    std::thread::scope(|s| {
        let handles: Vec<_> = reads
            .chunks(chunk)
            .map(|ch| s.spawn(move || ch.iter().map(|r| map_read(fm, p, r)).collect::<Vec<_>>()))
            .collect();
        for h in handles {
            out.push(h.join().expect("mapper thread panicked"));
        }
    });
    Ok(out.into_iter().flatten().collect())
}

// ---- SAM ------------------------------------------------------------------------------

pub fn write_sam<W: Write>(w: &mut W, fm: &FmIndex, results: &[MapResult], sort: bool, cmdline: &str) -> std::io::Result<()> {
    writeln!(w, "@HD\tVN:1.6\tSO:{}", if sort { "coordinate" } else { "unsorted" })?;
    for (n, l) in fm.reference.names.iter().zip(&fm.reference.lens) {
        writeln!(w, "@SQ\tSN:{}\tLN:{}", n, l)?;
    }
    writeln!(w, "@PG\tID:strand\tPN:strand\tCL:{}", cmdline)?;
    let mut order: Vec<usize> = (0..results.len()).collect();
    if sort {
        order.sort_by_key(|&i| match &results[i].hit {
            Some(h) => (0, h.rid, h.pos, i),
            None => (1, 0, 0, i),
        });
    }
    for i in order {
        let r = &results[i];
        match &r.hit {
            None => {
                writeln!(
                    w,
                    "{}\t4\t*\t0\t0\t*\t*\t0\t0\t{}\t{}",
                    r.read.name,
                    String::from_utf8_lossy(&r.read.seq),
                    String::from_utf8_lossy(&r.read.qual)
                )?;
            }
            Some(h) => {
                let (seq, qual) = if h.reverse {
                    (revcomp_ascii(&r.read.seq), r.read.qual.iter().rev().copied().collect::<Vec<u8>>())
                } else {
                    (r.read.seq.clone(), r.read.qual.clone())
                };
                writeln!(
                    w,
                    "{}\t{}\t{}\t{}\t{}\t{}\t*\t0\t0\t{}\t{}\tNM:i:{}\tAS:i:{}\tXS:i:{}",
                    r.read.name,
                    if h.reverse { 16 } else { 0 },
                    fm.reference.names[h.rid],
                    h.pos + 1,
                    h.mapq,
                    h.aln.cigar(seq.len()),
                    String::from_utf8_lossy(&seq),
                    String::from_utf8_lossy(&qual),
                    h.aln.edit_distance(),
                    h.aln.score,
                    h.second
                )?;
            }
        }
    }
    Ok(())
}

#[derive(Clone, Debug)]
pub struct SamRecord {
    pub name: String,
    pub flag: u16,
    pub rname: String,
    pub pos: usize, // 0-based; meaningful only when mapped
    pub mapq: u8,
    pub cigar: Vec<(u8, usize)>,
    pub seq: Vec<u8>,
    pub qual: Vec<u8>,
}

impl SamRecord {
    pub fn is_mapped(&self) -> bool {
        self.flag & 4 == 0
    }
    pub fn ref_len(&self) -> usize {
        self.cigar.iter().filter(|(o, _)| matches!(o, b'M' | b'D' | b'N' | b'=' | b'X')).map(|&(_, n)| n).sum()
    }
}

pub fn parse_cigar(s: &str) -> Result<Vec<(u8, usize)>, String> {
    if s == "*" {
        return Ok(vec![]);
    }
    let mut out = Vec::new();
    let mut num = String::new();
    for ch in s.chars() {
        if ch.is_ascii_digit() {
            num.push(ch);
        } else if "MIDNSHP=X".contains(ch) {
            let n: usize = num.parse().map_err(|_| format!("bad CIGAR {:?}", s))?;
            if n == 0 {
                return Err(format!("zero-length CIGAR op in {:?}", s));
            }
            out.push((ch as u8, n));
            num.clear();
        } else {
            return Err(format!("bad CIGAR {:?}", s));
        }
    }
    if !num.is_empty() {
        return Err(format!("bad CIGAR {:?} (trailing number)", s));
    }
    Ok(out)
}

pub struct SamFile {
    pub contigs: Vec<(String, usize)>,
    pub records: Vec<SamRecord>,
}

pub fn parse_sam(text: &str) -> Result<SamFile, String> {
    let mut contigs = Vec::new();
    let mut records = Vec::new();
    for (ln, line) in text.lines().enumerate() {
        let line = line.trim_end_matches('\r');
        if line.is_empty() {
            continue;
        }
        if let Some(h) = line.strip_prefix('@') {
            if h.starts_with("SQ") {
                let mut name = None;
                let mut len = None;
                for f in h.split('\t').skip(1) {
                    if let Some(n) = f.strip_prefix("SN:") {
                        name = Some(n.to_string());
                    }
                    if let Some(l) = f.strip_prefix("LN:") {
                        len = l.parse::<usize>().ok();
                    }
                }
                match (name, len) {
                    (Some(n), Some(l)) => contigs.push((n, l)),
                    _ => return Err(format!("line {}: malformed @SQ header", ln + 1)),
                }
            }
            continue;
        }
        let f: Vec<&str> = line.split('\t').collect();
        if f.len() < 11 {
            return Err(format!("line {}: SAM record has {} fields, need at least 11", ln + 1, f.len()));
        }
        let flag: u16 = f[1].parse().map_err(|_| format!("line {}: bad FLAG {:?}", ln + 1, f[1]))?;
        let pos1: usize = f[3].parse().map_err(|_| format!("line {}: bad POS {:?}", ln + 1, f[3]))?;
        let mapq: u8 = f[4].parse().map_err(|_| format!("line {}: bad MAPQ {:?}", ln + 1, f[4]))?;
        let cigar = parse_cigar(f[5]).map_err(|e| format!("line {}: {}", ln + 1, e))?;
        let seq: Vec<u8> = if f[9] == "*" { vec![] } else { f[9].to_ascii_uppercase().into_bytes() };
        let qual: Vec<u8> = if f[10] == "*" { vec![b'I'; seq.len()] } else { f[10].as_bytes().to_vec() };
        if flag & 4 == 0 {
            if pos1 == 0 {
                return Err(format!("line {}: mapped read with POS 0", ln + 1));
            }
            let qlen: usize = cigar.iter().filter(|(o, _)| matches!(o, b'M' | b'I' | b'S' | b'=' | b'X')).map(|&(_, n)| n).sum();
            if qlen != seq.len() {
                return Err(format!("line {}: CIGAR consumes {} query bases but SEQ has {}", ln + 1, qlen, seq.len()));
            }
            if qual.len() != seq.len() {
                return Err(format!("line {}: SEQ/QUAL length mismatch", ln + 1));
            }
        }
        records.push(SamRecord { name: f[0].to_string(), flag, rname: f[2].to_string(), pos: pos1.saturating_sub(1), mapq, cigar, seq, qual });
    }
    Ok(SamFile { contigs, records })
}

pub fn read_sam(path: &str) -> Result<SamFile, String> {
    let t = std::fs::read_to_string(path).map_err(|e| format!("{}: {}", path, e))?;
    parse_sam(&t).map_err(|e| format!("{}: {}", path, e))
}

// ---- evaluation against simulator truth -------------------------------------------------------

#[derive(Debug, Clone, Default)]
pub struct MapEval {
    pub total: usize,
    pub mapped: usize,
    pub correct: usize,
    /// rows: (mapq lower bound, mapped, correct)
    pub by_mapq: Vec<(u8, usize, usize)>,
    pub unparseable: usize,
}

/// Evaluate mapping accuracy from simulator read names `chr:pos:strand:id` (pos 1-based leftmost).
pub fn evaluate_sam(sam: &SamFile, tolerance: usize) -> MapEval {
    let mut ev = MapEval::default();
    let bins = [0u8, 1, 10, 20, 30, 40, 50, 60];
    let mut rows: Vec<(u8, usize, usize)> = bins.iter().map(|&b| (b, 0, 0)).collect();
    for r in &sam.records {
        ev.total += 1;
        let parts: Vec<&str> = r.name.split(':').collect();
        let truth = if parts.len() == 4 { parts[1].parse::<usize>().ok().map(|p| (parts[0], p - 1)) } else { None };
        let Some((tchr, tpos)) = truth else {
            ev.unparseable += 1;
            continue;
        };
        if !r.is_mapped() {
            continue;
        }
        ev.mapped += 1;
        let ok = r.rname == tchr && (r.pos as i64 - tpos as i64).unsigned_abs() as usize <= tolerance;
        if ok {
            ev.correct += 1;
        }
        for row in rows.iter_mut() {
            if r.mapq >= row.0 {
                row.1 += 1;
                if ok {
                    row.2 += 1;
                }
            }
        }
    }
    ev.by_mapq = rows;
    ev
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::rng::Rng;
    use crate::seq::{parse_fasta, Reference};

    fn build(seq: &str) -> FmIndex {
        FmIndex::build(Reference::from_fasta(&parse_fasta(&format!(">r\n{}\n", seq)).unwrap()).unwrap(), 4)
    }

    fn random_dna(rng: &mut Rng, n: usize) -> String {
        (0..n).map(|_| b"ACGT"[rng.below(4)] as char).collect()
    }

    fn fq(name: &str, s: &str) -> Fastq {
        Fastq { name: name.into(), seq: s.as_bytes().to_vec(), qual: vec![b'I'; s.len()] }
    }

    #[test]
    fn exact_forward_and_reverse_reads_map_back() {
        let mut rng = Rng::new(21);
        let g = random_dna(&mut rng, 5000);
        let fm = build(&g);
        let p = MapParams::default();
        for start in [0usize, 1, 777, 2500, 4899] {
            let s = &g[start..start + 100];
            let r = map_read(&fm, &p, &fq("f", s));
            let h = r.hit.expect("forward read must map");
            assert_eq!((h.pos, h.reverse), (start, false));
            assert_eq!(h.aln.cigar(100), "100M");
            assert_eq!(h.mapq, 60);
            let rc = String::from_utf8(revcomp_ascii(s.as_bytes())).unwrap();
            let r = map_read(&fm, &p, &fq("r", &rc));
            let h = r.hit.expect("reverse read must map");
            assert_eq!((h.pos, h.reverse), (start, true));
        }
    }

    #[test]
    fn mismatches_and_indels_are_aligned_with_correct_cigar() {
        let mut rng = Rng::new(22);
        let g = random_dna(&mut rng, 4000);
        let fm = build(&g);
        let p = MapParams::default();
        let mut s: Vec<u8> = g.as_bytes()[1000..1100].to_vec();
        s[50] = if s[50] == b'A' { b'C' } else { b'A' };
        let r = map_read(&fm, &p, &fq("mm", std::str::from_utf8(&s).unwrap())).hit.unwrap();
        assert_eq!((r.pos, r.aln.cigar(100)), (1000, "100M".to_string()));
        assert_eq!(r.aln.edit_distance(), 1);
        // 3-base deletion in the read
        let mut d = g.as_bytes()[1000..1100].to_vec();
        d.drain(40..43);
        let r = map_read(&fm, &p, &fq("del", std::str::from_utf8(&d).unwrap())).hit.unwrap();
        assert_eq!(r.pos, 1000);
        assert!(r.aln.cigar(97).contains("3D"), "{}", r.aln.cigar(97));
        // 2-base insertion
        let mut ins = g.as_bytes()[2000..2100].to_vec();
        ins.splice(60..60, *b"GG");
        let r = map_read(&fm, &p, &fq("ins", std::str::from_utf8(&ins).unwrap())).hit.unwrap();
        assert_eq!(r.pos, 2000);
        assert!(r.aln.cigar(102).contains("2I"), "{}", r.aln.cigar(102));
    }

    #[test]
    fn read_overhanging_reference_end_is_soft_clipped() {
        let mut rng = Rng::new(23);
        let g = random_dna(&mut rng, 3000);
        let fm = build(&g);
        let mut s = g[2940..].to_string(); // 60 real bases
        s.push_str(&random_dna(&mut rng, 40));
        let h = map_read(&fm, &MapParams::default(), &fq("tail", &s)).hit.unwrap();
        assert_eq!(h.pos, 2940);
        assert!(h.aln.cigar(100).ends_with("40S"), "{}", h.aln.cigar(100));
    }

    #[test]
    fn exact_repeat_gets_mapq_zero_unique_gets_high() {
        let mut rng = Rng::new(24);
        let unit = random_dna(&mut rng, 300);
        let g = format!("{}{}{}{}{}", random_dna(&mut rng, 1500), unit, random_dna(&mut rng, 1500), unit, random_dna(&mut rng, 1500));
        let fm = build(&g);
        let p = MapParams::default();
        let r = map_read(&fm, &p, &fq("rep", &unit[100..200])).hit.unwrap();
        assert_eq!(r.mapq, 0, "two identical copies must be ambiguous");
        let r = map_read(&fm, &p, &fq("uniq", &g[100..200])).hit.unwrap();
        assert!(r.mapq >= 55);
        // a diverged copy: read spanning a unique difference should prefer the right copy
        let mut other = g.clone().into_bytes();
        let second_copy = 1500 + 300 + 1500;
        other[second_copy + 150] = if other[second_copy + 150] == b'A' { b'C' } else { b'A' };
        let fm2 = build(std::str::from_utf8(&other).unwrap());
        let read = &std::str::from_utf8(&other).unwrap()[second_copy + 100..second_copy + 200];
        let h = map_read(&fm2, &p, &fq("div", read)).hit.unwrap();
        assert_eq!(h.pos, second_copy + 100);
        assert!(h.mapq > 0);
    }

    #[test]
    fn junk_and_short_and_n_reads() {
        let mut rng = Rng::new(25);
        let g = random_dna(&mut rng, 3000);
        let fm = build(&g);
        let p = MapParams::default();
        assert!(map_read(&fm, &p, &fq("junk", &random_dna(&mut rng, 100))).hit.is_none());
        assert!(map_read(&fm, &p, &fq("short", "ACGT")).hit.is_none());
        assert!(map_read(&fm, &p, &fq("empty", "")).hit.is_none());
        let mut s = g[500..600].as_bytes().to_vec();
        s[30] = b'N';
        let h = map_read(&fm, &p, &fq("n", std::str::from_utf8(&s).unwrap())).hit.unwrap();
        assert_eq!(h.pos, 500);
        let alln = "N".repeat(100);
        assert!(map_read(&fm, &p, &fq("alln", &alln)).hit.is_none());
    }

    #[test]
    fn multi_record_reference_and_boundary() {
        let mut rng = Rng::new(26);
        let a = random_dna(&mut rng, 2000);
        let b = random_dna(&mut rng, 2000);
        let fa = parse_fasta(&format!(">a\n{}\n>b\n{}\n", a, b)).unwrap();
        let fm = FmIndex::build(Reference::from_fasta(&fa).unwrap(), 4);
        let p = MapParams::default();
        let h = map_read(&fm, &p, &fq("x", &b[300..400])).hit.unwrap();
        assert_eq!((h.rid, h.pos), (1, 300));
        // a read straddling a|b must never be reported as mapping across the join
        let straddle = format!("{}{}", &a[1950..], &b[..50]);
        if let Some(h) = map_read(&fm, &p, &fq("s", &straddle)).hit {
            let end = h.pos + h.aln.ref_span();
            assert!(end <= fm.reference.lens[h.rid]);
        }
    }

    #[test]
    fn threads_give_identical_results() {
        let mut rng = Rng::new(27);
        let g = random_dna(&mut rng, 6000);
        let fm = build(&g);
        let reads: Vec<Fastq> = (0..300).map(|i| fq(&format!("r{}", i), &g[i * 15..i * 15 + 100])).collect();
        let a = map_all(&fm, &MapParams::default(), &reads).unwrap();
        let b = map_all(&fm, &MapParams { threads: 4, ..MapParams::default() }, &reads).unwrap();
        for (x, y) in a.iter().zip(&b) {
            assert_eq!(x.read.name, y.read.name);
            assert_eq!(x.hit.as_ref().map(|h| (h.pos, h.reverse, h.mapq)), y.hit.as_ref().map(|h| (h.pos, h.reverse, h.mapq)));
        }
    }

    #[test]
    fn sam_roundtrip() {
        let mut rng = Rng::new(28);
        let g = random_dna(&mut rng, 3000);
        let fm = build(&g);
        let p = MapParams::default();
        let rc = String::from_utf8(revcomp_ascii(g[800..900].as_bytes())).unwrap();
        let reads = vec![fq("r:801:-:0", &rc), fq("r:101:+:1", &g[100..200]), fq("junk", &random_dna(&mut rng, 100))];
        let res = map_all(&fm, &p, &reads).unwrap();
        let mut buf = Vec::new();
        write_sam(&mut buf, &fm, &res, true, "test").unwrap();
        let sam = parse_sam(&String::from_utf8(buf).unwrap()).unwrap();
        assert_eq!(sam.contigs, vec![("r".to_string(), 3000)]);
        assert_eq!(sam.records.len(), 3);
        assert_eq!(sam.records[0].pos, 100);
        assert_eq!(sam.records[1].pos, 800);
        assert_eq!(sam.records[1].flag, 16);
        assert_eq!(sam.records[1].seq, g.as_bytes()[800..900].to_vec(), "reverse-strand SEQ is stored on the forward strand");
        assert!(!sam.records[2].is_mapped());
        let ev = evaluate_sam(&sam, 5);
        assert_eq!(ev.unparseable, 1);
        assert_eq!(ev.correct, 2);
    }

    #[test]
    fn sam_parse_errors() {
        assert!(parse_sam("r\t0\tc\t5\t60\t10M\t*\t0\t0\tACGT\tIIII\n").is_err()); // cigar/seq mismatch
        assert!(parse_sam("r\t0\tc\n").is_err());
        assert!(parse_sam("r\tx\tc\t5\t60\t4M\t*\t0\t0\tACGT\tIIII\n").is_err());
        assert!(parse_sam("r\t0\tc\t0\t60\t4M\t*\t0\t0\tACGT\tIIII\n").is_err());
        assert!(parse_cigar("4M2Q").is_err());
        assert!(parse_cigar("M4").is_err());
        assert!(parse_cigar("0M").is_err());
        assert_eq!(parse_cigar("3S10M2D5M").unwrap().len(), 4);
    }

    #[test]
    fn mapq_model() {
        assert_eq!(mapq_from_scores(100, 0, 100, 1, false), 60);
        assert_eq!(mapq_from_scores(100, 100, 100, 1, false), 0);
        assert!(mapq_from_scores(100, 90, 100, 1, false) < 10);
        assert_eq!(mapq_from_scores(100, 0, 100, 1, true), 0);
        assert!(mapq_from_scores(40, 0, 100, 1, false) < 40);
    }

    #[test]
    fn param_validation() {
        let g = "ACGT".repeat(20);
        let fm = build(&g);
        assert!(map_all(&fm, &MapParams { threads: 0, ..MapParams::default() }, &[]).is_err());
        assert!(map_all(&fm, &MapParams { min_seed: 5, ..MapParams::default() }, &[]).is_err());
    }
}
