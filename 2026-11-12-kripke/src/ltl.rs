//! LTL model checking by tableau product (Clarke–Grumberg–Hamaguchi style).
//!
//! To check `φ` we search for a fair path satisfying `ψ = ¬φ`. `ψ` is put in negation normal form and
//! every temporal subformula is unrolled with the expansion laws
//!
//! ```text
//!   X g     = y(g)                    g U h = h ∨ (g ∧ y(g U h))
//!   F g     = g ∨ y(F g)              g R h = h ∧ (g ∨ y(g R h))
//!   G g     = g ∧ y(G g)
//! ```
//!
//! where each `y(φ')` is a fresh Boolean state variable constrained by `TRANS y ↔ next([[φ']])`.
//! Eventualities (`U`, `F`) add a fairness constraint `¬[[φ']] ∨ [[goal]]`, so the weak unrolling cannot
//! postpone them forever. `φ` holds iff the product has no fair path from `init ∧ [[ψ]]`.

use crate::bdd::{Bdd, FALSE};
use crate::check::{Checker, Stats, Verdict};
use crate::lang::*;
use crate::model::Model;
use crate::temporal::{lower_ltl, Ltl};
use std::collections::HashMap;

fn b<T>(x: T) -> Box<T> {
    Box::new(x)
}

/// Negation normal form: `Not` only directly above atoms; `Imp`/`Iff`/`Xor` eliminated.
pub fn nnf(f: &Ltl<Bdd>, neg: bool) -> Ltl<Bdd> {
    use Ltl::*;
    match (f, neg) {
        (Atom(_), false) => f.clone(),
        (Atom(_), true) => Not(b(f.clone())),
        (Not(x), n) => nnf(x, !n),
        (And(x, y), false) => And(b(nnf(x, false)), b(nnf(y, false))),
        (And(x, y), true) => Or(b(nnf(x, true)), b(nnf(y, true))),
        (Or(x, y), false) => Or(b(nnf(x, false)), b(nnf(y, false))),
        (Or(x, y), true) => And(b(nnf(x, true)), b(nnf(y, true))),
        (Imp(x, y), false) => Or(b(nnf(x, true)), b(nnf(y, false))),
        (Imp(x, y), true) => And(b(nnf(x, false)), b(nnf(y, true))),
        (Iff(x, y), n) => {
            // x <-> y  ==  (x & y) | (!x & !y)
            let eq = Or(b(And(x.clone(), y.clone())), b(And(b(Not(x.clone())), b(Not(y.clone())))));
            nnf(&eq, n)
        }
        (Xor(x, y), n) => {
            let ne = Or(b(And(x.clone(), b(Not(y.clone())))), b(And(b(Not(x.clone())), y.clone())));
            nnf(&ne, n)
        }
        (X(x), n) => X(b(nnf(x, n))),
        (F(x), false) => F(b(nnf(x, false))),
        (F(x), true) => G(b(nnf(x, true))),
        (G(x), false) => G(b(nnf(x, false))),
        (G(x), true) => F(b(nnf(x, true))),
        (U(x, y), false) => U(b(nnf(x, false)), b(nnf(y, false))),
        (U(x, y), true) => R(b(nnf(x, true)), b(nnf(y, true))),
        (R(x, y), false) => R(b(nnf(x, false)), b(nnf(y, false))),
        (R(x, y), true) => U(b(nnf(x, true)), b(nnf(y, true))),
    }
}

struct Tableau<'a> {
    md: &'a mut Model,
    memo: HashMap<Ltl<Bdd>, Bdd>,
    aux: HashMap<Ltl<Bdd>, u32>,
    order: Vec<Ltl<Bdd>>,
    eventualities: Vec<Ltl<Bdd>>,
}

impl<'a> Tableau<'a> {
    fn y(&mut self, f: &Ltl<Bdd>) -> Bdd {
        if let Some(&v) = self.aux.get(f) {
            return self.md.m.var(v);
        }
        let (c, _n) = self.md.add_aux_var();
        self.aux.insert(f.clone(), c);
        self.order.push(f.clone());
        self.md.m.var(c)
    }

