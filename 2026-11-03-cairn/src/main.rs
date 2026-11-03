use cairn::*;
use std::io::Write;
use std::process::ExitCode;

/// `println!` panics when stdout is a closed pipe (`cairn run x | head`); a CLI should just stop.
macro_rules! say {
    ($($arg:tt)*) => {{
        let mut o = std::io::stdout().lock();
        if writeln!(o, $($arg)*).is_err() {
            std::process::exit(0);
        }
    }};
}
macro_rules! sayn {
    ($($arg:tt)*) => {{
        let mut o = std::io::stdout().lock();
        if write!(o, $($arg)*).is_err() {
            std::process::exit(0);
        }
    }};
}

fn usage() -> ! {
    eprintln!(
        "cairn — garbage-collector laboratory

USAGE
  cairn run FILE [--gc NAME] [--heap WORDS] [--nursery WORDS] [--verify [--verify-every N]] [--torture]
                 [--stats] [--no-barrier] [--seed N] [--steps N]
  cairn bench FILE [--heap WORDS] [--nursery WORDS] [--gcs a,b,c]
  cairn compare FILE [--heap WORDS] [--nursery WORDS]       (differential: same output & graph everywhere)
  cairn fuzz [--iters N] [--seed N] [--heap WORDS]
  cairn report FILE -o OUT.html [--heap WORDS] [--nursery WORDS]
  cairn barrier-demo
  cairn list

COLLECTORS  marksweep semispace generational incremental compact
Sizes are in 8-byte words. Defaults: heap 1048576, nursery 32768."
    );
    std::process::exit(2)
}

pub struct Args {
    pub pos: Vec<String>,
    pub flags: std::collections::HashMap<String, String>,
}

const VALUE_FLAGS: [&str; 12] = [
    "--verify-every",
    "--gc",
    "--heap",
    "--nursery",
    "--seed",
    "--steps",
    "--iters",
    "--gcs",
    "--save",
    "--out",
    "-o",
    "--pace",
];
const BOOL_FLAGS: [&str; 5] = ["--verify", "--torture", "--stats", "--no-barrier", "--quiet"];
/// Largest heap the CLI will try to allocate (2^28 words = 2 GiB of address space).
const MAX_HEAP_WORDS: usize = 1 << 28;

fn parse_args(raw: &[String]) -> Result<Args, String> {
    let bool_flags = BOOL_FLAGS;
    let mut pos = Vec::new();
    let mut flags = std::collections::HashMap::new();
    let mut i = 0;
    while i < raw.len() {
        let a = &raw[i];
        if a.starts_with("--") || a == "-o" {
            if bool_flags.contains(&a.as_str()) {
                flags.insert(a.clone(), "1".into());
            } else if !VALUE_FLAGS.contains(&a.as_str()) {
                return Err(format!("unknown option '{a}' (see `cairn help`)"));
            } else {
                i += 1;
                let v = raw.get(i).ok_or_else(|| format!("{a} needs a value"))?;
                flags.insert(a.clone(), v.clone());
            }
        } else {
            pos.push(a.clone());
        }
        i += 1;
    }
    Ok(Args { pos, flags })
}

fn num(args: &Args, key: &str, default: usize) -> Result<usize, String> {
    match args.flags.get(key) {
        None => Ok(default),
        Some(s) => s
            .parse::<usize>()
            .map_err(|_| format!("{key}: '{s}' is not a non-negative integer")),
    }
}

fn config(args: &Args) -> Result<GcConfig, String> {
    let mut c = GcConfig::default();
    c.words = num(args, "--heap", c.words)?;
    c.nursery = num(args, "--nursery", c.nursery)?;
    if c.words < 64 {
        return Err("--heap must be at least 64 words".into());
    }
    if c.words > MAX_HEAP_WORDS || c.nursery > MAX_HEAP_WORDS {
        return Err(format!("--heap/--nursery are limited to {MAX_HEAP_WORDS} words"));
    }
    if let Some(p) = args.flags.get("--pace") {
        c.pace = p
            .parse::<usize>()
            .map_err(|_| format!("--pace: '{p}' is not a positive integer"))?
            .max(1);
    }
    c.barrier = !args.flags.contains_key("--no-barrier");
    Ok(c)
}

fn read_file(path: &str) -> Result<String, String> {
    std::fs::read_to_string(path).map_err(|e| format!("cannot read {path}: {e}"))
}

