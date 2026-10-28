//! Mash-style genome distance: bottom-s MinHash sketches of canonical k-mers, Jaccard estimate
//! from the merged sketch, Mash distance D = -1/k * ln(2j / (1 + j)), and UPGMA clustering to a
//! Newick tree.

use crate::dbg::rc;

#[derive(Clone, Debug)]
pub struct Sketch {
    pub k: usize,
    pub size: usize,
    pub hashes: Vec<u64>, // ascending, distinct, at most `size`
    pub kmers_seen: usize,
}

fn mix(mut x: u64) -> u64 {
    x = (x ^ (x >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
    x = (x ^ (x >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
    x ^ (x >> 31)
}

pub fn sketch(seqs: &[&[u8]], k: usize, size: usize) -> Result<Sketch, String> {
    if k < 5 || k > 31 {
        return Err("k must be within 5..=31".into());
    }
    if size == 0 {
        return Err("sketch size must be positive".into());
    }
    let m = (1u64 << (2 * k)) - 1;
    let mut all: Vec<u64> = Vec::new();
    let mut seen = 0usize;
    for s in seqs {
        let (mut fwd, mut len) = (0u64, 0usize);
        for &b in s.iter() {
            let x = match b.to_ascii_uppercase() {
                b'A' => 0u64,
                b'C' => 1,
                b'G' => 2,
                b'T' => 3,
                _ => {
                    len = 0;
                    continue;
                }
            };
            fwd = ((fwd << 2) | x) & m;
            len += 1;
            if len >= k {
                seen += 1;
                all.push(mix(fwd.min(rc(fwd, k))));
            }
        }
    }
    if all.is_empty() {
        return Err(format!("sequence has no valid {}-mers", k));
    }
    all.sort_unstable();
    all.dedup();
    all.truncate(size);
    Ok(Sketch { k, size, hashes: all, kmers_seen: seen })
}

/// Jaccard estimate via the bottom-s of the union.
pub fn jaccard(a: &Sketch, b: &Sketch) -> Result<f64, String> {
    if a.k != b.k {
        return Err(format!("sketches use different k ({} vs {})", a.k, b.k));
    }
    let s = a.size.min(b.size);
    let (mut i, mut j, mut taken, mut shared) = (0, 0, 0, 0);
    while taken < s && (i < a.hashes.len() || j < b.hashes.len()) {
        let (x, y) = (a.hashes.get(i).copied(), b.hashes.get(j).copied());
        match (x, y) {
            (Some(x), Some(y)) if x == y => {
                shared += 1;
                i += 1;
                j += 1;
            }
            (Some(x), Some(y)) => {
                if x < y {
                    i += 1
                } else {
                    j += 1
                }
            }
            (Some(_), None) => i += 1,
            (None, Some(_)) => j += 1,
            (None, None) => break,
        }
        taken += 1;
    }
    Ok(if taken == 0 { 0.0 } else { shared as f64 / taken as f64 })
}

pub fn distance(a: &Sketch, b: &Sketch) -> Result<f64, String> {
    let j = jaccard(a, b)?;
    if j <= 0.0 {
        return Ok(1.0);
    }
    Ok((-(1.0 / a.k as f64) * (2.0 * j / (1.0 + j)).ln()).clamp(0.0, 1.0))
}

pub fn distance_matrix(sk: &[Sketch]) -> Result<Vec<Vec<f64>>, String> {
    let n = sk.len();
    let mut d = vec![vec![0.0; n]; n];
    for i in 0..n {
        for j in i + 1..n {
            let x = distance(&sk[i], &sk[j])?;
            d[i][j] = x;
            d[j][i] = x;
        }
    }
    Ok(d)
}

/// UPGMA (average linkage) tree in Newick format with branch lengths.
pub fn upgma_newick(names: &[String], d: &[Vec<f64>]) -> Result<String, String> {
    let n = names.len();
    if n == 0 || d.len() != n {
        return Err("need at least one genome".into());
    }
    if n == 1 {
        return Ok(format!("{};", names[0]));
    }
    struct Node {
        newick: String,
        height: f64,
        size: usize,
    }
    let mut nodes: Vec<Option<Node>> = names.iter().map(|nm| Some(Node { newick: nm.clone(), height: 0.0, size: 1 })).collect();
    let mut dist: Vec<Vec<f64>> = d.to_vec();
    let mut active: Vec<usize> = (0..n).collect();
    while active.len() > 1 {
        let (mut bi, mut bj, mut best) = (0, 1, f64::INFINITY);
        for x in 0..active.len() {
            for y in x + 1..active.len() {
                let v = dist[active[x]][active[y]];
                if v < best {
                    best = v;
                    bi = x;
                    bj = y;
                }
            }
        }
        let (a, b) = (active[bi], active[bj]);
        let h = best / 2.0;
        let na = nodes[a].take().unwrap();
        let nb = nodes[b].take().unwrap();
        let merged = Node {
            newick: format!("({}:{:.5},{}:{:.5})", na.newick, (h - na.height).max(0.0), nb.newick, (h - nb.height).max(0.0)),
            height: h,
            size: na.size + nb.size,
        };
        // update distances into slot a (average linkage weighted by cluster size)
        for &c in &active {
            if c != a && c != b {
                let v = (dist[a][c] * na.size as f64 + dist[b][c] * nb.size as f64) / (na.size + nb.size) as f64;
                dist[a][c] = v;
                dist[c][a] = v;
            }
        }
        nodes[a] = Some(merged);
        active.remove(bj);
    }
    Ok(format!("{};", nodes[active[0]].take().unwrap().newick))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::rng::Rng;

    fn rand_dna(rng: &mut Rng, n: usize) -> Vec<u8> {
        (0..n).map(|_| b"ACGT"[rng.below(4)]).collect()
    }

    fn mutate(rng: &mut Rng, g: &[u8], rate: f64) -> Vec<u8> {
        g.iter().map(|&b| if rng.chance(rate) { loop { let n = b"ACGT"[rng.below(4)]; if n != b { break n; } } } else { b }).collect()
    }

    #[test]
    fn identical_and_unrelated_genomes() {
        let mut rng = Rng::new(1);
        let a = rand_dna(&mut rng, 50_000);
        let b = rand_dna(&mut rng, 50_000);
        let (sa, sb) = (sketch(&[&a], 21, 1000).unwrap(), sketch(&[&b], 21, 1000).unwrap());
        assert_eq!(distance(&sa, &sa).unwrap(), 0.0);
        assert_eq!(distance(&sa, &sb).unwrap(), 1.0);
        // strand-agnostic
        let rca = crate::seq::revcomp_ascii(&a);
        assert_eq!(distance(&sa, &sketch(&[&rca], 21, 1000).unwrap()).unwrap(), 0.0);
    }

    #[test]
    fn distance_tracks_the_true_substitution_rate() {
        let mut rng = Rng::new(2);
        let a = rand_dna(&mut rng, 200_000);
        let sa = sketch(&[&a], 21, 5000).unwrap();
        for rate in [0.005, 0.02, 0.05] {
            let b = mutate(&mut rng, &a, rate);
            let d = distance(&sa, &sketch(&[&b], 21, 5000).unwrap()).unwrap();
            assert!((d - rate).abs() < rate * 0.25 + 0.002, "rate {} estimated {}", rate, d);
        }
    }

    #[test]
    fn upgma_recovers_a_known_topology() {
        let mut rng = Rng::new(3);
        let root = rand_dna(&mut rng, 100_000);
        let left = mutate(&mut rng, &root, 0.06);
        let right = mutate(&mut rng, &root, 0.06);
        let a = mutate(&mut rng, &left, 0.01);
        let b = mutate(&mut rng, &left, 0.01);
        let c = mutate(&mut rng, &right, 0.01);
        let d = mutate(&mut rng, &right, 0.01);
        let names: Vec<String> = ["A", "B", "C", "D"].iter().map(|s| s.to_string()).collect();
        let sk: Vec<Sketch> = [&a, &b, &c, &d].iter().map(|g| sketch(&[g.as_slice()], 21, 4000).unwrap()).collect();
        let m = distance_matrix(&sk).unwrap();
        let nw = upgma_newick(&names, &m).unwrap();
        assert!(nw.contains("(A:") && nw.contains(",B:") || nw.contains("(B:") && nw.contains(",A:"), "{}", nw);
        // A and B are siblings: they appear inside the same innermost parentheses
        let cherry = |x: &str, y: &str| nw.contains(&format!("({}:", x)) && nw[nw.find(&format!("({}:", x)).unwrap()..].split(')').next().unwrap().contains(&format!(",{}:", y));
        assert!(cherry("A", "B") || cherry("B", "A"), "{}", nw);
        assert!(cherry("C", "D") || cherry("D", "C"), "{}", nw);
        assert!(nw.ends_with(';'));
    }

    #[test]
    fn errors() {
        assert!(sketch(&[b"ACGT"], 21, 100).is_err());
        assert!(sketch(&[b"ACGTACGTACGTACGTACGTACGT"], 40, 100).is_err());
        assert!(sketch(&[b"ACGTACGTACGTACGTACGTACGT"], 21, 0).is_err());
        let mut rng = Rng::new(4);
        let a = rand_dna(&mut rng, 5000);
        assert!(jaccard(&sketch(&[&a], 15, 100).unwrap(), &sketch(&[&a], 21, 100).unwrap()).is_err());
        assert_eq!(upgma_newick(&["x".to_string()], &[vec![0.0]]).unwrap(), "x;");
        assert!(upgma_newick(&[], &[]).is_err());
    }
}
