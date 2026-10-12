use std::process::exit;
use wick::ast::*;
use wick::interp::*;
use wick::trace::Profile;
use wick::{decode, disasm, encode, fuzz, validate, wat};

const USAGE: &str = "\
wick — a from-scratch WebAssembly toolchain

USAGE:
  wick asm <in.wat> [-o out.wasm] [--no-validate]   assemble WAT to a .wasm binary
  wick dis <in.wasm|in.wat>                         disassemble to WAT
  wick validate <file>                              validate a module (exit 0 = valid)
  wick run <file> [--invoke NAME ARGS...] [options] instantiate and run an export
        --fuel N        instruction budget (traps with `out of fuel`)
        --profile       print an execution profile after the run
        --html FILE     write a self-contained HTML profile report
        --trace N       record the first N executed instructions in the report
        --state         print memory hash and exported globals after the run
  wick info <file>                                  list sections, imports and exports
  wick fuzz --count N [--seed S] --out DIR          generate random programs + Wick's results
                                                    (compare against V8 with: node diff/diff.js DIR)
  wick mutants --count N --per K --out DIR          write almost-valid mutant modules (validator testing)
  wick check-batch DIR                              accept/reject verdict for every .wasm in DIR

Files ending in .wasm (or starting with \\0asm) are binary; anything else is parsed as WAT.
Float args accept decimal, inf, nan and bits:0xHEX (exact IEEE bit pattern).";

fn die(msg: impl std::fmt::Display, code: i32) -> ! {
    eprintln!("wick: {msg}");
    exit(code)
}

fn load(path: &str) -> Module {
    let data = std::fs::read(path).unwrap_or_else(|e| die(format!("cannot read {path}: {e}"), 1));
    if data.starts_with(b"\0asm") || path.ends_with(".wasm") {
        decode::decode(&data).unwrap_or_else(|e| die(format!("{path}: {e}"), 1))
    } else {
        let src = String::from_utf8(data).unwrap_or_else(|_| die(format!("{path}: not valid UTF-8 text and not a wasm binary"), 1));
        wat::parse_module(&src).unwrap_or_else(|e| die(format!("{path}:{e}"), 1))
    }
}

fn host_imports() -> Imports {
    wick::interp::standard_imports()
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.is_empty() || args[0] == "-h" || args[0] == "--help" || args[0] == "help" {
        println!("{USAGE}");
        return;
    }
    let cmd = args[0].as_str();
    let rest = &args[1..];
    match cmd {
        "asm" => {
            let mut input = None;
            let mut out = None;
            let mut check = true;
            let mut i = 0;
            while i < rest.len() {
                match rest[i].as_str() {
                    "-o" => {
                        i += 1;
                        out = Some(rest.get(i).cloned().unwrap_or_else(|| die("-o needs a path", 1)));
                    }
                    "--no-validate" => check = false,
                    s if s.starts_with('-') => die(format!("unknown option {s}"), 1),
                    s => input = Some(s.to_string()),
                }
                i += 1;
            }
            let input = input.unwrap_or_else(|| die("asm needs an input file", 1));
            let src = std::fs::read_to_string(&input).unwrap_or_else(|e| die(format!("cannot read {input}: {e}"), 1));
            let m = wat::parse_module(&src).unwrap_or_else(|e| die(format!("{input}:{e}"), 1));
            if check {
                validate::validate(&m).unwrap_or_else(|e| die(format!("{input}: {e}"), 1));
            }
            let bytes = encode::encode(&m);
            let out = out.unwrap_or_else(|| input.trim_end_matches(".wat").to_string() + ".wasm");
            std::fs::write(&out, &bytes).unwrap_or_else(|e| die(format!("cannot write {out}: {e}"), 1));
            eprintln!("wrote {out} ({} bytes)", bytes.len());
        }
        "dis" => {
            let f = rest.first().unwrap_or_else(|| die("dis needs a file", 1));
            print!("{}", disasm::disassemble(&load(f)));
        }
        "validate" => {
            let f = rest.first().unwrap_or_else(|| die("validate needs a file", 1));
            let m = load(f);
            match validate::validate(&m) {
                Ok(()) => println!("{f}: valid ({} functions, {} types)", m.all_func_types().len(), m.types.len()),
                Err(e) => die(format!("{f}: {e}"), 1),
            }
        }
        "info" => {
            let f = rest.first().unwrap_or_else(|| die("info needs a file", 1));
            let m = load(f);
            println!("types {}  imports {}  funcs {}  tables {}  memories {}  globals {}  exports {}  elems {}  datas {}", m.types.len(), m.imports.len(), m.funcs.len(), m.tables.len(), m.mems.len(), m.globals.len(), m.exports.len(), m.elems.len(), m.datas.len());
            for i in &m.imports {
                println!("import {}.{} {:?}", i.module, i.name, i.desc);
            }
            for e in &m.exports {
                println!("export {} {:?} #{}", e.name, e.kind, e.index);
            }
            println!("binary size: {} bytes", encode::encode(&m).len());
        }
        "run" => run_cmd(rest),
        "fuzz" => fuzz_cmd(rest),
        "check-batch" => check_batch(rest),
        "mutants" => mutants_cmd(rest),
        other => die(format!("unknown command `{other}`\n\n{USAGE}"), 1),
    }
}

