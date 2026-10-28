//! De Bruijn graph assembler: canonical k-mer counting, automatic error cut-off from the
//! k-mer spectrum, compacted unitig graph, tip clipping, bubble popping, contig output.
//!
//! The graph is bidirected: a k-mer and its reverse complement are one node (stored as the
//! lexicographically smaller *canonical* form). Everything is 2-bit packed in a `u64`, so
//! k <= 31 (odd, so no k-mer is its own reverse complement).

use crate::align::{align, Mode, Scoring};
use std::collections::{HashMap, HashSet};
use std::hash::{BuildHasherDefault, Hasher};

#[derive(Default)]
pub struct Fx(u64);
impl Hasher for Fx {
    fn finish(&self) -> u64 {
        self.0
    }
    fn write(&mut self, bytes: &[u8]) {
        for &b in bytes {
            self.0 = (self.0.rotate_left(5) ^ b as u64).wrapping_mul(0x517c_c1b7_2722_0a95);
        }
    }
    fn write_u64(&mut self, x: u64) {
        let mut h = x.wrapping_mul(0x9E37_79B9_7F4A_7C15);
        h ^= h >> 29;
        self.0 = h.wrapping_mul(0xBF58_476D_1CE4_E5B9);
    }
}
type Map<V> = HashMap<u64, V, BuildHasherDefault<Fx>>;
type Set = HashSet<u64, BuildHasherDefault<Fx>>;

#[derive(Clone, Debug)]
pub struct AsmParams {
    pub k: usize,
    /// None = choose from the k-mer spectrum
    pub min_count: Option<u32>,
    pub min_contig: usize,
    pub tip_len: Option<usize>,
    pub pop_bubbles: bool,
    pub bubble_identity: f64,
}

impl Default for AsmParams {
    fn default() -> AsmParams {
        AsmParams { k: 31, min_count: None, min_contig: 200, tip_len: None, pop_bubbles: true, bubble_identity: 0.9 }
    }
}

impl AsmParams {
    pub fn validate(&self) -> Result<(), String> {
        if self.k < 11 || self.k > 31 || self.k % 2 == 0 {
            return Err("k must be odd and within 11..=31".into());
        }
        if !(0.5..=1.0).contains(&self.bubble_identity) {
            return Err("bubble identity must be within [0.5, 1.0]".into());
        }
        if let Some(c) = self.min_count {
            if c == 0 {
                return Err("min-count must be at least 1".into());
            }
        }
        Ok(())
    }
}

#[derive(Clone, Debug)]
pub struct Contig {
    pub seq: Vec<u8>, // ASCII
    pub cov: f64,     // mean k-mer multiplicity
}

#[derive(Clone, Debug, Default)]
pub struct AsmStats {
    pub reads: usize,
    pub kmers_distinct: usize,
    pub kmers_solid: usize,
    pub cutoff: u32,
    pub cutoff_auto: bool,
    pub coverage_peak: u32,
    pub tips_removed: usize,
    pub bubbles_popped: usize,
    pub contigs: usize,
    pub total_len: usize,
    pub largest: usize,
    pub n50: usize,
    pub l50: usize,
    pub n90: usize,
}

// ---- 2-bit k-mer arithmetic (A=0 C=1 G=2 T=3) ----------------------------------------------

#[inline]
fn base2(b: u8) -> Option<u64> {
    match b {
        b'A' => Some(0),
        b'C' => Some(1),
        b'G' => Some(2),
        b'T' => Some(3),
        _ => None,
    }
}

#[inline]
fn mask(k: usize) -> u64 {
    if k == 32 {
        u64::MAX
    } else {
        (1u64 << (2 * k)) - 1
    }
}

#[inline]
pub fn rc(x: u64, k: usize) -> u64 {
    // complement = invert; reverse the order of 2-bit groups
    let mut v = !x;
    v = ((v >> 2) & 0x3333_3333_3333_3333) | ((v & 0x3333_3333_3333_3333) << 2);
    v = ((v >> 4) & 0x0F0F_0F0F_0F0F_0F0F) | ((v & 0x0F0F_0F0F_0F0F_0F0F) << 4);
    v = v.swap_bytes();
    v >> (64 - 2 * k)
}

