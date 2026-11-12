//! An independent explicit-state engine used as a test oracle.
//!
//! It shares *only* the parser and the AST with the symbolic checker. Expressions are evaluated on
//! concrete valuations (to *sets* of values, mirroring the symbolic union semantics), the state graph
//! is enumerated, and fair `EG` is decided with Tarjan SCCs instead of the Emerson–Lei fixpoint.

use crate::check::Trace;
use crate::lang::*;
use crate::temporal::{lower_ctl, lower_ltl, Ctl, Ltl};
use std::collections::{HashMap, HashSet, VecDeque};

#[derive(Clone, Debug, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub enum EV {
    B(bool),
    I(i64),
    S(String),
}

type Valuation = Vec<EV>;

pub struct Explicit {
    prog: Program,
    vars: Vec<VarDecl>,
    var_ix: HashMap<String, usize>,
    defines: HashMap<String, Expr>,
    syms: HashSet<String>,
    pub states: Vec<Valuation>,
    index: HashMap<Valuation, usize>,
    state_vars: Vec<usize>,
    input_vars: Vec<usize>,
    pub init: Vec<bool>,
    pub succ: Vec<Vec<usize>>,
    fair_sets: Vec<Vec<bool>>,
    fair_states: Option<Vec<bool>>,
    stutter: bool,
    /// States that had no successor before stuttering self-loops were added.
    deadlocked: Vec<bool>,
}

fn domain(ty: &Ty) -> Vec<EV> {
    match ty {
        Ty::Bool => vec![EV::B(false), EV::B(true)],
        Ty::Range(lo, hi) => (*lo..=*hi).map(EV::I).collect(),
        Ty::Enum(ns) => ns.iter().map(|n| EV::S(n.clone())).collect(),
    }
}

fn dedup(mut v: Vec<EV>) -> Vec<EV> {
    v.sort();
    v.dedup();
    v
}

struct Env<'a> {
    cur: &'a Valuation,
    nxt: Option<&'a Valuation>,
}

impl Explicit {
    pub fn new(prog: &Program, max_states: usize, stutter: bool) -> Result<Explicit, String> {
        let vars = prog.vars.clone();
        let mut var_ix = HashMap::new();
        let mut syms = HashSet::new();
        for (i, v) in vars.iter().enumerate() {
            var_ix.insert(v.name.clone(), i);
            if let Ty::Enum(ns) = &v.ty {
                for n in ns {
                    syms.insert(n.clone());
                }
            }
        }
        let defines: HashMap<String, Expr> = prog
            .defines
            .iter()
            .map(|(n, e, _)| (n.clone(), e.clone()))
            .collect();
        let state_vars: Vec<usize> = (0..vars.len()).filter(|&i| !vars[i].input).collect();
        let input_vars: Vec<usize> = (0..vars.len()).filter(|&i| vars[i].input).collect();
        let mut ex = Explicit {
            prog: prog.clone(),
            vars,
            var_ix,
            defines,
            syms,
            states: vec![],
            index: HashMap::new(),
            state_vars,
            input_vars,
            init: vec![],
            succ: vec![],
            fair_sets: vec![],
            fair_states: None,
            stutter,
            deadlocked: vec![],
        };
        ex.enumerate(max_states)?;
        ex.deadlocked = ex.succ.iter().map(|s| s.is_empty()).collect();
        if stutter {
            for i in 0..ex.succ.len() {
                if ex.succ[i].is_empty() {
                    ex.succ[i].push(i);
                }
            }
        }
        Ok(ex)
    }

    fn product(&self, which: &[usize]) -> Vec<Valuation> {
        // full-width valuations; variables not in `which` get a placeholder
        let mut out: Vec<Valuation> = vec![vec![EV::B(false); self.vars.len()]];
        for &vi in which {
            let dom = domain(&self.vars[vi].ty);
            let mut next = Vec::with_capacity(out.len() * dom.len());
            for base in &out {
                for d in &dom {
                    let mut v = base.clone();
                    v[vi] = d.clone();
                    next.push(v);
                }
            }
            out = next;
        }
        out
    }