fn run_cmd(rest: &[String]) {
    let mut file = None;
    let mut invoke: Option<String> = None;
    let mut fuel: Option<u64> = None;
    let mut profile = false;
    let mut html: Option<String> = None;
    let mut trace = 0usize;
    let mut state = false;
    let mut positional: Vec<String> = vec![];
    let mut i = 0;
    while i < rest.len() {
        let a = rest[i].as_str();
        let val = |i: &mut usize| -> String {
            *i += 1;
            rest.get(*i).cloned().unwrap_or_else(|| die(format!("{a} needs a value"), 1))
        };
        match a {
            "--invoke" => invoke = Some(val(&mut i)),
            "--fuel" => fuel = Some(val(&mut i).parse().unwrap_or_else(|_| die("--fuel needs a number", 1))),
            "--profile" => profile = true,
            "--html" => {
                html = Some(val(&mut i));
                profile = true;
            }
            "--trace" => {
                trace = val(&mut i).parse().unwrap_or_else(|_| die("--trace needs a number", 1));
                profile = true;
            }
            "--state" => state = true,
            s if s.starts_with("--") => die(format!("unknown option {s}"), 1),
            s => {
                if file.is_none() {
                    file = Some(s.to_string())
                } else {
                    positional.push(s.to_string())
                }
            }
        }
        i += 1;
    }
    let file = file.unwrap_or_else(|| die("run needs a file", 1));
    let module = load(&file);
    let mut inst = match Instance::new(module, host_imports()) {
        Ok(i) => i,
        Err(e) => die(format!("{file}: {e}"), if matches!(e, InstanceError::Trap(_)) { 2 } else { 1 }),
    };
    if let Some(f) = fuel {
        inst.fuel = f;
    }
    if profile {
        inst.profile = Some(Box::new(Profile::new(trace)));
    }
    let mut code = 0;
    if let Some(name) = &invoke {
        let ft = inst.export_func_type(name).unwrap_or_else(|e| die(e, 1));
        if positional.len() != ft.params.len() {
            die(format!("`{name}` takes {} argument(s) ({}), got {}", ft.params.len(), ft.params.iter().map(|t| t.name()).collect::<Vec<_>>().join(", "), positional.len()), 1);
        }
        let vals: Vec<Value> = ft.params.iter().zip(&positional).map(|(t, s)| Value::parse(*t, s).unwrap_or_else(|e| die(e, 1))).collect();
        match inst.invoke(name, &vals) {
            Ok(rs) => {
                for r in rs {
                    println!("{r}");
                }
            }
            Err(e) => {
                eprintln!("wick: {e}");
                code = 2;
            }
        }
    } else if !positional.is_empty() {
        die("arguments given without --invoke", 1);
    }
    if state {
        if let Some(m) = &inst.memory {
            println!("memory: {} page(s), fnv32 {:08x}", m.pages(), fuzz::fnv32(&m.data));
        }
        for e in inst.module.exports.clone() {
            if e.kind == ExportKind::Global {
                println!("global {} = {}", e.name, inst.get_global(&e.name).unwrap());
            }
        }
    }
    if profile {
        let p = inst.profile.take().unwrap();
        eprint!("{}", p.text_report(&inst.module));
        if let Some(h) = html {
            std::fs::write(&h, p.html_report(&inst.module, &file)).unwrap_or_else(|e| die(format!("cannot write {h}: {e}"), 1));
            eprintln!("wrote {h}");
        }
    }
    exit(code);
}

