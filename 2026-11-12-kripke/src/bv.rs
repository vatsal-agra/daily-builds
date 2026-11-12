//! Signed (two's complement) bit-vector circuits over BDDs, used for integer ranges too large to
//! tabulate (e.g. a 16-bit counter). Bits are least-significant first; the top bit is the sign.

use crate::bdd::{Bdd, Manager, FALSE, TRUE};

pub const MAX_WIDTH: usize = 64;

#[derive(Clone, Debug)]
pub struct Bv {
    pub bits: Vec<Bdd>,
}

impl Bv {
    pub fn width(&self) -> usize {
        self.bits.len()
    }

    pub fn sign(&self) -> Bdd {
        *self.bits.last().unwrap()
    }
}

/// Minimal-width two's complement constant.
pub fn constant(n: i64) -> Bv {
    let mut w = 1;
    while w < 64 && !(-(1i64 << (w - 1))..(1i64 << (w - 1))).contains(&n) {
        w += 1;
    }
    Bv { bits: (0..w).map(|i| if (n >> i) & 1 == 1 { TRUE } else { FALSE }).collect() }
}

pub fn extend(a: &Bv, w: usize) -> Bv {
    let mut bits = a.bits.clone();
    let s = a.sign();
    while bits.len() < w {
        bits.push(s);
    }
    Bv { bits }
}

/// Unsigned code bits as a non-negative signed value.
pub fn from_unsigned(bits: &[Bdd]) -> Bv {
    let mut b = bits.to_vec();
    b.push(FALSE);
    Bv { bits: b }
}

fn full_add(m: &mut Manager, a: Bdd, b: Bdd, c: Bdd) -> (Bdd, Bdd) {
    let ab = m.xor(a, b);
    let sum = m.xor(ab, c);
    let t1 = m.and(a, b);
    let t2 = m.and(ab, c);
    (sum, m.or(t1, t2))
}

/// `a + b` (+ carry-in), result one bit wider than the wider operand so it cannot overflow.
fn add_carry(m: &mut Manager, a: &Bv, b: &Bv, cin: Bdd) -> Bv {
    let w = a.width().max(b.width()) + 1;
    let (a, b) = (extend(a, w), extend(b, w));
    let mut carry = cin;
    let mut bits = Vec::with_capacity(w);
    for i in 0..w {
        let (s, c) = full_add(m, a.bits[i], b.bits[i], carry);
        bits.push(s);
        carry = c;
    }
    Bv { bits }
}

pub fn add(m: &mut Manager, a: &Bv, b: &Bv) -> Bv {
    trim(add_carry(m, a, b, FALSE))
}

pub fn neg(m: &mut Manager, a: &Bv) -> Bv {
    let w = a.width() + 1;
    let e = extend(a, w);
    let inv = Bv { bits: e.bits.iter().map(|&x| m.not(x)).collect() };
    trim(add_carry(m, &inv, &constant(0), TRUE))
}

pub fn sub(m: &mut Manager, a: &Bv, b: &Bv) -> Bv {
    let w = a.width().max(b.width()) + 1;
    let e = extend(b, w);
    let inv = Bv { bits: e.bits.iter().map(|&x| m.not(x)).collect() };
    trim(add_carry(m, &extend(a, w), &inv, TRUE))
}

/// Drop redundant sign bits (keeps the circuit narrow).
fn trim(mut a: Bv) -> Bv {
    while a.bits.len() > 1 && a.bits[a.bits.len() - 1] == a.bits[a.bits.len() - 2] {
        a.bits.pop();
    }
    a
}

pub fn mul(m: &mut Manager, a: &Bv, b: &Bv) -> Bv {
    let w = (a.width() + b.width()).min(MAX_WIDTH + 1);
    let (a, b) = (extend(a, w), extend(b, w));
    let mut acc = Bv { bits: vec![FALSE; w] };
    for i in 0..w {
        // partial product: (a << i) & b_i, truncated to w bits
        let mut pp = vec![FALSE; w];
        for j in i..w {
            pp[j] = m.and(a.bits[j - i], b.bits[i]);
        }
        let mut carry = FALSE;
        let mut bits = Vec::with_capacity(w);
        for k in 0..w {
            let (s, c) = full_add(m, acc.bits[k], pp[k], carry);
            bits.push(s);
            carry = c;
        }
        acc = Bv { bits };
    }
    trim(acc)
}

