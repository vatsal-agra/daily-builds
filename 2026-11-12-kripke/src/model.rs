//! Compile a parsed `Program` into a symbolic transition system over BDDs.
//!
//! Values of integer / enum / boolean-set expressions are *guarded value tables*:
//! `[(value, guard)]` where `guard` is a BDD over state variables saying when the expression can take
//! that value. Tables may overlap (union semantics), which is exactly how `{a, b}` sets and
//! nondeterministic assignments are represented.

use crate::bdd::{Bdd, Manager, FALSE, TRUE};
use crate::bv::{self, Bv};
use crate::lang::*;
use std::collections::{BTreeMap, HashMap};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub enum Val {
    B(bool),
    I(i64),
    S(usize),
}

#[derive(Clone, Debug)]
pub struct VarInfo {
    pub name: String,
    pub ty: Ty,
    pub input: bool,
    /// BDD variables of the current-state bits, least significant first.
    pub cur: Vec<u32>,
    /// BDD variables of the next-state bits (empty for inputs).
    pub nxt: Vec<u32>,
    pub size: usize,
}

#[derive(Clone, Debug)]
enum V {
    Bool(Bdd),
    Tab(Vec<(Val, Bdd)>),
    /// Integer alternatives as bit-vectors (union semantics, like `Tab`); used for large ranges.
    Bv(Vec<(Bv, Bdd)>),
}

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Ctx {
    /// Plain state predicate: no inputs, no `next`.
    State,
    /// Transition context: inputs and `next(..)` allowed.
    Trans,
}

#[derive(Clone, Copy)]
struct Mode {
    next: bool,
    ctx: Ctx,
}

const MAX_TAB: usize = 1 << 12;
const MAX_ALT_PAIRS: usize = 256;
const MAX_PAIRS: usize = 1 << 17;

pub struct Model {
    pub m: Manager,
    pub prog: Program,
    pub vars: Vec<VarInfo>,
    pub syms: Vec<String>,
    var_ix: HashMap<String, usize>,
    sym_ix: HashMap<String, usize>,
    defines: HashMap<String, Expr>,
    expanding: Vec<String>,
    pub lax_ranges: bool,
    /// Conjunction of every variable's legal-code constraint (current, next and input copies).
    dom_all: Bdd,
    // compiled parts
    pub init: Bdd,
    pub trans: Bdd,
    /// State constraint (domains ∧ INVAR). Holds on both ends of every transition.
    pub space: Bdd,
    pub fair: Vec<Bdd>,
    pub cur_vars: Vec<u32>,
    pub nxt_vars: Vec<u32>,
    pub inp_vars: Vec<u32>,
    pub cur_cube: Bdd,
    pub nxt_cube: Bdd,
    pub inp_cube: Bdd,
    pub inp_nxt_cube: Bdd,
    to_next: HashMap<u32, u32>,
    to_cur: HashMap<u32, u32>,
    /// Weak-spot warnings collected during compilation (e.g. unused definitions).
    pub warnings: Vec<String>,
}

fn bits_for(n: usize) -> usize {
    let mut b = 1;
    while (1usize << b) < n {
        b += 1;
    }
    b
}

fn edit_distance(a: &str, b: &str) -> usize {
    let a: Vec<char> = a.chars().collect();
    let b: Vec<char> = b.chars().collect();
    let mut prev: Vec<usize> = (0..=b.len()).collect();
    for i in 1..=a.len() {
        let mut cur = vec![i];
        for j in 1..=b.len() {
            let c = if a[i - 1] == b[j - 1] { 0 } else { 1 };
            cur.push((prev[j] + 1).min(cur[j - 1] + 1).min(prev[j - 1] + c));
        }
        prev = cur;
    }
    prev[b.len()]
}