#[inline]
fn canon(x: u64, k: usize) -> u64 {
    x.min(rc(x, k))
}

fn kmer_to_ascii(x: u64, k: usize) -> Vec<u8> {
    (0..k).map(|i| b"ACGT"[((x >> (2 * (k - 1 - i))) & 3) as usize]).collect()
}

#[cfg(test)]
fn ascii_to_kmer(s: &[u8]) -> u64 {
    s.iter().fold(0u64, |a, &b| (a << 2) | base2(b).unwrap())
}

/// Count canonical k-mers in all reads (both strands folded together). k-mers with an
/// ambiguous base are skipped, and the window restarts after it.
pub fn count_kmers(reads: &[&[u8]], k: usize) -> Map<u32> {
    let mut counts: Map<u32> = Map::default();
    let m = mask(k);
    for r in reads {
        let (mut fwd, mut len) = (0u64, 0usize);
        for &b in r.iter() {
            match base2(b.to_ascii_uppercase()) {
                Some(x) => {
                    fwd = ((fwd << 2) | x) & m;
                    len += 1;
                    if len >= k {
                        let c = counts.entry(canon(fwd, k)).or_insert(0);
                        *c = c.saturating_add(1);
                    }
                }
                None => len = 0,
            }
        }
    }
    counts
}

/// Histogram h[c] = number of distinct k-mers seen exactly c times (c clipped at 255).
pub fn spectrum(counts: &Map<u32>) -> Vec<u64> {
    let mut h = vec![0u64; 256];
    for &c in counts.values() {
        h[(c as usize).min(255)] += 1;
    }
    h
}

/// Choose the error/solid cut-off at the first valley of the (smoothed) spectrum, and report the
/// coverage peak. Falls back to 2 when the spectrum has no clear valley.
pub fn auto_cutoff(h: &[u64]) -> (u32, u32) {
    let sm: Vec<f64> = (0..h.len())
        .map(|i| {
            let lo = i.saturating_sub(1).max(1);
            let hi = (i + 1).min(h.len() - 1);
            let s: u64 = h[lo..=hi].iter().sum();
            s as f64 / (hi - lo + 1) as f64
        })
        .collect();
    let mut valley = None;
    for i in 2..h.len() - 2 {
        if sm[i] <= sm[i - 1] && sm[i] < sm[i + 1] && sm[i + 1] <= sm[i + 2] {
            valley = Some(i);
            break;
        }
    }
    let v = match valley {
        Some(v) => v,
        None => return (2, h.iter().enumerate().skip(2).max_by_key(|(_, &x)| x).map(|(i, _)| i as u32).unwrap_or(0)),
    };
    let peak = (v..h.len()).max_by(|&a, &b| sm[a].partial_cmp(&sm[b]).unwrap()).unwrap();
    // the valley must be clearly below the coverage peak, otherwise it is just noise
    if sm[v] > 0.8 * sm[peak] || peak < 2 * v.max(1) / 2 + 1 {
        return (2, peak as u32);
    }
    (v.max(2) as u32, peak as u32)
}

// ---- unitig construction --------------------------------------------------------------------

struct Graph<'a> {
    k: usize,
    solid: &'a Map<u32>,
}

impl<'a> Graph<'a> {
    #[inline]
    fn has(&self, x: u64) -> bool {
        self.solid.contains_key(&canon(x, self.k))
    }
    fn succ(&self, x: u64) -> Vec<u64> {
        let m = mask(self.k);
        (0..4u64).map(|b| ((x << 2) | b) & m).filter(|&y| self.has(y)).collect()
    }
    fn pred(&self, x: u64) -> Vec<u64> {
        self.succ(rc(x, self.k)).into_iter().map(|y| rc(y, self.k)).collect()
    }
}

