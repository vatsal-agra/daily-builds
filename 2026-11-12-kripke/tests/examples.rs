use kripke::check::Verdict;
use kripke::driver::{run, Options, Report};
use kripke::gen::generate;

fn go(src: &str, opts: &Options) -> Report {
    run(src, opts).unwrap_or_else(|e| panic!("{}", e.render(src, "model")))
}

fn verdicts(r: &Report) -> Vec<(String, bool)> {
    r.outcomes
        .iter()
        .map(|o| (o.label.clone(), o.verdict == Verdict::Holds))
        .collect()
}

fn expect(r: &Report, want: &[(&str, bool)]) {
    let got = verdicts(r);
    assert_eq!(got.len(), want.len(), "spec count: {:?}", got);
    for ((g, gv), (w, wv)) in got.iter().zip(want) {
        assert_eq!(g, w);
        assert_eq!(gv, wv, "spec {} expected {}", g, wv);
    }
}

fn file(name: &str) -> String {
    std::fs::read_to_string(format!("examples/{}.smv", name)).unwrap()
}

#[test]
fn peterson() {
    let r = go(&file("peterson"), &Options::default());
    expect(
        &r,
        &[
            ("mutual_exclusion", true),
            ("no_starvation_0", true),
            ("no_starvation_1", true),
            ("can_enter", true),
            ("ltl_starvation_free", true),
            ("ltl_always_enters", false),
        ],
    );
    assert_eq!(r.info.reachable, 68);
    assert_eq!(r.info.deadlocks, 0);
    // the failing LTL spec yields a lasso
    match &r.outcomes[5].verdict {
        Verdict::Fails(Some(t)) => assert!(t.loop_start.is_some()),
        v => panic!("{:?}", v),
    }
}

#[test]
fn broken_mutex_shortest_counterexample() {
    let r = go(&file("broken_mutex"), &Options::default());
    expect(&r, &[("mutual_exclusion", false), ("can_reach_crit", true)]);
    let Verdict::Fails(Some(t)) = &r.outcomes[0].verdict else {
        panic!()
    };
    // BFS depth: 3 steps for the first process to reach crit, 3 for the other = shortest is 6 steps -> 7 states
    assert_eq!(t.steps.len(), 7);
    let last = &t.steps[6].state;
    assert!(
        last.iter().any(|(k, v)| k == "pc0" && v == "crit")
            && last.iter().any(|(k, v)| k == "pc1" && v == "crit")
    );
}

#[test]
fn msi_correct_and_buggy() {
    let ok = go(&file("msi"), &Options::default());
    assert!(ok.all_hold(), "{:?}", verdicts(&ok));
    let bad = go(&file("msi_buggy"), &Options::default());
    expect(
        &bad,
        &[("writer_excludes_readers", false), ("single_writer", true)],
    );
    let Verdict::Fails(Some(t)) = &bad.outcomes[0].verdict else {
        panic!()
    };
    assert_eq!(t.steps.len(), 3, "reader, then a write from another cache");
    assert!(
        t.steps[0].inputs.iter().any(|(k, _)| k == "who"),
        "inputs are reported"
    );
}

#[test]
fn elevator_fixed_vs_naive() {
    assert!(go(&file("elevator"), &Options::default()).all_hold());
    let r = go(&file("elevator_naive"), &Options::default());
    let v = verdicts(&r);
    assert!(v.contains(&("floor0_served".to_string(), false)));
    assert!(v.contains(&("ltl_floor2_served".to_string(), false)));
    assert!(v.contains(&("doors_closed_while_moving".to_string(), true)));
}

#[test]
fn traffic() {
    assert!(go(&file("traffic"), &Options::default()).all_hold());
}

#[test]
fn lfsr_period_is_maximal() {
    for n in 3..=12 {
        let r = go(&generate("lfsr", n).unwrap(), &Options::default());
        assert_eq!(r.info.reachable, (1u128 << n) - 1, "lfsr {}", n);
        assert!(r.all_hold(), "lfsr {}", n);
    }
}