pub fn eq(m: &mut Manager, a: &Bv, b: &Bv) -> Bdd {
    let w = a.width().max(b.width());
    let (a, b) = (extend(a, w), extend(b, w));
    let mut r = TRUE;
    for i in 0..w {
        let e = m.iff(a.bits[i], b.bits[i]);
        r = m.and(r, e);
    }
    r
}

/// `a < b` (signed).
pub fn lt(m: &mut Manager, a: &Bv, b: &Bv) -> Bdd {
    let d = sub(m, a, b);
    d.sign()
}

pub fn le(m: &mut Manager, a: &Bv, b: &Bv) -> Bdd {
    let g = lt(m, b, a);
    m.not(g)
}

/// Pick `then` where `c` holds and `els` elsewhere.
pub fn ite(m: &mut Manager, c: Bdd, t: &Bv, e: &Bv) -> Bv {
    let w = t.width().max(e.width());
    let (t, e) = (extend(t, w), extend(e, w));
    Bv { bits: (0..w).map(|i| m.ite(c, t.bits[i], e.bits[i])).collect() }
}

/// Truncating division and Euclidean remainder (`0 <= r < c`) by a positive constant.
pub fn divmod_const(m: &mut Manager, a: &Bv, c: i64) -> (Bv, Bv) {
    assert!(c > 0);
    let negative = a.sign();
    let na = neg(m, a);
    let abs = ite(m, negative, &na, a);
    let ubits: Vec<Bdd> = {
        // |a| as unsigned bits (sign bit of |a| is zero except for the impossible minimum)
        let mut b = abs.bits.clone();
        b.pop();
        if b.is_empty() {
            b.push(FALSE);
        }
        b
    };
    let cb = constant(c);
    let rw = cb.width() + 1;
    let mut rem = Bv { bits: vec![FALSE; rw] };
    let mut qbits = vec![FALSE; ubits.len()];
    for i in (0..ubits.len()).rev() {
        // rem = (rem << 1) | bit
        let mut bits = vec![ubits[i]];
        bits.extend_from_slice(&rem.bits[..rw - 1]);
        let shifted = Bv { bits };
        let ge = le(m, &cb, &shifted);
        let diff = sub(m, &shifted, &cb);
        let chosen = ite(m, ge, &diff, &shifted);
        rem = extend(&chosen, rw);
        rem.bits.truncate(rw);
        qbits[i] = ge;
    }
    let q_abs = from_unsigned(&qbits);
    let nq = neg(m, &q_abs);
    let quot = ite(m, negative, &nq, &q_abs);
    // remainder of |a|; for negative a with a nonzero remainder, Euclid wants c - r
    let r_abs = from_unsigned(&rem.bits[..rw - 1]);
    let nonzero = {
        let z = eq(m, &r_abs, &constant(0));
        m.not(z)
    };
    let flip = m.and(negative, nonzero);
    let c_minus_r = sub(m, &cb, &r_abs);
    let rem_fixed = ite(m, flip, &c_minus_r, &r_abs);
    (trim(quot), trim(rem_fixed))
}

/// Unsigned `bits < c`.
pub fn ult_const(m: &mut Manager, bits: &[Bdd], c: u64) -> Bdd {
    if bits.len() < 64 && c >= (1u64 << bits.len()) {
        return TRUE;
    }
    let mut lt = FALSE;
    let mut eq = TRUE;
    for i in (0..bits.len()).rev() {
        let cb = (c >> i) & 1 == 1;
        let nx = m.not(bits[i]);
        if cb {
            let t = m.and(eq, nx);
            lt = m.or(lt, t);
            eq = m.and(eq, bits[i]);
        } else {
            eq = m.and(eq, nx);
        }
    }
    lt
}