#[derive(Clone, Debug)]
struct Unitig {
    kmers: Vec<u64>, // oriented k-mers along the unitig
    seq: Vec<u8>,
    cov: f64,
}

fn build_unitigs(solid: &Map<u32>, k: usize) -> Vec<Unitig> {
    let g = Graph { k, solid };
    let mut visited: Set = Set::default();
    let mut keys: Vec<u64> = solid.keys().copied().collect();
    keys.sort_unstable(); // deterministic output
    let mut out = Vec::new();
    for &start in &keys {
        if visited.contains(&start) {
            continue;
        }
        visited.insert(start);
        // extend right
        let mut right: Vec<u64> = Vec::new();
        let mut x = start;
        loop {
            let s = g.succ(x);
            if s.len() != 1 {
                break;
            }
            let y = s[0];
            if g.pred(y).len() != 1 || visited.contains(&canon(y, k)) {
                break;
            }
            visited.insert(canon(y, k));
            right.push(y);
            x = y;
        }
        // extend left = extend right on the reverse complement
        let mut left: Vec<u64> = Vec::new();
        let mut x = rc(start, k);
        loop {
            let s = g.succ(x);
            if s.len() != 1 {
                break;
            }
            let y = s[0];
            if g.pred(y).len() != 1 || visited.contains(&canon(y, k)) {
                break;
            }
            visited.insert(canon(y, k));
            left.push(y);
            x = y;
        }
        let mut kmers: Vec<u64> = left.iter().rev().map(|&y| rc(y, k)).collect();
        kmers.push(start);
        kmers.extend(right);
        let mut seq = kmer_to_ascii(kmers[0], k);
        for &km in &kmers[1..] {
            seq.push(b"ACGT"[(km & 3) as usize]);
        }
        let cov = kmers.iter().map(|&km| solid[&canon(km, k)] as f64).sum::<f64>() / kmers.len() as f64;
        out.push(Unitig { kmers, seq, cov });
    }
    out
}

fn remove_unitigs(solid: &mut Map<u32>, unitigs: &[&Unitig], k: usize) {
    for u in unitigs {
        for &km in &u.kmers {
            solid.remove(&canon(km, k));
        }
    }
}

/// Dead-end unitigs shorter than `max_len` hanging off a junction.
fn find_tips<'a>(unitigs: &'a [Unitig], solid: &Map<u32>, k: usize, max_len: usize) -> Vec<&'a Unitig> {
    let g = Graph { k, solid };
    let mut tips = Vec::new();
    for u in unitigs {
        if u.seq.len() >= max_len {
            continue;
        }
        let first = u.kmers[0];
        let last = *u.kmers.last().unwrap();
        let preds = g.pred(first);
        let succs = g.succ(last);
        let attached_to_junction = if preds.is_empty() && !succs.is_empty() {
            // dead start, joined on the right: the junction has competing branches if a successor has other predecessors
            succs.iter().any(|&y| g.pred(y).len() > 1) || succs.len() > 1
        } else if succs.is_empty() && !preds.is_empty() {
            preds.iter().any(|&y| g.succ(y).len() > 1) || preds.len() > 1
        } else {
            false
        };
        if attached_to_junction {
            tips.push(u);
        }
    }
    tips
}

fn identity(a: &[u8], b: &[u8]) -> f64 {
    let ac = crate::seq::to_codes_n(a);
    let bc = crate::seq::to_codes_n(b);
    let band = (a.len() as i64 - b.len() as i64).abs() + 8;
    let off = b.len() as i64 - a.len() as i64;
    match align(&ac, &bc, Mode::Global, &Scoring::default(), Some((off.min(0) - band, off.max(0) + band))) {
        Ok(Some(al)) => al.matches() as f64 / a.len().max(b.len()) as f64,
        _ => 0.0,
    }
}