    fn enumerate(&mut self, max_states: usize) -> Result<(), String> {
        let total: usize = self
            .state_vars
            .iter()
            .map(|&i| domain(&self.vars[i].ty).len())
            .product();
        if total > max_states {
            return Err(format!(
                "explicit state space too large ({} candidate states)",
                total
            ));
        }
        let cands = self.product(&self.state_vars.clone());
        // legal states: INVAR and plain assignments
        let inputs_placeholder = self.product(&[]);
        let _ = inputs_placeholder;
        for c in cands {
            if self.legal_state(&c)? {
                self.index.insert(c.clone(), self.states.len());
                self.states.push(c);
            }
        }
        let n = self.states.len();
        // init
        for s in &self.states.clone() {
            let ok = self.is_init(s)?;
            self.init.push(ok);
        }
        // transitions
        let input_vals = self.product(&self.input_vars.clone());
        self.succ = vec![vec![]; n];
        for i in 0..n {
            let mut targets: HashSet<usize> = HashSet::new();
            for iv in &input_vals {
                // merge the input values into the current valuation
                let mut cur = self.states[i].clone();
                for &vi in &self.input_vars {
                    cur[vi] = iv[vi].clone();
                }
                if !self.inputs_ok(&cur)? {
                    continue;
                }
                for j in 0..n {
                    if targets.contains(&j) {
                        continue;
                    }
                    if self.trans_ok(&cur, &self.states[j].clone())? {
                        targets.insert(j);
                    }
                }
            }
            let mut t: Vec<usize> = targets.into_iter().collect();
            t.sort();
            self.succ[i] = t;
        }
        // fairness
        let mut sets = vec![];
        for f in self.prog.fairness.clone() {
            let mut set = vec![];
            for s in &self.states {
                set.push(self.truthy(&f, &Env { cur: s, nxt: None })?);
            }
            sets.push(set);
        }
        self.fair_sets = sets;
        Ok(())
    }

    // ------------------------------------------------------------------ concrete semantics

    fn eval(&self, e: &Expr, env: &Env, depth: usize) -> Result<Vec<EV>, String> {
        if depth > 200 {
            return Err("expression nesting too deep".into());
        }
        let d = depth + 1;
        Ok(match &e.k {
            Ek::Int(n) => vec![EV::I(*n)],
            Ek::Bool(b) => vec![EV::B(*b)],
            Ek::Id(name) => {
                if let Some(&vi) = self.var_ix.get(name) {
                    vec![env.cur[vi].clone()]
                } else if let Some(def) = self.defines.get(name) {
                    self.eval(def, env, d)?
                } else if self.syms.contains(name) {
                    vec![EV::S(name.clone())]
                } else {
                    return Err(format!("unknown identifier {}", name));
                }
            }
            Ek::Next(inner) => {
                let nxt = env.nxt.ok_or("next() outside transition")?;
                self.eval(
                    inner,
                    &Env {
                        cur: nxt,
                        nxt: None,
                    },
                    d,
                )?
            }
            Ek::Un(UnOp::Not, a) => vec![EV::B(!self.truthy_v(&self.eval(a, env, d)?))],
            Ek::Un(UnOp::Neg, a) => {
                let mut out = vec![];
                for v in self.eval(a, env, d)? {
                    match v {
                        EV::I(n) => out.push(EV::I(-n)),
                        _ => return Err("neg of non-int".into()),
                    }
                }
                dedup(out)
            }
            Ek::Un(..) | Ek::EU(..) | Ek::AU(..) => {
                return Err("temporal operator in expression".into())
            }
            Ek::Set(es) => {
                let mut out = vec![];
                for x in es {
                    out.extend(self.eval(x, env, d)?);
                }
                dedup(out)
            }
            Ek::Case(arms) => {
                for (c, v) in arms {
                    if self.truthy_v(&self.eval(c, env, d)?) {
                        return self.eval(v, env, d);
                    }
                }
                vec![]
            }
            Ek::Bin(op, a, b) => {
                let va = self.eval(a, env, d)?;
                let vb = self.eval(b, env, d)?;
                use BinOp::*;
                match op {
                    And => vec![EV::B(self.truthy_v(&va) && self.truthy_v(&vb))],
                    Or => vec![EV::B(self.truthy_v(&va) || self.truthy_v(&vb))],
                    Xor => vec![EV::B(self.truthy_v(&va) != self.truthy_v(&vb))],
                    Imp => vec![EV::B(!self.truthy_v(&va) || self.truthy_v(&vb))],
                    Iff => vec![EV::B(self.truthy_v(&va) == self.truthy_v(&vb))],
                    Eq | In => vec![EV::B(va.iter().any(|x| vb.contains(x)))],
                    Ne => vec![EV::B(!va.iter().any(|x| vb.contains(x)))],
                    Lt | Le | Gt | Ge => {
                        let mut any = false;
                        for x in &va {
                            for y in &vb {
                                if let (EV::I(x), EV::I(y)) = (x, y) {
                                    any |= match op {
                                        Lt => x < y,
                                        Le => x <= y,
                                        Gt => x > y,
                                        _ => x >= y,
                                    };
                                } else {
                                    return Err("comparison of non-integers".into());
                                }
                            }
                        }
                        vec![EV::B(any)]
                    }
                    Add | Sub | Mul | Div | Mod => {
                        let mut out = vec![];
                        for x in &va {
                            for y in &vb {
                                if let (EV::I(x), EV::I(y)) = (x, y) {
                                    let r = match op {
                                        Add => x.checked_add(*y),
                                        Sub => x.checked_sub(*y),
                                        Mul => x.checked_mul(*y),
                                        Div => (*y != 0).then(|| x / y),
                                        _ => (*y != 0).then(|| x.rem_euclid(y.abs())),
                                    };
                                    if let Some(r) = r {
                                        out.push(EV::I(r));
                                    }
                                } else {
                                    return Err("arithmetic on non-integers".into());
                                }
                            }
                        }
                        dedup(out)
                    }
                    Until | Release => return Err("temporal operator in expression".into()),
                }
            }
        })
    }

