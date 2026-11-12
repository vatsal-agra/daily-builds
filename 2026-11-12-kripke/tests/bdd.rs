use kripke::bdd::{Bdd, Manager, FALSE, TRUE};
use kripke::fuzz::Rng;
use std::collections::HashMap;

const N: usize = 6;

/// Truth table of a function over N variables as a 64-bit mask (bit i = value at assignment i).
fn table(m: &Manager, f: Bdd) -> u64 {
    let mut t = 0u64;
    for a in 0..(1u64 << N) {
        if m.eval(f, &|v| (a >> v) & 1 == 1) {
            t |= 1 << a;
        }
    }
    t
}

fn var_table(v: usize) -> u64 {
    let mut t = 0;
    for a in 0..(1u64 << N) {
        if (a >> v) & 1 == 1 {
            t |= 1 << a;
        }
    }
    t
}

fn random_fn(m: &mut Manager, r: &mut Rng, depth: usize) -> (Bdd, u64) {
    if depth == 0 || r.chance(1, 5) {
        return match r.below(4) {
            0 => (TRUE, !0),
            1 => (FALSE, 0),
            _ => {
                let v = r.below(N);
                (m.var(v as u32), var_table(v))
            }
        };
    }
    let (a, ta) = random_fn(m, r, depth - 1);
    let (b, tb) = random_fn(m, r, depth - 1);
    match r.below(7) {
        0 => (m.and(a, b), ta & tb),
        1 => (m.or(a, b), ta | tb),
        2 => (m.xor(a, b), ta ^ tb),
        3 => (m.not(a), !ta),
        4 => (m.imp(a, b), !ta | tb),
        5 => (m.iff(a, b), !(ta ^ tb)),
        _ => {
            let (c, tc) = random_fn(m, r, depth - 1);
            (m.ite(a, b, c), (ta & tb) | (!ta & tc))
        }
    }
}

fn setup() -> Manager {
    let mut m = Manager::new();
    for _ in 0..N {
        m.new_var();
    }
    m
}

fn exists_table(t: u64, vars: &[usize]) -> u64 {
    let mut out = 0u64;
    for a in 0..(1u64 << N) {
        // exists over `vars`: any assignment agreeing with `a` outside vars satisfies t
        let mut any = false;
        for s in 0..(1u64 << vars.len()) {
            let mut b = a;
            for (i, &v) in vars.iter().enumerate() {
                b = (b & !(1 << v)) | (((s >> i) & 1) << v);
            }
            if (t >> b) & 1 == 1 {
                any = true;
                break;
            }
        }
        if any {
            out |= 1 << a;
        }
    }
    out
}

#[test]
fn operations_match_truth_tables() {
    let mut r = Rng(12345);
    for _ in 0..400 {
        let mut m = setup();
        let (f, tf) = random_fn(&mut m, &mut r, 4);
        let (g, tg) = random_fn(&mut m, &mut r, 4);
        assert_eq!(table(&m, f), tf);
        // canonicity: equal functions are the same node
        let (f2, tf2) = random_fn(&mut m, &mut r, 3);
        if tf2 == tf {
            assert_eq!(f2, f, "hash-consing must give equal functions equal handles");
        }
        let vars: Vec<usize> = (0..N).filter(|_| r.chance(1, 3)).collect();
        let cube = m.cube(&vars.iter().map(|&v| v as u32).collect::<Vec<_>>());
        let e = m.exists(f, cube);
        assert_eq!(table(&m, e), exists_table(tf, &vars));
        let a = m.forall(f, cube);
        assert_eq!(table(&m, a), !exists_table(!tf, &vars));
        let ae = m.and_exists(f, g, cube);
        assert_eq!(table(&m, ae), exists_table(tf & tg, &vars));
        // sat count
        let all: Vec<u32> = (0..N as u32).collect();
        assert_eq!(m.sat_count(f, &all), tf.count_ones() as u128);
        // pick_one satisfies f
        match m.pick_one(f, &all) {
            Some(bits) => assert!(m.eval(f, &|v| bits[v as usize])),
            None => assert_eq!(tf, 0),
        }
        m.check_invariants().unwrap();
    }
}

