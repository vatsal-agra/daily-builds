//! Differential fuzzing: generate random mutator programs (aliasing, cycles, vectors, strings,
//! forced collections) and demand that every collector — under the oracle, optionally under
//! torture — prints exactly what a collector-free reference run prints.

use crate::vm::{run_source, VmOptions};
use crate::{GcConfig, ALL_GCS};

struct Rng(u64);
impl Rng {
    fn next(&mut self) -> u64 {
        let mut x = self.0;
        x ^= x >> 12;
        x ^= x << 25;
        x ^= x >> 27;
        self.0 = x;
        x.wrapping_mul(0x2545F4914F6CDD1D) >> 11
    }
    fn below(&mut self, n: u64) -> u64 {
        self.next() % n
    }
    fn pick<'a>(&mut self, xs: &[&'a str]) -> &'a str {
        xs[self.below(xs.len() as u64) as usize]
    }
}

const NG: u64 = 8;

const PRELUDE: &str = r#"
(fn (scar x) (if (pair? x) (car x) nil))
(fn (scdr x) (if (pair? x) (cdr x) nil))
(fn (ssetcar p v) (if (pair? p) (set-car! p v) nil))
(fn (ssetcdr p v) (if (pair? p) (set-cdr! p v) nil))
(fn (svref v i) (if (and (vector? v) (> (vlen v) 0)) (vref v (% i (vlen v))) nil))
(fn (svset v i x) (if (and (vector? v) (> (vlen v) 0)) (vset! v (% i (vlen v)) x) nil))
(fn (sstr x) (if (string? x) x "?"))
"#;

fn expr(r: &mut Rng, depth: u32) -> String {
    let g = |r: &mut Rng| format!("g{}", r.below(NG));
    if depth == 0 {
        return match r.below(5) {
            0 => format!("{}", r.below(100) as i64 - 20),
            1 => "nil".into(),
            2 => "i".into(),
            _ => g(r),
        };
    }
    match r.below(12) {
        0 | 1 => format!("(cons {} {})", expr(r, depth - 1), expr(r, depth - 1)),
        2 => format!("(scar {})", expr(r, depth - 1)),
        3 => format!("(scdr {})", expr(r, depth - 1)),
        4 => format!("(vector {} {})", 1 + r.below(24), expr(r, depth - 1)),
        5 => format!("(svref {} {})", expr(r, depth - 1), expr(r, 0)),
        6 => format!("(strcat (sstr {}) (str {}))", g(r), r.below(1000)),
        7 => format!("(str {})", r.below(100000)),
        8 => format!("(vector {})", r.below(4)),
        9 => format!("(+ {} 1)", r.pick(&["i", "7", "(rand 50)"])),
        _ => expr(r, 0),
    }
}

fn stmt(r: &mut Rng) -> String {
    let g = format!("g{}", r.below(NG));
    match r.below(27) {
        0..=4 => format!("(set! {g} {})", expr(r, 3)),
        5 | 6 => format!("(ssetcar {g} {})", expr(r, 2)),
        7 | 8 => format!("(ssetcdr {g} {})", expr(r, 2)),
        9 | 10 => format!("(svset {g} (rand 40) {})", expr(r, 2)),
        11 => format!("(set! {g} g{})", r.below(NG)),
        12 => format!("(let ((t {})) (set! {g} (cons t t)))", expr(r, 2)),
        13 => format!("(ssetcdr {g} {g})"), // self cycle
        14 => "(gc)".to_string(),
        15 => "(gc-minor)".to_string(),
        16 => format!("(set! {g} nil)"),
        17 => format!("(when (< (rand 100) 30) (set! {g} {}))", expr(r, 2)),
        18 => format!("(print (digest {g}))"),
        // hoist: load a child, delete the heap reference, keep only a root — the SATB hazard
        19..=21 => format!("(let ((t (scar {g}))) (ssetcar {g} nil) (set! g{} t))", r.below(NG)),
        23 | 24 => "(gc-begin)".to_string(),
        25 => format!(
            "(begin (gc-begin) (let ((t (scar {g}))) (ssetcar {g} nil) (set! g{} t)))",
            r.below(NG)
        ),
        22 => format!("(let ((t (scdr {g}))) (ssetcdr {g} nil) (set! g{} t))", r.below(NG)),
        _ => format!("(let ((junk {})) (set! junk (cons junk junk)))", expr(r, 3)),
    }
}