    fn truthy_v(&self, v: &[EV]) -> bool {
        v.contains(&EV::B(true))
    }

    fn truthy(&self, e: &Expr, env: &Env) -> Result<bool, String> {
        Ok(self.truthy_v(&self.eval(e, env, 0)?))
    }

    fn legal_state(&self, s: &Valuation) -> Result<bool, String> {
        let env = Env { cur: s, nxt: None };
        for e in &self.prog.invars {
            if !self.truthy(e, &env)? {
                return Ok(false);
            }
        }
        for a in &self.prog.assigns {
            if a.kind == AssignKind::Plain && !self.vars[self.var_ix[&a.var]].input {
                let vals = self.eval(&a.expr, &env, 0)?;
                if !vals.contains(&s[self.var_ix[&a.var]]) {
                    return Ok(false);
                }
            }
        }
        Ok(true)
    }

    fn is_init(&self, s: &Valuation) -> Result<bool, String> {
        let env = Env { cur: s, nxt: None };
        for e in &self.prog.inits {
            if !self.truthy(e, &env)? {
                return Ok(false);
            }
        }
        for a in &self.prog.assigns {
            if a.kind == AssignKind::Init {
                let vals = self.eval(&a.expr, &env, 0)?;
                if !vals.contains(&s[self.var_ix[&a.var]]) {
                    return Ok(false);
                }
            }
        }
        Ok(true)
    }

    /// Constraints on the input valuation alone (plain assignments to inputs).
    fn inputs_ok(&self, cur: &Valuation) -> Result<bool, String> {
        let env = Env { cur, nxt: None };
        for a in &self.prog.assigns {
            if a.kind == AssignKind::Plain && self.vars[self.var_ix[&a.var]].input {
                let vals = self.eval(&a.expr, &env, 0)?;
                if !vals.contains(&cur[self.var_ix[&a.var]]) {
                    return Ok(false);
                }
            }
        }
        Ok(true)
    }

    pub fn trans_ok(&self, cur: &Valuation, nxt: &Valuation) -> Result<bool, String> {
        let env = Env {
            cur,
            nxt: Some(nxt),
        };
        for e in &self.prog.transes {
            if !self.truthy(e, &env)? {
                return Ok(false);
            }
        }
        for a in &self.prog.assigns {
            if a.kind == AssignKind::Next {
                let vals = self.eval(&a.expr, &env, 0)?;
                if !vals.contains(&nxt[self.var_ix[&a.var]]) {
                    return Ok(false);
                }
            }
        }
        Ok(true)
    }

    // ------------------------------------------------------------------ graph algorithms

    pub fn n(&self) -> usize {
        self.states.len()
    }

    fn pred_lists(&self) -> Vec<Vec<usize>> {
        let mut p = vec![vec![]; self.n()];
        for (i, ss) in self.succ.iter().enumerate() {
            for &j in ss {
                p[j].push(i);
            }
        }
        p
    }