fn cmd_run(args: &Args) -> Result<(), String> {
    let path = args.pos.first().ok_or("run needs a FILE")?;
    let src = read_file(path)?;
    let cfg = config(args)?;
    let gcname = args.flags.get("--gc").map(|s| s.as_str()).unwrap_or("generational");
    let prog = lang::compile(&src).map_err(|e| format!("{path}: {e}"))?;
    let gc = make_gc(gcname, &cfg)?;
    let opts = vm::VmOptions {
        verify: args.flags.contains_key("--verify"),
        verify_every: num(args, "--verify-every", 1)? as u64,
        torture: args.flags.contains_key("--torture"),
        stream: true,
        seed: num(args, "--seed", 0x9E3779B9)? as u64,
        step_limit: num(args, "--steps", usize::MAX)? as u64,
        ..Default::default()
    };
    let mut m = vm::Vm::new(gc, opts);
    let res = m.run(&prog);
    if args.flags.contains_key("--stats") {
        eprintln!("{}", report::stats_table(&[(m.gc.name().to_string(), m.gc.as_ref())]));
        if m.gc.name() == "incremental" || args.flags.contains_key("--verify") {
            eprintln!("oracle checks: {}", m.verify_checks);
        }
    }
    res.map_err(|e| format!("{path}: runtime error: {e}"))
}

fn collectors_from(args: &Args) -> Result<Vec<String>, String> {
    let list: Vec<String> = match args.flags.get("--gcs") {
        Some(s) => s.split(',').map(|x| x.trim().to_string()).collect(),
        None => ALL_GCS.iter().map(|s| s.to_string()).collect(),
    };
    if list.is_empty() || list.iter().any(|s| s.is_empty()) {
        return Err("--gcs needs a comma-separated list of collector names".into());
    }
    Ok(list)
}

fn load(args: &Args, what: &str) -> Result<(String, String, lang::Program), String> {
    let path = args.pos.first().ok_or(format!("{what} needs a FILE"))?.clone();
    let src = read_file(&path)?;
    let prog = lang::compile(&src).map_err(|e| format!("{path}: {e}"))?;
    Ok((path, src, prog))
}

fn cmd_bench(args: &Args) -> Result<(), String> {
    let (path, _src, prog) = load(args, "bench")?;
    let cfg = config(args)?;
    let mut rows = Vec::new();
    let mut outputs: Vec<(String, String)> = Vec::new();
    for g in collectors_from(args)? {
        let r = bench::run_one(&prog, &g, &cfg, vm::VmOptions::default())?;
        if let Ok(o) = &r.outcome {
            outputs.push((g.clone(), o.clone()));
        }
        rows.push(bench::row_of(&r));
    }
    say!("{path}  (heap {} words, nursery {})", cfg.words, cfg.nursery);
    sayn!("{}", bench::table(&rows));
    if let Some((first, out0)) = outputs.first() {
        if let Some((g, _)) = outputs.iter().find(|(_, o)| o != out0) {
            return Err(format!("OUTPUT MISMATCH: {g} differs from {first}"));
        }
        say!("outputs identical across {} collector(s)", outputs.len());
    }
    Ok(())
}

fn cmd_compare(args: &Args) -> Result<(), String> {
    let (path, _src, prog) = load(args, "compare")?;
    let cfg = config(args)?;
    let mut base: Option<(String, String, snapshot_t)> = None;
    let mut bad = false;
    for g in collectors_from(args)? {
        let opts = vm::VmOptions {
            verify: args.flags.contains_key("--verify"),
            verify_every: num(args, "--verify-every", 1)? as u64,
            torture: args.flags.contains_key("--torture"),
            ..Default::default()
        };
        let r = bench::run_one(&prog, &g, &cfg, opts)?;
        match &r.outcome {
            Err(e) => {
                say!("{g:<13} FAILED: {e}");
                bad = true;
            }
            Ok(out) => {
                let snap = verify::snapshot(r.vm.gc.as_ref(), &r.vm.roots);
                let errs = verify::check_heap(r.vm.gc.as_ref(), &r.vm.roots);
                let same = match &base {
                    None => {
                        base = Some((g.clone(), out.clone(), snap.clone()));
                        true
                    }
                    Some((_, o, s)) => o == out && *s == snap,
                };
                say!(
                    "{g:<13} {}  {} objects reachable, digest {:016x}, {} oracle checks{}",
                    if same && errs.is_empty() { "OK  " } else { "DIFF" },
                    snap.nodes.len(),
                    snap.digest(),
                    r.vm.verify_checks,
                    if errs.is_empty() {
                        String::new()
                    } else {
                        format!(", heap errors: {}", errs[0])
                    }
                );
                bad |= !same || !errs.is_empty();
            }
        }
    }
    if bad {
        Err(format!("{path}: collectors disagree or failed"))
    } else {
        say!("all collectors agree on output and final reachable graph");
        Ok(())
    }
}

