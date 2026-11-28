use sux::fm::FmIndex;
use sux::util::*;

fn naive_find(t: &[u8], p: &[u8]) -> Vec<usize> {
    if p.is_empty() || p.len() > t.len() {
        return vec![];
    }
    (0..=t.len() - p.len()).filter(|&i| &t[i..i + p.len()] == p).collect()
}

fn random_text(rng: &mut Rng, n: usize, sigma: u64) -> Vec<u8> {
    (0..n).map(|_| if sigma > 200 { rng.below(256) as u8 } else { b'a' + rng.below(sigma) as u8 }).collect()
}

#[test]
fn locate_count_extract_match_naive() {
    let mut rng = Rng::new(11);
    for &(n, sigma, rate) in &[(0usize, 2u64, 4usize), (1, 2, 1), (50, 2, 1), (200, 3, 4), (1500, 4, 16), (1500, 256, 7), (3000, 2, 64)] {
        let t = random_text(&mut rng, n, sigma);
        let fm = FmIndex::build(&t, rate).unwrap();
        assert_eq!(fm.len(), n);
        for _ in 0..60 {
            let len = 1 + rng.below(6) as usize;
            let p: Vec<u8> = if n > 0 && rng.chance(0.7) {
                let s = rng.below(n as u64) as usize;
                t[s..(s + len).min(n)].to_vec()
            } else {
                random_text(&mut rng, len, sigma)
            };
            let want = naive_find(&t, &p);
            assert_eq!(fm.count(&p), want.len(), "count n={n} p={p:?}");
            assert_eq!(fm.locate(&p).unwrap(), want, "locate n={n} p={p:?}");
        }
        for _ in 0..60 {
            if n == 0 {
                break;
            }
            let a = rng.below(n as u64 + 1) as usize;
            let b = a + rng.below((n - a) as u64 + 1) as usize;
            assert_eq!(fm.extract(a, b).unwrap(), &t[a..b], "extract {a}..{b} n={n} rate={rate}");
        }
        assert_eq!(fm.extract(0, n).unwrap(), t);
        assert!(fm.extract(0, n + 1).is_err());
    }
}

#[test]
fn texts_with_nul_and_all_bytes() {
    let t: Vec<u8> = (0..=255u8).cycle().take(2000).collect();
    let fm = FmIndex::build(&t, 8).unwrap();
    assert_eq!(fm.extract(0, t.len()).unwrap(), t);
    assert_eq!(fm.locate(&[255, 0, 1]).unwrap(), naive_find(&t, &[255, 0, 1]));
    assert_eq!(fm.count(&[0]), naive_find(&t, &[0]).len());
}

#[test]
fn grep_lines_match_naive() {
    let text = b"alpha beta\nbeta gamma beta\n\nno match here\nlast beta\nbeta";
    let fm = FmIndex::build(text, 4).unwrap();
    assert_eq!(fm.line_count(), 6);
    let hits = fm.grep(b"beta").unwrap();
    let want: Vec<(usize, Vec<usize>)> = vec![(1, vec![6]), (2, vec![0, 11]), (5, vec![5]), (6, vec![0])];
    assert_eq!(hits.iter().map(|h| (h.line, h.columns.clone())).collect::<Vec<_>>(), want);
    assert_eq!(hits[1].text, b"beta gamma beta");
    assert_eq!(fm.line(3).unwrap(), b"");
    assert_eq!(fm.line(6).unwrap(), b"beta");
    assert!(fm.line(0).is_err() && fm.line(7).is_err());
    assert!(fm.grep(b"").is_err());
    assert!(fm.grep(b"a\nb").is_err());
    assert!(fm.grep(b"zzz").unwrap().is_empty());
}

#[test]
fn trailing_newline_line_count() {
    let fm = FmIndex::build(b"a\nb\n", 2).unwrap();
    assert_eq!(fm.line_count(), 2);
    assert_eq!(fm.line(2).unwrap(), b"b");
    let fm = FmIndex::build(b"", 2).unwrap();
    assert_eq!(fm.line_count(), 0);
    assert!(fm.grep(b"x").unwrap().is_empty());
}

#[test]
fn persistence_roundtrip_and_corruption_never_panics() {
    let mut rng = Rng::new(12);
    let t = random_text(&mut rng, 800, 4);
    let fm = FmIndex::build(&t, 8).unwrap();
    let bytes = fm.save_bytes();
    let back = FmIndex::load_bytes(&bytes).unwrap();
    assert_eq!(back.extract(0, t.len()).unwrap(), t);
    assert_eq!(back.locate(b"ab").unwrap(), fm.locate(b"ab").unwrap());
    // truncation
    for cut in (0..bytes.len()).step_by(37) {
        assert!(FmIndex::load_bytes(&bytes[..cut]).is_err());
    }
    // single-byte flips are caught by the checksum
    for i in (0..bytes.len()).step_by(53) {
        let mut b = bytes.clone();
        b[i] ^= 0x40;
        assert!(FmIndex::load_bytes(&b).is_err(), "flip at {i} accepted");
    }
    // flips with a *recomputed* checksum must still never panic (structural validation)
    for i in (16..bytes.len() - 8).step_by(11) {
        let mut b = bytes.clone();
        b[i] ^= 0xFF;
        let len = b.len();
        let sum = fnv1a(&b[16..len - 8]);
        b[len - 8..].copy_from_slice(&sum.to_le_bytes());
        let _ = FmIndex::load_bytes(&b).map(|f| {
            // even if it loads, querying must not panic
            let _ = f.count(b"ab");
        });
    }
}

#[test]
fn index_is_smaller_than_text_on_repetitive_nothing_but_bounded() {
    // On English-like text with sample rate 32 the index must stay within a sane factor.
    let mut rng = Rng::new(13);
    let words = ["the", "quick", "brown", "fox", "jumps", "over", "lazy", "dog", "and", "runs", "away"];
    let mut t = Vec::new();
    while t.len() < 200_000 {
        t.extend_from_slice(words[rng.below(words.len() as u64) as usize].as_bytes());
        t.push(if rng.chance(0.1) { b'\n' } else { b' ' });
    }
    let fm = FmIndex::build(&t, 32).unwrap();
    let ratio = fm.total_bits() as f64 / (t.len() * 8) as f64;
    assert!(ratio < 1.6, "index/text ratio {ratio}");
    assert_eq!(fm.count(b"quick brown"), naive_find(&t, b"quick brown").len());
}
