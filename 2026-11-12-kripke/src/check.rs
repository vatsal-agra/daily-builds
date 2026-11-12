//! Symbolic reachability, fair CTL model checking (Emerson–Lei), and witness / counterexample
//! construction (shortest paths and fair lassos).
//!
//! Garbage-collection discipline: BDD handles held in Rust locals are only safe across a GC if they are
//! pinned (`Manager::pin`) or passed as `extra` roots to `maybe_gc`. Every fixpoint below does both.

use crate::bdd::{Bdd, FALSE, TRUE};
use crate::model::Model;
use crate::temporal::Ctl;
use std::collections::HashMap;

#[derive(Clone, Debug, PartialEq)]
pub struct Step {
    pub state: Vec<(String, String)>,
    /// Input valuation used on the transition *leaving* this state (empty if the model has no inputs
    /// or this is the last state of a finite trace).
    pub inputs: Vec<(String, String)>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Trace {
    pub steps: Vec<Step>,
    /// For a lasso: index of the state the last step returns to.
    pub loop_start: Option<usize>,
}

#[derive(Clone, Debug, PartialEq)]
pub enum Verdict {
    Holds,
    Fails(Option<Trace>),
}

#[derive(Clone, Debug, Default)]
pub struct Stats {
    pub fixpoint_iterations: usize,
    pub images: usize,
}

pub struct Reach {
    pub set: Bdd,
    /// BFS frontiers: `layers[i]` = states first reached after exactly `i` steps.
    pub layers: Vec<Bdd>,
}

pub struct Checker<'a> {
    pub md: &'a mut Model,
    fair_states: Option<Bdd>,
    reach: Option<Reach>,
    pub stats: Stats,
}