fn fuzz_cmd(rest: &[String]) {
    let mut count = 100u64;
    let mut seed = 1u64;
    let mut out = None;
    let mut i = 0;
    while i < rest.len() {
        let a = rest[i].as_str();
        i += 1;
        let v = rest.get(i).cloned();
        match a {
            "--count" => count = v.and_then(|v| v.parse().ok()).unwrap_or_else(|| die("--count needs a number", 1)),
            "--seed" => seed = v.and_then(|v| v.parse().ok()).unwrap_or_else(|| die("--seed needs a number", 1)),
            "--out" => out = Some(v.unwrap_or_else(|| die("--out needs a directory", 1))),
            s => die(format!("unknown fuzz option {s}"), 1),
        }
        i += 1;
    }
    let out = out.unwrap_or_else(|| die("fuzz needs --out DIR", 1));
    std::fs::create_dir_all(&out).unwrap_or_else(|e| die(format!("cannot create {out}: {e}"), 1));
    let mut skipped = 0;
    for k in 0..count {
        let s = seed + k;
        let case = fuzz::generate(s);
        if let Err(e) = validate::validate(&case.module) {
            die(format!("generator bug: seed {s} produced an invalid module: {e}"), 3);
        }
        let bytes = encode::encode(&case.module);
        // the binary must also survive a decode round-trip
        match decode::decode(&bytes) {
            Ok(m2) => {
                if encode::encode(&m2) != bytes {
                    die(format!("codec bug: seed {s} does not re-encode identically"), 3);
                }
            }
            Err(e) => die(format!("codec bug: seed {s}: {e}"), 3),
        }
        let json = fuzz::run_case_json(s, &case);
        if json.contains("\"skip\":\"") {
            skipped += 1;
        }
        std::fs::write(format!("{out}/case{s}.wasm"), &bytes).unwrap();
        std::fs::write(format!("{out}/case{s}.json"), json).unwrap();
        std::fs::write(format!("{out}/case{s}.wat"), disasm::disassemble(&case.module)).unwrap();
    }
    eprintln!("generated {count} case(s) in {out} (seeds {seed}..{}), {skipped} skipped", seed + count - 1);
}

/// Verdicts for every `*.wasm` in a directory, one `name<TAB>verdict` line each. Used by the
/// validator differential test (`diff/validate_diff.js`). Modules that validate are also
/// instantiated and every export is called with zero arguments under a fuel limit, so a validator
/// that wrongly accepts a module shows up as an interpreter panic here.
fn check_batch(rest: &[String]) {
    let dir = rest.first().unwrap_or_else(|| die("check-batch needs a directory", 1));
    let mut names: Vec<_> = std::fs::read_dir(dir).unwrap_or_else(|e| die(format!("cannot read {dir}: {e}"), 1)).filter_map(|e| e.ok()).map(|e| e.path()).filter(|p| p.extension().map_or(false, |x| x == "wasm")).collect();
    names.sort();
    std::panic::set_hook(Box::new(|_| {}));
    for p in names {
        let data = std::fs::read(&p).unwrap();
        let verdict = std::panic::catch_unwind(|| {
            let m = match decode::decode(&data) {
                Err(e) => return format!("REJECT decode: {e}"),
                Ok(m) => m,
            };
            if let Err(e) = validate::validate(&m) {
                return format!("REJECT validate: {e}");
            }
            // accepted: execute exports defensively
            let mut inst = match Instance::new(m, host_imports()) {
                Ok(i) => i,
                Err(_) => return "ACCEPT".to_string(),
            };
            let exports: Vec<String> = inst.module.exports.iter().filter(|e| e.kind == ExportKind::Func).map(|e| e.name.clone()).collect();
            for name in exports {
                let ft = inst.export_func_type(&name).unwrap();
                let args: Vec<Value> = ft.params.iter().map(|t| Value::zero(*t)).collect();
                inst.fuel = 200_000;
                let _ = inst.invoke(&name, &args);
            }
            "ACCEPT".to_string()
        })
        .unwrap_or_else(|_| "PANIC".to_string());
        println!("{}\t{}", p.file_name().unwrap().to_string_lossy(), verdict);
    }
}

/// `wick mutants --count N --seed S --per K --out DIR`: write K AST-mutated (almost valid) variants
/// of each of N generated programs, for the validator differential test.
fn mutants_cmd(rest: &[String]) {
    let (mut count, mut seed, mut per, mut out) = (100u64, 1u64, 10u64, None);
    let mut i = 0;
    while i < rest.len() {
        let a = rest[i].as_str();
        i += 1;
        let v = rest.get(i).cloned();
        match a {
            "--count" => count = v.and_then(|v| v.parse().ok()).unwrap_or_else(|| die("--count needs a number", 1)),
            "--seed" => seed = v.and_then(|v| v.parse().ok()).unwrap_or_else(|| die("--seed needs a number", 1)),
            "--per" => per = v.and_then(|v| v.parse().ok()).unwrap_or_else(|| die("--per needs a number", 1)),
            "--out" => out = Some(v.unwrap_or_else(|| die("--out needs a directory", 1))),
            s => die(format!("unknown option {s}"), 1),
        }
        i += 1;
    }
    let out = out.unwrap_or_else(|| die("mutants needs --out DIR", 1));
    std::fs::create_dir_all(&out).unwrap_or_else(|e| die(format!("cannot create {out}: {e}"), 1));
    for k in 0..count {
        let case = fuzz::generate(seed + k);
        let mut rng = fuzz::Rng(seed + k + 0x77);
        for j in 0..per {
            let m = fuzz::mutate_module(&case.module, &mut rng);
            std::fs::write(format!("{out}/mut{}_{j}.wasm", seed + k), encode::encode(&m)).unwrap();
        }
    }
    eprintln!("wrote {} mutants to {out}", count * per);
}
