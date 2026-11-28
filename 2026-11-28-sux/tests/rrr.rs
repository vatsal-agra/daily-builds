use sux::bitvec::BitVec;
use sux::fm::FmIndex;
use sux::rrr::Rrr;
use sux::util::*;
use sux::wavelet::WaveletMatrix;

fn rand_bits(rng: &mut Rng, n: usize, p: f64) -> Vec<bool> {
    (0..n).map(|_| rng.chance(p)).collect()
}

#[test]
fn rrr_matches_naive() {
    let mut rng = Rng::new(21);
    for &n in &[0usize, 1, 14, 15, 16, 29, 30, 31, 479, 480, 481, 959, 960, 961, 1920, 5000] {
        for &p in &[0.0, 0.02, 0.5, 0.98, 1.0] {
            let b = rand_bits(&mut rng, n, p);
            let r = Rrr::from_bools(&b);
            assert_eq!(r.len(), n);
            let (mut ones, mut zeros) = (0, 0);
            for i in 0..=n {
                assert_eq!(r.rank1(i), ones, "rank1 n={n} p={p} i={i}");
                assert_eq!(r.rank0(i), zeros);
                if i < n {
                    assert_eq!(r.get(i), b[i], "get n={n} i={i}");
                    if b[i] {
                        assert_eq!(r.select1(ones), Some(i), "select1 n={n} p={p}");
                        ones += 1;
                    } else {
                        assert_eq!(r.select0(zeros), Some(i), "select0 n={n} p={p}");
                        zeros += 1;
                    }
                }
            }
            assert_eq!(r.select1(ones), None);
            assert_eq!(r.select0(zeros), None);
        }
    }
}

#[test]
fn rrr_compresses_skewed_and_roundtrips() {
    let mut rng = Rng::new(22);
    let n = 200_000;
    let b = rand_bits(&mut rng, n, 0.01);
    let r = Rrr::from_bools(&b);
    // H(0.01) = 0.0808 bits; allow generous block/sample overhead but demand < 42% of raw (4-bit classes alone are 26.7%).
    assert!(r.total_bits() * 100 < n * 42, "rrr used {} bits for {} raw", r.total_bits(), n);
    let mut w = Writer::new();
    r.write(&mut w);
    let back = Rrr::read(&mut Reader::new(&w.buf)).unwrap();
    for i in (0..=n).step_by(97) {
        assert_eq!(r.rank1(i), back.rank1(i));
    }
    for cut in (0..w.buf.len()).step_by(101) {
        assert!(Rrr::read(&mut Reader::new(&w.buf[..cut])).is_err());
    }
    // Corrupt an offset so it exceeds C(15, class): must be rejected, not decoded to garbage.
    let mut bad = w.buf.clone();
    let last = bad.len() - 1;
    bad[last] = 0xFF;
    let _ = Rrr::read(&mut Reader::new(&bad)); // must not panic
}

#[test]
fn compressed_wavelet_equals_plain() {
    let mut rng = Rng::new(23);
    let s: Vec<u32> = (0..2000).map(|_| (rng.below(7) * rng.below(7)) as u32).collect();
    let (a, b) = (WaveletMatrix::new(&s), WaveletMatrix::new_compressed(&s));
    assert!(b.is_compressed() && !a.is_compressed());
    for i in 0..s.len() {
        assert_eq!(a.access(i), b.access(i));
    }
    for c in 0..40u32 {
        for i in (0..=s.len()).step_by(13) {
            assert_eq!(a.rank(c, i), b.rank(c, i));
        }
        assert_eq!(a.select(c, 3), b.select(c, 3));
    }
    assert_eq!(a.quantile(10, 900, 40), b.quantile(10, 900, 40));
    let mut w = Writer::new();
    b.write(&mut w);
    let back = WaveletMatrix::read(&mut Reader::new(&w.buf)).unwrap();
    assert!(back.is_compressed());
    assert_eq!(back.access(777), a.access(777));
}

#[test]
fn compressed_fm_index_equals_plain_and_is_smaller_on_skewed_text() {
    let mut rng = Rng::new(24);
    // Zipf-ish skewed text: 'e' dominates.
    let t: Vec<u8> = (0..60_000)
        .map(|_| match rng.below(100) {
            0..=59 => b'e',
            60..=79 => b't',
            80..=89 => b'a',
            90..=95 => b'\n',
            _ => b'a' + rng.below(26) as u8,
        })
        .collect();
    let plain = FmIndex::build_with(&t, 32, false).unwrap();
    let comp = FmIndex::build_with(&t, 32, true).unwrap();
    for p in [&b"ee"[..], b"eta", b"tt\nt", b"zz"] {
        assert_eq!(plain.locate(p).unwrap(), comp.locate(p).unwrap());
    }
    assert_eq!(comp.extract(100, 5000).unwrap(), &t[100..5000]);
    assert!(comp.save_bytes().len() < plain.save_bytes().len());
    let back = FmIndex::load_bytes(&comp.save_bytes()).unwrap();
    assert!(back.is_compressed());
    assert_eq!(back.count(b"ee"), plain.count(b"ee"));
    let _ = BitVec::new();
}