impl Model {
    pub fn compile(prog: Program, lax_ranges: bool) -> Res<Model> {
        let mut m = Manager::new();
        let mut vars: Vec<VarInfo> = Vec::new();
        let mut var_ix = HashMap::new();
        let mut syms: Vec<String> = Vec::new();
        let mut sym_ix: HashMap<String, usize> = HashMap::new();
        let mut cur_vars = vec![];
        let mut nxt_vars = vec![];
        let mut inp_vars = vec![];
        let mut to_next = HashMap::new();
        let mut to_cur = HashMap::new();
        for d in &prog.vars {
            if var_ix.contains_key(&d.name) {
                return Err(Error::new(d.pos, format!("variable '{}' declared twice", d.name)));
            }
            let size = match &d.ty {
                Ty::Bool => 2,
                Ty::Range(lo, hi) => (hi - lo + 1) as usize,
                Ty::Enum(names) => {
                    for n in names {
                        if !sym_ix.contains_key(n) {
                            sym_ix.insert(n.clone(), syms.len());
                            syms.push(n.clone());
                        }
                    }
                    names.len()
                }
            };
            let nb = if d.ty == Ty::Bool { 1 } else { bits_for(size) };
            let mut cur = vec![];
            let mut nxt = vec![];
            for _ in 0..nb {
                let c = m.new_var();
                cur.push(c);
                if d.input {
                    inp_vars.push(c);
                } else {
                    let n = m.new_var();
                    nxt.push(n);
                    cur_vars.push(c);
                    nxt_vars.push(n);
                    to_next.insert(c, n);
                    to_cur.insert(n, c);
                }
            }
            var_ix.insert(d.name.clone(), vars.len());
            vars.push(VarInfo { name: d.name.clone(), ty: d.ty.clone(), input: d.input, cur, nxt, size });
        }
        for (n, _, pos) in &prog.defines {
            if var_ix.contains_key(n) {
                return Err(Error::new(*pos, format!("'{}' is both a variable and a definition", n)));
            }
        }
        let mut defines = HashMap::new();
        for (n, e, pos) in &prog.defines {
            if defines.insert(n.clone(), e.clone()).is_some() {
                return Err(Error::new(*pos, format!("definition '{}' declared twice", n)));
            }
            if sym_ix.contains_key(n) {
                return Err(Error::new(*pos, format!("'{}' is both an enum value and a definition", n)));
            }
        }
        for n in var_ix.keys() {
            if sym_ix.contains_key(n) {
                let pos = prog.vars[var_ix[n]].pos;
                return Err(Error::new(pos, format!("'{}' is both a variable and an enum value", n)));
            }
        }
        let cur_cube = m.cube(&cur_vars);
        let nxt_cube = m.cube(&nxt_vars);
        let inp_cube = m.cube(&inp_vars);
        let inp_nxt_cube = {
            let mut a = nxt_vars.clone();
            a.extend(&inp_vars);
            m.cube(&a)
        };
        let mut model = Model {
            m,
            prog: prog.clone(),
            vars,
            syms,
            var_ix,
            sym_ix,
            defines,
            expanding: vec![],
            lax_ranges,
            dom_all: TRUE,
            init: TRUE,
            trans: TRUE,
            space: TRUE,
            fair: vec![],
            cur_vars,
            nxt_vars,
            inp_vars,
            cur_cube,
            nxt_cube,
            inp_cube,
            inp_nxt_cube,
            to_next,
            to_cur,
            warnings: vec![],
        };
        let mut dom = TRUE;
        for vi in 0..model.vars.len() {
            let d = model.domain(vi, false);
            dom = model.m.and(dom, d);
            if !model.vars[vi].input {
                let dn = model.domain(vi, true);
                dom = model.m.and(dom, dn);
            }
        }
        model.dom_all = dom;
        model.m.pin(dom);
        model.build(&prog)?;
        Ok(model)
    }

    // ------------------------------------------------------------------ variable plumbing

    pub fn var_index(&self, name: &str) -> Option<usize> {
        self.var_ix.get(name).copied()
    }

    fn code_bdd(&mut self, bits: &[u32], code: usize) -> Bdd {
        let lits: Vec<(u32, bool)> = bits.iter().enumerate().map(|(i, &b)| (b, (code >> i) & 1 == 1)).collect();
        self.m.literals(&lits)
    }

    /// BDD of "the variable holds a code that is a legal value".
    fn domain(&mut self, vi: usize, next: bool) -> Bdd {
        let v = self.vars[vi].clone();
        let bits = if next { &v.nxt } else { &v.cur };
        if v.ty == Ty::Bool || v.size == 1usize << bits.len() {
            return TRUE;
        }
        let nodes: Vec<Bdd> = bits.iter().map(|&b| self.m.var(b)).collect();
        bv::ult_const(&mut self.m, &nodes, v.size as u64)
    }

    fn val_of_code(&self, vi: usize, code: usize) -> Val {
        match &self.vars[vi].ty {
            Ty::Bool => Val::B(code == 1),
            Ty::Range(lo, _) => Val::I(lo + code as i64),
            Ty::Enum(names) => Val::S(self.sym_ix[&names[code]]),
        }
    }

    /// Code of `val` in variable `vi`, if representable.
    fn code_of_val(&self, vi: usize, val: Val) -> Option<usize> {
        match (&self.vars[vi].ty, val) {
            (Ty::Bool, Val::B(b)) => Some(b as usize),
            (Ty::Range(lo, hi), Val::I(n)) if n >= *lo && n <= *hi => Some((n - lo) as usize),
            (Ty::Enum(names), Val::S(s)) => names.iter().position(|n| *n == self.syms[s]),
            _ => None,
        }
    }

    pub fn val_str(&self, v: Val) -> String {
        match v {
            Val::B(b) => if b { "TRUE" } else { "FALSE" }.into(),
            Val::I(n) => n.to_string(),
            Val::S(s) => self.syms[s].clone(),
        }
    }

    pub fn ty_str(&self, vi: usize) -> String {
        match &self.vars[vi].ty {
            Ty::Bool => "boolean".into(),
            Ty::Range(a, b) => format!("{}..{}", a, b),
            Ty::Enum(n) => format!("{{{}}}", n.join(", ")),
        }
    }

    fn read_var(&mut self, vi: usize, next: bool) -> V {
        let v = self.vars[vi].clone();
        let bits = if next { v.nxt.clone() } else { v.cur.clone() };
        if v.ty == Ty::Bool {
            return V::Bool(self.m.var(bits[0]));
        }
        if v.size > MAX_TAB {
            let Ty::Range(lo, _) = v.ty else { unreachable!("only ranges are large") };
            let b = bv::from_unsigned(&bits.iter().map(|&x| self.m.var(x)).collect::<Vec<_>>());
            let b = if lo == 0 { b } else { bv::add(&mut self.m, &b, &bv::constant(lo)) };
            return V::Bv(vec![(b, TRUE)]);
        }
        let mut tab = Vec::new();
        for c in 0..v.size {
            let g = self.code_bdd(&bits, c);
            tab.push((self.val_of_code(vi, c), g));
        }
        V::Tab(tab)
    }

    // ------------------------------------------------------------------ expression compilation