    fn val(&mut self, f: &Ltl<Bdd>) -> Bdd {
        if let Some(&v) = self.memo.get(f) {
            return v;
        }
        let r = match f {
            Ltl::Atom(a) => *a,
            Ltl::Not(x) => match &**x {
                Ltl::Atom(a) => self.md.m.not(*a),
                _ => unreachable!("not in NNF"),
            },
            Ltl::And(x, y) => {
                let (p, q) = (self.val(x), self.val(y));
                self.md.m.and(p, q)
            }
            Ltl::Or(x, y) => {
                let (p, q) = (self.val(x), self.val(y));
                self.md.m.or(p, q)
            }
            Ltl::X(x) => self.y(x),
            Ltl::U(g, h) => {
                self.note_eventuality(f);
                let (pg, ph) = (self.val(g), self.val(h));
                let yy = self.y(f);
                let t = self.md.m.and(pg, yy);
                self.md.m.or(ph, t)
            }
            Ltl::F(g) => {
                self.note_eventuality(f);
                let pg = self.val(g);
                let yy = self.y(f);
                self.md.m.or(pg, yy)
            }
            Ltl::R(g, h) => {
                let (pg, ph) = (self.val(g), self.val(h));
                let yy = self.y(f);
                let t = self.md.m.or(pg, yy);
                self.md.m.and(ph, t)
            }
            Ltl::G(g) => {
                let pg = self.val(g);
                let yy = self.y(f);
                self.md.m.and(pg, yy)
            }
            Ltl::Imp(..) | Ltl::Iff(..) | Ltl::Xor(..) => unreachable!("not in NNF"),
        };
        self.memo.insert(f.clone(), r);
        r
    }

    fn note_eventuality(&mut self, f: &Ltl<Bdd>) {
        if !self.eventualities.contains(f) {
            self.eventualities.push(f.clone());
        }
    }
}

/// Number of auxiliary tableau variables used (for reporting) and the verdict.
pub struct LtlResult {
    pub verdict: Verdict,
    pub stats: Stats,
    pub aux_vars: usize,
}

pub fn check(prog: &Program, expr: &Expr, lax: bool) -> Res<LtlResult> {
    let mut md = Model::compile(prog.clone(), lax)?;
    let phi = {
        let md_ref = &mut md;
        lower_ltl(expr, &mut |e| {
            let a = md_ref.atom(e)?;
            Ok(md_ref.m.pin(a))
        })?
    };
    let psi = nnf(&phi, true);
    let base_trans = md.trans;
    let base_init = md.init;
    let mut tb = Tableau { md: &mut md, memo: HashMap::new(), aux: HashMap::new(), order: vec![], eventualities: vec![] };
    let top = tb.val(&psi);
    let mut constraints = vec![];
    let mut i = 0;
    while i < tb.order.len() {
        let phi_i = tb.order[i].clone();
        let v = tb.val(&phi_i);
        let map = tb.md.to_next_map().clone();
        let vn = tb.md.m.rename(v, &map);
        let yc = tb.aux[&phi_i];
        let yv = tb.md.m.var(yc);
        let c = tb.md.m.iff(yv, vn);
        constraints.push(c);
        i += 1;
    }
    let mut fairs = vec![];
    for ev in tb.eventualities.clone() {
        let (node, goal) = match &ev {
            Ltl::U(_, h) => (tb.val(&ev), tb.val(h)),
            Ltl::F(g) => (tb.val(&ev), tb.val(g)),
            _ => unreachable!(),
        };
        let nn = tb.md.m.not(node);
        fairs.push(tb.md.m.or(nn, goal));
    }
    let aux_vars = tb.order.len();
    let mut trans = base_trans;
    for c in constraints {
        trans = tb.md.m.and(trans, c);
    }
    let init = tb.md.m.and(base_init, top);
    md.finish_extension(init, trans, fairs);
    let mut ck = Checker::new(&mut md);
    let fair = ck.fair();
    let init = ck.md.init;
    let bad = ck.md.m.and(init, fair);
    let verdict = if bad == FALSE {
        Verdict::Holds
    } else {
        let s = ck.pick_state(bad);
        let sp = ck.md.space;
        let (cubes, lp) = ck.lasso(s, sp);
        let tr = ck.to_trace(&cubes, lp);
        Verdict::Fails(Some(tr))
    };
    Ok(LtlResult { verdict, stats: ck.stats.clone(), aux_vars })
}
