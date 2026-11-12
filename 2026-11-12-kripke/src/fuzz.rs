//! Random model generator and symbolic-vs-explicit differential checker.

use crate::check::Verdict;
use crate::driver::{run_program, Options};
use crate::explicit::Explicit;
use crate::lang::*;
use std::time::Instant;

pub struct Rng(pub u64);

impl Rng {
    pub fn next(&mut self) -> u64 {
        // xorshift64*
        let mut x = self.0;
        x ^= x >> 12;
        x ^= x << 25;
        x ^= x >> 27;
        self.0 = x;
        x.wrapping_mul(0x2545F4914F6CDD1D)
    }

    pub fn below(&mut self, n: usize) -> usize {
        (self.next() % n as u64) as usize
    }

    pub fn chance(&mut self, num: usize, den: usize) -> bool {
        self.below(den) < num
    }

    fn pick<'a, T>(&mut self, xs: &'a [T]) -> &'a T {
        &xs[self.below(xs.len())]
    }
}

const SYMS: [&str; 3] = ["x", "y", "z"];

struct Gen<'a> {
    r: &'a mut Rng,
    has_input: bool,
    /// Inputs may only appear in transition contexts.
    allow: bool,
}

impl<'a> Gen<'a> {
    fn bvar(&mut self) -> String {
        if self.has_input && self.allow && self.r.chance(1, 5) {
            "iv".to_string()
        } else {
            format!("b{}", self.r.below(3))
        }
    }

    fn int(&mut self, depth: usize, next_ok: bool) -> String {
        match self.r.below(if depth == 0 { 3 } else { 5 }) {
            0 => "r".to_string(),
            1 => format!("{}", self.r.below(4)),
            2 => {
                if self.has_input && self.allow && self.r.chance(1, 3) {
                    "ir".to_string()
                } else if next_ok && self.r.chance(1, 4) {
                    "next(r)".to_string()
                } else {
                    "r".to_string()
                }
            }
            3 => format!(
                "(({} + {}) mod 4)",
                self.int(depth - 1, next_ok),
                self.int(depth - 1, next_ok)
            ),
            _ => format!(
                "(({} * {}) mod 4)",
                self.int(depth - 1, next_ok),
                self.int(depth - 1, next_ok)
            ),
        }
    }

    fn boolean(&mut self, depth: usize, next_ok: bool) -> String {
        let leaf = depth == 0;
        match self.r.below(if leaf { 6 } else { 13 }) {
            0 => self.bvar(),
            1 => {
                if next_ok && self.r.chance(1, 3) {
                    format!("next(b{})", self.r.below(3))
                } else {
                    self.bvar()
                }
            }
            2 => format!(
                "(r {} {})",
                self.r.pick(&["=", "!=", "<", "<=", ">", ">="]),
                self.r.below(4)
            ),
            3 => format!("(e {} {})", self.r.pick(&["=", "!="]), self.r.pick(&SYMS)),
            4 => ["TRUE", "FALSE"][self.r.below(2)].to_string(),
            5 => format!("(r in {{{}, {}}})", self.r.below(4), self.r.below(4)),
            6 => format!("(!{})", self.boolean(depth - 1, next_ok)),
            7 => format!(
                "({} & {})",
                self.boolean(depth - 1, next_ok),
                self.boolean(depth - 1, next_ok)
            ),
            8 => format!(
                "({} | {})",
                self.boolean(depth - 1, next_ok),
                self.boolean(depth - 1, next_ok)
            ),
            9 => format!(
                "({} -> {})",
                self.boolean(depth - 1, next_ok),
                self.boolean(depth - 1, next_ok)
            ),
            10 => format!(
                "({} <-> {})",
                self.boolean(depth - 1, next_ok),
                self.boolean(depth - 1, next_ok)
            ),
            11 => format!(
                "({} {} {})",
                self.int(depth - 1, next_ok),
                self.r.pick(&["=", "<", "<=", "!="]),
                self.int(depth - 1, next_ok)
            ),
            _ => format!(
                "({} xor {})",
                self.boolean(depth - 1, next_ok),
                self.boolean(depth - 1, next_ok)
            ),
        }
    }