#[test]
fn rename_restrict_and_allsat() {
    let mut r = Rng(777);
    for _ in 0..200 {
        let mut m = setup();
        let (f, tf) = random_fn(&mut m, &mut r, 4);
        // rename: swap vars 0<->1, 2<->3 (a permutation, so truth table permutes)
        let mut map = HashMap::new();
        map.insert(0u32, 1u32);
        map.insert(1, 0);
        map.insert(2, 3);
        map.insert(3, 2);
        let g = m.rename(f, &map);
        for a in 0..(1u64 << N) {
            let swap = |a: u64, i: usize, j: usize| {
                let (bi, bj) = ((a >> i) & 1, (a >> j) & 1);
                (a & !(1 << i) & !(1 << j)) | (bj << i) | (bi << j)
            };
            let b = swap(swap(a, 0, 1), 2, 3);
            assert_eq!(m.eval(g, &|v| (a >> v) & 1 == 1), (tf >> b) & 1 == 1);
        }
        // restrict x4 = 1
        let mut lits = HashMap::new();
        lits.insert(4u32, true);
        let h = m.restrict(f, &lits);
        for a in 0..(1u64 << N) {
            assert_eq!(m.eval(h, &|v| (a >> v) & 1 == 1), (tf >> (a | (1 << 4))) & 1 == 1);
        }
        // all_sat cubes cover exactly the satisfying assignments
        let cubes = m.all_sat(f, 1 << 12);
        let mut covered = 0u64;
        for c in &cubes {
            for a in 0..(1u64 << N) {
                if c.iter().all(|&(v, b)| ((a >> v) & 1 == 1) == b) {
                    assert_eq!(covered >> a & 1, 0, "cubes must be disjoint");
                    covered |= 1 << a;
                }
            }
        }
        assert_eq!(covered, tf);
    }
}

#[test]
fn gc_keeps_roots_and_frees_garbage() {
    let mut r = Rng(99);
    let mut m = setup();
    let (keep, tk) = random_fn(&mut m, &mut r, 5);
    m.pin(keep);
    for _ in 0..50 {
        let _ = random_fn(&mut m, &mut r, 5);
    }
    let before = m.allocated();
    m.gc(&[]);
    assert!(m.allocated() <= before);
    assert_eq!(table(&m, keep), tk);
    m.check_invariants().unwrap();
    assert_eq!(m.allocated(), m.dag_size(&[keep]));
    // freed slots are reused and the manager still works
    let (g, tg) = random_fn(&mut m, &mut r, 5);
    assert_eq!(table(&m, g), tg);
    let both = m.and(g, keep);
    assert_eq!(table(&m, both), tg & tk);
    m.check_invariants().unwrap();
}

#[test]
fn swaps_preserve_functions_and_sifting_never_grows() {
    let mut r = Rng(4242);
    for _ in 0..100 {
        let mut m = setup();
        let fs: Vec<(Bdd, u64)> = (0..3).map(|_| random_fn(&mut m, &mut r, 5)).collect();
        for (f, _) in &fs {
            m.pin(*f);
        }
        for _ in 0..20 {
            let lv = r.below(N - 1);
            m.swap_levels(lv);
            m.gc(&[]);
            m.check_invariants().unwrap();
            for (f, t) in &fs {
                assert_eq!(table(&m, *f), *t, "swap changed a function");
            }
        }
        let blocks: Vec<Vec<u32>> = vec![vec![m.var_at_level(0), m.var_at_level(1)], vec![m.var_at_level(2)], vec![m.var_at_level(3), m.var_at_level(4), m.var_at_level(5)]];
        let roots: Vec<Bdd> = fs.iter().map(|x| x.0).collect();
        let (b, a) = m.sift_blocks(&blocks, &roots);
        assert!(a <= b, "sifting must not increase the DAG size ({} -> {})", b, a);
        m.check_invariants().unwrap();
        for (f, t) in &fs {
            assert_eq!(table(&m, *f), *t, "sifting changed a function");
        }
        // blocks stay contiguous
        let ord = m.order();
        for blk in &blocks {
            let mut lv: Vec<u32> = blk.iter().map(|&v| m.level_of(v)).collect();
            lv.sort();
            assert!(lv.windows(2).all(|w| w[1] == w[0] + 1), "block split: {:?} order {:?}", blk, ord);
        }
    }
}

#[test]
fn comparator_order_matters() {
    // x == y over n-bit numbers: exponential when all x bits precede all y bits, linear interleaved.
    let n = 10;
    let build = |interleaved: bool| {
        let mut m = Manager::new();
        let vars: Vec<u32> = (0..2 * n).map(|_| m.new_var()).collect();
        let (xs, ys): (Vec<u32>, Vec<u32>) = if interleaved {
            ((0..n).map(|i| vars[2 * i]).collect(), (0..n).map(|i| vars[2 * i + 1]).collect())
        } else {
            ((0..n).map(|i| vars[i]).collect(), (0..n).map(|i| vars[n + i]).collect())
        };
        let mut f = TRUE;
        for i in 0..n {
            let (a, b) = (m.var(xs[i]), m.var(ys[i]));
            let e = m.iff(a, b);
            f = m.and(f, e);
        }
        (m.dag_size(&[f]), m, f)
    };
    let (bad, _, _) = build(false);
    let (good, _, _) = build(true);
    assert!(bad > 20 * good, "bad order {} nodes vs good {}", bad, good);
}