/// Simple bubbles: P -> {A,B,..} -> S where every branch has one predecessor and one successor and
/// all branches rejoin at S. Branches that look like the best-covered one are dropped.
fn find_bubbles<'a>(unitigs: &'a [Unitig], solid: &Map<u32>, k: usize, min_identity: f64, max_len: usize) -> Vec<&'a Unitig> {
    let g = Graph { k, solid };
    // oriented first k-mer -> (unitig index, forward?)
    let mut starts: HashMap<u64, (usize, bool), BuildHasherDefault<Fx>> = HashMap::default();
    for (i, u) in unitigs.iter().enumerate() {
        starts.insert(u.kmers[0], (i, true));
        starts.insert(rc(*u.kmers.last().unwrap(), k), (i, false));
    }
    let mut drop: Vec<usize> = Vec::new();
    let mut dropped: HashSet<usize> = HashSet::new();
    for (i, u) in unitigs.iter().enumerate() {
        for fwd in [true, false] {
            let end = if fwd { *u.kmers.last().unwrap() } else { rc(u.kmers[0], k) };
            let branches: Vec<(usize, bool)> = g.succ(end).into_iter().filter_map(|y| starts.get(&y).copied()).collect();
            if branches.len() < 2 {
                continue;
            }
            // each branch: single successor, single predecessor, short
            let mut ok: Vec<(usize, bool, u64)> = Vec::new();
            for &(bi, bf) in &branches {
                let b = &unitigs[bi];
                if b.seq.len() > max_len || bi == i {
                    continue;
                }
                let (bfirst, blast) = if bf { (b.kmers[0], *b.kmers.last().unwrap()) } else { (rc(*b.kmers.last().unwrap(), k), rc(b.kmers[0], k)) };
                let s = g.succ(blast);
                if s.len() == 1 && g.pred(bfirst).len() == 1 {
                    ok.push((bi, bf, s[0]));
                }
            }
            if ok.len() < 2 {
                continue;
            }
            // group by the node where they rejoin
            ok.sort_by_key(|x| x.2);
            let mut gi = 0;
            while gi < ok.len() {
                let mut gj = gi;
                while gj < ok.len() && ok[gj].2 == ok[gi].2 {
                    gj += 1;
                }
                let grp = &ok[gi..gj];
                if grp.len() >= 2 {
                    let orient = |&(bi, bf, _): &(usize, bool, u64)| -> Vec<u8> {
                        if bf {
                            unitigs[bi].seq.clone()
                        } else {
                            crate::seq::revcomp_ascii(&unitigs[bi].seq)
                        }
                    };
                    let best = grp.iter().max_by(|a, b| unitigs[a.0].cov.partial_cmp(&unitigs[b.0].cov).unwrap()).unwrap();
                    let best_seq = orient(best);
                    for cand in grp {
                        if cand.0 == best.0 || dropped.contains(&cand.0) || dropped.contains(&best.0) {
                            continue;
                        }
                        if identity(&best_seq, &orient(cand)) >= min_identity {
                            dropped.insert(cand.0);
                            drop.push(cand.0);
                        }
                    }
                }
                gi = gj;
            }
        }
    }
    drop.iter().map(|&i| &unitigs[i]).collect()
}

pub fn n_stats(lens: &[usize], frac: f64, total: usize) -> (usize, usize) {
    let mut v = lens.to_vec();
    v.sort_unstable_by(|a, b| b.cmp(a));
    let mut acc = 0;
    for (i, &l) in v.iter().enumerate() {
        acc += l;
        if acc as f64 >= frac * total as f64 {
            return (l, i + 1);
        }
    }
    (0, 0)
}

pub struct Assembly {
    pub contigs: Vec<Contig>,
    pub stats: AsmStats,
    pub spectrum: Vec<u64>,
}

