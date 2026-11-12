use kripke::driver::{run, Options};
use kripke::report::{render_report, RenderOpts};
use std::process::exit;

const USAGE: &str = "\
kripke — a symbolic model checker (BDDs, CTL, LTL, fairness)

USAGE
  kripke check FILE [options]      check every SPEC / LTLSPEC / INVARSPEC in FILE
  kripke FILE [options]            same as `check`
  kripke explicit FILE             cross-check FILE against the independent explicit-state engine
  kripke gen NAME N                print a generated model (philosophers, tokenring, counter, ...)
  kripke fuzz [--count N] [--seed S]   differential-test the symbolic engine on random models
  kripke dot FILE WHAT             Graphviz of a BDD: init | trans | reach
  kripke sim FILE [--steps N] [--seed S]   print a random execution
  kripke help

OPTIONS (check)
  --reorder          dynamic variable reordering (pair-preserving sifting) before checking
  --stutter          give deadlock states a self-loop (so CTL/LTL see every state as having an infinite path)
  --lax              allow assignments that can leave a variable's type (those transitions are disabled)
  --html FILE        also write a self-contained HTML report
  --full-traces      never abbreviate long counterexamples
  --stats            print BDD / fixpoint statistics and the variable order
  --quiet            only print verdict lines (no traces)

EXIT STATUS  0 all properties hold | 1 some property fails | 2 error in input
";

fn die(msg: &str) -> ! {
    eprintln!("kripke: {}", msg);
    exit(2)
}

fn read_source(path: &str) -> String {
    match std::fs::read(path) {
        Ok(bytes) => match String::from_utf8(bytes) {
            Ok(s) => s,
            Err(e) => die(&format!("{}: not valid UTF-8 text (invalid byte at offset {})", path, e.utf8_error().valid_up_to())),
        },
        Err(e) => die(&format!("cannot read {}: {}", path, e)),
    }
}

fn flag(args: &[String], name: &str) -> bool {
    args.iter().any(|a| a == name)
}

fn value<'a>(args: &'a [String], name: &str) -> Option<&'a str> {
    args.iter().position(|a| a == name).map(|i| match args.get(i + 1) {
        Some(v) => v.as_str(),
        None => die(&format!("{} needs a value", name)),
    })
}

fn check_unknown_flags(args: &[String], known_flags: &[&str], known_values: &[&str]) {
    let mut i = 0;
    while i < args.len() {
        let a = &args[i];
        if known_values.contains(&a.as_str()) {
            i += 2;
            continue;
        }
        if a.starts_with("--") && !known_flags.contains(&a.as_str()) {
            die(&format!("unknown option {} (see `kripke help`)", a));
        }
        i += 1;
    }
}

fn main_inner() -> i32 {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.is_empty() || args[0] == "help" || args[0] == "--help" || args[0] == "-h" {
        print!("{}", USAGE);
        return if args.is_empty() { 2 } else { 0 };
    }
    let (cmd, rest): (&str, &[String]) = match args[0].as_str() {
        "check" | "explicit" | "gen" | "fuzz" | "dot" | "sim" => (args[0].as_str(), &args[1..]),
        _ => ("check", &args[..]),
    };
    match cmd {
        "check" => cmd_check(rest),
        "explicit" => cmd_explicit(rest),
        "gen" => cmd_gen(rest),
        "fuzz" => cmd_fuzz(rest),
        "dot" => cmd_dot(rest),
        "sim" => cmd_sim(rest),
        _ => unreachable!(),
    }
}

fn path_arg(rest: &[String]) -> &str {
    match rest.iter().find(|a| !a.starts_with("--")) {
        Some(p) => p,
        None => die("missing model file (see `kripke help`)"),
    }
}