    fn bool_value(&mut self) -> String {
        match self.r.below(5) {
            0 => "{TRUE, FALSE}".to_string(),
            1 => self.boolean(1, false),
            2 => "TRUE".to_string(),
            3 => "FALSE".to_string(),
            _ => self.bvar(),
        }
    }

    fn int_value(&mut self) -> String {
        match self.r.below(4) {
            0 => format!("{{{}, {}}}", self.r.below(4), self.r.below(4)),
            1 => self.int(2, false),
            2 => format!("{}", self.r.below(4)),
            _ => format!(
                "{{{}, {}, {}}}",
                self.r.below(4),
                self.r.below(4),
                self.r.below(4)
            ),
        }
    }

    fn sym_value(&mut self) -> String {
        match self.r.below(3) {
            0 => format!("{{{}, {}}}", self.r.pick(&SYMS), self.r.pick(&SYMS)),
            1 => "e".to_string(),
            _ => self.r.pick(&SYMS).to_string(),
        }
    }

    fn case_of(&mut self, value: &mut dyn FnMut(&mut Self) -> String) -> String {
        let arms = self.r.below(3);
        let mut s = String::from("case ");
        for _ in 0..arms {
            let c = self.boolean(2, false);
            let v = value(self);
            s.push_str(&format!("{} : {}; ", c, v));
        }
        let v = value(self);
        s.push_str(&format!("TRUE : {}; esac", v));
        s
    }

    fn ctl(&mut self, depth: usize) -> String {
        if depth == 0 {
            return self.boolean(1, false);
        }
        match self.r.below(14) {
            0 => format!("EX {}", self.paren_ctl(depth - 1)),
            1 => format!("AX {}", self.paren_ctl(depth - 1)),
            2 => format!("EF {}", self.paren_ctl(depth - 1)),
            3 => format!("AF {}", self.paren_ctl(depth - 1)),
            4 => format!("EG {}", self.paren_ctl(depth - 1)),
            5 => format!("AG {}", self.paren_ctl(depth - 1)),
            6 => format!("E[{} U {}]", self.ctl(depth - 1), self.ctl(depth - 1)),
            7 => format!("A[{} U {}]", self.ctl(depth - 1), self.ctl(depth - 1)),
            8 => format!("({} & {})", self.ctl(depth - 1), self.ctl(depth - 1)),
            9 => format!("({} | {})", self.ctl(depth - 1), self.ctl(depth - 1)),
            10 => format!("({} -> {})", self.ctl(depth - 1), self.ctl(depth - 1)),
            11 => format!("(!{})", self.paren_ctl(depth - 1)),
            12 => format!(
                "AG ({} -> AF {})",
                self.boolean(1, false),
                self.paren_ctl(depth - 1)
            ),
            _ => format!("({} <-> {})", self.ctl(depth - 1), self.ctl(depth - 1)),
        }
    }

    fn paren_ctl(&mut self, depth: usize) -> String {
        format!("({})", self.ctl(depth))
    }
}

