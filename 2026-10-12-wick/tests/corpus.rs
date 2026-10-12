//! Runs the hand-written conformance corpus in tests/corpus/*.wat.
//!
//! A file holds one or more modules separated by lines starting with `;; ---`. Directives live in
//! comments and run in order against one instance per module:
//!   ;; assert  <export> <typed args...> => <typed results...>
//!   ;; trap    <export> <typed args...> => <trap category>
//!   ;; global  <export> => <typed value>
//!   ;; invalid <message substring>        module must fail validation
//!   ;; malformed <message substring>      WAT must fail to parse
//!   ;; link-error <substring> | ;; init-trap <category>   instantiation must fail
//! Typed values look like `i32:5`, `f64:-0`, `f32:nan`, `f32:bits:0x7fc00001`.
use wick::ast::ValType;
use wick::interp::*;
use wick::*;

pub fn parse_typed(s: &str) -> Value {
    let (t, rest) = s.split_once(':').unwrap_or_else(|| panic!("bad typed value `{s}`"));
    let ty = ValType::parse(t).unwrap_or_else(|| panic!("bad type in `{s}`"));
    Value::parse(ty, rest).unwrap_or_else(|e| panic!("{e}"))
}

pub fn same(expected: &Value, got: &Value, nan_is_wildcard: bool) -> bool {
    match (expected, got) {
        (Value::F32(a), Value::F32(b)) => (a.is_nan() && b.is_nan() && nan_is_wildcard) || a.to_bits() == b.to_bits(),
        (Value::F64(a), Value::F64(b)) => (a.is_nan() && b.is_nan() && nan_is_wildcard) || a.to_bits() == b.to_bits(),
        (a, b) => a == b,
    }
}

fn run_chunk(file: &str, idx: usize, chunk: &str) -> usize {
    let tag = format!("{file}[module {idx}]");
    let directives: Vec<&str> = chunk.lines().filter_map(|l| l.trim().strip_prefix(";; ")).filter(|l| ["assert ", "trap ", "global ", "invalid ", "malformed ", "link-error ", "init-trap "].iter().any(|p| l.starts_with(p))).collect();
    let mut count = 0;
    let parsed = wat::parse_module(chunk);
    if let Some(d) = directives.iter().find(|d| d.starts_with("malformed ")) {
        let want = d["malformed ".len()..].trim();
        let e = parsed.err().unwrap_or_else(|| panic!("{tag}: expected a parse error containing `{want}` but it parsed"));
        assert!(e.msg.contains(want), "{tag}: parse error `{}` does not contain `{want}`", e.msg);
        return 1;
    }
    let module = parsed.unwrap_or_else(|e| panic!("{tag}: unexpected parse error: {e}"));
    if let Some(d) = directives.iter().find(|d| d.starts_with("invalid ")) {
        let want = d["invalid ".len()..].trim();
        let e = validate::validate(&module).err().unwrap_or_else(|| panic!("{tag}: expected validation error containing `{want}` but module is valid"));
        assert!(e.to_string().contains(want), "{tag}: validation error `{e}` does not contain `{want}`");
        return 1;
    }
    let inst = Instance::new(module, standard_imports());
    if let Some(d) = directives.iter().find(|d| d.starts_with("link-error ") || d.starts_with("init-trap ")) {
        let e = inst.err().unwrap_or_else(|| panic!("{tag}: expected instantiation to fail"));
        if let Some(w) = d.strip_prefix("link-error ") {
            assert!(matches!(e, InstanceError::Link(_)) && e.to_string().contains(w.trim()), "{tag}: got `{e}`");
        } else {
            let want = d["init-trap ".len()..].trim();
            match e {
                InstanceError::Trap(t) => assert_eq!(t.category(), want, "{tag}"),
                other => panic!("{tag}: expected trap, got {other}"),
            }
        }
        return 1;
    }
    let mut inst = inst.unwrap_or_else(|e| panic!("{tag}: instantiation failed: {e}"));
    for d in directives {
        let (kind, rest) = d.split_once(' ').unwrap();
        let (lhs, rhs) = rest.split_once("=>").map(|(a, b)| (a.trim(), b.trim())).unwrap_or((rest.trim(), ""));
        let mut it = lhs.split_whitespace();
        let name = it.next().unwrap();
        match kind {
            "assert" | "trap" => {
                let args: Vec<Value> = it.map(parse_typed).collect();
                let r = inst.invoke(name, &args);
                if kind == "assert" {
                    let want: Vec<Value> = rhs.split_whitespace().map(parse_typed).collect();
                    let got = r.unwrap_or_else(|e| panic!("{tag}: {d}: unexpected {e}"));
                    assert!(want.len() == got.len() && want.iter().zip(&got).all(|(a, b)| same(a, b, true)), "{tag}: {d}\n   got {:?}", got.iter().map(|v| v.to_string()).collect::<Vec<_>>());
                } else {
                    match r {
                        Err(InvokeError::Trap(t)) => {
                            let cat = if t.category() == "conv" { "int_overflow_or_conv" } else { t.category() };
                            let want = if rhs == "conv" { "int_overflow_or_conv" } else { rhs };
                            assert_eq!(cat, want, "{tag}: {d}");
                        }
                        other => panic!("{tag}: {d}: expected trap, got {other:?}"),
                    }
                }
            }
            "global" => {
                let got = inst.get_global(name).unwrap_or_else(|| panic!("{tag}: no global {name}"));
                assert!(same(&parse_typed(rhs), &got, true), "{tag}: {d}: got {got}");
            }
            _ => unreachable!(),
        }
        count += 1;
    }
    count
}

#[test]
fn conformance_corpus() {
    let dir = concat!(env!("CARGO_MANIFEST_DIR"), "/tests/corpus");
    let mut files: Vec<_> = std::fs::read_dir(dir).unwrap().map(|e| e.unwrap().path()).filter(|p| p.extension().map_or(false, |e| e == "wat")).collect();
    files.sort();
    assert!(!files.is_empty());
    let mut total = 0;
    for f in files {
        let src = std::fs::read_to_string(&f).unwrap();
        let name = f.file_name().unwrap().to_string_lossy().to_string();
        let mut chunks: Vec<String> = vec![String::new()];
        for line in src.lines() {
            if line.trim_start().starts_with(";; ---") {
                chunks.push(String::new());
            } else {
                let c = chunks.last_mut().unwrap();
                c.push_str(line);
                c.push('\n');
            }
        }
        for (i, c) in chunks.iter().enumerate() {
            if c.trim().is_empty() {
                continue;
            }
            total += run_chunk(&name, i, c);
        }
    }
    println!("corpus: {total} directives passed");
    assert!(total > 100);
}