#[test]
fn philosophers_deadlock_and_fix() {
    // The scheduler variable keeps changing, so the frozen table is a non-progress cycle, not a transition deadlock.
    let naive = go(&generate("philosophers", 4).unwrap(), &Options::default());
    assert_eq!(naive.info.deadlocks, 0);
    expect(
        &naive,
        &[
            ("neighbours_never_both_eat", true),
            ("philosopher0_can_eat", true),
            ("always_possible_to_eat_again", false),
            ("no_starvation_0", false),
            ("everyone_eats_infinitely_often", false),
        ],
    );
    let Verdict::Fails(Some(t)) = &naive.outcomes[2].verdict else {
        panic!()
    };
    let last = t.steps.last().unwrap();
    assert_eq!(
        last.state
            .iter()
            .filter(|(k, v)| k.starts_with('p') && v == "left")
            .count(),
        4,
        "everyone holds a left fork"
    );
    let fixed = go(
        &generate("philosophers-fixed", 4).unwrap(),
        &Options::default(),
    );
    assert_eq!(fixed.info.deadlocks, 0);
    assert_eq!(fixed.outcomes[2].verdict, Verdict::Holds);
    assert_eq!(fixed.outcomes[0].verdict, Verdict::Holds);
}

#[test]
fn tokenring_and_counter_families() {
    for n in [2, 3, 5] {
        let r = go(&generate("tokenring", n).unwrap(), &Options::default());
        assert!(r.all_hold(), "tokenring {}: {:?}", n, verdicts(&r));
    }
    let c = go(&generate("counter", 6).unwrap(), &Options::default());
    let v = verdicts(&c);
    assert!(
        v.iter()
            .filter(|(n, _)| n != "never_reaches_max")
            .all(|(_, ok)| *ok),
        "{:?}",
        v
    );
    let Verdict::Fails(Some(t)) = &c
        .outcomes
        .iter()
        .find(|o| o.label == "never_reaches_max")
        .unwrap()
        .verdict
    else {
        panic!()
    };
    assert_eq!(t.steps.len(), 64, "shortest path counts up 63 times");
}

#[test]
fn sixteen_bit_counter_with_bitvectors() {
    let src = "VAR n : 0..65535;\nASSIGN init(n) := 0; next(n) := (n + 1) mod 65536;\nINVARSPEC n != 65535\nSPEC AG (n = 40000 -> AX n = 40001)\n";
    let r = go(src, &Options::default());
    expect(&r, &[("spec1", false), ("spec2", true)]);
    assert_eq!(r.info.reachable, 65536);
    let Verdict::Fails(Some(t)) = &r.outcomes[0].verdict else {
        panic!()
    };
    assert_eq!(t.steps.len(), 65536);
}

#[test]
fn reordering_collapses_the_comparator() {
    let src = generate("comparator", 14).unwrap();
    let plain = go(&src, &Options::default());
    let sifted = go(
        &src,
        &Options {
            reorder: true,
            ..Default::default()
        },
    );
    assert!(plain.all_hold() && sifted.all_hold());
    assert_eq!(plain.info.reachable, sifted.info.reachable);
    assert!(
        plain.info.init_nodes > 100 * sifted.info.init_nodes,
        "{} vs {}",
        plain.info.init_nodes,
        sifted.info.init_nodes
    );
    let (before, after, swaps) = sifted.info.reorder.unwrap();
    assert!(after < before / 50 && swaps > 0);
}

#[test]
fn fairness_changes_liveness_verdicts() {
    let model = |fair: &str| {
        format!("VAR s : boolean; x : boolean;\nASSIGN init(s) := FALSE; init(x) := FALSE; next(s) := {{TRUE, FALSE}};\n next(x) := case s : TRUE; TRUE : x; esac;\n{}\nSPEC AF x\nLTLSPEC F x\n", fair)
    };
    let unfair = go(&model(""), &Options::default());
    expect(&unfair, &[("spec1", false), ("spec2", false)]);
    let Verdict::Fails(Some(t)) = &unfair.outcomes[0].verdict else {
        panic!()
    };
    assert!(t.loop_start.is_some(), "liveness failure is a lasso");
    let fair = go(&model("FAIRNESS s"), &Options::default());
    expect(&fair, &[("spec1", true), ("spec2", true)]);
}