/// Generate a random small model with a mix of CTL, invariant and LTL specs.
pub fn gen_model(seed: u64) -> String {
    let mut rng = Rng(seed.wrapping_mul(0x9E3779B97F4A7C15) | 1);
    for _ in 0..4 {
        rng.next();
    }
    let has_input = rng.chance(1, 2);
    let mut g = Gen {
        r: &mut rng,
        has_input,
        allow: false,
    };
    let mut s = String::from("MODULE main\n");
    if has_input {
        s.push_str("IVAR iv : boolean;\n     ir : 0..2;\n");
    }
    s.push_str("VAR b0 : boolean; b1 : boolean; b2 : boolean;\n    r : 0..3;\n    e : {x, y, z};\nASSIGN\n");
    for v in ["b0", "b1", "b2"] {
        if g.r.chance(2, 3) {
            let x = g.bool_value();
            s.push_str(&format!("  init({}) := {};\n", v, x));
        }
        if g.r.chance(4, 5) {
            g.allow = true;
            let c = g.case_of(&mut |g| g.bool_value());
            g.allow = false;
            s.push_str(&format!("  next({}) := {};\n", v, c));
        }
    }
    if g.r.chance(2, 3) {
        let x = g.int_value();
        s.push_str(&format!("  init(r) := {};\n", x));
    }
    if g.r.chance(4, 5) {
        g.allow = true;
        let c = g.case_of(&mut |g| g.int_value());
        g.allow = false;
        s.push_str(&format!("  next(r) := {};\n", c));
    }
    if g.r.chance(2, 3) {
        let x = g.sym_value();
        s.push_str(&format!("  init(e) := {};\n", x));
    }
    if g.r.chance(4, 5) {
        g.allow = true;
        let c = g.case_of(&mut |g| g.sym_value());
        g.allow = false;
        s.push_str(&format!("  next(e) := {};\n", c));
    }
    if g.r.chance(1, 4) {
        let c = g.boolean(2, false);
        s.push_str(&format!("INIT {}\n", c));
    }
    if g.r.chance(1, 4) {
        g.allow = true;
        let c = g.boolean(2, true);
        g.allow = false;
        s.push_str(&format!("TRANS {}\n", c));
    }
    if g.r.chance(1, 5) {
        let c = g.boolean(2, false);
        s.push_str(&format!("INVAR {}\n", c));
    }
    let nfair = g.r.below(3);
    for _ in 0..nfair {
        let c = g.boolean(1, false);
        s.push_str(&format!("FAIRNESS {}\n", c));
    }
    for _ in 0..5 {
        let c = g.ctl(3);
        s.push_str(&format!("SPEC {}\n", c));
    }
    for _ in 0..2 {
        let c = g.boolean(2, false);
        s.push_str(&format!("INVARSPEC {}\n", c));
    }
    // LTL patterns in the ACTL-equivalent fragment (so the explicit oracle can decide them)
    for _ in 0..2 {
        let (p, q) = (g.boolean(1, false), g.boolean(1, false));
        let f = match g.r.below(6) {
            0 => format!("G ({})", p),
            1 => format!("F ({})", p),
            2 => format!("X ({})", p),
            3 => format!("({}) U ({})", p, q),
            4 => format!("G F ({})", p),
            _ => format!("G (({}) -> F ({}))", p, q),
        };
        s.push_str(&format!("LTLSPEC {}\n", f));
    }
    // and two LTL formulas outside that fragment: only checked for trace validity
    let (p, q) = (g.boolean(1, false), g.boolean(1, false));
    s.push_str(&format!("LTLSPEC F G ({})\n", p));
    s.push_str(&format!("LTLSPEC G (({}) -> X ({}))\n", p, q));
    s
}