#[allow(non_camel_case_types)]
type snapshot_t = verify::Snapshot;

fn cmd_report(args: &Args) -> Result<(), String> {
    let (path, src, prog) = load(args, "report")?;
    let cfg = config(args)?;
    let out = args.flags.get("-o").or(args.flags.get("--out")).ok_or("report needs -o OUT.html")?;
    let mut results = Vec::new();
    for g in collectors_from(args)? {
        results.push(bench::run_one(&prog, &g, &cfg, vm::VmOptions::default())?);
    }
    let html = report::html_report(&path, &src, &results, &cfg);
    std::fs::write(out, html).map_err(|e| format!("cannot write {out}: {e}"))?;
    say!("wrote {out}");
    Ok(())
}

fn cmd_barrier_demo() -> Result<(), String> {
    for h in [
        demo::satb_hazard(true),
        demo::satb_hazard(false),
        demo::old_to_young_hazard(true),
        demo::old_to_young_hazard(false),
    ] {
        say!("== {} — barrier {}", h.title, if h.barrier { "ON" } else { "OFF" });
        for s in &h.steps {
            say!("   {s}");
        }
        if h.violations.is_empty() {
            say!("   oracle: heap consistent, nothing lost");
        } else {
            say!("   oracle: CORRUPTION — {}", h.violations[0]);
        }
        say!();
        if h.barrier == h.violations.is_empty() {
            continue;
        }
        return Err(format!("unexpected outcome for '{}' (barrier {})", h.title, h.barrier));
    }
    say!("barriers on => safe; barriers off => the oracle catches the lost object.");
    Ok(())
}

fn cmd_fuzz(args: &Args) -> Result<(), String> {
    let iters = num(args, "--iters", 200)? as u64;
    let seed = num(args, "--seed", 1)? as u64;
    let mut cfg = fuzz::fuzz_cfg();
    if args.flags.contains_key("--heap") {
        cfg.words = num(args, "--heap", cfg.words)?;
    }
    cfg.barrier = !args.flags.contains_key("--no-barrier");
    let torture = args.flags.contains_key("--torture");
    let only = args.flags.get("--gcs").cloned();
    let list: Vec<String> = match only {
        Some(s) => s.split(',').map(|x| x.trim().to_string()).collect(),
        None => fuzz::default_collectors().iter().map(|s| s.to_string()).collect(),
    };
    let refs: Vec<&str> = list.iter().map(|s| s.as_str()).collect();
    for g in &refs {
        make_gc(g, &cfg)?;
    }
    eprintln!(
        "fuzzing {iters} programs from seed {seed} under {} (oracle on{})",
        refs.join(","),
        if torture { ", torture on" } else { "" }
    );
    match fuzz::fuzz(iters, seed, &cfg, &refs, torture) {
        Ok(n) => {
            say!(
                "fuzz: {n} programs x {} collectors agreed with the collector-free reference",
                refs.len()
            );
            Ok(())
        }
        Err(f) => {
            if let Some(dir) = args.flags.get("--save") {
                let _ = std::fs::write(format!("{dir}/fuzz-fail-{}.cairn", f.seed), &f.program);
            }
            Err(format!("seed {} FAILED under {} ({}): {}", f.seed, f.collector, f.mode, f.detail))
        }
    }
}

fn main() -> ExitCode {
    let raw: Vec<String> = std::env::args().skip(1).collect();
    if raw.is_empty() {
        usage();
    }
    let cmd = raw[0].clone();
    let rest = raw[1..].to_vec();
    // programs recurse; give the evaluator real stack space
    let h = std::thread::Builder::new()
        .stack_size(1 << 30)
        .spawn(move || -> Result<(), String> {
            let args = parse_args(&rest)?;
            match cmd.as_str() {
                "run" => cmd_run(&args),
                "fuzz" => cmd_fuzz(&args),
                "bench" => cmd_bench(&args),
                "compare" => cmd_compare(&args),
                "report" => cmd_report(&args),
                "barrier-demo" => cmd_barrier_demo(),
                "list" => {
                    for g in ALL_GCS {
                        say!("{g}");
                    }
                    Ok(())
                }
                "-h" | "--help" | "help" => usage(),
                other => Err(format!("unknown command '{other}' (try `cairn help`)")),
            }
        })
        .unwrap();
    match h.join() {
        Ok(Ok(())) => ExitCode::SUCCESS,
        Ok(Err(e)) => {
            eprintln!("cairn: {e}");
            ExitCode::from(1)
        }
        Err(_) => {
            eprintln!("cairn: internal error (panic)");
            ExitCode::from(101)
        }
    }
}