fn cmd_check(rest: &[String]) -> i32 {
    check_unknown_flags(rest, &["--reorder", "--stutter", "--lax", "--full-traces", "--stats", "--quiet", "--gc-stress"], &["--html"]);
    let path = {
        let mut skip = false;
        let mut found = None;
        for a in rest {
            if skip {
                skip = false;
                continue;
            }
            if a == "--html" {
                skip = true;
                continue;
            }
            if !a.starts_with("--") {
                found = Some(a.as_str());
                break;
            }
        }
        found.unwrap_or_else(|| die("missing model file (see `kripke help`)"))
    };
    let src = read_source(path);
    let opts = Options { reorder: flag(rest, "--reorder"), gc_stress: flag(rest, "--gc-stress"), lax: flag(rest, "--lax"), stutter: flag(rest, "--stutter") };
    match run(&src, &opts) {
        Ok(r) => {
            let ro = RenderOpts { verbose: flag(rest, "--stats"), full_traces: flag(rest, "--full-traces"), quiet: flag(rest, "--quiet") };
            print!("{}", render_report(&r, &ro));
            if let Some(out) = value(rest, "--html") {
                let html = kripke::html::render_html(&r, path, &src);
                if let Err(e) = std::fs::write(out, html) {
                    die(&format!("cannot write {}: {}", out, e));
                }
                println!("wrote {}", out);
            }
            if r.all_hold() {
                0
            } else {
                1
            }
        }
        Err(e) => {
            eprint!("{}", e.render(&src, path));
            2
        }
    }
}

fn cmd_explicit(rest: &[String]) -> i32 {
    check_unknown_flags(rest, &["--stutter"], &[]);
    let path = path_arg(rest);
    let src = read_source(path);
    let prog = match kripke::lang::parse(&src) {
        Ok(p) => p,
        Err(e) => {
            eprint!("{}", e.render(&src, path));
            return 2;
        }
    };
    let stutter = flag(rest, "--stutter");
    let sym = match kripke::driver::run_program(&prog, &Options { stutter, ..Default::default() }, std::time::Instant::now()) {
        Ok(r) => r,
        Err(e) => {
            eprint!("{}", e.render(&src, path));
            return 2;
        }
    };
    let mut ex = match kripke::explicit::Explicit::new(&prog, 200_000, stutter) {
        Ok(e) => e,
        Err(m) => die(&format!("explicit engine: {}", m)),
    };
    let (reach, diam, dead) = ex.reachability();
    let nreach = reach.iter().filter(|&&b| b).count();
    let bad = std::cell::Cell::new(0);
    let line = |what: &str, a: String, b: String| {
        let ok = a == b;
        println!("{:<22} symbolic {:>10}   explicit {:>10}   {}", what, a, b, if ok { "agree" } else { "MISMATCH" });
        if !ok {
            bad.set(bad.get() + 1);
        }
    };
    line("reachable states", sym.info.reachable.to_string(), nreach.to_string());
    line("diameter", sym.info.diameter.to_string(), diam.to_string());
    line("deadlock states", sym.info.deadlocks.to_string(), dead.to_string());
    line("initial states", sym.info.init_states.to_string(), ex.init_count().to_string());
    line("fair states", sym.info.fair_states.to_string(), ex.fair_count().to_string());
    for (i, sp) in prog.specs.iter().enumerate() {
        let o = &sym.outcomes[i];
        let s = o.verdict == kripke::check::Verdict::Holds;
        let e = match sp.kind {
            kripke::lang::SpecKind::Ctl => ex.check_ctl(&sp.expr).map(Some),
            kripke::lang::SpecKind::Invar => ex.check_invar(&sp.expr).map(Some),
            kripke::lang::SpecKind::Ltl => ex.check_ltl_fragment(&sp.expr),
        };
        match e {
            Ok(Some(e)) => line(&o.label, s.to_string(), e.to_string()),
            Ok(None) => println!("{:<22} symbolic {:>10}   explicit {:>10}   (LTL outside the ACTL-equivalent fragment: no oracle)", o.label, s, "-"),
            Err(e) => die(&e.to_string()),
        }
        if let kripke::check::Verdict::Fails(Some(t)) = &o.verdict {
            match ex.validate_trace(t) {
                Ok(()) => println!("{:<22} counterexample validated by the explicit engine", ""),
                Err(m) => {
                    println!("{:<22} counterexample INVALID: {}", "", m);
                    bad.set(bad.get() + 1);
                }
            }
        }
    }
    if bad.get() == 0 {
        println!("\nboth engines agree");
        0
    } else {
        println!("\n{} disagreement(s)", bad.get());
        1
    }
}

