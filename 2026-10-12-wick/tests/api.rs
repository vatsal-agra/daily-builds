//! Library-level tests: imports/exports, host functions, limits, fuel, profiler, formatting,
//! decoder corner cases (datacount, truncation, hostile counts).
use std::cell::RefCell;
use std::rc::Rc;
use wick::ast::*;
use wick::interp::*;
use wick::trap::Trap;
use wick::*;

fn module(src: &str) -> Module {
    wat::parse_module(src).unwrap_or_else(|e| panic!("{e}"))
}

#[test]
fn host_functions_receive_typed_arguments_and_return_values() {
    let log: Rc<RefCell<Vec<String>>> = Rc::default();
    let l2 = log.clone();
    let mut im = Imports::default();
    im.func("host", "mix", &[ValType::I32, ValType::F64], &[ValType::I64], move |a| {
        l2.borrow_mut().push(format!("{:?}", a));
        match (a[0], a[1]) {
            (Value::I32(x), Value::F64(y)) => Ok(vec![Value::I64(x as i64 * 1000 + y as i64)]),
            _ => Err(Trap::Host("bad args".into())),
        }
    });
    let m = module(r#"(module (import "host" "mix" (func $mix (param i32 f64) (result i64)))
        (func (export "go") (result i64) (call $mix (i32.const 7) (f64.const 2.9))))"#);
    let mut inst = Instance::new(m, im).unwrap();
    assert_eq!(inst.invoke("go", &[]).unwrap(), vec![Value::I64(7002)]);
    assert_eq!(log.borrow().len(), 1);
    assert!(log.borrow()[0].contains("I32(7)") && log.borrow()[0].contains("F64(2.9)"));
}

#[test]
fn host_trap_propagates_and_instance_stays_usable() {
    let mut im = Imports::default();
    im.func("h", "boom", &[], &[], |_| Err(Trap::Host("kaboom".into())));
    let m = module(r#"(module (import "h" "boom" (func $b)) (global $g (mut i32) (i32.const 0))
        (func (export "go") (global.set $g (i32.const 1)) (call $b) (global.set $g (i32.const 2)))
        (func (export "ok") (result i32) (i32.const 9))
        (export "g" (global $g)))"#);
    let mut inst = Instance::new(m, im).unwrap();
    match inst.invoke("go", &[]) {
        Err(InvokeError::Trap(Trap::Host(s))) => assert_eq!(s, "kaboom"),
        other => panic!("{other:?}"),
    }
    // state written before the trap persists; the instance still runs
    assert_eq!(inst.get_global("g"), Some(Value::I32(1)));
    assert_eq!(inst.invoke("ok", &[]).unwrap(), vec![Value::I32(9)]);
}

