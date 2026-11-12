use kripke::lang::{parse, parse_expr};

fn roundtrip(src: &str) {
    let e = parse_expr(src).unwrap_or_else(|e| panic!("{}: {}", src, e));
    let printed = format!("{}", e);
    let e2 = parse_expr(&printed).unwrap_or_else(|e| panic!("reparse of `{}` failed: {}", printed, e));
    assert_eq!(printed, format!("{}", e2), "printing is not a fixed point for {}", src);
}

#[test]
fn printing_round_trips_and_minimises_parentheses() {
    for src in [
        "a & b & c",
        "a & (b & c)",
        "a | b & c",
        "(a | b) & c",
        "a -> b -> c",
        "(a -> b) -> c",
        "a <-> (b <-> c)",
        "!(a & b)",
        "!a & b",
        "AG (a -> AF b)",
        "AG a -> AF b",
        "E[a U b] & A[c U d]",
        "x + y * z - 1 = w mod 3",
        "(x + y) * z",
        "x - (y - z)",
        "x in {1, 2, 3} & y != 2",
        "G (F p) & X q",
        "a U b U c",
        "(a U b) U c",
        "next(x) = case a : 1; TRUE : 2; esac",
        "-x + 1 < 3",
        "-(x + 1)",
    ] {
        roundtrip(src);
    }
    assert_eq!(format!("{}", parse_expr("a & b & c").unwrap()), "a & b & c");
    assert_eq!(format!("{}", parse_expr("(a & b) & c").unwrap()), "a & b & c");
    assert_eq!(format!("{}", parse_expr("a & (b & c)").unwrap()), "a & (b & c)");
    assert_eq!(format!("{}", parse_expr("AG x = 3").unwrap()), "AG (x = 3)");
}

#[test]
fn precedence_matches_the_documentation() {
    // temporal prefix operators take a whole comparison; & binds tighter than | which binds tighter than ->
    assert_eq!(format!("{}", parse_expr("AG p -> q | r & s").unwrap()), "AG p -> q | r & s");
    let e = parse_expr("AG p -> q").unwrap();
    assert!(matches!(&e.k, kripke::lang::Ek::Bin(kripke::lang::BinOp::Imp, ..)));
}

#[test]
fn syntax_errors_are_positioned() {
    for (src, line, frag) in [
        ("VAR x : boolean;\nSPEC AG x &\n", 3, "expected an expression"),
        ("VAR x boolean;", 1, "expected ':'"),
        ("VAR x : 3..1;", 1, "empty range"),
        ("VAR x : {a};", 1, "at least two"),
        ("VAR x : {a, a};", 1, "duplicate enum"),
        ("VAR x : boolean;\nASSIGN next(x) := case x : TRUE;", 2, "expected an expression"),
        ("INIT x $ y", 1, "unexpected character"),
        ("VAR 9x : boolean;", 1, "expected an identifier"),
        ("MODULE other\nVAR x : boolean;", 1, "MODULE main"),
        ("VAR x : boolean;\nSPEC E[x U]", 2, "expected an expression"),
    ] {
        let err = parse(src).unwrap_err();
        assert_eq!(err.pos.line, line, "{}: {}", src, err);
        assert!(err.msg.contains(frag), "`{}`: message `{}` lacks `{}`", src, err.msg, frag);
    }
}

#[test]
fn absurd_nesting_is_an_error_not_a_crash() {
    let deep = format!("VAR x : boolean;\nSPEC {}x{}", "(".repeat(100_000), ")".repeat(100_000));
    let err = std::thread::Builder::new().stack_size(64 << 20).spawn(move || parse(&deep).unwrap_err()).unwrap().join().unwrap();
    assert!(err.msg.contains("nested too deeply"));
    let bangs = format!("VAR x : boolean;\nSPEC {}x", "!".repeat(100_000));
    let err = std::thread::Builder::new().stack_size(64 << 20).spawn(move || parse(&bangs).unwrap_err()).unwrap().join().unwrap();
    assert!(err.msg.contains("nested too deeply"));
}