    /// (reachable set, diameter, deadlock count)
    pub fn reachability(&self) -> (Vec<bool>, usize, usize) {
        let n = self.n();
        let mut dist = vec![usize::MAX; n];
        let mut q = VecDeque::new();
        for i in 0..n {
            if self.init[i] {
                dist[i] = 0;
                q.push_back(i);
            }
        }
        while let Some(i) = q.pop_front() {
            for &j in &self.succ[i] {
                if dist[j] == usize::MAX {
                    dist[j] = dist[i] + 1;
                    q.push_back(j);
                }
            }
        }
        let reach: Vec<bool> = dist.iter().map(|&d| d != usize::MAX).collect();
        let diam = dist
            .iter()
            .filter(|&&d| d != usize::MAX)
            .copied()
            .max()
            .unwrap_or(0);
        let dead = (0..n)
            .filter(|&i| reach[i] && self.succ[i].is_empty())
            .count();
        (reach, diam, dead)
    }

    /// Fair EG via SCC decomposition of the subgraph induced by `f`.
    fn eg_fair(&self, f: &[bool]) -> Vec<bool> {
        let n = self.n();
        // iterative Tarjan restricted to f
        let mut index = vec![usize::MAX; n];
        let mut low = vec![0usize; n];
        let mut on = vec![false; n];
        let mut stack = vec![];
        let mut comp = vec![usize::MAX; n];
        let mut ncomp = 0;
        let mut counter = 0;
        for root in 0..n {
            if !f[root] || index[root] != usize::MAX {
                continue;
            }
            let mut work: Vec<(usize, usize)> = vec![(root, 0)];
            index[root] = counter;
            low[root] = counter;
            counter += 1;
            stack.push(root);
            on[root] = true;
            while let Some(&mut (v, ref mut ei)) = work.last_mut() {
                let succs: Vec<usize> = self.succ[v].iter().copied().filter(|&w| f[w]).collect();
                if *ei < succs.len() {
                    let w = succs[*ei];
                    *ei += 1;
                    if index[w] == usize::MAX {
                        index[w] = counter;
                        low[w] = counter;
                        counter += 1;
                        stack.push(w);
                        on[w] = true;
                        work.push((w, 0));
                    } else if on[w] {
                        low[v] = low[v].min(index[w]);
                    }
                } else {
                    if low[v] == index[v] {
                        loop {
                            let w = stack.pop().unwrap();
                            on[w] = false;
                            comp[w] = ncomp;
                            if w == v {
                                break;
                            }
                        }
                        ncomp += 1;
                    }
                    work.pop();
                    if let Some(&(p, _)) = work.last() {
                        low[p] = low[p].min(low[v]);
                    }
                }
            }
        }
        let mut members: Vec<Vec<usize>> = vec![vec![]; ncomp];
        for v in 0..n {
            if comp[v] != usize::MAX {
                members[comp[v]].push(v);
            }
        }
        let mut good = vec![false; n];
        for ms in &members {
            let nontrivial = ms.len() > 1 || self.succ[ms[0]].contains(&ms[0]);
            if !nontrivial {
                continue;
            }
            if self.fair_sets.iter().all(|fs| ms.iter().any(|&v| fs[v])) {
                for &v in ms {
                    good[v] = true;
                }
            }
        }
        // backward closure inside f
        let preds = self.pred_lists();
        let mut res = good.clone();
        let mut q: VecDeque<usize> = (0..n).filter(|&i| good[i]).collect();
        while let Some(v) = q.pop_front() {
            for &p in &preds[v] {
                if f[p] && !res[p] {
                    res[p] = true;
                    q.push_back(p);
                }
            }
        }
        res
    }

    pub fn fair(&mut self) -> Vec<bool> {
        if self.fair_states.is_none() {
            let all = vec![true; self.n()];
            self.fair_states = Some(self.eg_fair(&all));
        }
        self.fair_states.clone().unwrap()
    }

    fn eu(&mut self, f: &[bool], g: &[bool]) -> Vec<bool> {
        let fair = self.fair();
        let n = self.n();
        let preds = self.pred_lists();
        let mut res: Vec<bool> = (0..n).map(|i| g[i] && fair[i]).collect();
        let mut q: VecDeque<usize> = (0..n).filter(|&i| res[i]).collect();
        while let Some(v) = q.pop_front() {
            for &p in &preds[v] {
                if f[p] && !res[p] {
                    res[p] = true;
                    q.push_back(p);
                }
            }
        }
        res
    }

    fn ex(&mut self, f: &[bool]) -> Vec<bool> {
        let fair = self.fair();
        (0..self.n())
            .map(|i| self.succ[i].iter().any(|&j| f[j] && fair[j]))
            .collect()
    }