#[test]
fn host_function_returning_wrong_types_is_rejected() {
    let mut im = Imports::default();
    im.func("h", "liar", &[], &[ValType::I32], |_| Ok(vec![Value::F64(1.0)]));
    let m = module(r#"(module (import "h" "liar" (func $l (result i32))) (func (export "go") (result i32) (call $l)) (export "direct" (func $l)))"#);
    let mut inst = Instance::new(m, im).unwrap();
    assert!(matches!(inst.invoke("go", &[]), Err(InvokeError::Trap(Trap::Host(_)))));
    // finding #8: calling the import directly through the API is checked as well
    assert!(matches!(inst.invoke("direct", &[]), Err(InvokeError::Trap(Trap::Host(_)))));
}

#[test]
fn link_errors_are_specific() {
    let m = || module(r#"(module (import "a" "f" (func (param i32))) (import "a" "g" (global i32)) (import "a" "m" (memory 2)))"#);
    let e = Instance::new(m(), Imports::default()).err().unwrap();
    assert!(e.to_string().contains("missing function import `a.f`"), "{e}");
    let mut im = Imports::default();
    im.func("a", "f", &[ValType::I64], &[], |_| Ok(vec![]));
    let e = Instance::new(m(), im).err().unwrap();
    assert!(e.to_string().contains("wrong signature"), "{e}");
    let mut im = Imports::default();
    im.func("a", "f", &[ValType::I32], &[], |_| Ok(vec![]));
    im.globals.insert(("a".into(), "g".into()), Value::F32(1.0));
    let e = Instance::new(m(), im).err().unwrap();
    assert!(e.to_string().contains("wrong type"), "{e}");
    let mut im = Imports::default();
    im.func("a", "f", &[ValType::I32], &[], |_| Ok(vec![]));
    im.globals.insert(("a".into(), "g".into()), Value::I32(5));
    im.memories.insert(("a".into(), "m".into()), Memory::new(1, None));
    let e = Instance::new(m(), im).err().unwrap();
    assert!(e.to_string().contains("limits"), "{e}");
}

#[test]
fn imported_memory_global_and_table_are_used() {
    let m = module(
        r#"(module
        (import "env" "mem" (memory 1))
        (import "env" "base" (global $base i32))
        (import "env" "tab" (table 2 funcref))
        (global $derived i32 (global.get $base))
        (func $seven (result i32) (i32.const 7))
        (elem (i32.const 1) $seven)
        (data (global.get $base) "\2a")
        (func (export "peek") (result i32) (i32.load8_u (global.get $base)))
        (func (export "derived") (result i32) (global.get $derived))
        (func (export "viaTable") (result i32) (call_indirect (result i32) (i32.const 1))))"#,
    );
    let mut im = Imports::default();
    let mut mem = Memory::new(1, Some(4));
    mem.data[100] = 1;
    im.memories.insert(("env".into(), "mem".into()), mem);
    im.globals.insert(("env".into(), "base".into()), Value::I32(100));
    im.tables.insert(("env".into(), "tab".into()), Table { elems: vec![None; 2], max: Some(2) });
    let mut inst = Instance::new(m, im).unwrap();
    assert_eq!(inst.invoke("peek", &[]).unwrap(), vec![Value::I32(42)], "data segment overwrote the host-provided memory at the imported offset");
    assert_eq!(inst.invoke("derived", &[]).unwrap(), vec![Value::I32(100)]);
    assert_eq!(inst.invoke("viaTable", &[]).unwrap(), vec![Value::I32(7)]);
}

#[test]
fn fuel_limits_execution_and_is_resumable_per_call() {
    let m = module(r#"(module (func (export "spin") (param i32) (result i32) (local i32)
        (loop $l (local.set 1 (i32.add (local.get 1) (i32.const 1))) (br_if $l (i32.lt_u (local.get 1) (local.get 0))))
        (local.get 1)))"#);
    let mut inst = Instance::new(m, Imports::default()).unwrap();
    inst.fuel = 1000;
    assert_eq!(inst.invoke("spin", &[Value::I32(10)]).unwrap(), vec![Value::I32(10)]);
    assert!(inst.fuel < 1000 && inst.fuel > 0);
    assert!(matches!(inst.invoke("spin", &[Value::I32(1_000_000)]), Err(InvokeError::Trap(Trap::OutOfFuel))));
    inst.fuel = u64::MAX;
    assert_eq!(inst.invoke("spin", &[Value::I32(100000)]).unwrap(), vec![Value::I32(100000)]);
}

