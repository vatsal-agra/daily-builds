use sux::bitvec::*;
use sux::ef::EliasFano;
use sux::sais::suffix_array_bytes;
use sux::util::*;
use sux::wavelet::WaveletMatrix;

fn rand_bits(rng: &mut Rng, n: usize, p: f64) -> Vec<bool> {
    (0..n).map(|_| rng.chance(p)).collect()
}

#[test]
fn bitvector_rank_select_matches_naive() {
    let mut rng = Rng::new(1);
    for &n in &[0usize, 1, 2, 63, 64, 65, 511, 512, 513, 1000, 5000, 70_000] {
        for &p in &[0.0, 0.01, 0.5, 0.99, 1.0] {
            let b = rand_bits(&mut rng, n, p);
            let rs = RankSelect::new(BitVec::from_bools(&b));
            let (mut ones, mut zeros) = (0, 0);
            for i in 0..=n {
                assert_eq!(rs.rank1(i), ones, "rank1 n={n} p={p} i={i}");
                assert_eq!(rs.rank0(i), zeros);
                if i < n {
                    assert_eq!(rs.get(i), b[i]);
                    if b[i] {
                        assert_eq!(rs.select1(ones), Some(i), "select1 n={n} p={p}");
                        ones += 1;
                    } else {
                        assert_eq!(rs.select0(zeros), Some(i), "select0 n={n} p={p}");
                        zeros += 1;
                    }
                }
            }
            assert_eq!(rs.select1(ones), None);
            assert_eq!(rs.select0(zeros), None);
            assert_eq!(rs.count_ones(), ones);
        }
    }
}

#[test]
fn bitvector_overhead_is_25_percent_plus_samples() {
    let mut rng = Rng::new(2);
    let b = rand_bits(&mut rng, 1_000_000, 0.5);
    let rs = RankSelect::new(BitVec::from_bools(&b));
    let ratio = rs.overhead_bits() as f64 / 1_000_000.0;
    assert!(ratio > 0.24 && ratio < 0.27, "overhead ratio {ratio}");
}

#[test]
fn bitvector_serialisation_roundtrip_and_stray_bits() {
    let mut rng = Rng::new(3);
    let b = rand_bits(&mut rng, 777, 0.3);
    let rs = RankSelect::new(BitVec::from_bools(&b));
    let mut w = Writer::new();
    rs.write(&mut w);
    let back = RankSelect::read(&mut Reader::new(&w.buf)).unwrap();
    for i in 0..=777 {
        assert_eq!(rs.rank1(i), back.rank1(i));
    }
    // Truncation must be an error, not a panic.
    for cut in 0..w.buf.len() {
        assert!(RankSelect::read(&mut Reader::new(&w.buf[..cut])).is_err());
    }
}

#[test]
fn select_in_word_exhaustive_small() {
    let mut rng = Rng::new(4);
    for _ in 0..2000 {
        let w = rng.next_u64() & rng.next_u64();
        let mut k = 0;
        for bit in 0..64 {
            if (w >> bit) & 1 == 1 {
                assert_eq!(select_in_word(w, k), bit);
                k += 1;
            }
        }
    }
}

fn naive_rank(v: &[u64], x: u64) -> usize {
    v.iter().filter(|&&y| y < x).count()
}

#[test]
fn elias_fano_matches_naive() {
    let mut rng = Rng::new(5);
    for &(n, maxgap) in &[(0usize, 1u64), (1, 10), (50, 1), (200, 3), (1000, 50), (500, 100_000)] {
        let mut v = Vec::new();
        let mut cur = rng.below(5);
        for _ in 0..n {
            v.push(cur);
            cur += rng.below(maxgap + 1);
        }
        let ef = EliasFano::new(&v).unwrap();
        assert_eq!(ef.len(), n);
        for (i, &x) in v.iter().enumerate() {
            assert_eq!(ef.get(i), Some(x));
        }
        assert_eq!(ef.get(n), None);
        let top = v.last().copied().unwrap_or(0) + 3;
        for x in 0..=top.min(3000) {
            let r = naive_rank(&v, x);
            assert_eq!(ef.rank(x), r, "rank {x} n={n}");
            assert_eq!(ef.successor(x).map(|p| p.1), v.get(r).copied());
            let pred = v.iter().rposition(|&y| y <= x);
            assert_eq!(ef.predecessor(x).map(|p| p.0), pred);
            assert_eq!(ef.contains(x), v.contains(&x));
        }
        assert_eq!(ef.iter().collect::<Vec<_>>(), v);
        // Roundtrip
        let mut w = Writer::new();
        ef.write(&mut w);
        let back = EliasFano::read(&mut Reader::new(&w.buf)).unwrap();
        assert_eq!(back.iter().collect::<Vec<_>>(), v);
    }
}

