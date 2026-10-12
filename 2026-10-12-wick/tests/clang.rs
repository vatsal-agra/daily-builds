//! End-to-end check on *real compiler output*: C workloads are compiled to wasm32 by clang and run
//! on Wick; the answers must equal those of the same C compiled natively. Skipped (with a notice)
//! when clang, wasm-ld or a native C compiler is not installed.
use std::process::Command;
use wick::interp::*;
use wick::*;

fn have(tool: &str) -> bool {
    Command::new(tool).arg("--version").output().map(|o| o.status.success()).unwrap_or(false)
}

#[test]
fn clang_compiled_programs_match_native_execution() {
    if !(have("clang") && have("wasm-ld") && have("gcc")) {
        eprintln!("SKIPPED: needs clang + wasm-ld + gcc");
        return;
    }
    let root = env!("CARGO_MANIFEST_DIR");
    let dir = std::env::temp_dir().join(format!("wick-clang-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let wasm = dir.join("programs.wasm");
    let native = dir.join("native");
    let st = Command::new("clang")
        .args(["--target=wasm32", "-nostdlib", "-O2", "-mbulk-memory", "-ffp-contract=off", "-Wl,--no-entry", "-Wl,--export-dynamic", "-Wl,--initial-memory=4194304", "-Wl,-z,stack-size=131072", "-o"])
        .arg(&wasm)
        .arg(format!("{root}/tests/c/programs.c"))
        .status()
        .unwrap();
    assert!(st.success(), "clang failed");
    let st = Command::new("gcc").args(["-O2", "-ffp-contract=off", "-o"]).arg(&native).arg(format!("{root}/tests/c/driver.c")).arg("-lm").status().unwrap();
    assert!(st.success(), "gcc failed");
    let expected = String::from_utf8(Command::new(&native).output().unwrap().stdout).unwrap();

    let module = decode::decode(&std::fs::read(&wasm).unwrap()).expect("decode clang output");
    let mut inst = Instance::new(module, Imports::default()).expect("instantiate clang output");
    let mut checked = 0;
    for line in expected.lines() {
        // "name arg => type:value"
        let (lhs, rhs) = line.split_once(" => ").unwrap();
        let mut it = lhs.split(' ');
        let name = it.next().unwrap();
        let arg: i32 = it.next().unwrap().parse().unwrap();
        let (ty, val) = rhs.split_once(':').unwrap();
        let got = inst.invoke(name, &[Value::I32(arg)]).unwrap_or_else(|e| panic!("{name}({arg}): {e}"));
        let want = Value::parse(ast::ValType::parse(ty).unwrap(), val).unwrap();
        assert_eq!(got.len(), 1);
        match (&want, &got[0]) {
            (Value::F64(a), Value::F64(b)) => assert_eq!(a.to_bits(), b.to_bits(), "{name}({arg})"),
            (a, b) => assert_eq!(a, b, "{name}({arg})"),
        }
        checked += 1;
    }
    println!("clang-compiled workloads matched native results: {checked} calls");
    assert!(checked >= 30);
    let _ = std::fs::remove_dir_all(&dir);
}
