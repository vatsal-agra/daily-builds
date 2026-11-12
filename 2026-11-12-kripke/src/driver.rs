//! Orchestration: parse → compile → (reorder) → analyse → check every spec.

use crate::bdd::{Bdd, FALSE};
use crate::check::{Checker, Stats, Trace, Verdict};
use crate::lang::*;
use crate::ltl;
use crate::model::Model;
use crate::temporal::lower_ctl;
use std::time::Instant;

#[derive(Clone, Debug, Default)]
pub struct Options {
    /// Allow assignments that can leave a variable's type (the offending transitions are disabled).
    pub lax: bool,
    /// Run dynamic sifting after compilation.
    pub reorder: bool,
    /// Collect garbage at every opportunity (testing aid).
    pub gc_stress: bool,
}

#[derive(Clone, Debug)]
pub struct SpecOutcome {
    pub label: String,
    pub kind: SpecKind,
    pub text: String,
    pub verdict: Verdict,
    pub micros: u128,
    pub pos: Pos,
}

#[derive(Clone, Debug, Default)]
pub struct ModelInfo {
    pub state_vars: usize,
    pub input_vars: usize,
    pub state_bits: usize,
    pub input_bits: usize,
    pub init_states: u128,
    pub reachable: u128,
    pub diameter: usize,
    pub deadlocks: u128,
    pub deadlock_example: Option<Trace>,
    pub fair_constraints: usize,
    pub fair_states: u128,
    pub trans_nodes: usize,
    pub init_nodes: usize,
    pub reach_nodes: usize,
    pub reorder: Option<(usize, usize, usize)>, // (nodes before, after, swaps)
    pub order: Vec<String>,
    pub gc_runs: usize,
    pub stats: Stats,
    pub warnings: Vec<String>,
    pub total_micros: u128,
}

#[derive(Clone, Debug)]
pub struct Report {
    pub info: ModelInfo,
    pub outcomes: Vec<SpecOutcome>,
}

impl Report {
    pub fn all_hold(&self) -> bool {
        self.outcomes.iter().all(|o| o.verdict == Verdict::Holds)
    }
}

pub fn bit_names(md: &Model) -> Vec<String> {
    let mut names = vec![String::new(); md.m.num_vars()];
    for v in &md.vars {
        for (i, &b) in v.cur.iter().enumerate() {
            names[b as usize] = if v.cur.len() == 1 { v.name.clone() } else { format!("{}.{}", v.name, i) };
        }
        for (i, &b) in v.nxt.iter().enumerate() {
            names[b as usize] = if v.nxt.len() == 1 { format!("{}'", v.name) } else { format!("{}.{}'", v.name, i) };
        }
    }
    names
}

/// Reorder with {x, x'} pairs kept adjacent. Returns (before, after, swaps).
pub fn reorder(md: &mut Model) -> (usize, usize, usize) {
    // blocks: one per state bit (cur, nxt adjacent in the initial order), singletons for input bits
    let mut blocks: Vec<Vec<u32>> = vec![];
    for v in &md.vars {
        for (i, &c) in v.cur.iter().enumerate() {
            if v.input {
                blocks.push(vec![c]);
            } else {
                blocks.push(vec![c, v.nxt[i]]);
            }
        }
    }
    let mut roots = vec![md.init, md.trans, md.space];
    roots.extend(md.fair.iter().copied());
    let swaps0 = md.m.swaps;
    let (b, a) = md.m.sift_blocks(&blocks, &roots);
    (b, a, md.m.swaps - swaps0)
}

pub fn spec_text(s: &Spec) -> String {
    format!("{}", s.expr)
}

pub fn spec_label(s: &Spec, ix: usize) -> String {
    match &s.name {
        Some(n) => n.clone(),
        None => format!("spec{}", ix + 1),
    }
}

pub fn run(src: &str, opts: &Options) -> Res<Report> {
    let t0 = Instant::now();
    let prog = parse(src)?;
    run_program(&prog, opts, t0)
}

