use wick::*;

fn same_modulo_names(a: &ast::Module, b: &ast::Module) -> Result<(), String> {
    macro_rules! eq {
        ($f:ident) => {
            if a.$f != b.$f {
                return Err(format!("{} differ:\n{:?}\nvs\n{:?}", stringify!($f), a.$f, b.$f));
            }
        };
    }
    eq!(types);
    eq!(imports);
    eq!(funcs);
    eq!(tables);
    eq!(mems);
    eq!(globals);
    eq!(exports);
    eq!(start);
    eq!(elems);
    eq!(codes);
    eq!(datas);
    Ok(())
}

#[test]
fn disassembly_reassembles_identically_on_generated_programs() {
    for seed in 1..=1500u64 {
        let case = fuzz::generate(seed);
        let text = disasm::disassemble(&case.module);
        let m2 = wat::parse_module(&text).unwrap_or_else(|e| panic!("seed {seed}: disassembly does not parse: {e}\n{text}"));
        same_modulo_names(&case.module, &m2).unwrap_or_else(|e| panic!("seed {seed}: {e}"));
        validate::validate(&m2).unwrap();
    }
}

#[test]
fn binary_roundtrip_is_byte_identical_on_generated_programs() {
    for seed in 1..=1500u64 {
        let case = fuzz::generate(seed);
        let bytes = encode::encode(&case.module);
        let m2 = decode::decode(&bytes).unwrap_or_else(|e| panic!("seed {seed}: {e}"));
        assert_eq!(encode::encode(&m2), bytes, "seed {seed}");
    }
}
