use std::collections::BTreeSet;
use sux::louds::Louds;
use sux::util::*;

fn rand_key(rng: &mut Rng, maxlen: u64, sigma: u64) -> Vec<u8> {
    (0..rng.below(maxlen + 1)).map(|_| rng.below(sigma) as u8).collect()
}

#[test]
fn louds_matches_btreeset() {
    let mut rng = Rng::new(31);
    for &(n, maxlen, sigma) in &[(0usize, 3u64, 2u64), (1, 0, 2), (5, 4, 2), (200, 6, 3), (500, 12, 26), (400, 5, 256)] {
        let keys: Vec<Vec<u8>> = (0..n).map(|_| rand_key(&mut rng, maxlen, sigma)).collect();
        let set: BTreeSet<Vec<u8>> = keys.iter().cloned().collect();
        let t = Louds::build(&keys);
        assert_eq!(t.len(), set.len(), "n={n}");
        let mut ids = BTreeSet::new();
        for k in &set {
            let id = t.id_of(k).unwrap_or_else(|| panic!("missing {k:?}"));
            assert!(id < set.len() && ids.insert(id), "ids must be a dense permutation");
            assert_eq!(t.key_of(id).as_deref(), Some(&k[..]));
        }
        assert_eq!(t.key_of(set.len()), None);
        for _ in 0..300 {
            let probe = rand_key(&mut rng, maxlen + 1, sigma);
            assert_eq!(t.contains(&probe), set.contains(&probe), "probe {probe:?}");
            let want: Vec<Vec<u8>> = set.iter().filter(|k| k.starts_with(&probe)).cloned().collect();
            assert_eq!(t.complete(&probe, usize::MAX), want, "complete {probe:?}");
            assert_eq!(t.count_prefix(&probe), want.len());
            assert_eq!(t.complete(&probe, 3), want.iter().take(3).cloned().collect::<Vec<_>>());
        }
    }
}

#[test]
fn louds_roundtrip_and_hostile_files() {
    let words = ["", "a", "ab", "abc", "abd", "b", "banana", "band", "bandana", "can"];
    let t = Louds::build(&words);
    let bytes = t.save_bytes();
    let back = Louds::load_bytes(&bytes).unwrap();
    assert_eq!(back.complete(b"ban", 10).len(), 3);
    assert!(back.contains(b"") && back.contains(b"abd") && !back.contains(b"abe"));
    for cut in (0..bytes.len()).step_by(3) {
        assert!(Louds::load_bytes(&bytes[..cut]).is_err());
    }
    let mut rng = Rng::new(32);
    for _ in 0..3000 {
        let mut b = bytes.clone();
        let i = 16 + rng.below((b.len() - 24) as u64) as usize;
        b[i] ^= 1 << rng.below(8);
        let len = b.len();
        let sum = fnv1a(&b[16..len - 8]);
        b[len - 8..].copy_from_slice(&sum.to_le_bytes());
        if let Ok(t) = Louds::load_bytes(&b) {
            // loaded despite the damage: queries must still be panic-free
            let _ = t.complete(b"", 50);
            let _ = t.contains(b"ban");
            let _ = t.key_of(2);
            let _ = t.count_prefix(b"a");
        }
    }
}

#[test]
fn louds_is_compact_on_prefix_sharing_keys() {
    // Dictionary-like keys: stems share prefixes, endings repeat. (Uniformly random keys share
    // almost nothing, and then no trie beats the raw strings by much — see README.)
    let mut rng = Rng::new(33);
    let stems: Vec<Vec<u8>> = (0..400).map(|_| (0..3 + rng.below(4)).map(|_| b'a' + rng.below(26) as u8).collect()).collect();
    let ends: [&[u8]; 8] = [b"", b"s", b"ed", b"ing", b"er", b"ers", b"ly", b"ness"];
    let mut keys = Vec::new();
    for s in &stems {
        for e in ends {
            keys.push([&s[..], e].concat());
        }
    }
    let t = Louds::build(&keys);
    let raw: usize = keys.iter().map(|k| (k.len() + 1) * 8).sum();
    assert!(t.total_bits() * 10 < raw * 8, "trie {} bits vs raw {} bits", t.total_bits(), raw);
    assert_eq!(t.len(), keys.len());
}