pub fn run_program(prog: &Program, opts: &Options, t0: Instant) -> Res<Report> {
    let mut md = Model::compile(prog.clone(), opts.lax)?;
    md.m.gc_stress = opts.gc_stress;
    let mut info = ModelInfo::default();
    if opts.reorder {
        info.reorder = Some(reorder(&mut md));
    }
    info.state_vars = md.vars.iter().filter(|v| !v.input).count();
    info.input_vars = md.vars.iter().filter(|v| v.input).count();
    info.state_bits = md.cur_vars.len();
    info.input_bits = md.inp_vars.len();
    info.fair_constraints = md.fair.len();
    // ---- pre-lower specs so atom compilation errors surface before any heavy work
    enum Lowered {
        Ctl(crate::temporal::Ctl<Bdd>),
        Invar(Bdd),
        Ltl,
    }
    let mut lowered = vec![];
    for s in &prog.specs {
        match s.kind {
            SpecKind::Invar => {
                if s.expr.is_temporal() {
                    return Err(Error::new(s.expr.pos, "INVARSPEC must be a plain state predicate"));
                }
                let a = md.atom(&s.expr)?;
                md.m.pin(a);
                lowered.push(Lowered::Invar(a));
            }
            SpecKind::Ctl => {
                let md_ref = &mut md;
                let c = lower_ctl(&s.expr, &mut |e| {
                    let a = md_ref.atom(e)?;
                    Ok(md_ref.m.pin(a))
                })?;
                lowered.push(Lowered::Ctl(c));
            }
            SpecKind::Ltl => {
                // validate now (atoms compile against this model); checked later in a product model
                let md_ref = &mut md;
                crate::temporal::lower_ltl(&s.expr, &mut |e| md_ref.atom(e))?;
                lowered.push(Lowered::Ltl);
            }
        }
    }
    let mut outcomes = vec![];
    {
        let mut ck = Checker::new(&mut md);
        let init = ck.md.init;
        info.init_states = ck.md.count_states(init);
        if init == FALSE {
            info.warnings.push("the initial-state set is empty: every universal property holds vacuously".to_string());
        }
        let (rset, diam) = {
            let r = ck.reach();
            (r.set, r.layers.len() - 1)
        };
        info.reachable = ck.md.count_states(rset);
        info.diameter = diam;
        info.reach_nodes = ck.md.m.dag_size(&[rset]);
        let dead = ck.deadlocks();
        info.deadlocks = ck.md.count_states(dead);
        if dead != FALSE {
            let s = ck.pick_state(dead);
            // shortest path from init to this deadlock
            let to = s;
            let sp = ck.md.space;
            let init = ck.md.init;
            let init_state = ck.pick_state(init);
            let _ = init_state;
            let mut best: Option<Vec<Bdd>> = None;
            // search from the whole initial set: use layers of reach to find the shortest prefix
            let layers = ck.reach().layers.clone();
            for (i, &l) in layers.iter().enumerate() {
                let hit = ck.md.m.and(l, dead);
                if hit != FALSE {
                    let mut path = vec![FALSE; i + 1];
                    path[i] = ck.pick_state(hit);
                    for j in (0..i).rev() {
                        let pr = ck.md.preimage(path[j + 1]);
                        let cand = ck.md.m.and(pr, layers[j]);
                        path[j] = ck.pick_state(cand);
                    }
                    best = Some(path);
                    break;
                }
            }
            let _ = (to, sp);
            if let Some(p) = best {
                info.deadlock_example = Some(ck.to_trace(&p, None));
            }
        }
        let fair = ck.fair();
        info.fair_states = ck.md.count_states(fair);
        if info.fair_states == 0 && init != FALSE {
            info.warnings.push("no state has an infinite (fair) path: CTL formulas with path quantifiers are decided over an empty set of paths".to_string());
        }
        for (i, s) in prog.specs.iter().enumerate() {
            let t = Instant::now();
            let verdict = match &lowered[i] {
                Lowered::Invar(p) => ck.check_invariant(*p),
                Lowered::Ctl(c) => ck.check_ctl(c),
                Lowered::Ltl => Verdict::Holds, // placeholder, replaced below
            };
            outcomes.push(SpecOutcome {
                label: spec_label(s, i),
                kind: s.kind,
                text: spec_text(s),
                verdict,
                micros: t.elapsed().as_micros(),
                pos: s.pos,
            });
        }
        info.stats = ck.stats.clone();
        info.trans_nodes = ck.md.m.dag_size(&[ck.md.trans]);
        info.init_nodes = ck.md.m.dag_size(&[ck.md.init]);
    }
    // LTL specs get their own product models
    for (i, s) in prog.specs.iter().enumerate() {
        if let Lowered::Ltl = &lowered[i] {
            let t = Instant::now();
            let r = ltl::check(prog, &s.expr, opts.lax)?;
            outcomes[i].verdict = r.verdict;
            outcomes[i].micros = t.elapsed().as_micros();
            info.stats.fixpoint_iterations += r.stats.fixpoint_iterations;
            info.stats.images += r.stats.images;
        }
    }
    info.order = md.m.order().iter().map(|&v| bit_names(&md)[v as usize].clone()).collect();
    info.gc_runs = md.m.gc_runs;
    info.warnings.extend(md.warnings.clone());
    info.total_micros = t0.elapsed().as_micros();
    Ok(Report { info, outcomes })
}