pub fn assemble(reads: &[&[u8]], p: &AsmParams) -> Result<Assembly, String> {
    p.validate()?;
    let k = p.k;
    let mut stats = AsmStats { reads: reads.len(), ..Default::default() };
    if reads.iter().all(|r| r.len() < k) {
        return Err(format!("no read is at least k={} bases long; lower -k", k));
    }
    let counts = count_kmers(reads, k);
    stats.kmers_distinct = counts.len();
    let spec = spectrum(&counts);
    let (auto, peak) = auto_cutoff(&spec);
    let cutoff = p.min_count.unwrap_or(auto);
    stats.cutoff = cutoff;
    stats.cutoff_auto = p.min_count.is_none();
    stats.coverage_peak = peak;
    let mut solid: Map<u32> = counts.into_iter().filter(|&(_, c)| c >= cutoff).collect();
    stats.kmers_solid = solid.len();
    if solid.is_empty() {
        return Err(format!("no k-mer occurs at least {} times — coverage too low for k={}; try a smaller -k or --min-count 1", cutoff, k));
    }
    let tip_max = p.tip_len.unwrap_or(2 * k);
    // alternate clipping and popping until the graph stops changing
    for _round in 0..12 {
        let mut changed = false;
        loop {
            let unitigs = build_unitigs(&solid, k);
            let tips = find_tips(&unitigs, &solid, k, tip_max);
            if tips.is_empty() {
                break;
            }
            stats.tips_removed += tips.len();
            remove_unitigs(&mut solid, &tips, k);
            changed = true;
        }
        if p.pop_bubbles {
            let unitigs = build_unitigs(&solid, k);
            let bubbles = find_bubbles(&unitigs, &solid, k, p.bubble_identity, 4 * k + 20);
            if !bubbles.is_empty() {
                stats.bubbles_popped += bubbles.len();
                remove_unitigs(&mut solid, &bubbles, k);
                changed = true;
            }
        }
        if !changed {
            break;
        }
    }
    let unitigs = build_unitigs(&solid, k);
    let mut contigs: Vec<Contig> = unitigs.into_iter().filter(|u| u.seq.len() >= p.min_contig).map(|u| Contig { seq: u.seq, cov: u.cov }).collect();
    contigs.sort_by(|a, b| b.seq.len().cmp(&a.seq.len()).then_with(|| a.seq.cmp(&b.seq)));
    let lens: Vec<usize> = contigs.iter().map(|c| c.seq.len()).collect();
    stats.contigs = contigs.len();
    stats.total_len = lens.iter().sum();
    stats.largest = lens.first().copied().unwrap_or(0);
    let (n50, l50) = n_stats(&lens, 0.5, stats.total_len);
    stats.n50 = n50;
    stats.l50 = l50;
    stats.n90 = n_stats(&lens, 0.9, stats.total_len).0;
    Ok(Assembly { contigs, stats, spectrum: spec })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::rng::Rng;

    fn rand_dna(rng: &mut Rng, n: usize) -> Vec<u8> {
        (0..n).map(|_| b"ACGT"[rng.below(4)]).collect()
    }

    fn shotgun(rng: &mut Rng, g: &[u8], cov: usize, len: usize, err: f64) -> Vec<Vec<u8>> {
        (0..cov * g.len() / len)
            .map(|_| {
                let st = rng.below(g.len() - len + 1);
                let mut s = g[st..st + len].to_vec();
                if rng.chance(0.5) {
                    s = crate::seq::revcomp_ascii(&s);
                }
                for b in s.iter_mut() {
                    if rng.chance(err) {
                        *b = b"ACGT"[rng.below(4)];
                    }
                }
                s
            })
            .collect()
    }

    #[test]
    fn rc_and_pack_roundtrip() {
        let mut rng = Rng::new(1);
        for k in [11usize, 21, 31] {
            for _ in 0..200 {
                let s = rand_dna(&mut rng, k);
                let x = ascii_to_kmer(&s);
                assert_eq!(kmer_to_ascii(x, k), s);
                assert_eq!(kmer_to_ascii(rc(x, k), k), crate::seq::revcomp_ascii(&s));
                assert_eq!(rc(rc(x, k), k), x);
                assert_eq!(canon(x, k), canon(rc(x, k), k));
            }
        }
    }

    #[test]
    fn counts_fold_strands_and_skip_ambiguous() {
        let c = count_kmers(&[b"ACGTA", b"TACGT"], 3);
        // ACG and CGT are reverse complements; TAC/GTA likewise
        assert_eq!(c[&canon(ascii_to_kmer(b"ACG"), 3)], 4);
        let c = count_kmers(&[b"ACNGT"], 3);
        assert!(c.is_empty(), "windows containing N must be skipped");
    }

    #[test]
    fn perfect_reads_reassemble_a_unique_genome_exactly() {
        let mut rng = Rng::new(2);
        let g = rand_dna(&mut rng, 20_000);
        let reads = shotgun(&mut rng, &g, 30, 100, 0.0);
        let refs: Vec<&[u8]> = reads.iter().map(|r| r.as_slice()).collect();
        let a = assemble(&refs, &AsmParams { min_count: Some(1), ..AsmParams::default() }).unwrap();
        assert_eq!(a.contigs.len(), 1, "stats {:?}", a.stats);
        let c = &a.contigs[0].seq;
        // random read starts leave a few uncovered bases at both genome ends; everything else must be exact
        let (gs, rs) = (String::from_utf8(g.clone()).unwrap(), String::from_utf8(crate::seq::revcomp_ascii(&g)).unwrap());
        let cs = String::from_utf8(c.clone()).unwrap();
        assert!(gs.contains(&cs) || rs.contains(&cs), "contig must be an exact substring of the genome (either strand)");
        assert!(c.len() >= g.len() - 150, "contig {} vs genome {}", c.len(), g.len());
    }

    #[test]
    fn errors_are_cleaned_by_cutoff_tips_and_bubbles() {
        let mut rng = Rng::new(3);
        let g = rand_dna(&mut rng, 30_000);
        let reads = shotgun(&mut rng, &g, 40, 100, 0.01);
        let refs: Vec<&[u8]> = reads.iter().map(|r| r.as_slice()).collect();
        let a = assemble(&refs, &AsmParams::default()).unwrap();
        assert!(a.stats.cutoff_auto && a.stats.cutoff >= 2, "{:?}", a.stats);
        assert!(a.stats.coverage_peak >= 15, "peak {:?}", a.stats);
        let rcg = crate::seq::revcomp_ascii(&g);
        let big = &a.contigs[0].seq;
        assert!(a.stats.n50 > 20_000, "{:?}", a.stats);
        // largest contig is a substring of the genome (either strand): no residual errors
        let gs = String::from_utf8(g.clone()).unwrap();
        let rs = String::from_utf8(rcg).unwrap();
        let cs = String::from_utf8(big.clone()).unwrap();
        assert!(gs.contains(&cs) || rs.contains(&cs), "assembled contig contains errors");
    }

    #[test]
    fn heterozygous_snp_bubble_is_popped_and_dead_end_clipped() {
        let mut rng = Rng::new(4);
        let g = rand_dna(&mut rng, 6000);
        let mut h2 = g.clone();
        h2[3000] = if h2[3000] == b'A' { b'C' } else { b'A' };
        let mut reads = shotgun(&mut rng, &g, 20, 100, 0.0);
        reads.extend(shotgun(&mut rng, &h2, 20, 100, 0.0));
        let refs: Vec<&[u8]> = reads.iter().map(|r| r.as_slice()).collect();
        let with = assemble(&refs, &AsmParams { min_count: Some(2), ..AsmParams::default() }).unwrap();
        assert!(with.stats.bubbles_popped >= 1, "{:?}", with.stats);
        assert_eq!(with.contigs.len(), 1, "{:?}", with.stats);
        let without = assemble(&refs, &AsmParams { min_count: Some(2), pop_bubbles: false, ..AsmParams::default() }).unwrap();
        assert!(without.contigs.len() > with.contigs.len(), "unpopped graph must fragment at the SNP");
    }

    #[test]
    fn contigs_break_exactly_at_repeat_junctions() {
        // U1 R U2 R U3 with perfect reads: the repeat R must be its own unitig (merge on entry,
        // branch on exit), giving exactly U1, R, U2, U3 — and every contig must be genome sequence.
        let mut rng = Rng::new(8);
        let (u1, u2, u3, r) = (rand_dna(&mut rng, 1500), rand_dna(&mut rng, 1500), rand_dna(&mut rng, 1500), rand_dna(&mut rng, 300));
        let g: Vec<u8> = [u1.as_slice(), &r, &u2, &r, &u3].concat();
        let reads = shotgun(&mut rng, &g, 60, 100, 0.0);
        let refs: Vec<&[u8]> = reads.iter().map(|r| r.as_slice()).collect();
        let a = assemble(&refs, &AsmParams { min_count: Some(1), min_contig: 50, ..AsmParams::default() }).unwrap();
        assert_eq!(a.contigs.len(), 4, "{:?}", a.contigs.iter().map(|c| c.seq.len()).collect::<Vec<_>>());
        let gs = String::from_utf8(g.clone()).unwrap();
        let rs = String::from_utf8(crate::seq::revcomp_ascii(&g)).unwrap();
        for c in &a.contigs {
            let cs = String::from_utf8(c.seq.clone()).unwrap();
            assert!(gs.contains(&cs) || rs.contains(&cs));
        }
        let shortest = a.contigs.iter().map(|c| c.seq.len()).min().unwrap();
        assert!((300..=335).contains(&shortest), "repeat unitig should be ~R plus k-1 overlap context, got {}", shortest);
    }

    #[test]
    fn auto_cutoff_finds_the_valley() {
        // error mode at 1, valley near 4-5, coverage peak near 20
        let mut h = vec![0u64; 256];
        for c in 1..=60usize {
            let err = 5000.0 * (-(c as f64) * 1.2).exp();
            let sig = 800.0 * (-((c as f64 - 20.0).powi(2)) / 50.0).exp();
            h[c] = (err + sig) as u64;
        }
        let (cut, peak) = auto_cutoff(&h);
        assert!((3..=8).contains(&cut), "cutoff {}", cut);
        assert!((17..=23).contains(&peak), "peak {}", peak);
        // flat/noisy spectrum -> safe default
        let flat = vec![10u64; 256];
        assert_eq!(auto_cutoff(&flat).0, 2);
    }

    #[test]
    fn rejects_bad_inputs() {
        assert!(assemble(&[b"ACGT"], &AsmParams::default()).is_err());
        assert!(assemble(&[b"ACGT"], &AsmParams { k: 30, ..AsmParams::default() }).is_err());
        assert!(assemble(&[b"ACGT"], &AsmParams { k: 5, ..AsmParams::default() }).is_err());
        assert!(assemble(&[b"ACGT"], &AsmParams { min_count: Some(0), ..AsmParams::default() }).is_err());
        // every k-mer unique but cutoff 5 -> nothing solid
        let mut rng = Rng::new(5);
        let r = rand_dna(&mut rng, 200);
        assert!(assemble(&[&r], &AsmParams { min_count: Some(5), ..AsmParams::default() }).is_err());
    }

    #[test]
    fn n_stats_basic() {
        assert_eq!(n_stats(&[100, 80, 60, 40, 20], 0.5, 300), (80, 2));
        assert_eq!(n_stats(&[], 0.5, 0), (0, 0));
    }

    #[test]
    fn deterministic() {
        let mut rng = Rng::new(6);
        let g = rand_dna(&mut rng, 5000);
        let reads = shotgun(&mut rng, &g, 25, 100, 0.005);
        let refs: Vec<&[u8]> = reads.iter().map(|r| r.as_slice()).collect();
        let a = assemble(&refs, &AsmParams::default()).unwrap();
        let b = assemble(&refs, &AsmParams::default()).unwrap();
        assert_eq!(a.contigs.iter().map(|c| c.seq.clone()).collect::<Vec<_>>(), b.contigs.iter().map(|c| c.seq.clone()).collect::<Vec<_>>());
    }
}