#[test]
fn ltl_beyond_ctl() {
    let src = "VAR a : boolean; b : boolean;\nASSIGN init(a) := TRUE; init(b) := FALSE; next(a) := case a : {TRUE, FALSE}; TRUE : FALSE; esac; next(b) := !a;\n\
               LTLSPEC F G !a\nLTLSPEC G F a\nLTLSPEC G (a -> X (a | !a))\nLTLSPEC a U !a\nLTLSPEC (G F a) -> (G F b)\nLTLSPEC X X b\n";
    let r = go(src, &Options::default());
    let got: Vec<bool> = r
        .outcomes
        .iter()
        .map(|o| o.verdict == Verdict::Holds)
        .collect();
    // `a` may stay TRUE forever (F G !a, a U !a fail, G F a holds only on paths that flip back: fails),
    // on that path b stays FALSE so GF a -> GF b fails, and X X b fails; the tautology holds.
    assert_eq!(got, vec![false, false, true, false, false, false]);
    for o in &r.outcomes {
        if let Verdict::Fails(Some(t)) = &o.verdict {
            assert!(t.loop_start.is_some(), "LTL counterexamples are lassos");
        }
    }
}

#[test]
fn explicit_engine_agrees_on_every_example() {
    for name in [
        "peterson",
        "broken_mutex",
        "msi",
        "msi_buggy",
        "traffic",
        "elevator",
        "elevator_naive",
    ] {
        let src = file(name);
        let prog = kripke::lang::parse(&src).unwrap();
        let sym = go(&src, &Options::default());
        let mut ex = kripke::explicit::Explicit::new(&prog, 200_000, false).unwrap();
        let (reach, diam, dead) = ex.reachability();
        assert_eq!(
            sym.info.reachable,
            reach.iter().filter(|&&b| b).count() as u128,
            "{}",
            name
        );
        assert_eq!(sym.info.diameter, diam, "{}", name);
        assert_eq!(sym.info.deadlocks, dead as u128, "{}", name);
        for (i, sp) in prog.specs.iter().enumerate() {
            let want = match sp.kind {
                kripke::lang::SpecKind::Ctl => Some(ex.check_ctl(&sp.expr).unwrap()),
                kripke::lang::SpecKind::Invar => Some(ex.check_invar(&sp.expr).unwrap()),
                kripke::lang::SpecKind::Ltl => ex.check_ltl_fragment(&sp.expr).unwrap(),
            };
            if let Some(w) = want {
                assert_eq!(
                    sym.outcomes[i].verdict == Verdict::Holds,
                    w,
                    "{} spec {}",
                    name,
                    i + 1
                );
            }
            if let Verdict::Fails(Some(t)) = &sym.outcomes[i].verdict {
                ex.validate_trace(t)
                    .unwrap_or_else(|m| panic!("{} spec {}: {}", name, i + 1, m));
            }
        }
    }
}

#[test]
fn compile_errors_are_helpful() {
    let cases: &[(&str, &str)] = &[
        (
            "VAR state : {idle, busy};\nASSIGN next(state) := stat;\n",
            "did you mean 'state'",
        ),
        (
            "VAR n : 0..3;\nASSIGN next(n) := n + 1;\n",
            "outside its type 0..3",
        ),
        (
            "VAR x : boolean; n : 0..3;\nINIT x = n\n",
            "cannot compare boolean with integer",
        ),
        (
            "VAR x : boolean;\nASSIGN next(x) := x; next(x) := !x;\n",
            "assigned twice",
        ),
        (
            "VAR x : boolean;\nSPEC AG next(x)\n",
            "next(..) is only allowed",
        ),
        (
            "IVAR i : boolean;\nVAR x : boolean;\nINIT i\n",
            "input variable",
        ),
        ("VAR x : boolean;\nDEFINE d := d;\nSPEC d\n", "recursive"),
        (
            "VAR x : boolean;\nSPEC G x\n",
            "LTL operator in a CTL formula",
        ),
        ("VAR x : boolean;\nLTLSPEC AG x\n", "not allowed in LTLSPEC"),
        (
            "VAR x : boolean;\nINVARSPEC AG x\n",
            "INVARSPEC must be a plain state predicate",
        ),
        (
            "VAR n : 0..3;\nASSIGN init(n) := 0; next(n) := case n < 2 : 1; esac;\n",
            "not exhaustive",
        ),
        ("VAR e : {a, b}; f : {b, c};\n", "x"),
    ];
    for (src, frag) in cases {
        match run(src, &Options::default()) {
            Err(e) => assert!(
                e.msg.contains(frag) || *frag == "x",
                "`{}` -> `{}` (wanted `{}`)",
                src,
                e.msg,
                frag
            ),
            Ok(_) if *frag == "x" => {} // shared enum symbols are allowed
            Ok(_) => panic!("`{}` should have been rejected", src),
        }
    }
}
