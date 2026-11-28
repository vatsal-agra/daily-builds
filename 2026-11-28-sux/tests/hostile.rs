//! Hostile-input tests added during the adversarial review (REVIEW.md).
use std::sync::mpsc;
use std::time::Duration;
use sux::ef::EliasFano;
use sux::fm::FmIndex;
use sux::util::*;

/// Run `f` on a thread; fail if it panics or exceeds the deadline (hang).
fn guarded<F: FnOnce() + Send + 'static>(what: &str, f: F) {
    let (tx, rx) = mpsc::channel();
    std::thread::spawn(move || {
        let r = std::panic::catch_unwind(std::panic::AssertUnwindSafe(f));
        let _ = tx.send(r.is_ok());
    });
    match rx.recv_timeout(Duration::from_secs(10)) {
        Ok(true) => {}
        Ok(false) => panic!("{what}: panicked"),
        Err(_) => panic!("{what}: hung"),
    }
}

fn resum(b: &mut [u8]) {
    let len = b.len();
    let sum = fnv1a(&b[16..len - 8]);
    b[len - 8..].copy_from_slice(&sum.to_le_bytes());
}

#[test]
fn ef_empty_or_sparse_does_not_allocate_per_universe() {
    let e = EliasFano::with_universe(&[], 1 << 40).unwrap();
    assert!(e.total_bits() < 4096, "empty EF with huge universe used {} bits", e.total_bits());
    let e = EliasFano::with_universe(&[5, 1 << 39], 1 << 40).unwrap();
    assert!(e.total_bits() < 4096, "2-element EF used {} bits", e.total_bits());
    assert_eq!(e.get(1), Some(1 << 39));
    assert_eq!(e.rank(1 << 38), 1);
}

#[test]
fn ef_extreme_values() {
    assert!(EliasFano::new(&[u64::MAX]).is_err() || EliasFano::new(&[u64::MAX]).unwrap().get(0) == Some(u64::MAX));
    let e = EliasFano::new(&[0, u64::MAX - 1]).unwrap();
    assert_eq!(e.get(1), Some(u64::MAX - 1));
    assert_eq!(e.predecessor(u64::MAX), Some((1, u64::MAX - 1)));
    assert_eq!(e.successor(u64::MAX), None);
}

#[test]
fn corrupt_but_checksummed_index_never_panics_or_hangs() {
    let mut rng = Rng::new(99);
    let t: Vec<u8> = (0..600).map(|_| b"ab\nc"[rng.below(4) as usize]).collect();
    for compressed in [false, true] {
        let bytes = FmIndex::build_with(&t, 8, compressed).unwrap().save_bytes();
        for round in 0..4000u64 {
            let mut b = bytes.clone();
            let flips = 1 + rng.below(3);
            for _ in 0..flips {
                let i = 16 + rng.below((b.len() - 24) as u64) as usize;
                b[i] ^= 1 << rng.below(8);
            }
            resum(&mut b);
            guarded(&format!("round {round} compressed={compressed}"), move || {
                if let Ok(fm) = FmIndex::load_bytes(&b) {
                    let _ = fm.count(b"ab");
                    let _ = fm.locate(b"a");
                    let _ = fm.locate(b"b\n");
                    let _ = fm.extract(0, fm.len());
                    let _ = fm.extract(3, 17);
                    let _ = fm.grep(b"c");
                    let _ = fm.line(1);
                    let _ = fm.line(fm.line_count());
                }
            });
        }
    }
}

#[test]
fn wavelet_handles_full_32_bit_symbols() {
    use sux::wavelet::WaveletMatrix;
    let s = [u32::MAX, 0, 7, u32::MAX, 1 << 31];
    let wm = WaveletMatrix::new(&s);
    assert_eq!(wm.bit_width(), 32);
    assert_eq!(wm.access(3), Some(u32::MAX));
    assert_eq!(wm.rank(u32::MAX, 5), 2);
    assert_eq!(wm.select(u32::MAX, 1), Some(3));
    assert_eq!(wm.quantile(0, 5, 4), Some(u32::MAX));
    assert_eq!(wm.count_less(0, 5, u32::MAX), 3);
    let narrow = WaveletMatrix::new(&[1, 2, 3]);
    assert_eq!(narrow.rank(1 << 20, 3), 0); // symbol wider than the matrix: absent, no panic
    assert_eq!(narrow.select(1 << 20, 0), None);
    assert_eq!(narrow.count_less(0, 3, 1 << 20), 3);
}

#[test]
fn fm_empty_pattern_semantics_and_error_messages() {
    let fm = FmIndex::build(b"abc", 2).unwrap();
    assert_eq!(fm.count(b""), 4); // n + 1 positions
    assert!(fm.locate(b"").is_err());
    let e = fm.extract(2, 1).unwrap_err().to_string();
    assert!(e.contains("after"), "{e}");
    let e = fm.extract(0, 9).unwrap_err().to_string();
    assert!(e.contains("beyond"), "{e}");
    assert!(FmIndex::build(b"x", 0).is_err());
    assert!(FmIndex::build(b"x", 5000).is_err());
}