#[test]
fn elias_fano_rejects_bad_input_and_is_compact() {
    assert!(EliasFano::new(&[3, 2]).is_err());
    assert!(EliasFano::with_universe(&[5], 5).is_err());
    let mut rng = Rng::new(6);
    let (n, u) = (100_000usize, 100_000_000u64);
    let mut v: Vec<u64> = (0..n).map(|_| rng.below(u)).collect();
    v.sort();
    let ef = EliasFano::new(&v).unwrap();
    let bound = (n as f64) * (2.0 + (u as f64 / n as f64).log2());
    assert!((ef.payload_bits() as f64) <= bound, "{} > {}", ef.payload_bits(), bound);
    assert!(ef.total_bits() < n * 64 / 3, "should beat 64-bit ints by 3x");
}

#[test]
fn wavelet_matches_naive() {
    let mut rng = Rng::new(7);
    for &(n, sigma) in &[(0usize, 2u64), (1, 2), (100, 2), (300, 5), (1000, 256), (500, 1000), (200, 1)] {
        let s: Vec<u32> = (0..n).map(|_| rng.below(sigma) as u32).collect();
        let wm = WaveletMatrix::new(&s);
        for (i, &x) in s.iter().enumerate() {
            assert_eq!(wm.access(i), Some(x));
        }
        assert_eq!(wm.access(n), None);
        for c in 0..(sigma as u32 + 2) {
            let mut cnt = 0;
            for i in 0..=n {
                assert_eq!(wm.rank(c, i), cnt, "rank c={c} i={i}");
                if i < n && s[i] == c {
                    assert_eq!(wm.select(c, cnt), Some(i));
                    cnt += 1;
                }
            }
            assert_eq!(wm.select(c, cnt), None);
        }
        for _ in 0..200 {
            if n == 0 {
                break;
            }
            let l = rng.below(n as u64) as usize;
            let r = l + rng.below((n - l) as u64 + 1) as usize;
            let mut sorted = s[l..r].to_vec();
            sorted.sort();
            for k in 0..sorted.len().min(5) {
                assert_eq!(wm.quantile(l, r, k), Some(sorted[k]));
            }
            assert_eq!(wm.quantile(l, r, r - l), None);
            let (lo, hi) = (rng.below(sigma + 1) as u32, rng.below(sigma + 2) as u32);
            let expect = s[l..r].iter().filter(|&&x| x >= lo && x < hi).count();
            assert_eq!(wm.count_range(l, r, lo, hi), expect);
            let nv = sorted.iter().copied().find(|&x| x >= lo);
            assert_eq!(wm.next_value(l, r, lo), nv);
        }
    }
}

#[test]
fn wavelet_roundtrip_and_corruption() {
    let mut rng = Rng::new(8);
    let s: Vec<u32> = (0..500).map(|_| rng.below(40) as u32).collect();
    let wm = WaveletMatrix::new(&s);
    let mut w = Writer::new();
    wm.write(&mut w);
    let back = WaveletMatrix::read(&mut Reader::new(&w.buf)).unwrap();
    for i in 0..500 {
        assert_eq!(back.access(i), Some(s[i]));
    }
    for cut in (0..w.buf.len()).step_by(7) {
        assert!(WaveletMatrix::read(&mut Reader::new(&w.buf[..cut])).is_err());
    }
}

#[test]
fn sais_matches_naive_sort() {
    let mut rng = Rng::new(9);
    for &(n, sigma) in &[(0usize, 2u64), (1, 2), (2, 2), (3, 2), (10, 2), (100, 2), (500, 3), (2000, 4), (3000, 256), (400, 1)] {
        for _ in 0..5 {
            let t: Vec<u8> = (0..n).map(|_| rng.below(sigma) as u8).collect();
            let sa = suffix_array_bytes(&t);
            let mut naive: Vec<usize> = (0..n).collect();
            naive.sort_by(|&a, &b| t[a..].cmp(&t[b..]));
            assert_eq!(sa, naive, "n={n} sigma={sigma} t={t:?}");
        }
    }
    // Highly repetitive worst cases.
    let t: Vec<u8> = b"abababababababababababab".repeat(20);
    let mut naive: Vec<usize> = (0..t.len()).collect();
    naive.sort_by(|&a, &b| t[a..].cmp(&t[b..]));
    assert_eq!(suffix_array_bytes(&t), naive);
}