#[test]
fn invoke_checks_arguments() {
    let m = module(r#"(module (func (export "f") (param i32 f32) (result f32) (local.get 1)))"#);
    let mut inst = Instance::new(m, Imports::default()).unwrap();
    assert!(matches!(inst.invoke("f", &[Value::I32(1)]), Err(InvokeError::BadArgs(_))));
    assert!(matches!(inst.invoke("f", &[Value::I32(1), Value::F64(1.0)]), Err(InvokeError::BadArgs(_))));
    assert!(matches!(inst.invoke("nope", &[]), Err(InvokeError::NoExport(_))));
    assert_eq!(inst.invoke("f", &[Value::I32(1), Value::F32(2.5)]).unwrap(), vec![Value::F32(2.5)]);
}

#[test]
fn non_function_export_is_reported() {
    let m = module(r#"(module (memory (export "m") 1) (func (export "f")))"#);
    let mut inst = Instance::new(m, Imports::default()).unwrap();
    assert!(matches!(inst.invoke("m", &[]), Err(InvokeError::NotFunc(_))));
}

#[test]
fn value_formatting_uses_the_values_own_width() {
    assert_eq!(Value::F32(0.1).to_string(), "f32:0.1");
    assert_eq!(Value::F64(0.1).to_string(), "f64:0.1");
    assert_eq!(Value::F32(-0.0).to_string(), "f32:-0");
    assert_eq!(Value::F64(f64::NAN).to_string(), "f64:nan");
    assert_eq!(Value::F64(f64::NEG_INFINITY).to_string(), "f64:-inf");
    assert_eq!(Value::F64(1e300).to_string(), "f64:1e300");
    assert_eq!(Value::F64(123456.5).to_string(), "f64:123456.5");
    assert_eq!(Value::I64(i64::MIN).to_string(), "i64:-9223372036854775808");
    assert_eq!(Value::parse(ValType::F32, "bits:0x7fc00001").unwrap().to_raw(), 0x7fc00001);
    assert!(Value::parse(ValType::I32, "1.5").is_err());
    assert_eq!(Value::parse(ValType::I32, "0xffffffff").unwrap(), Value::I32(-1));
    assert_eq!(Value::parse(ValType::I64, "-0x8000000000000000").unwrap(), Value::I64(i64::MIN));
}

#[test]
fn data_count_section_is_accepted_and_cross_checked() {
    // (module (memory 1) (data (i32.const 0) "ab")) with a datacount section in the right place.
    let good: Vec<u8> = [
        b"\0asm\x01\0\0\0".as_slice(),
        &[5, 3, 1, 0, 1],                          // memory section
        &[12, 1, 1],                               // datacount = 1
        &[11, 8, 1, 0, 0x41, 0, 0x0b, 2, b'a', b'b'], // data section
    ]
    .concat();
    let m = decode::decode(&good).unwrap();
    assert_eq!(m.datas.len(), 1);
    let mut bad = good.clone();
    bad[15] = 2; // datacount says 2 segments
    assert!(decode::decode(&bad).unwrap_err().msg.contains("data count"));
    // datacount after the code section is out of order
    let misordered: Vec<u8> = [b"\0asm\x01\0\0\0".as_slice(), &[10, 1, 0], &[12, 1, 0]].concat();
    assert!(decode::decode(&misordered).unwrap_err().msg.contains("out of order"));
}

#[test]
fn decoder_rejects_hostile_binaries_without_panicking() {
    let hdr = b"\0asm\x01\0\0\0";
    let cases: Vec<(&str, Vec<u8>)> = vec![
        ("giant vector", [hdr.as_slice(), &[1, 6, 0xff, 0xff, 0xff, 0xff, 0x0f, 0]].concat()),
        ("section size past EOF", [hdr.as_slice(), &[1, 100, 0]].concat()),
        ("section size LEB too long", [hdr.as_slice(), &[1, 0x80, 0x80, 0x80, 0x80, 0x80, 0]].concat()),
        ("unknown section", [hdr.as_slice(), &[99, 0]].concat()),
        ("duplicate section", [hdr.as_slice(), &[5, 3, 1, 0, 1, 5, 3, 1, 0, 1]].concat()),
        ("section underrun", [hdr.as_slice(), &[5, 4, 1, 0, 1, 0]].concat()),
        ("bad type tag", [hdr.as_slice(), &[1, 4, 1, 0x61, 0, 0]].concat()),
        ("bad valtype", [hdr.as_slice(), &[1, 5, 1, 0x60, 1, 0x70, 0]].concat()),
        ("truncated header", b"\0asm\x01\0".to_vec()),
        ("bad magic", b"\x7fELF\x01\0\0\0".to_vec()),
        ("non-UTF8 export name", [hdr.as_slice(), &[7, 5, 1, 2, 0xff, 0xfe, 0]].concat()),
        ("function without code", [hdr.as_slice(), &[1, 4, 1, 0x60, 0, 0, 3, 2, 1, 0]].concat()),
    ];
    for (name, bytes) in cases {
        let r = std::panic::catch_unwind(|| decode::decode(&bytes));
        match r {
            Ok(Err(_)) => {}
            Ok(Ok(_)) => panic!("{name}: accepted"),
            Err(_) => panic!("{name}: decoder panicked"),
        }
    }
}

#[test]
fn every_prefix_of_a_real_binary_is_handled_cleanly() {
    let m = module(&std::fs::read_to_string(concat!(env!("CARGO_MANIFEST_DIR"), "/tests/corpus/calls.wat")).unwrap().split(";; assert").next().unwrap().to_string());
    let bytes = encode::encode(&m);
    // Cutting exactly at a section boundary yields a legitimately smaller module; any other cut must fail.
    let mut boundaries = vec![8usize];
    let mut pos = 8;
    while pos < bytes.len() {
        let size = {
            let mut p = pos + 1;
            let v = leb::read_u(&bytes, &mut p, 32).unwrap() as usize;
            (p - pos - 1, v)
        };
        pos += 1 + size.0 + size.1;
        boundaries.push(pos);
    }
    for n in 0..bytes.len() {
        let r = std::panic::catch_unwind(|| decode::decode(&bytes[..n]).ok().map(|m| validate::validate(&m).is_ok()));
        assert!(r.is_ok(), "panic on {n}-byte prefix");
        if matches!(r, Ok(Some(_))) {
            assert!(boundaries.contains(&n), "a {n}-byte prefix (mid-section) decoded successfully");
        }
    }
    assert!(decode::decode(&bytes).is_ok());
}

#[test]
fn memory_growth_respects_declared_and_engine_limits() {
    let m = module(r#"(module (memory 1 2) (func (export "g") (param i32) (result i32) (memory.grow (local.get 0))))"#);
    let mut inst = Instance::new(m, Imports::default()).unwrap();
    assert_eq!(inst.invoke("g", &[Value::I32(1)]).unwrap(), vec![Value::I32(1)]);
    assert_eq!(inst.invoke("g", &[Value::I32(1)]).unwrap(), vec![Value::I32(-1)]);
    assert_eq!(inst.invoke("g", &[Value::I32(-1)]).unwrap(), vec![Value::I32(-1)], "delta is unsigned: 4294967295 pages");
    let m = module(r#"(module (memory 1) (func (export "g") (param i32) (result i32) (memory.grow (local.get 0))))"#);
    let mut inst = Instance::new(m, Imports::default()).unwrap();
    assert_eq!(inst.invoke("g", &[Value::I32(100000)]).unwrap(), vec![Value::I32(-1)], "beyond the 65536-page spec limit");
}

#[test]
fn profiler_counts_instructions_calls_and_edges() {
    let m = module(r#"(module
        (func $leaf (param i32) (result i32) (i32.add (local.get 0) (i32.const 1)))
        (func (export "top") (result i32) (call $leaf (call $leaf (i32.const 0)))))"#);
    let mut inst = Instance::new(m, Imports::default()).unwrap();
    inst.profile = Some(Box::new(trace::Profile::new(100)));
    inst.invoke("top", &[]).unwrap();
    let p = inst.profile.take().unwrap();
    assert_eq!(p.funcs[&0].calls, 2);
    assert_eq!(p.funcs[&1].calls, 1);
    assert_eq!(p.edges[&(Some(1), 0)], 2);
    assert_eq!(p.edges[&(None, 1)], 1);
    // leaf: local.get, i32.const, i32.add, end = 4 each; top: i32.const, call, call, end = 4
    assert_eq!(p.funcs[&0].instrs, 8);
    assert_eq!(p.funcs[&1].instrs, 4);
    assert_eq!(p.total, 12);
    assert_eq!(p.max_depth, 2);
    assert_eq!(p.trace.len(), 12);
    assert_eq!(p.ops["end"], 3);
    let html = p.html_report(&inst.module, "t<est>");
    assert!(html.starts_with("<!doctype html>") && html.contains("t&lt;est&gt;") && html.contains("$leaf"));
    assert!(p.text_report(&inst.module).contains("instructions executed : 12"));
}