    fn kind_name(v: Val) -> &'static str {
        match v {
            Val::B(_) => "boolean",
            Val::I(_) => "integer",
            Val::S(_) => "symbolic",
        }
    }

    fn tab_kind(t: &[(Val, Bdd)]) -> Option<&'static str> {
        t.first().map(|(v, _)| Self::kind_name(*v))
    }

    fn to_tab(&mut self, v: V) -> Vec<(Val, Bdd)> {
        match v {
            V::Tab(t) => t,
            V::Bool(b) => {
                let nb = self.m.not(b);
                let mut t = vec![];
                if b != FALSE {
                    t.push((Val::B(true), b));
                }
                if nb != FALSE {
                    t.push((Val::B(false), nb));
                }
                t
            }
            V::Bv(_) => unreachable!("bit-vector value reached to_tab: callers must dispatch first"),
        }
    }

    /// Integer alternatives of an expression as bit-vectors.
    fn to_alts(&mut self, v: V, pos: Pos) -> Res<Vec<(Bv, Bdd)>> {
        match v {
            V::Bv(a) => Ok(a),
            V::Bool(_) => Err(Error::new(pos, "expected an integer expression, found a boolean")),
            V::Tab(t) => {
                for (val, _) in &t {
                    if !matches!(val, Val::I(_)) {
                        return Err(Error::new(pos, format!("expected an integer expression, found {} value {}", Self::kind_name(*val), self.val_str(*val))));
                    }
                }
                if t.len() <= 16 {
                    return Ok(t.into_iter().map(|(v, g)| match v {
                        Val::I(n) => (bv::constant(n), g),
                        _ => unreachable!(),
                    }).collect());
                }
                // many entries: build bit functions, which is only valid if the guards are disjoint
                let mut acc = FALSE;
                for (_, g) in &t {
                    if self.m.and(acc, *g) != FALSE {
                        return Err(Error::new(pos, "cannot combine a nondeterministic multi-valued expression with a large integer range"));
                    }
                    acc = self.m.or(acc, *g);
                }
                let lo = t.iter().map(|(v, _)| if let Val::I(n) = v { *n } else { 0 }).min().unwrap();
                let hi = t.iter().map(|(v, _)| if let Val::I(n) = v { *n } else { 0 }).max().unwrap();
                let w = bv::constant(lo).width().max(bv::constant(hi).width());
                let mut bits = vec![FALSE; w];
                for (val, g) in &t {
                    if let Val::I(n) = val {
                        for (i, b) in bits.iter_mut().enumerate() {
                            if (n >> i) & 1 == 1 {
                                *b = self.m.or(*b, *g);
                            }
                        }
                    }
                }
                Ok(vec![(Bv { bits }, acc)])
            }
        }
    }

    fn bv_pairs_ok(&self, a: usize, b: usize, pos: Pos) -> Res<()> {
        if a * b > MAX_ALT_PAIRS {
            return Err(Error::new(pos, "too many nondeterministic alternatives in a large-integer expression"));
        }
        Ok(())
    }

    fn bv_binop(&mut self, op: BinOp, va: V, vb: V, pos: Pos) -> Res<V> {
        use BinOp::*;
        let aa = self.to_alts(va, pos)?;
        let ab = self.to_alts(vb, pos)?;
        self.bv_pairs_ok(aa.len(), ab.len(), pos)?;
        let mut cmp_acc = FALSE;
        let mut alts: Vec<(Bv, Bdd)> = vec![];
        for (x, gx) in &aa {
            for (y, gy) in &ab {
                let g = self.m.and(*gx, *gy);
                if g == FALSE {
                    continue;
                }
                match op {
                    Eq | Ne | In | Lt | Le | Gt | Ge => {
                        let c = match op {
                            Eq | Ne | In => bv::eq(&mut self.m, x, y),
                            Lt => bv::lt(&mut self.m, x, y),
                            Le => bv::le(&mut self.m, x, y),
                            Gt => bv::lt(&mut self.m, y, x),
                            _ => bv::le(&mut self.m, y, x),
                        };
                        let t = self.m.and(g, c);
                        cmp_acc = self.m.or(cmp_acc, t);
                    }
                    Add => alts.push((bv::add(&mut self.m, x, y), g)),
                    Sub => alts.push((bv::sub(&mut self.m, x, y), g)),
                    Mul => alts.push((bv::mul(&mut self.m, x, y), g)),
                    Div | Mod => {
                        // only constant positive divisors are supported on bit-vectors
                        let c = y.bits.iter().enumerate().try_fold(0i64, |acc, (i, &b)| {
                            if b == TRUE {
                                Some(if i + 1 == y.bits.len() { acc - (1i64 << i) } else { acc | (1i64 << i) })
                            } else if b == FALSE {
                                Some(acc)
                            } else {
                                None
                            }
                        });
                        match c {
                            Some(c) if c > 0 => {
                                let (q, r) = bv::divmod_const(&mut self.m, x, c);
                                alts.push((if op == Div { q } else { r }, g));
                            }
                            Some(0) => return Err(Error::new(pos, "division by zero")),
                            _ => return Err(Error::new(pos, "division / mod of a large integer needs a positive constant divisor")),
                        }
                    }
                    _ => unreachable!(),
                }
                if alts.iter().any(|(b, _)| b.width() > bv::MAX_WIDTH) {
                    return Err(Error::new(pos, "integer expression is wider than 64 bits"));
                }
            }
        }
        Ok(match op {
            Eq | In | Lt | Le | Gt | Ge => V::Bool(cmp_acc),
            Ne => V::Bool(self.m.not(cmp_acc)),
            _ => V::Bv(alts),
        })
    }

    fn to_bool(&mut self, v: V, pos: Pos) -> Res<Bdd> {
        match v {
            V::Bool(b) => Ok(b),
            V::Bv(_) => Err(Error::new(pos, "expected a boolean expression, found an integer")),
            V::Tab(t) => {
                let mut acc = FALSE;
                for (val, g) in t {
                    match val {
                        Val::B(true) => acc = self.m.or(acc, g),
                        Val::B(false) => {}
                        other => return Err(Error::new(pos, format!("expected a boolean expression, found {} value {}", Self::kind_name(other), self.val_str(other)))),
                    }
                }
                Ok(acc)
            }
        }
    }

    fn merge(&mut self, pairs: Vec<(Val, Bdd)>) -> Vec<(Val, Bdd)> {
        let mut map: BTreeMap<Val, Bdd> = BTreeMap::new();
        for (v, g) in pairs {
            if g == FALSE {
                continue;
            }
            let e = map.entry(v).or_insert(FALSE);
            *e = self.m.or(*e, g);
        }
        map.into_iter().collect()
    }

    pub fn atom(&mut self, e: &Expr) -> Res<Bdd> {
        let v = self.comp(e, Mode { next: false, ctx: Ctx::State })?;
        self.to_bool(v, e.pos)
    }

    pub fn atom_ctx(&mut self, e: &Expr, ctx: Ctx) -> Res<Bdd> {
        let v = self.comp(e, Mode { next: false, ctx })?;
        self.to_bool(v, e.pos)
    }

    fn comp(&mut self, e: &Expr, mode: Mode) -> Res<V> {
        match &e.k {
            Ek::Int(n) => Ok(V::Tab(vec![(Val::I(*n), TRUE)])),
            Ek::Bool(b) => Ok(V::Bool(if *b { TRUE } else { FALSE })),
            Ek::Id(name) => self.comp_id(name, e.pos, mode),
            Ek::Next(inner) => {
                if mode.ctx != Ctx::Trans {
                    return Err(Error::new(e.pos, "next(..) is only allowed in TRANS and next-state assignments"));
                }
                if mode.next {
                    return Err(Error::new(e.pos, "next(next(..)) is not allowed"));
                }
                self.comp(inner, Mode { next: true, ctx: mode.ctx })
            }
            Ek::Un(op, a) => match op {
                UnOp::Not => {
                    let v = self.comp(a, mode)?;
                    let b = self.to_bool(v, a.pos)?;
                    Ok(V::Bool(self.m.not(b)))
                }
                UnOp::Neg => {
                    let v = self.comp(a, mode)?;
                    if let V::Bv(alts) = v {
                        let out = alts.iter().map(|(b, g)| (bv::neg(&mut self.m, b), *g)).collect();
                        return Ok(V::Bv(out));
                    }
                    let t = self.to_tab(v);
                    let mut out = vec![];
                    for (val, g) in t {
                        match val {
                            Val::I(n) => out.push((Val::I(-n), g)),
                            other => return Err(Error::new(e.pos, format!("unary '-' needs an integer, found {} value {}", Self::kind_name(other), self.val_str(other)))),
                        }
                    }
                    Ok(V::Tab(out))
                }
                _ => Err(Error::new(e.pos, "temporal operators are only allowed in SPEC / LTLSPEC formulas")),
            },
            Ek::EU(..) | Ek::AU(..) => Err(Error::new(e.pos, "temporal operators are only allowed in SPEC / LTLSPEC formulas")),
            Ek::Set(es) => {
                let mut vs = vec![];
                for x in es {
                    vs.push(self.comp(x, mode)?);
                }
                if vs.iter().any(|v| matches!(v, V::Bv(_))) {
                    let mut alts = vec![];
                    for v in vs {
                        alts.extend(self.to_alts(v, e.pos)?);
                    }
                    return Ok(V::Bv(alts));
                }
                let mut all = vec![];
                for v in vs {
                    all.extend(self.to_tab(v));
                }
                let t = self.merge(all);
                self.check_homogeneous(&t, e.pos)?;
                Ok(V::Tab(t))
            }
            Ek::Case(arms) => {
                let mut remaining = TRUE;
                let mut parts: Vec<V> = vec![];
                let mut guards: Vec<Bdd> = vec![];
                for (c, v) in arms {
                    let cv = self.comp(c, mode)?;
                    let cb = self.to_bool(cv, c.pos)?;
                    let eff = self.m.and(cb, remaining);
                    guards.push(eff);
                    parts.push(self.comp(v, mode)?);
                    let ncb = self.m.not(cb);
                    remaining = self.m.and(remaining, ncb);
                }
                if remaining != FALSE && !self.case_uncovered_ok(remaining) {
                    return Err(Error::new(e.pos, "case expression is not exhaustive: add a final 'TRUE : ...;' arm"));
                }
                if parts.iter().any(|p| matches!(p, V::Bv(_))) {
                    let mut alts = vec![];
                    for (p, g) in parts.into_iter().zip(guards) {
                        for (b, bg) in self.to_alts(p, e.pos)? {
                            let x = self.m.and(g, bg);
                            if x != FALSE {
                                alts.push((b, x));
                            }
                        }
                    }
                    return Ok(V::Bv(alts));
                }
                if parts.iter().all(|p| matches!(p, V::Bool(_))) {
                    let mut acc = FALSE;
                    for (p, g) in parts.iter().zip(&guards) {
                        if let V::Bool(b) = p {
                            let x = self.m.and(*g, *b);
                            acc = self.m.or(acc, x);
                        }
                    }
                    return Ok(V::Bool(acc));
                }
                let mut all = vec![];
                for (p, g) in parts.into_iter().zip(guards) {
                    for (val, vg) in self.to_tab(p) {
                        let x = self.m.and(g, vg);
                        all.push((val, x));
                    }
                }
                let t = self.merge(all);
                self.check_homogeneous(&t, e.pos)?;
                Ok(V::Tab(t))
            }
            Ek::Bin(op, a, b) => self.comp_bin(*op, a, b, e.pos, mode),
        }
    }

    /// An uncovered `case` remainder is acceptable only if it contains no legal state at all
    /// (e.g. it is exactly the set of unused enum/range codes).
    fn case_uncovered_ok(&mut self, remaining: Bdd) -> bool {
        let dom = self.dom_all;
        self.m.and(remaining, dom) == FALSE
    }

    fn check_homogeneous(&self, t: &[(Val, Bdd)], pos: Pos) -> Res<()> {
        if let Some(k) = Self::tab_kind(t) {
            for (v, _) in t {
                if Self::kind_name(*v) != k {
                    return Err(Error::new(
                        pos,
                        format!("mixed types in one expression: {} and {} ({})", k, Self::kind_name(*v), self.val_str(*v)),
                    ));
                }
            }
        }
        Ok(())
    }

    fn comp_id(&mut self, name: &str, pos: Pos, mode: Mode) -> Res<V> {
        if let Some(&vi) = self.var_ix.get(name) {
            if self.vars[vi].input {
                if mode.ctx != Ctx::Trans {
                    return Err(Error::new(pos, format!("input variable '{}' may only be used in TRANS and next-state assignments", name)));
                }
                if mode.next {
                    return Err(Error::new(pos, format!("input variable '{}' has no next-state copy", name)));
                }
            }
            return Ok(self.read_var(vi, mode.next));
        }
        if let Some(def) = self.defines.get(name).cloned() {
            if self.expanding.iter().any(|n| n == name) {
                return Err(Error::new(pos, format!("definition '{}' is recursive", name)));
            }
            self.expanding.push(name.to_string());
            let r = self.comp(&def, mode);
            self.expanding.pop();
            return r;
        }
        if let Some(&s) = self.sym_ix.get(name) {
            return Ok(V::Tab(vec![(Val::S(s), TRUE)]));
        }
        let mut cands: Vec<&String> = self.var_ix.keys().chain(self.defines.keys()).chain(self.sym_ix.keys()).collect();
        cands.sort_by_key(|c| edit_distance(c, name));
        let hint = match cands.first() {
            Some(c) if edit_distance(c, name) <= 2.max(name.len() / 3) => format!(" (did you mean '{}'?)", c),
            _ => String::new(),
        };
        Err(Error::new(pos, format!("unknown identifier '{}'{}", name, hint)))
    }

    fn comp_bin(&mut self, op: BinOp, a: &Expr, b: &Expr, pos: Pos, mode: Mode) -> Res<V> {
        use BinOp::*;
        if matches!(op, Until | Release) {
            return Err(Error::new(pos, "temporal operators are only allowed in SPEC / LTLSPEC formulas"));
        }
        let va = self.comp(a, mode)?;
        let vb = self.comp(b, mode)?;
        let numeric = matches!(op, Eq | Ne | In | Lt | Le | Gt | Ge | Add | Sub | Mul | Div | Mod);
        if numeric && (matches!(va, V::Bv(_)) || matches!(vb, V::Bv(_))) {
            return self.bv_binop(op, va, vb, pos);
        }
        match op {
            And | Or | Xor | Imp | Iff => {
                let x = self.to_bool(va, a.pos)?;
                let y = self.to_bool(vb, b.pos)?;
                Ok(V::Bool(match op {
                    And => self.m.and(x, y),
                    Or => self.m.or(x, y),
                    Xor => self.m.xor(x, y),
                    Imp => self.m.imp(x, y),
                    _ => self.m.iff(x, y),
                }))
            }
            Eq | Ne | In => {
                if let (V::Bool(x), V::Bool(y)) = (&va, &vb) {
                    let r = self.m.iff(*x, *y);
                    return Ok(V::Bool(if op == Ne { self.m.not(r) } else { r }));
                }
                let ta = self.to_tab(va);
                let tb = self.to_tab(vb);
                if let (Some(ka), Some(kb)) = (Self::tab_kind(&ta), Self::tab_kind(&tb)) {
                    if ka != kb {
                        return Err(Error::new(pos, format!("cannot compare {} with {}", ka, kb)));
                    }
                }
                let mut ga: BTreeMap<Val, Bdd> = BTreeMap::new();
                for (v, g) in ta {
                    ga.insert(v, g);
                }
                let mut acc = FALSE;
                for (v, g) in tb {
                    if let Some(&h) = ga.get(&v) {
                        let x = self.m.and(g, h);
                        acc = self.m.or(acc, x);
                    }
                }
                Ok(V::Bool(if op == Ne { self.m.not(acc) } else { acc }))
            }
            Lt | Le | Gt | Ge => {
                let ta = self.int_tab(va, a.pos, "comparison")?;
                let tb = self.int_tab(vb, b.pos, "comparison")?;
                // normalise to "x < y" / "x <= y"
                let (x, y, strict) = match op {
                    Lt => (ta, tb, true),
                    Le => (ta, tb, false),
                    Gt => (tb, ta, true),
                    _ => (tb, ta, false),
                };
                let mut acc = FALSE;
                let mut prefix = FALSE;
                let mut i = 0;
                for (yv, yg) in &y {
                    while i < x.len() && (if strict { x[i].0 < *yv } else { x[i].0 <= *yv }) {
                        prefix = self.m.or(prefix, x[i].1);
                        i += 1;
                    }
                    let t = self.m.and(*yg, prefix);
                    acc = self.m.or(acc, t);
                }
                Ok(V::Bool(acc))
            }
            Add | Sub | Mul | Div | Mod => {
                let ta = self.int_tab(va, a.pos, "arithmetic")?;
                let tb = self.int_tab(vb, b.pos, "arithmetic")?;
                if ta.len() * tb.len() > MAX_PAIRS {
                    let na = V::Tab(ta.into_iter().map(|(n, g)| (Val::I(n), g)).collect());
                    let nb = V::Tab(tb.into_iter().map(|(n, g)| (Val::I(n), g)).collect());
                    return self.bv_binop(op, na, nb, pos);
                }
                let mut out = vec![];
                for (x, gx) in &ta {
                    for (y, gy) in &tb {
                        let r = match op {
                            Add => x.checked_add(*y),
                            Sub => x.checked_sub(*y),
                            Mul => x.checked_mul(*y),
                            Div | Mod if *y == 0 => {
                                let g = self.m.and(*gx, *gy);
                                let bad = self.m.and(g, self.dom_all);
                                if bad != FALSE && !self.lax_ranges {
                                    return Err(Error::new(
                                        pos,
                                        "the divisor can be zero here; guard the division with a case (or pass --lax to disable those transitions)",
                                    ));
                                }
                                None
                            }
                            Div => Some(x / y),
                            _ => Some(x.rem_euclid(y.abs())),
                        };
                        if let Some(r) = r {
                            let g = self.m.and(*gx, *gy);
                            if g != FALSE {
                                out.push((Val::I(r), g));
                            }
                        }
                    }
                }
                let t = self.merge(out);
                if t.len() > MAX_TAB {
                    return Err(Error::new(pos, "expression has too many distinct values"));
                }
                Ok(V::Tab(t))
            }
            _ => unreachable!(),
        }
    }

    fn int_tab(&mut self, v: V, pos: Pos, what: &str) -> Res<Vec<(i64, Bdd)>> {
        let t = self.to_tab(v);
        let mut out = vec![];
        for (val, g) in t {
            match val {
                Val::I(n) => out.push((n, g)),
                other => return Err(Error::new(pos, format!("{} needs integers, found {} value {}", what, Self::kind_name(other), self.val_str(other)))),
            }
        }
        out.sort_by_key(|x| x.0);
        Ok(out)
    }

    // ------------------------------------------------------------------ assembling the system

    fn assign_rel_v(&mut self, vi: usize, v: V, next: bool, pos: Pos, legal: Bdd) -> Res<Bdd> {
        match v {
            V::Bv(alts) => self.assign_rel_bv(vi, alts, next, pos, legal),
            other => {
                let t = self.to_tab(other);
                self.assign_rel(vi, t, next, pos, legal)
            }
        }
    }

    fn assign_rel_bv(&mut self, vi: usize, alts: Vec<(Bv, Bdd)>, next: bool, pos: Pos, legal: Bdd) -> Res<Bdd> {
        let Ty::Range(lo, hi) = self.vars[vi].ty else {
            return Err(Error::new(pos, format!("cannot assign an integer to '{}' of type {}", self.vars[vi].name, self.ty_str(vi))));
        };
        let bits = if next { self.vars[vi].nxt.clone() } else { self.vars[vi].cur.clone() };
        let (clo, chi) = (bv::constant(lo), bv::constant(hi));
        let mut acc = FALSE;
        for (b, g) in alts {
            let a = bv::le(&mut self.m, &clo, &b);
            let c = bv::le(&mut self.m, &b, &chi);
            let inr = self.m.and(a, c);
            let nin = self.m.not(inr);
            let bad = {
                let t = self.m.and(g, nin);
                self.m.and(t, legal)
            };
            if bad != FALSE && !self.lax_ranges {
                return Err(Error::new(
                    pos,
                    format!(
                        "assignment to '{}' can leave its type {} (for example by overflowing); guard it with a case, use `mod`, or pass --lax to disable such transitions",
                        self.vars[vi].name,
                        self.ty_str(vi)
                    ),
                ));
            }
            let diff = bv::sub(&mut self.m, &b, &clo);
            let diff = bv::extend(&diff, bits.len().max(diff.width()));
            let mut eqb = TRUE;
            for (i, &vb) in bits.iter().enumerate() {
                let x = self.m.var(vb);
                let e = self.m.iff(x, diff.bits[i]);
                eqb = self.m.and(eqb, e);
            }
            let t = self.m.and(g, inr);
            let t = self.m.and(t, eqb);
            acc = self.m.or(acc, t);
        }
        Ok(acc)
    }

    /// `var ∈ table` as a relation (over current or next bits), erroring if the table can produce a
    /// value outside the variable's type in some legal situation.
    fn assign_rel(&mut self, vi: usize, tab: Vec<(Val, Bdd)>, next: bool, pos: Pos, legal: Bdd) -> Res<Bdd> {
        let bits = if next { self.vars[vi].nxt.clone() } else { self.vars[vi].cur.clone() };
        let mut acc = FALSE;
        for (val, g) in tab {
            match self.code_of_val(vi, val) {
                Some(c) => {
                    let cb = self.code_bdd(&bits, c);
                    let x = self.m.and(g, cb);
                    acc = self.m.or(acc, x);
                }
                None => {
                    let bad = self.m.and(g, legal);
                    if bad != FALSE && !self.lax_ranges {
                        let kind_ok = match (&self.vars[vi].ty, val) {
                            (Ty::Bool, Val::B(_)) | (Ty::Range(..), Val::I(_)) | (Ty::Enum(_), Val::S(_)) => true,
                            _ => false,
                        };
                        let what = if kind_ok {
                            format!("outside its type {}", self.ty_str(vi))
                        } else {
                            format!("of the wrong kind for its type {}", self.ty_str(vi))
                        };
                        return Err(Error::new(
                            pos,
                            format!(
                                "assignment to '{}' can produce {} ({}), which is {}; guard it with a case, use `mod`, or pass --lax to disable such transitions",
                                self.vars[vi].name,
                                self.val_str(val),
                                Self::kind_name(val),
                                what
                            ),
                        ));
                    }
                }
            }
        }
        Ok(acc)
    }

    fn build(&mut self, prog: &Program) -> Res<()> {
        // domains
        let mut space = TRUE;
        let mut legal_trans = TRUE;
        for vi in 0..self.vars.len() {
            let d = self.domain(vi, false);
            if !self.vars[vi].input {
                space = self.m.and(space, d);
            }
            legal_trans = self.m.and(legal_trans, d);
            if !self.vars[vi].input {
                let dn = self.domain(vi, true);
                legal_trans = self.m.and(legal_trans, dn);
            }
        }
        let dom_space = space;
        let mut invar = TRUE;
        for e in &prog.invars {
            let b = self.atom_ctx(e, Ctx::State)?;
            invar = self.m.and(invar, b);
        }
        // assignments
        let mut seen: HashMap<(String, u8), Pos> = HashMap::new();
        let mut init = TRUE;
        let mut trans = TRUE;
        for a in &prog.assigns {
            let vi = *self.var_ix.get(&a.var).ok_or_else(|| {
                let mut cands: Vec<&String> = self.var_ix.keys().collect();
                cands.sort_by_key(|c| edit_distance(c, &a.var));
                let hint = cands.first().map(|c| format!(" (did you mean '{}'?)", c)).unwrap_or_default();
                Error::new(a.pos, format!("assignment to undeclared variable '{}'{}", a.var, hint))
            })?;
            let kind_id = match a.kind {
                AssignKind::Init => 0u8,
                AssignKind::Next => 1,
                AssignKind::Plain => 2,
            };
            if seen.insert((a.var.clone(), kind_id), a.pos).is_some() {
                return Err(Error::new(a.pos, format!("'{}' is assigned twice", a.var)));
            }
            if self.vars[vi].input && a.kind != AssignKind::Plain {
                return Err(Error::new(a.pos, format!("input variable '{}' cannot have init/next assignments", a.var)));
            }
            match a.kind {
                AssignKind::Init => {
                    let v = self.comp(&a.expr, Mode { next: false, ctx: Ctx::State })?;
                    let r = self.assign_rel_v(vi, v, false, a.expr.pos, dom_space)?;
                    init = self.m.and(init, r);
                }
                AssignKind::Next => {
                    let v = self.comp(&a.expr, Mode { next: false, ctx: Ctx::Trans })?;
                    let r = self.assign_rel_v(vi, v, true, a.expr.pos, legal_trans)?;
                    trans = self.m.and(trans, r);
                }
                AssignKind::Plain => {
                    let ctx = if self.vars[vi].input { Ctx::Trans } else { Ctx::State };
                    let v = self.comp(&a.expr, Mode { next: false, ctx })?;
                    let r = self.assign_rel_v(vi, v, false, a.expr.pos, dom_space)?;
                    if self.vars[vi].input {
                        // constraint on an input: applies to the transition relation
                        trans = self.m.and(trans, r);
                    } else {
                        invar = self.m.and(invar, r);
                    }
                }
            }
        }
        for e in &prog.inits {
            let b = self.atom_ctx(e, Ctx::State)?;
            init = self.m.and(init, b);
        }
        for e in &prog.transes {
            let b = self.atom_ctx(e, Ctx::Trans)?;
            trans = self.m.and(trans, b);
        }
        // the state constraint holds in every state, i.e. on both ends of every step
        space = self.m.and(space, invar);
        let space_n = self.m.rename(space, &self.to_next.clone());
        let inp_dom = {
            let mut d = TRUE;
            for vi in 0..self.vars.len() {
                if self.vars[vi].input {
                    let x = self.domain(vi, false);
                    d = self.m.and(d, x);
                }
            }
            d
        };
        // Plain assignments to state variables refer to the current copy only; invariants hold on both ends.
        let mut t = self.m.and(trans, space);
        t = self.m.and(t, space_n);
        t = self.m.and(t, inp_dom);
        let init = self.m.and(init, space);
        self.init = init;
        self.trans = t;
        self.space = space;
        let mut fair = vec![];
        for e in &prog.fairness {
            let b = self.atom(e)?;
            fair.push(b);
        }
        self.fair = fair;
        // keep the long-lived functions alive across garbage collections
        for b in [self.init, self.trans, self.space, self.cur_cube, self.nxt_cube, self.inp_cube, self.inp_nxt_cube] {
            self.m.pin(b);
        }
        for b in self.fair.clone() {
            self.m.pin(b);
        }
        Ok(())
    }

    // ------------------------------------------------------------------ image computation

    /// Give every reachable-or-not deadlock state a self-loop ("stutter"), making the relation total.
    pub fn stutter_deadlocks(&mut self) {
        let mut ex_vars = self.nxt_vars.clone();
        ex_vars.extend(&self.inp_vars);
        let cube = self.m.cube(&ex_vars);
        let has_succ = self.m.exists(self.trans, cube);
        let dead = self.m.diff(self.space, has_succ);
        let mut eq = TRUE;
        for (&c, &n) in self.cur_vars.clone().iter().zip(self.nxt_vars.clone().iter()) {
            let (a, b) = (self.m.var(c), self.m.var(n));
            let e = self.m.iff(a, b);
            eq = self.m.and(eq, e);
        }
        let mut inp_dom = TRUE;
        for vi in 0..self.vars.len() {
            if self.vars[vi].input {
                let d = self.domain(vi, false);
                inp_dom = self.m.and(inp_dom, d);
            }
        }
        let stutter = self.m.and(dead, eq);
        let stutter = self.m.and(stutter, inp_dom);
        self.trans = self.m.or(self.trans, stutter);
        let t = self.trans;
        self.m.pin(t);
    }

    pub fn to_next_map(&self) -> &HashMap<u32, u32> {
        &self.to_next
    }

    pub fn to_cur_map(&self) -> &HashMap<u32, u32> {
        &self.to_cur
    }

    /// Successors of the state set `x` (over current vars), as a state set over current vars.
    pub fn image(&mut self, x: Bdd) -> Bdd {
        let mut cube_vars: Vec<u32> = self.cur_vars.clone();
        cube_vars.extend(&self.inp_vars);
        let cube = self.m.cube(&cube_vars);
        let nx = self.m.and_exists(x, self.trans, cube);
        let map = self.to_cur.clone();
        self.m.rename(nx, &map)
    }

    /// Predecessors of the state set `x`: states with some transition into `x`.
    pub fn preimage(&mut self, x: Bdd) -> Bdd {
        let map = self.to_next.clone();
        let xn = self.m.rename(x, &map);
        let cube = self.inp_nxt_cube;
        self.m.and_exists(self.trans, xn, cube)
    }

    pub fn count_states(&self, set: Bdd) -> u128 {
        self.m.sat_count(set, &self.cur_vars)
    }

    // ------------------------------------------------------------------ states <-> assignments

    /// Decode bit assignment `(var, value)` of the current-state bits of the non-input variables.
    pub fn decode_state(&self, bits: &HashMap<u32, bool>) -> Vec<(String, String)> {
        let mut out = vec![];
        for v in self.vars.iter().filter(|v| !v.input) {
            out.push((v.name.clone(), self.decode_var(v, bits, false)));
        }
        out
    }

    pub fn decode_inputs(&self, bits: &HashMap<u32, bool>) -> Vec<(String, String)> {
        let mut out = vec![];
        for v in self.vars.iter().filter(|v| v.input) {
            out.push((v.name.clone(), self.decode_var(v, bits, false)));
        }
        out
    }

    fn decode_var(&self, v: &VarInfo, bits: &HashMap<u32, bool>, next: bool) -> String {
        let bs = if next { &v.nxt } else { &v.cur };
        let mut code = 0usize;
        for (i, b) in bs.iter().enumerate() {
            if *bits.get(b).unwrap_or(&false) {
                code |= 1 << i;
            }
        }
        match &v.ty {
            Ty::Bool => if code == 1 { "TRUE" } else { "FALSE" }.to_string(),
            Ty::Range(lo, _) => (lo + code as i64).to_string(),
            Ty::Enum(names) => names.get(code).cloned().unwrap_or_else(|| format!("?{}", code)),
        }
    }

    /// Total number of Boolean state bits (cur) — handy for statistics.
    pub fn num_state_bits(&self) -> usize {
        self.cur_vars.len()
    }

    /// Add an auxiliary (tableau) Boolean state variable; returns (current, next) BDD variables.
    pub fn add_aux_var(&mut self) -> (u32, u32) {
        let c = self.m.new_var();
        let n = self.m.new_var();
        self.cur_vars.push(c);
        self.nxt_vars.push(n);
        self.to_next.insert(c, n);
        self.to_cur.insert(n, c);
        (c, n)
    }

    /// Install the product system after `add_aux_var` calls: recompute cubes, replace init/trans, add fairness.
    pub fn finish_extension(&mut self, init: Bdd, trans: Bdd, extra_fair: Vec<Bdd>) {
        self.cur_cube = self.m.cube(&self.cur_vars.clone());
        self.nxt_cube = self.m.cube(&self.nxt_vars.clone());
        let mut inx = self.nxt_vars.clone();
        inx.extend(&self.inp_vars);
        self.inp_nxt_cube = self.m.cube(&inx);
        self.init = init;
        self.trans = trans;
        self.fair.extend(extra_fair);
        for b in [self.init, self.trans, self.cur_cube, self.nxt_cube, self.inp_nxt_cube] {
            self.m.pin(b);
        }
        for b in self.fair.clone() {
            self.m.pin(b);
        }
    }

    pub fn sym_id(&self, name: &str) -> Option<usize> {
        self.sym_ix.get(name).copied()
    }
}
