//! Measured space and speed for every structure, against the obvious naive alternative.
//! Nothing here is hard-coded: bits are counted from the built structures, times are wall-clock.
use crate::bitvec::{BitVec, RankSelect};
use crate::ef::EliasFano;
use crate::fm::FmIndex;
use crate::louds::Louds;
use crate::rrr::Rrr;
use crate::util::Rng;
use crate::wavelet::WaveletMatrix;
use std::hint::black_box;
use std::time::Instant;

pub struct Row {
    pub structure: String,
    pub bits_per_item: f64,
    pub naive_bits_per_item: f64,
    pub query: String,
    pub ns_per_query: f64,
    pub naive_ns: Option<f64>,
}

fn time_ns<F: FnMut(usize) -> u64>(iters: usize, mut f: F) -> f64 {
    let t = Instant::now();
    let mut acc = 0u64;
    for i in 0..iters {
        acc = acc.wrapping_add(f(i));
    }
    black_box(acc);
    t.elapsed().as_nanos() as f64 / iters as f64
}

/// `scale` 1.0 = full run; the tests use a small value.
pub fn run(scale: f64) -> Vec<Row> {
    let sz = |n: usize| ((n as f64 * scale) as usize).max(1000);
    let mut rows = Vec::new();
    let mut rng = Rng::new(2026);
    let q = sz(200_000);

    // --- plain rank/select bitvector, p = 0.5 ---
    let n = sz(8_000_000);
    let bools: Vec<bool> = (0..n).map(|_| rng.chance(0.5)).collect();
    let rs = RankSelect::new(BitVec::from_bools(&bools));
    let probes: Vec<usize> = (0..q).map(|_| rng.below(n as u64) as usize).collect();
    // naive: precomputed u32 prefix-sum table (fast but 32 bits per bit)
    let mut prefix = Vec::with_capacity(n + 1);
    let mut c = 0u32;
    prefix.push(0);
    for &b in &bools {
        c += b as u32;
        prefix.push(c);
    }
    rows.push(Row {
        structure: "RankSelect (rank9)".into(),
        bits_per_item: rs.total_bits() as f64 / n as f64,
        naive_bits_per_item: 32.0,
        query: "rank1".into(),
        ns_per_query: time_ns(q, |i| rs.rank1(probes[i]) as u64),
        naive_ns: Some(time_ns(q, |i| prefix[probes[i]] as u64)),
    });
    let ones = rs.count_ones();
    let sprobes: Vec<usize> = (0..q).map(|_| rng.below(ones as u64) as usize).collect();
    let ones_pos: Vec<u32> = bools.iter().enumerate().filter(|(_, &b)| b).map(|(i, _)| i as u32).collect();
    rows.push(Row {
        structure: "RankSelect (rank9)".into(),
        bits_per_item: rs.total_bits() as f64 / n as f64,
        naive_bits_per_item: 32.0 * ones as f64 / n as f64,
        query: "select1".into(),
        ns_per_query: time_ns(q, |i| rs.select1(sprobes[i]).unwrap() as u64),
        naive_ns: Some(time_ns(q, |i| ones_pos[sprobes[i]] as u64)),
    });
    drop((prefix, ones_pos));

    // --- RRR on a sparse vector (p = 0.01) ---
    let sparse: Vec<bool> = (0..n).map(|_| rng.chance(0.01)).collect();
    let sbv = BitVec::from_bools(&sparse);
    let rrr = Rrr::new(&sbv);
    let plain = RankSelect::new(sbv);
    rows.push(Row {
        structure: "Rrr (p = 0.01)".into(),
        bits_per_item: rrr.total_bits() as f64 / n as f64,
        naive_bits_per_item: plain.total_bits() as f64 / n as f64,
        query: "rank1 (vs plain rank9)".into(),
        ns_per_query: time_ns(q, |i| rrr.rank1(probes[i]) as u64),
        naive_ns: Some(time_ns(q, |i| plain.rank1(probes[i]) as u64)),
    });
    drop(plain);

    // --- Elias–Fano: 1M ids over a 2^30 universe ---
    let m = sz(1_000_000);
    let mut vals: Vec<u64> = (0..m).map(|_| rng.below(1 << 30)).collect();
    vals.sort_unstable();
    let ef = EliasFano::new(&vals).unwrap();
    let eprobes: Vec<usize> = (0..q).map(|_| rng.below(m as u64) as usize).collect();
    rows.push(Row {
        structure: "EliasFano (u = 2^30)".into(),
        bits_per_item: ef.total_bits() as f64 / m as f64,
        naive_bits_per_item: 64.0,
        query: "get(i)".into(),
        ns_per_query: time_ns(q, |i| ef.get(eprobes[i]).unwrap()),
        naive_ns: Some(time_ns(q, |i| vals[eprobes[i]])),
    });
    let xs: Vec<u64> = (0..q).map(|_| rng.below(1 << 30)).collect();
    rows.push(Row {
        structure: "EliasFano (u = 2^30)".into(),
        bits_per_item: ef.total_bits() as f64 / m as f64,
        naive_bits_per_item: 64.0,
        query: "rank(x) (vs binary search)".into(),
        ns_per_query: time_ns(q, |i| ef.rank(xs[i]) as u64),
        naive_ns: Some(time_ns(q, |i| vals.partition_point(|&v| v < xs[i]) as u64)),
    });

    // --- Wavelet matrix over 1M bytes (skewed) ---
    let wn = sz(1_000_000);
    let seq: Vec<u32> = (0..wn).map(|_| (rng.below(16) * rng.below(16)) as u32).collect();
    let wm = WaveletMatrix::new(&seq);
    let wprobes: Vec<usize> = (0..q).map(|_| rng.below(wn as u64) as usize).collect();
    rows.push(Row {
        structure: "WaveletMatrix (sigma<=226)".into(),
        bits_per_item: wm.total_bits() as f64 / wn as f64,
        naive_bits_per_item: 32.0,
        query: "rank(c, i)".into(),
        ns_per_query: time_ns(q / 4, |i| wm.rank(seq[wprobes[i]], wprobes[i]) as u64),
        naive_ns: None,
    });
    let ranges: Vec<(usize, usize)> = (0..q / 20).map(|_| { let l = rng.below(wn as u64 - 1000) as usize; (l, l + 1000) }).collect();
    rows.push(Row {
        structure: "WaveletMatrix (sigma<=226)".into(),
        bits_per_item: wm.total_bits() as f64 / wn as f64,
        naive_bits_per_item: 32.0,
        query: "median of 1000-range (vs sort)".into(),
        ns_per_query: time_ns(ranges.len(), |i| wm.quantile(ranges[i].0, ranges[i].1, 500).unwrap() as u64),
        naive_ns: Some(time_ns(ranges.len(), |i| {
            let mut v = seq[ranges[i].0..ranges[i].1].to_vec();
            v.sort_unstable();
            v[500] as u64
        })),
    });

    // --- FM-index on synthetic word text ---
    let words: Vec<String> = (0..2000).map(|i| {
        let mut r = Rng::new(i as u64 + 7);
        (0..2 + r.below(7)).map(|_| (b'a' + r.below(26) as u8) as char).collect()
    }).collect();
    let tn = sz(4_000_000);
    let mut text = Vec::with_capacity(tn + 16);
    while text.len() < tn {
        // Zipf-ish: low word indexes are far more likely.
        let i = ((rng.below(2000) * rng.below(2000)) / 2000) as usize;
        text.extend_from_slice(words[i].as_bytes());
        text.push(if rng.chance(0.08) { b'\n' } else { b' ' });
    }
    let pats: Vec<Vec<u8>> = (0..200).map(|_| { let s = rng.below(text.len() as u64 - 8) as usize; text[s..s + 6].to_vec() }).collect();
    let naive_count = |p: &[u8]| text.windows(p.len()).filter(|w| *w == p).count() as u64;
    for (name, comp, rate) in [("FmIndex plain/32", false, 32), ("FmIndex RRR/128", true, 128)] {
        let fm = FmIndex::build_with(&text, rate, comp).unwrap();
        rows.push(Row {
            structure: name.into(),
            bits_per_item: fm.total_bits() as f64 / text.len() as f64,
            naive_bits_per_item: 8.0,
            query: "count(6-byte pattern) (vs scan)".into(),
            ns_per_query: time_ns(pats.len(), |i| fm.count(&pats[i]) as u64),
            naive_ns: Some(time_ns(pats.len().min(20), |i| naive_count(&pats[i]))),
        });
        rows.push(Row {
            structure: name.into(),
            bits_per_item: fm.total_bits() as f64 / text.len() as f64,
            naive_bits_per_item: 8.0,
            query: "locate (per occurrence)".into(),
            ns_per_query: {
                let mut occ = 0usize;
                let t = Instant::now();
                for p in pats.iter().take(50) {
                    occ += fm.locate(p).unwrap().len();
                }
                t.elapsed().as_nanos() as f64 / occ.max(1) as f64
            },
            naive_ns: None,
        });
    }

    // --- LOUDS trie of 100k random words ---
    let tk = sz(100_000);
    let keys: Vec<Vec<u8>> = (0..tk).map(|_| (0..4 + rng.below(8)).map(|_| b'a' + rng.below(26) as u8).collect()).collect();
    let trie = Louds::build(&keys);
    let raw_bits: usize = keys.iter().map(|k| (k.len() + 1) * 8).sum();
    let set: std::collections::BTreeSet<&Vec<u8>> = keys.iter().collect();
    let kp: Vec<usize> = (0..q).map(|_| rng.below(tk as u64) as usize).collect();
    rows.push(Row {
        structure: "Louds trie".into(),
        bits_per_item: trie.total_bits() as f64 / trie.len() as f64,
        naive_bits_per_item: raw_bits as f64 / keys.len() as f64,
        query: "lookup (vs BTreeSet)".into(),
        ns_per_query: time_ns(q, |i| trie.id_of(&keys[kp[i]]).unwrap() as u64),
        naive_ns: Some(time_ns(q, |i| set.contains(&keys[kp[i]]) as u64)),
    });
    rows
}

pub fn render(rows: &[Row]) -> String {
    let mut s = String::new();
    s.push_str(&format!(
        "{:<28} {:>9} {:>9}  {:<32} {:>10} {:>10}\n",
        "structure", "bits/item", "naive", "query", "ns/query", "naive ns"
    ));
    s.push_str(&"-".repeat(106));
    s.push('\n');
    for r in rows {
        s.push_str(&format!(
            "{:<28} {:>9.2} {:>9.2}  {:<32} {:>10.1} {:>10}\n",
            r.structure,
            r.bits_per_item,
            r.naive_bits_per_item,
            r.query,
            r.ns_per_query,
            r.naive_ns.map_or("-".to_string(), |v| format!("{v:.1}"))
        ));
    }
    s
}