pub fn gen_program(seed: u64) -> String {
    let mut r = Rng(seed.wrapping_mul(0x9E3779B97F4A7C15) | 1);
    for _ in 0..4 {
        r.next();
    }
    let mut s = String::from(PRELUDE);
    for i in 0..NG {
        s.push_str(&format!("(def g{i} nil)\n"));
    }
    // ballast: a long untouched chain held by the *last* global, so a collector that scans roots
    // last-to-first spends a long time in it while the mutator shuffles the other globals
    let ballast = 80 + r.below(170);
    s.push_str(&format!(
        "(def ballast nil)\n(let ((k 0)) (while (< k {ballast}) (set! ballast (cons k ballast)) (set! k (+ k 1))))\n"
    ));
    let iters = 30 + r.below(120);
    s.push_str(&format!("(let ((i 0)) (while (< i {iters})\n"));
    let n = 4 + r.below(8);
    for _ in 0..n {
        s.push_str("  ");
        s.push_str(&stmt(&mut r));
        s.push('\n');
    }
    s.push_str("  (set! i (+ i 1))))\n");
    for i in 0..NG {
        s.push_str(&format!("(print \"g{i}\" (digest g{i}))\n"));
    }
    s.push_str("(print \"ballast\" (digest ballast))\n");
    s
}

#[derive(Debug)]
pub struct Failure {
    pub seed: u64,
    pub collector: String,
    pub mode: &'static str,
    pub detail: String,
    pub program: String,
}

/// The reference run: the program on a heap so large it never collects.
fn reference(prog: &str) -> Result<String, String> {
    let cfg = GcConfig {
        words: 4_000_000,
        nursery: 1 << 20,
        ..Default::default()
    };
    run_source(prog, "marksweep", &cfg, VmOptions::default()).map(|(o, _)| o)
}

pub fn check_seed(seed: u64, cfg: &GcConfig, collectors: &[&str], torture: bool) -> Result<(), Box<Failure>> {
    let prog = gen_program(seed);
    // vary the incremental collector's pacing so marking overlaps the mutator in different ways
    let mut cfg = cfg.clone();
    cfg.pace = [1, 3, 9][(seed % 3) as usize];
    cfg.trigger = [0.08, 0.35, 0.6][((seed / 3) % 3) as usize];
    let cfg = &cfg;
    let want = match reference(&prog) {
        Ok(o) => o,
        // programs that legitimately error (e.g. out of reference memory) are not interesting
        Err(_) => return Ok(()),
    };
    for g in collectors {
        let mut modes: Vec<(&'static str, bool)> = vec![("verify", false)];
        if torture {
            modes.push(("verify+torture", true));
        }
        for (mode, tort) in modes {
            let opts = VmOptions {
                verify: true,
                torture: tort,
                ..Default::default()
            };
            let got = run_source(&prog, g, cfg, opts);
            let bad = match &got {
                Ok((o, _)) if *o == want => None,
                Ok((o, _)) => Some(format!("output differs from reference:\n--- want\n{want}--- got\n{o}")),
                Err(e) => Some(e.clone()),
            };
            if let Some(detail) = bad {
                return Err(Box::new(Failure {
                    seed,
                    collector: g.to_string(),
                    mode,
                    detail,
                    program: prog,
                }));
            }
        }
    }
    Ok(())
}

pub fn fuzz(iters: u64, start_seed: u64, cfg: &GcConfig, collectors: &[&str], torture: bool) -> Result<u64, Box<Failure>> {
    for k in 0..iters {
        check_seed(start_seed + k, cfg, collectors, torture)?;
    }
    Ok(iters)
}

pub fn default_collectors() -> Vec<&'static str> {
    ALL_GCS.to_vec()
}

pub fn fuzz_cfg() -> GcConfig {
    GcConfig {
        words: 12000,
        nursery: 900,
        barrier: true,
        trigger: 0.35,
        pace: 3,
    }
}