    fn not(f: &[bool]) -> Vec<bool> {
        f.iter().map(|b| !b).collect()
    }

    pub fn eval_ctl(&mut self, c: &Ctl<Vec<bool>>) -> Vec<bool> {
        let n = self.n();
        let all = vec![true; n];
        match c {
            Ctl::Atom(a) => a.clone(),
            Ctl::Not(x) => Self::not(&self.eval_ctl(x)),
            Ctl::And(a, b) => {
                let (x, y) = (self.eval_ctl(a), self.eval_ctl(b));
                (0..n).map(|i| x[i] && y[i]).collect()
            }
            Ctl::Or(a, b) => {
                let (x, y) = (self.eval_ctl(a), self.eval_ctl(b));
                (0..n).map(|i| x[i] || y[i]).collect()
            }
            Ctl::Imp(a, b) => {
                let (x, y) = (self.eval_ctl(a), self.eval_ctl(b));
                (0..n).map(|i| !x[i] || y[i]).collect()
            }
            Ctl::Iff(a, b) => {
                let (x, y) = (self.eval_ctl(a), self.eval_ctl(b));
                (0..n).map(|i| x[i] == y[i]).collect()
            }
            Ctl::Xor(a, b) => {
                let (x, y) = (self.eval_ctl(a), self.eval_ctl(b));
                (0..n).map(|i| x[i] != y[i]).collect()
            }
            Ctl::EX(a) => {
                let x = self.eval_ctl(a);
                self.ex(&x)
            }
            Ctl::AX(a) => {
                let x = Self::not(&self.eval_ctl(a));
                Self::not(&self.ex(&x))
            }
            Ctl::EF(a) => {
                let x = self.eval_ctl(a);
                self.eu(&all, &x)
            }
            Ctl::AF(a) => {
                let x = Self::not(&self.eval_ctl(a));
                Self::not(&self.eg_fair(&x))
            }
            Ctl::EG(a) => {
                let x = self.eval_ctl(a);
                self.eg_fair(&x)
            }
            Ctl::AG(a) => {
                let x = Self::not(&self.eval_ctl(a));
                Self::not(&self.eu(&all, &x))
            }
            Ctl::EU(a, b) => {
                let (x, y) = (self.eval_ctl(a), self.eval_ctl(b));
                self.eu(&x, &y)
            }
            Ctl::AU(a, b) => {
                let (f, g) = (self.eval_ctl(a), self.eval_ctl(b));
                let ng = Self::not(&g);
                let bad: Vec<bool> = (0..n).map(|i| !f[i] && !g[i]).collect();
                let e1 = self.eu(&ng, &bad);
                let e2 = self.eg_fair(&ng);
                (0..n).map(|i| !(e1[i] || e2[i])).collect()
            }
        }
    }

    // ------------------------------------------------------------------ spec-level helpers

    pub fn atom(&self, e: &Expr) -> Res<Vec<bool>> {
        let mut out = vec![];
        for s in &self.states {
            out.push(
                self.truthy(e, &Env { cur: s, nxt: None })
                    .map_err(|m| Error::new(e.pos, m))?,
            );
        }
        Ok(out)
    }

    pub fn check_ctl(&mut self, e: &Expr) -> Res<bool> {
        let c = lower_ctl(e, &mut |x| self.atom(x))?;
        let sat = self.eval_ctl(&c);
        Ok((0..self.n()).all(|i| !self.init[i] || sat[i]))
    }

    pub fn check_invar(&mut self, e: &Expr) -> Res<bool> {
        let p = self.atom(e)?;
        let (reach, _, _) = self.reachability();
        Ok((0..self.n()).all(|i| !reach[i] || p[i]))
    }