impl<'a> Checker<'a> {
    pub fn new(md: &'a mut Model) -> Checker<'a> {
        Checker {
            md,
            fair_states: None,
            reach: None,
            stats: Stats::default(),
        }
    }

    fn neg(&mut self, f: Bdd) -> Bdd {
        let sp = self.md.space;
        self.md.m.diff(sp, f)
    }

    fn pre(&mut self, x: Bdd) -> Bdd {
        self.stats.images += 1;
        self.md.preimage(x)
    }

    // ------------------------------------------------------------------ reachability

    pub fn reach(&mut self) -> &Reach {
        if self.reach.is_none() {
            let init = self.md.init;
            self.md.m.pin(init);
            let mut layers = vec![init];
            let mut visited = init;
            let mut frontier = init;
            let mark = self.md.m.pin_mark();
            loop {
                // layers and visited must survive, as must the model constants (pinned in the model)
                let mut extra = layers.clone();
                extra.push(visited);
                extra.push(frontier);
                self.md.m.maybe_gc(&extra);
                self.stats.images += 1;
                self.stats.fixpoint_iterations += 1;
                let img = self.md.image(frontier);
                let new = self.md.m.diff(img, visited);
                if new == FALSE {
                    break;
                }
                visited = self.md.m.or(visited, new);
                layers.push(new);
                frontier = new;
            }
            self.md.m.pin_release(mark);
            for &l in &layers {
                self.md.m.pin(l);
            }
            self.md.m.pin(visited);
            self.reach = Some(Reach {
                set: visited,
                layers,
            });
        }
        self.reach.as_ref().unwrap()
    }

    /// Reachable states with no outgoing transition.
    pub fn deadlocks(&mut self) -> Bdd {
        let r = self.reach().set;
        let sp = self.md.space;
        let has_succ = self.pre(sp);
        self.md.m.diff(r, has_succ)
    }

    // ------------------------------------------------------------------ CTL fixpoints

    /// `E[f U g]` over the raw transition relation (no fairness).
    fn eu_raw(&mut self, f: Bdd, g: Bdd) -> Bdd {
        let mark = self.md.m.pin_mark();
        self.md.m.pin(f);
        self.md.m.pin(g);
        let sp = self.md.space;
        let mut y = self.md.m.and(g, sp);
        loop {
            self.md.m.maybe_gc(&[y]);
            self.stats.fixpoint_iterations += 1;
            let p = self.pre(y);
            let step = self.md.m.and(f, p);
            let ny = self.md.m.or(y, step);
            if ny == y {
                break;
            }
            y = ny;
        }
        self.md.m.pin_release(mark);
        y
    }

    /// Fair `EG f`: states from which a path stays in `f` forever and visits every fairness set
    /// infinitely often (Emerson–Lei greatest fixpoint).
    pub fn eg_fair(&mut self, f: Bdd, fairs: &[Bdd]) -> Bdd {
        let mark = self.md.m.pin_mark();
        self.md.m.pin(f);
        for &x in fairs {
            self.md.m.pin(x);
        }
        let sp = self.md.space;
        let mut z = self.md.m.and(f, sp);
        loop {
            self.md.m.maybe_gc(&[z]);
            self.stats.fixpoint_iterations += 1;
            let iter_mark = self.md.m.pin_mark();
            self.md.m.pin(z);
            let mut nz = z;
            if fairs.is_empty() {
                let p = self.pre(z);
                nz = self.md.m.and(nz, p);
            } else {
                for &fc in fairs {
                    let target = self.md.m.and(z, fc);
                    self.md.m.pin(target);
                    let u = self.eu_raw(f, target);
                    self.md.m.pin(u);
                    let p = self.pre(u);
                    nz = self.md.m.and(nz, p);
                    self.md.m.pin(nz);
                }
            }
            self.md.m.pin_release(iter_mark);
            if nz == z {
                break;
            }
            z = nz;
        }
        self.md.m.pin_release(mark);
        z
    }

    /// States that start at least one fair path (`EG_fair true`).
    pub fn fair(&mut self) -> Bdd {
        if let Some(f) = self.fair_states {
            return f;
        }
        let fairs = self.md.fair.clone();
        let sp = self.md.space;
        let z = self.eg_fair(sp, &fairs);
        self.md.m.pin(z);
        self.fair_states = Some(z);
        z
    }

    pub fn eg(&mut self, f: Bdd) -> Bdd {
        let fairs = self.md.fair.clone();
        self.eg_fair(f, &fairs)
    }

    pub fn ex(&mut self, f: Bdd) -> Bdd {
        let mark = self.md.m.pin_mark();
        self.md.m.pin(f);
        let fair = self.fair();
        let t = self.md.m.and(f, fair);
        let r = self.pre(t);
        self.md.m.pin_release(mark);
        r
    }

    pub fn eu(&mut self, f: Bdd, g: Bdd) -> Bdd {
        let mark = self.md.m.pin_mark();
        self.md.m.pin(f);
        self.md.m.pin(g);
        let fair = self.fair();
        let t = self.md.m.and(g, fair);
        let r = self.eu_raw(f, t);
        self.md.m.pin_release(mark);
        r
    }

    /// Evaluate a CTL formula to the set of states satisfying it (a subset of the state space).
    pub fn eval(&mut self, c: &Ctl<Bdd>) -> Bdd {
        let mark = self.md.m.pin_mark();
        let sp = self.md.space;
        let r = match c {
            Ctl::Atom(a) => self.md.m.and(*a, sp),
            Ctl::Not(x) => {
                let v = self.eval(x);
                self.neg(v)
            }
            Ctl::And(a, b) => {
                let x = self.eval(a);
                self.md.m.pin(x);
                let y = self.eval(b);
                self.md.m.and(x, y)
            }
            Ctl::Or(a, b) => {
                let x = self.eval(a);
                self.md.m.pin(x);
                let y = self.eval(b);
                self.md.m.or(x, y)
            }
            Ctl::Imp(a, b) => {
                let x = self.eval(a);
                self.md.m.pin(x);
                let y = self.eval(b);
                let nx = self.neg(x);
                self.md.m.or(nx, y)
            }
            Ctl::Iff(a, b) => {
                let x = self.eval(a);
                self.md.m.pin(x);
                let y = self.eval(b);
                let e = self.md.m.iff(x, y);
                self.md.m.and(e, sp)
            }
            Ctl::Xor(a, b) => {
                let x = self.eval(a);
                self.md.m.pin(x);
                let y = self.eval(b);
                self.md.m.xor(x, y)
            }
            Ctl::EX(a) => {
                let x = self.eval(a);
                self.ex(x)
            }
            Ctl::AX(a) => {
                let x = self.eval(a);
                let nx = self.neg(x);
                self.md.m.pin(nx);
                let e = self.ex(nx);
                self.neg(e)
            }
            Ctl::EF(a) => {
                let x = self.eval(a);
                self.eu(sp, x)
            }
            Ctl::AF(a) => {
                let x = self.eval(a);
                let nx = self.neg(x);
                let e = self.eg(nx);
                self.neg(e)
            }
            Ctl::EG(a) => {
                let x = self.eval(a);
                self.eg(x)
            }
            Ctl::AG(a) => {
                let x = self.eval(a);
                let nx = self.neg(x);
                self.md.m.pin(nx);
                let e = self.eu(sp, nx);
                self.neg(e)
            }
            Ctl::EU(a, b) => {
                let x = self.eval(a);
                self.md.m.pin(x);
                let y = self.eval(b);
                self.eu(x, y)
            }
            Ctl::AU(a, b) => {
                // A[f U g] = ¬E[¬g U (¬f ∧ ¬g)] ∧ ¬EG ¬g
                let x = self.eval(a);
                self.md.m.pin(x);
                let y = self.eval(b);
                self.md.m.pin(y);
                let ng = self.neg(y);
                self.md.m.pin(ng);
                let nf = self.neg(x);
                let bad = self.md.m.and(nf, ng);
                self.md.m.pin(bad);
                let e1 = self.eu(ng, bad);
                self.md.m.pin(e1);
                let e2 = self.eg(ng);
                let either = self.md.m.or(e1, e2);
                self.neg(either)
            }
        };
        self.md.m.pin_release(mark);
        r
    }

    // ------------------------------------------------------------------ states and traces

    pub fn pick_state(&mut self, set: Bdd) -> Bdd {
        let vars = self.md.cur_vars.clone();
        let bits = self
            .md
            .m
            .pick_one(set, &vars)
            .expect("pick_state on an empty set");
        let lits: Vec<(u32, bool)> = vars.iter().cloned().zip(bits).collect();
        let c = self.md.m.literals(&lits);
        self.md.m.pin(c)
    }

    fn cube_bits(&self, cube: Bdd) -> HashMap<u32, bool> {
        let vars = self.md.cur_vars.clone();
        let bits = self.md.m.pick_one(cube, &vars).expect("empty cube");
        vars.into_iter().zip(bits).collect()
    }

    /// Shortest path (list of state cubes) from the single state `from` to any state in `to`, moving
    /// only through states in `within`. With `min_steps == 1` the path must have at least one step
    /// (used to close loops).
    pub fn shortest_path(
        &mut self,
        from: Bdd,
        to: Bdd,
        within: Bdd,
        min_steps: usize,
    ) -> Option<Vec<Bdd>> {
        let mark = self.md.m.pin_mark();
        self.md.m.pin(from);
        self.md.m.pin(to);
        self.md.m.pin(within);
        let mut layers: Vec<Bdd> = vec![from];
        let mut visited;
        if min_steps == 0 {
            visited = from;
            let hit = self.md.m.and(from, to);
            if hit != FALSE {
                self.md.m.pin_release(mark);
                return Some(vec![from]);
            }
        } else {
            let img = self.md.image(from);
            let l1 = self.md.m.and(img, within);
            if l1 == FALSE {
                self.md.m.pin_release(mark);
                return None;
            }
            layers.push(l1);
            visited = l1;
            let hit = self.md.m.and(l1, to);
            if hit != FALSE {
                return Some(self.backtrack(layers, hit, mark));
            }
        }
        loop {
            let last = *layers.last().unwrap();
            let mut extra = layers.clone();
            extra.push(visited);
            self.md.m.maybe_gc(&extra);
            self.stats.images += 1;
            let img = self.md.image(last);
            let inw = self.md.m.and(img, within);
            let new = self.md.m.diff(inw, visited);
            if new == FALSE {
                self.md.m.pin_release(mark);
                return None;
            }
            visited = self.md.m.or(visited, new);
            layers.push(new);
            let hit = self.md.m.and(new, to);
            if hit != FALSE {
                return Some(self.backtrack(layers, hit, mark));
            }
        }
    }

    fn backtrack(&mut self, layers: Vec<Bdd>, hit: Bdd, mark: usize) -> Vec<Bdd> {
        for &l in &layers {
            self.md.m.pin(l);
        }
        let k = layers.len() - 1;
        let mut path = vec![FALSE; k + 1];
        path[k] = self.pick_state(hit);
        for i in (0..k).rev() {
            let p = self.pre(path[i + 1]);
            let cand = self.md.m.and(p, layers[i]);
            path[i] = self.pick_state(cand);
        }
        // keep only the (tiny) cubes alive for the caller
        let cubes = path.clone();
        self.md.m.pin_release(mark);
        for &c in &cubes {
            self.md.m.pin(c);
        }
        cubes
    }

    /// Turn a list of state cubes into a printable trace, choosing concrete input values.
    pub fn to_trace(&mut self, cubes: &[Bdd], loop_start: Option<usize>) -> Trace {
        let mut steps = Vec::new();
        let next_map = self.md.to_next_map().clone();
        let inp_vars = self.md.inp_vars.clone();
        for (i, &c) in cubes.iter().enumerate() {
            let bits = self.cube_bits(c);
            let state = self.md.decode_state(&bits);
            let succ = if i + 1 < cubes.len() {
                Some(cubes[i + 1])
            } else {
                loop_start.map(|l| cubes[l])
            };
            let mut inputs = vec![];
            if let (Some(s), false) = (succ, inp_vars.is_empty()) {
                let sn = self.md.m.rename(s, &next_map);
                let t = self.md.m.and(self.md.trans, c);
                let t = self.md.m.and(t, sn);
                if let Some(vals) = self.md.m.pick_one(t, &inp_vars) {
                    let map: HashMap<u32, bool> = inp_vars.iter().cloned().zip(vals).collect();
                    inputs = self.md.decode_inputs(&map);
                }
            }
            steps.push(Step { state, inputs });
        }
        Trace { steps, loop_start }
    }

    // ------------------------------------------------------------------ invariants

    /// Check `AG p`-style invariant by BFS; returns a shortest counterexample.
    pub fn check_invariant(&mut self, p: Bdd) -> Verdict {
        self.md.m.pin(p);
        let _ = self.reach();
        let layers: Vec<Bdd> = self.reach.as_ref().unwrap().layers.clone();
        let np = self.neg(p);
        self.md.m.pin(np);
        for (i, &l) in layers.iter().enumerate() {
            let bad = self.md.m.and(l, np);
            if bad != FALSE {
                let mark = self.md.m.pin_mark();
                let mut path = vec![FALSE; i + 1];
                path[i] = self.pick_state(bad);
                for j in (0..i).rev() {
                    let pr = self.pre(path[j + 1]);
                    let cand = self.md.m.and(pr, layers[j]);
                    path[j] = self.pick_state(cand);
                }
                let tr = self.to_trace(&path, None);
                self.md.m.pin_release(mark);
                return Verdict::Fails(Some(tr));
            }
        }
        Verdict::Holds
    }

    // ------------------------------------------------------------------ CTL verdicts & witnesses

    pub fn check_ctl(&mut self, c: &Ctl<Bdd>) -> Verdict {
        let sat = self.eval(c);
        self.md.m.pin(sat);
        let nsat = self.neg(sat);
        let init = self.md.init;
        let bad = self.md.m.and(init, nsat);
        if bad == FALSE {
            return Verdict::Holds;
        }
        let s = self.pick_state(bad);
        let neg = negate(c);
        let mark = self.md.m.pin_mark();
        let (cubes, lp) = self.witness(&neg, s);
        let tr = self.to_trace(&cubes, lp);
        self.md.m.pin_release(mark);
        Verdict::Fails(Some(tr))
    }

    /// Build a path (state cubes + optional loop start) demonstrating `psi` from state `s`.
    /// Only existential structure can be demonstrated; anything else yields the single state.
    pub fn witness(&mut self, psi: &Ctl<Bdd>, s: Bdd) -> (Vec<Bdd>, Option<usize>) {
        let sp = self.md.space;
        match psi {
            Ctl::EF(f) | Ctl::EU(_, f) => {
                let within = match psi {
                    Ctl::EU(g, _) => {
                        let gs = self.eval(g);
                        self.md.m.pin(gs);
                        let fs = self.eval(f);
                        self.md.m.or(gs, fs)
                    }
                    _ => sp,
                };
                self.md.m.pin(within);
                let fs = self.eval(f);
                let fair = self.fair();
                let target = self.md.m.and(fs, fair);
                self.md.m.pin(target);
                match self.shortest_path(s, target, within, 0) {
                    Some(path) => {
                        let last = *path.last().unwrap();
                        let tail = self.witness(f, last);
                        compose(path, tail)
                    }
                    None => (vec![s], None),
                }
            }
            Ctl::EX(f) => {
                let fs = self.eval(f);
                let fair = self.fair();
                let target = self.md.m.and(fs, fair);
                let img = self.md.image(s);
                let cand = self.md.m.and(img, target);
                if cand == FALSE {
                    return (vec![s], None);
                }
                let t = self.pick_state(cand);
                let tail = self.witness(f, t);
                compose(vec![s, t], tail)
            }
            Ctl::EG(f) => {
                let fs = self.eval(f);
                self.md.m.pin(fs);
                self.lasso(s, fs)
            }
            Ctl::And(a, b) => {
                if a.is_pathy() {
                    self.witness(a, s)
                } else if b.is_pathy() {
                    self.witness(b, s)
                } else {
                    (vec![s], None)
                }
            }
            Ctl::Or(a, b) => {
                let sa = self.eval(a);
                let hit = self.md.m.and(sa, s);
                if hit != FALSE {
                    self.witness(a, s)
                } else {
                    self.witness(b, s)
                }
            }
            _ => (vec![s], None),
        }
    }

    /// A fair lasso (prefix + cycle) from `s` staying inside `f` forever.
    pub fn lasso(&mut self, s: Bdd, f: Bdd) -> (Vec<Bdd>, Option<usize>) {
        let z = self.eg(f);
        self.md.m.pin(z);
        let fairs = self.md.fair.clone();
        let mut prefix: Vec<Bdd> = vec![];
        let mut start = s;
        for _ in 0..100_000 {
            let mut path = vec![start];
            let mut last = start;
            for &fc in &fairs {
                let target = self.md.m.and(z, fc);
                self.md.m.pin(target);
                let p = self.shortest_path(last, target, z, 0).expect(
                    "fair lasso: a fairness set must be reachable inside EG (fixpoint invariant)",
                );
                path.extend_from_slice(&p[1..]);
                last = *path.last().unwrap();
            }
            if let Some(c) = self.shortest_path(last, start, z, 1) {
                let mut full = prefix.clone();
                full.extend_from_slice(&path);
                full.extend_from_slice(&c[1..c.len() - 1]);
                return (full, Some(prefix.len()));
            }
            // could not close the loop: the end of this walk lies in a later strongly connected component
            if last == start {
                let img = self.md.image(last);
                let cand = self.md.m.and(img, z);
                let nxt = self.pick_state(cand);
                prefix.push(last);
                start = nxt;
            } else {
                prefix.extend_from_slice(&path[..path.len() - 1]);
                start = last;
            }
        }
        panic!("lasso construction did not terminate");
    }
}

fn compose(mut head: Vec<Bdd>, tail: (Vec<Bdd>, Option<usize>)) -> (Vec<Bdd>, Option<usize>) {
    let offset = head.len() - 1;
    head.extend_from_slice(&tail.0[1..]);
    (head, tail.1.map(|l| l + offset))
}

/// Push a negation through the top-level structure so that existential witnesses become visible.
pub fn negate(c: &Ctl<Bdd>) -> Ctl<Bdd> {
    use Ctl::*;
    let bx = Box::new;
    match c {
        Not(x) => (**x).clone(),
        Imp(a, b) => And(a.clone(), bx(negate(b))),
        Or(a, b) => And(bx(negate(a)), bx(negate(b))),
        And(a, b) => Or(bx(negate(a)), bx(negate(b))),
        AG(f) => EF(bx(negate(f))),
        AF(f) => EG(bx(negate(f))),
        AX(f) => EX(bx(negate(f))),
        AU(f, g) => {
            let ng = negate(g);
            Or(
                bx(EU(bx(ng.clone()), bx(And(bx(negate(f)), bx(ng.clone()))))),
                bx(EG(bx(ng))),
            )
        }
        other => Not(bx(other.clone())),
    }
}

impl crate::bdd::Manager {
    /// Drop the most recent pin (used inside fixpoint loops).
    pub fn pins_pop(&mut self) {
        let n = self.pin_mark();
        if n > 0 {
            self.pin_release(n - 1);
        }
    }
}

#[allow(dead_code)]
const _: Bdd = TRUE;