fn cmd_gen(rest: &[String]) -> i32 {
    let name = rest.first().map(|s| s.as_str()).unwrap_or_else(|| die("usage: kripke gen NAME N"));
    let n: usize = match rest.get(1) {
        Some(v) => v.parse().unwrap_or_else(|_| die("N must be a positive integer")),
        None => die("usage: kripke gen NAME N"),
    };
    match kripke::gen::generate(name, n) {
        Ok(s) => {
            print!("{}", s);
            0
        }
        Err(e) => die(&e),
    }
}

fn cmd_fuzz(rest: &[String]) -> i32 {
    check_unknown_flags(rest, &[], &["--count", "--seed"]);
    let count: u64 = value(rest, "--count").map(|v| v.parse().unwrap_or_else(|_| die("--count needs a number"))).unwrap_or(200);
    let seed0: u64 = value(rest, "--seed").map(|v| v.parse().unwrap_or_else(|_| die("--seed needs a number"))).unwrap_or(1);
    let mut bad = 0;
    for seed in seed0..seed0 + count {
        let src = kripke::fuzz::gen_model(seed);
        let mut rng = kripke::fuzz::Rng(seed * 7919 + 13);
        match kripke::fuzz::cross_check(&src, &mut rng) {
            Ok(m) if m.is_empty() => {}
            Ok(m) => {
                bad += 1;
                println!("seed {}: {}", seed, m.join("; "));
            }
            Err(e) => {
                bad += 1;
                println!("seed {}: {}", seed, e);
            }
        }
    }
    println!("{} random models cross-checked, {} disagreement(s)", count, bad);
    if bad == 0 {
        0
    } else {
        1
    }
}

fn cmd_dot(rest: &[String]) -> i32 {
    let path = path_arg(rest);
    let what = rest.iter().filter(|a| !a.starts_with("--")).nth(1).map(|s| s.as_str()).unwrap_or("reach");
    let src = read_source(path);
    let prog = match kripke::lang::parse(&src) {
        Ok(p) => p,
        Err(e) => {
            eprint!("{}", e.render(&src, path));
            return 2;
        }
    };
    let mut md = match kripke::model::Model::compile(prog, false) {
        Ok(m) => m,
        Err(e) => {
            eprint!("{}", e.render(&src, path));
            return 2;
        }
    };
    let root = match what {
        "init" => md.init,
        "trans" => md.trans,
        "reach" => {
            let mut ck = kripke::check::Checker::new(&mut md);
            ck.reach().set
        }
        other => die(&format!("unknown BDD '{}': choose init, trans or reach", other)),
    };
    let names = kripke::driver::bit_names(&md);
    print!("{}", md.m.to_dot(&[(what.to_string(), root)], &|v| names[v as usize].clone()));
    0
}

fn cmd_sim(rest: &[String]) -> i32 {
    check_unknown_flags(rest, &[], &["--steps", "--seed"]);
    let path = path_arg(rest);
    let steps: usize = value(rest, "--steps").map(|v| v.parse().unwrap_or_else(|_| die("--steps needs a number"))).unwrap_or(10);
    let seed: u64 = value(rest, "--seed").map(|v| v.parse().unwrap_or_else(|_| die("--seed needs a number"))).unwrap_or(1);
    let src = read_source(path);
    match kripke::sim::simulate(&src, steps, seed) {
        Ok(t) => {
            print!("{}", kripke::report::render_trace(&t, ""));
            0
        }
        Err(e) => {
            eprint!("{}", e.render(&src, path));
            2
        }
    }
}

fn main() {
    // Deeply nested or very long expressions recurse deeply; give the worker a generous stack.
    let child = std::thread::Builder::new().stack_size(1 << 30).spawn(main_inner).expect("cannot start worker thread");
    match child.join() {
        Ok(code) => exit(code),
        Err(_) => {
            eprintln!("kripke: internal error (this is a bug; please report the model that triggered it)");
            exit(70)
        }
    }
}