/// Cross-check one model. Returns a list of mismatches (empty = agreement).
pub fn cross_check(src: &str, rng: &mut Rng) -> Result<Vec<String>, String> {
    let prog =
        parse(src).map_err(|e| format!("generated model does not parse: {} \n{}", e, src))?;
    let opts = Options {
        lax: false,
        reorder: rng.chance(1, 2),
        gc_stress: rng.chance(1, 3),
        stutter: rng.chance(1, 3),
    };
    let report = run_program(&prog, &opts, Instant::now())
        .map_err(|e| format!("generated model does not compile: {}\n{}", e, src))?;
    let mut ex =
        Explicit::new(&prog, 4096, opts.stutter).map_err(|e| format!("explicit: {}", e))?;
    let mut bad = vec![];
    let (reach, diam, dead) = ex.reachability();
    let nreach = reach.iter().filter(|&&b| b).count() as u128;
    if report.info.reachable != nreach {
        bad.push(format!(
            "reachable: symbolic {} vs explicit {}",
            report.info.reachable, nreach
        ));
    }
    if nreach > 0 && report.info.diameter != diam {
        bad.push(format!(
            "diameter: symbolic {} vs explicit {}",
            report.info.diameter, diam
        ));
    }
    if report.info.deadlocks != dead as u128 {
        bad.push(format!(
            "deadlocks: symbolic {} vs explicit {}",
            report.info.deadlocks, dead
        ));
    }
    if report.info.init_states != ex.init_count() as u128 {
        bad.push(format!(
            "init states: symbolic {} vs explicit {}",
            report.info.init_states,
            ex.init_count()
        ));
    }
    if report.info.fair_states != ex.fair_count() as u128 {
        bad.push(format!(
            "fair states: symbolic {} vs explicit {}",
            report.info.fair_states,
            ex.fair_count()
        ));
    }
    if let Some(t) = &report.info.deadlock_example {
        if let Err(m) = ex.validate_trace(t) {
            bad.push(format!("deadlock trace invalid: {}", m));
        }
    }
    for (i, sp) in prog.specs.iter().enumerate() {
        let o = &report.outcomes[i];
        let sym = o.verdict == Verdict::Holds;
        let exp = match sp.kind {
            SpecKind::Ctl => Some(ex.check_ctl(&sp.expr).map_err(|e| e.to_string())?),
            SpecKind::Invar => Some(ex.check_invar(&sp.expr).map_err(|e| e.to_string())?),
            SpecKind::Ltl => ex.check_ltl_fragment(&sp.expr).map_err(|e| e.to_string())?,
        };
        if let Some(exp) = exp {
            if exp != sym {
                bad.push(format!(
                    "spec {} `{}`: symbolic {} vs explicit {}",
                    i + 1,
                    o.text,
                    sym,
                    exp
                ));
            }
        }
        if let Verdict::Fails(Some(t)) = &o.verdict {
            if let Err(m) = ex.validate_trace(t) {
                bad.push(format!(
                    "spec {} `{}`: invalid counterexample: {}",
                    i + 1,
                    o.text,
                    m
                ));
            }
            if matches!(sp.kind, SpecKind::Ltl) {
                // every LTL counterexample must be a lasso whose loop is fair
                if t.loop_start.is_none() || !ex.lasso_is_fair(t) {
                    bad.push(format!(
                        "spec {} `{}`: LTL counterexample is not a fair lasso",
                        i + 1,
                        o.text
                    ));
                }
            }
            if matches!(sp.kind, SpecKind::Invar) {
                let last = t.steps.last().unwrap();
                if ex.eval_state_expr(&sp.expr, &last.state).unwrap_or(true) {
                    bad.push(format!(
                        "spec {} `{}`: invariant counterexample's last state satisfies it",
                        i + 1,
                        o.text
                    ));
                }
            }
            // `AG p` / `AF p` with an atomic body have easily checked traces
            if sp.kind == SpecKind::Ctl {
                if let Ek::Un(op @ (UnOp::AG | UnOp::AF), body) = &sp.expr.k {
                    if !body.is_temporal() {
                        if *op == UnOp::AG {
                            let last = t.steps.last().unwrap();
                            if ex.eval_state_expr(body, &last.state).unwrap_or(true) {
                                bad.push(format!("spec {}: AG counterexample ends in a state satisfying the body", i + 1));
                            }
                        } else {
                            if t.loop_start.is_none() || !ex.lasso_is_fair(t) {
                                bad.push(format!(
                                    "spec {}: AF counterexample is not a fair lasso",
                                    i + 1
                                ));
                            }
                            for s in &t.steps {
                                if ex.eval_state_expr(body, &s.state).unwrap_or(true) {
                                    bad.push(format!("spec {}: AF counterexample visits a state satisfying the body", i + 1));
                                    break;
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    Ok(bad)
}