    /// LTL formulas in the fragment that coincides with ACTL (under fair-path semantics) are decided
    /// via their CTL translation: `G p`, `F p`, `X p`, `p U q`, `G F p`, `G (p -> F q)`.
    pub fn check_ltl_fragment(&mut self, e: &Expr) -> Res<Option<bool>> {
        let l = lower_ltl(e, &mut |x| self.atom(x))?;
        let b = Box::new;
        let c: Option<Ctl<Vec<bool>>> = match l {
            Ltl::G(x) => match *x {
                Ltl::Atom(p) => Some(Ctl::AG(b(Ctl::Atom(p)))),
                Ltl::F(y) => match *y {
                    Ltl::Atom(p) => Some(Ctl::AG(b(Ctl::AF(b(Ctl::Atom(p)))))),
                    _ => None,
                },
                Ltl::Imp(p, q) => match (*p, *q) {
                    (Ltl::Atom(p), Ltl::F(q)) => match *q {
                        Ltl::Atom(q) => Some(Ctl::AG(b(Ctl::Imp(
                            b(Ctl::Atom(p)),
                            b(Ctl::AF(b(Ctl::Atom(q)))),
                        )))),
                        _ => None,
                    },
                    _ => None,
                },
                _ => None,
            },
            Ltl::F(x) => match *x {
                Ltl::Atom(p) => Some(Ctl::AF(b(Ctl::Atom(p)))),
                _ => None,
            },
            Ltl::X(x) => match *x {
                Ltl::Atom(p) => Some(Ctl::AX(b(Ctl::Atom(p)))),
                _ => None,
            },
            Ltl::U(p, q) => match (*p, *q) {
                (Ltl::Atom(p), Ltl::Atom(q)) => Some(Ctl::AU(b(Ctl::Atom(p)), b(Ctl::Atom(q)))),
                _ => None,
            },
            _ => None,
        };
        Ok(c.map(|c| {
            let sat = self.eval_ctl(&c);
            (0..self.n()).all(|i| !self.init[i] || sat[i])
        }))
    }

    pub fn fair_count(&mut self) -> usize {
        self.fair().iter().filter(|&&b| b).count()
    }

    pub fn init_count(&self) -> usize {
        self.init.iter().filter(|&&b| b).count()
    }

    fn parse_val(s: &str) -> EV {
        match s {
            "TRUE" => EV::B(true),
            "FALSE" => EV::B(false),
            _ => match s.parse::<i64>() {
                Ok(n) => EV::I(n),
                Err(_) => EV::S(s.to_string()),
            },
        }
    }

    fn trace_valuations(&self, t: &Trace) -> Vec<(Valuation, Valuation)> {
        // (state valuation, valuation including this step's inputs)
        let mut out = vec![];
        for s in &t.steps {
            let mut v = vec![EV::B(false); self.vars.len()];
            for (name, val) in &s.state {
                v[self.var_ix[name]] = Self::parse_val(val);
            }
            let mut with_inputs = v.clone();
            for (name, val) in &s.inputs {
                with_inputs[self.var_ix[name]] = Self::parse_val(val);
            }
            out.push((v, with_inputs));
        }
        out
    }

    /// Validate that a trace is a real execution: initial first state, legal states, every step a
    /// transition (with the reported inputs), and the loop-back step for lassos.
    pub fn validate_trace(&self, t: &Trace) -> Result<(), String> {
        let vs = self.trace_valuations(t);
        if vs.is_empty() {
            return Err("empty trace".into());
        }
        for (s, _) in &vs {
            if !self.index.contains_key(s) {
                return Err(format!("trace state {:?} is not a legal state", s));
            }
        }
        let first = self.index[&vs[0].0];
        if !self.init[first] {
            return Err("first state is not initial".into());
        }
        for i in 0..vs.len() {
            let succ = if i + 1 < vs.len() {
                Some(&vs[i + 1].0)
            } else {
                t.loop_start.map(|l| &vs[l].0)
            };
            if let Some(nx) = succ {
                let cur = &vs[i].1;
                let is_stutter =
                    self.stutter && &vs[i].0 == nx && self.deadlocked[self.index[&vs[i].0]];
                if !self.inputs_ok(cur)? || !(is_stutter || self.trans_ok(cur, nx)?) {
                    return Err(format!("step {} -> next is not a transition", i + 1));
                }
            }
        }
        Ok(())
    }

    /// Does every fairness constraint hold somewhere in the loop of this lasso?
    pub fn lasso_is_fair(&self, t: &Trace) -> bool {
        let l = match t.loop_start {
            Some(l) => l,
            None => return false,
        };
        let vs = self.trace_valuations(t);
        self.prog.fairness.iter().all(|f| {
            vs[l..]
                .iter()
                .any(|(s, _)| self.truthy(f, &Env { cur: s, nxt: None }).unwrap_or(false))
        })
    }

    pub fn eval_state_expr(&self, e: &Expr, state: &[(String, String)]) -> Result<bool, String> {
        let mut v = vec![EV::B(false); self.vars.len()];
        for (name, val) in state {
            v[self.var_ix[name]] = Self::parse_val(val);
        }
        self.truthy(e, &Env { cur: &v, nxt: None })
    }
}
