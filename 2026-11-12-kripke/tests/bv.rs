use kripke::bdd::{Bdd, Manager, TRUE};
use kripke::bv::{self, Bv};

/// Evaluate a bit-vector under assignment `a` (bit i of `a` is variable i) as a signed integer.
fn val(m: &Manager, b: &Bv, a: u64) -> i64 {
    let w = b.width();
    let mut x: i64 = 0;
    for i in 0..w {
        if m.eval(b.bits[i], &|v| (a >> v) & 1 == 1) {
            x |= 1 << i;
        }
    }
    if m.eval(b.sign(), &|v| (a >> v) & 1 == 1) && w < 64 {
        x |= -1i64 << w;
    }
    x
}

fn holds(m: &Manager, f: Bdd, a: u64) -> bool {
    m.eval(f, &|v| (a >> v) & 1 == 1)
}

const W: usize = 4; // each operand is a W-bit unsigned variable block

fn operand(m: &mut Manager, base: u32) -> Bv {
    let bits: Vec<Bdd> = (0..W as u32).map(|i| m.var(base + i)).collect();
    bv::from_unsigned(&bits)
}

#[test]
fn arithmetic_matches_integers() {
    let mut m = Manager::new();
    for _ in 0..2 * W {
        m.new_var();
    }
    let a = operand(&mut m, 0);
    let b = operand(&mut m, W as u32);
    let sum = bv::add(&mut m, &a, &b);
    let dif = bv::sub(&mut m, &a, &b);
    let prod = bv::mul(&mut m, &a, &b);
    let na = bv::neg(&mut m, &a);
    let lt = bv::lt(&mut m, &a, &b);
    let le = bv::le(&mut m, &a, &b);
    let eq = bv::eq(&mut m, &a, &b);
    let c = bv::constant(-5);
    let sum_c = bv::add(&mut m, &a, &c);
    let lt_c = bv::lt(&mut m, &a, &c);
    for asg in 0..(1u64 << (2 * W)) {
        let x = (asg & ((1 << W) - 1)) as i64;
        let y = (asg >> W) as i64;
        assert_eq!(val(&m, &sum, asg), x + y);
        assert_eq!(val(&m, &dif, asg), x - y);
        assert_eq!(val(&m, &prod, asg), x * y);
        assert_eq!(val(&m, &na, asg), -x);
        assert_eq!(holds(&m, lt, asg), x < y);
        assert_eq!(holds(&m, le, asg), x <= y);
        assert_eq!(holds(&m, eq, asg), x == y);
        assert_eq!(val(&m, &sum_c, asg), x - 5);
        assert_eq!(holds(&m, lt_c, asg), x < -5);
    }
}

#[test]
fn divmod_by_constants_including_negatives() {
    let mut m = Manager::new();
    for _ in 0..W {
        m.new_var();
    }
    let a0 = operand(&mut m, 0);
    let shifted = bv::sub(&mut m, &a0, &bv::constant(8)); // range -8..7
    for c in [1i64, 2, 3, 5, 7, 16] {
        let (q, r) = bv::divmod_const(&mut m, &shifted, c);
        for asg in 0..(1u64 << W) {
            let x = asg as i64 - 8;
            assert_eq!(val(&m, &q, asg), x / c, "{} / {}", x, c);
            assert_eq!(val(&m, &r, asg), x.rem_euclid(c), "{} mod {}", x, c);
        }
    }
}

#[test]
fn unsigned_const_compare() {
    let mut m = Manager::new();
    for _ in 0..W {
        m.new_var();
    }
    let bits: Vec<Bdd> = (0..W as u32).map(|i| m.var(i)).collect();
    for c in 0..=20u64 {
        let f = bv::ult_const(&mut m, &bits, c);
        for asg in 0..(1u64 << W) {
            assert_eq!(holds(&m, f, asg), asg < c);
        }
    }
    let _ = TRUE;
}
