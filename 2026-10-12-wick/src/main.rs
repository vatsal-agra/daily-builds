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

Files ending in .wasm (or starting with \\0asm) are binary; anything else is parsed as WAT.
Float args accept decimal, inf, nan and bits:0xHEX (exact IEEE bit pattern).";

fn die(msg: impl std::fmt::Display, code: i32) -> ! {
    eprintln!("wick: {msg}");
    exit(code)
}

fn load(path: &str) -> Module {
    let data = std::fs::read(path).unwrap_or_else(|e| die(format!("cannot read {path}: {e}"), 1));
    if data.starts_with(b"\0asm") {
        decode::decode(&data).unwrap_or_else(|e| die(format!("{path}: {e}"), 1))
    } else {
        let src = String::from_utf8(data).unwrap_or_else(|_| die(format!("{path}: not valid UTF-8 text and not a wasm binary"), 1));
        wat::parse_module(&src).unwrap_or_else(|e| die(format!("{path}:{e}"), 1))
    }
}

fn host_imports() -> Imports {
    let mut im = Imports::default();
    im.func("env", "print_i32", &[ValType::I32], &[], |a| {
        if let Value::I32(v) = a[0] {
            println!("{v}")
        }
        Ok(vec![])
    });
    im.func("env", "print_i64", &[ValType::I64], &[], |a| {
        if let Value::I64(v) = a[0] {
            println!("{v}")
        }
        Ok(vec![])
    });
    im.func("env", "print_f32", &[ValType::F32], &[], |a| {
        println!("{}", a[0]);
        Ok(vec![])
    });
    im.func("env", "print_f64", &[ValType::F64], &[], |a| {
        println!("{}", a[0]);
        Ok(vec![])
    });
    im.func("env", "print_char", &[ValType::I32], &[], |a| {
        if let Value::I32(v) = a[0] {
            print!("{}", char::from_u32(v as u32).unwrap_or('\u{fffd}'))
        }
        Ok(vec![])
    });
    im
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
