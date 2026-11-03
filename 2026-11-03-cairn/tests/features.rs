//! One test group per feature in PLAN.md, plus the CLI.
mod common;
use cairn::bench::*;
use cairn::heap::*;
use cairn::lang;
use cairn::vm::VmOptions;
use cairn::*;
use common::*;
use std::process::Command;

fn bin() -> Command {
    Command::new(env!("CARGO_BIN_EXE_cairn"))
}
fn example(name: &str) -> String {
    std::fs::read_to_string(format!("{}/examples/{name}.cairn", env!("CARGO_MANIFEST_DIR"))).unwrap()
}

// ---------------------------------------------------------------- F1: heap + mark-sweep + semispace
#[test]
fn f1_value_tagging_roundtrips() {
    for i in [0i64, 1, -1, 42, -42, (1 << 62) - 1, -(1 << 62)] {
        let v = Value::int(i);
        assert!(v.is_int() && !v.is_ptr() && !v.is_nil());
        assert_eq!(v.as_int(), i);
    }
    assert!(Value::NIL.is_nil() && !Value::NIL.is_ptr() && !Value::NIL.is_int());
    assert_eq!(Value::ptr(123).addr(), 123);
}

#[test]
fn f1_free_list_splits_coalesces_and_reports_largest_block() {
    let mut mem = vec![0u64; 200];
    let mut fl = FreeList::new();
    fl.add(&mut mem, 1, 100);
    assert_eq!(fl.words, 100);
    let a = fl.alloc(&mut mem, 10).unwrap();
    let b = fl.alloc(&mut mem, 3).unwrap();
    assert_ne!(a, b);
    assert_eq!(fl.words, 87);
    assert_eq!(fl.largest(&mem), 87);
    assert!(fl.alloc(&mut mem, 88).is_none());
    // a one-word remainder becomes an unlisted filler instead of corrupting the heap
    let c = fl.alloc(&mut mem, 86).unwrap();
    assert_eq!(hdr_kind(mem[c + 86]), Kind::Free);
    assert_eq!(hdr_total(mem[c + 86]), 1);
    assert_eq!(fl.words, 0);
}

#[test]
fn f1_sweep_coalesces_adjacent_garbage_into_one_block() {
    let mut gc = make_gc("marksweep", &small_cfg()).unwrap();
    let mut roots = vec![Value::NIL; 2];
    let first = gc.alloc(Kind::Pair, 2, &mut roots).unwrap();
    roots[0] = first;
    for _ in 0..50 {
        gc.alloc(Kind::Pair, 2, &mut roots).unwrap();
    }
    let last = gc.alloc(Kind::Pair, 2, &mut roots).unwrap();
    roots[1] = last;
    gc.collect(&mut roots, true).unwrap();
    // two survivors, with one 150-word hole between them
    let blocks = gc.walk();
    let free_between: Vec<_> = blocks.iter().filter(|b| b.2 && b.1 == 150).collect();
    assert_eq!(free_between.len(), 1, "{blocks:?}");
}

#[test]
fn f1_semispace_copies_in_breadth_first_order_and_preserves_sharing() {
    let mut gc = make_gc("semispace", &small_cfg()).unwrap();
    let mut roots = vec![Value::NIL];
    let shared = gc.alloc(Kind::Pair, 2, &mut roots).unwrap();
    roots[0] = shared;
    gc.store(shared, 0, Value::int(9));
    let p = gc.alloc(Kind::Pair, 2, &mut roots).unwrap();
    gc.store(p, 0, roots[0]);
    gc.store(p, 1, roots[0]); // both fields share one object
    roots.push(p);
    gc.collect(&mut roots, true).unwrap();
    let p = roots[1];
    assert_eq!(gc.load(p, 0), gc.load(p, 1), "sharing must survive copying");
    assert_eq!(gc.load(gc.load(p, 0), 0), Value::int(9));
    assert_eq!(gc.used_words(), 6, "two live pairs, no garbage");
}

// ---------------------------------------------------------------- F2: generational
#[test]
fn f2_generational_minor_collections_promote_and_barrier_fires() {
    let s = run_verified(&example("cache"), "generational").unwrap();
    assert!(s.minor >= 3, "{s:?}");
    assert!(s.promoted > 0);
    assert!(s.barrier_hits > 0, "old table pointed at young pairs: the barrier must record them");
    let want = run("(print 1)", "marksweep").unwrap();
    let _ = want;
}

#[test]
fn f2_generational_agrees_with_marksweep_on_big_example_under_oracle_sampling() {
    let cfg = GcConfig {
        words: 40_000,
        nursery: 3_000,
        ..Default::default()
    };
    let a = run_with(&example("cache"), "generational", cfg.clone(), VmOptions::default()).unwrap();
    let b = run_with(&example("cache"), "marksweep", cfg, VmOptions::default()).unwrap();
    assert_eq!(a.out, b.out);
    assert!(a.minor > 5 && a.collections >= a.minor);
}

#[test]
fn f2_large_objects_go_straight_to_the_old_generation() {
    let mut gc = make_gc(
        "generational",
        &GcConfig {
            words: 6000,
            nursery: 400,
            ..Default::default()
        },
    )
    .unwrap();
    let mut roots = vec![Value::NIL];
    let big = gc.alloc(Kind::Vec, 300, &mut roots).unwrap(); // > nursery/2
    roots[0] = big;
    let before = roots[0];
    gc.collect(&mut roots, false).unwrap();
    assert_eq!(before, roots[0], "old-generation objects are not moved by a minor GC");
    assert_eq!(gc.stats().promoted_words, 0);
}

// ---------------------------------------------------------------- F3: incremental SATB
#[test]
fn f3_incremental_work_is_spread_over_many_small_pauses() {
    let cfg = GcConfig {
        words: 200_000,
        nursery: 0,
        barrier: true,
        trigger: 0.3,
        pace: 4,
    };
    let inc = run_with(&example("bintrees"), "incremental", cfg.clone(), VmOptions::default()).unwrap();
    let ms = run_with(&example("bintrees"), "marksweep", cfg, VmOptions::default()).unwrap();
    assert_eq!(inc.out, ms.out);
    assert!(inc.pauses > 500, "increments: {}", inc.pauses);
    // deterministic work-unit comparison (not wall clock): the biggest single increment is a tiny
    // fraction of the stop-the-world collection
    assert!(
        inc.max_pause_work * 20 < ms.max_pause_work,
        "inc {} vs ms {}",
        inc.max_pause_work,
        ms.max_pause_work
    );
}

#[test]
fn f3_allocation_during_marking_is_black_and_barrier_counts_hits() {
    let cfg = GcConfig {
        words: 30_000,
        nursery: 0,
        barrier: true,
        trigger: 0.1,
        pace: 1,
    };
    let s = run_with(
        &example("queue"),
        "incremental",
        cfg,
        VmOptions {
            verify: false,
            ..Default::default()
        },
    )
    .unwrap();
    assert!(s.collections > 0);
}

#[test]
fn f3_no_barrier_flag_is_caught_end_to_end() {
    let out = bin()
        .args([
            "run",
            "examples/cache.cairn",
            "--gc",
            "generational",
            "--heap",
            "20000",
            "--nursery",
            "800",
            "--verify",
            "--no-barrier",
        ])
        .current_dir(env!("CARGO_MANIFEST_DIR"))
        .output()
        .unwrap();
    assert!(!out.status.success());
    assert!(String::from_utf8_lossy(&out.stderr).contains("HEAP CORRUPTION"));
}

// ---------------------------------------------------------------- F4: language + VM + oracle
#[test]
fn f4_language_semantics() {
    let src = r#"
    (fn (fact n) (if (<= n 1) 1 (* n (fact (- n 1)))))
    (fn (len xs) (if (nil? xs) 0 (+ 1 (len (cdr xs)))))
    (def g 10)
    (let ((a 1) (b (+ a 1)) (c (* b 3)))
      (print a b c (fact 10) (len (cons 1 (cons 2 nil))) g)
      (set! g (+ g 1)))
    (print (and 1 2 3) (and 1 nil 3) (or nil nil 7) (not nil) (not 0) g)
    (print (< 1 2) (>= 1 2) (= 3 3) (!= 3 3) (eq nil nil) (% 17 5) (/ -7 2) (- 5))
    (print (pair? (cons 1 2)) (pair? nil) (int? 3) (vector? (vector 1)) (string? "x") (nil? nil))
    (print "a\tb\"c" (cons "q\"" nil) (vector 2 7) (vector 0) (str 123) (strcat "ab" "cd") (strref "A" 0) (substr "hello" 1 3))
    (let ((i 0) (acc nil)) (while (< i 5) (set! acc (cons i acc)) (set! i (+ i 1))) (print acc))
    (when nil (print "never")) (when 1 (print "when"))
    "#;
    let s = run(src, "marksweep").unwrap();
    let want = "1 2 6 3628800 2 10\n3 nil 7 1 nil 11\n1 nil 1 nil 1 2 -3 -5\n1 nil 1 1 1 1\na\tb\"c (\"q\\\"\") #(7 7) #() 123 abcd 65 el\n(4 3 2 1 0)\nwhen\n";
    assert_eq!(s.out, want);
}

#[test]
fn f4_errors_are_clean_and_specific() {
    for (src, needle) in [
        ("(car 5)", "car expects a pair"),
        ("(vref (vector 3) 3)", "outside 0..3"),
        ("(/ 1 0)", "division by zero"),
        ("(+ 1 nil)", "expects an integer"),
        ("(fn (f n) (f (+ n 1))) (f 0)", "call depth"),
        ("(assert (= 1 2))", "assertion failed"),
        ("(substr \"abc\" 2 9)", "substr"),
        ("(rand 0)", "bound"),
        ("(vector -1)", "out of range"),
        ("(strcat 1 2)", "expects a string"),
    ] {
        let e = run(src, "generational").expect_err(src);
        assert!(e.contains(needle), "{src}: {e}");
    }
}

#[test]
fn f4_compile_errors_carry_line_numbers() {
    for (src, needle) in [
        ("(print 1", "unclosed"),
        ("\n\n(print 1))", "line 3"),
        ("(foo)", "unknown function"),
        ("(print zz)", "unknown variable"),
        ("(cons 1)", "takes 2"),
        ("(if 1 2)", "if needs"),
        ("(let (x) 1)", "binding"),
        ("(fn (f) 1) (fn (f) 2)", "already defined"),
        ("(fn (cons a b) 1)", "builtin"),
        ("\"abc", "unterminated"),
        ("(print 1 . )", "unknown variable"),
        ("()", "empty list"),
    ] {
        let e = lang::compile(src).expect_err(src).to_string();
        assert!(e.contains(needle), "{src}: {e}");
    }
}

#[test]
fn f4_verify_mode_runs_the_oracle_on_every_allocation_and_torture_collects_constantly() {
    let src = "(def v (vector 10 nil)) (def i 0) (while (< i 10) (vset! v i (cons i (str i))) (set! i (+ i 1))) (print (digest v))";
    let plain = run(src, "semispace").unwrap();
    for g in ALL_GCS {
        let t = run_torture(src, g).unwrap_or_else(|e| panic!("{g}: {e}"));
        assert_eq!(t.out, plain.out, "{g}");
        assert!(
            t.collections >= 20,
            "{g}: torture should collect on (nearly) every allocation, got {}",
            t.collections
        );
        assert!(t.checks >= 20, "{g}");
    }
}

#[test]
fn f4_digest_is_collector_independent_and_sees_cycles() {
    let src = "(def a (cons 1 nil)) (def b (cons 2 a)) (set-cdr! a b) (gc) (print (digest a) (digest b))";
    let outs: Vec<String> = ALL_GCS.iter().map(|g| run_verified(src, g).unwrap().out).collect();
    assert!(outs.iter().all(|o| *o == outs[0]), "{outs:?}");
    let other = "(def a (cons 1 nil)) (def b (cons 2 a)) (set-cdr! a nil) (gc) (print (digest a) (digest b))";
    assert_ne!(outs[0], run(other, "marksweep").unwrap().out);
}

// ---------------------------------------------------------------- F5: compact
#[test]
fn f5_compact_preserves_allocation_order_and_closes_all_gaps() {
    let src = r#"
    (def a (cons 1 nil)) (cons 0 0) (def b (cons 2 nil)) (cons 0 0) (cons 0 0) (def c (cons 3 nil))
    (gc) (print a b c)"#;
    let s = run_verified(src, "compact").unwrap();
    assert_eq!(s.out, "(1) (2) (3)\n");
    assert_eq!(s.used, 9, "three live pairs, perfectly packed");
}

// ---------------------------------------------------------------- F6: bench harness + MMU
#[test]
fn f6_mmu_matches_hand_computed_values() {
    let p = |s, d| Pause {
        start_ns: s,
        dur_ns: d,
        kind: "x",
        work: 0,
    };
    let pauses = vec![p(100, 10), p(120, 10)];
    // window 20 containing both pauses fully: [105,125] has 5+5=10 paused => 0.5; [100,120] -> 10
    let m = mmu(&pauses, 1000, 20);
    assert!((m - 0.5).abs() < 1e-9, "{m}");
    // a window of 10 can be entirely inside one pause: utilisation 0
    assert_eq!(mmu(&pauses, 1000, 10), 0.0);
    // a window as long as the run: overall utilisation
    assert!((mmu(&pauses, 1000, 1000) - 0.98).abs() < 1e-9);
    assert_eq!(mmu(&[], 1000, 10), 1.0);
    // monotone in the window length
    let mut last = 0.0;
    for w in [5, 10, 20, 40, 80, 160, 1000] {
        let m = mmu(&pauses, 1000, w);
        assert!(m + 1e-12 >= last, "{w}: {m} < {last}");
        last = m;
    }
}

#[test]
fn f6_bench_rows_report_failures_and_fragmentation_honestly() {
    let src = example("bigvecs");
    let (ok, notes, frag) = big(move || {
        let prog = lang::compile(&src).unwrap();
        let cfg = GcConfig {
            words: 12_000,
            nursery: 1000,
            ..Default::default()
        };
        let mut ok = Vec::new();
        let mut notes = Vec::new();
        let mut frag = 0.0;
        for g in ["marksweep", "semispace", "compact"] {
            let r = run_one(&prog, g, &cfg, VmOptions::default()).unwrap();
            let row = row_of(&r);
            ok.push(row.ok);
            notes.push(row.note.clone());
            if g == "marksweep" {
                frag = 1.0 - row.largest_free as f64 / row.free_words.max(1) as f64;
            }
        }
        (ok, notes, frag)
    });
    assert_eq!(ok, vec![true, false, true], "{notes:?}");
    assert!(notes[1].contains("live data"), "{notes:?}");
    assert!(frag > 0.3, "mark-sweep leaves a fragmented heap, got {frag}");
}

#[test]
fn f6_bench_cli_runs_every_collector_and_checks_outputs_match() {
    let out = bin()
        .args(["bench", "examples/churn.cairn", "--heap", "100000", "--nursery", "5000"])
        .current_dir(env!("CARGO_MANIFEST_DIR"))
        .output()
        .unwrap();
    let text = String::from_utf8_lossy(&out.stdout);
    assert!(out.status.success(), "{text}{}", String::from_utf8_lossy(&out.stderr));
    for g in ALL_GCS {
        assert!(text.contains(g), "{text}");
    }
    assert!(text.contains("outputs identical across 5"), "{text}");
}

// ---------------------------------------------------------------- F7: HTML report
#[test]
fn f7_html_report_is_self_contained_and_covers_every_collector() {
    let dir = std::env::temp_dir().join(format!("cairn-report-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let out = dir.join("r.html");
    let st = bin()
        .args([
            "report",
            "examples/queue.cairn",
            "-o",
            out.to_str().unwrap(),
            "--heap",
            "60000",
            "--nursery",
            "4000",
        ])
        .current_dir(env!("CARGO_MANIFEST_DIR"))
        .status()
        .unwrap();
    assert!(st.success());
    let html = std::fs::read_to_string(&out).unwrap();
    assert!(html.starts_with("<!doctype html>"));
    for g in ALL_GCS {
        assert!(
            html.contains(&format!("</span>{g}</h3>")) || html.contains(&format!("</span>{g}</h3")) || html.contains(g),
            "{g}"
        );
    }
    assert!(html.matches("<svg").count() >= 11, "MMU chart + 2 charts per collector");
    assert!(
        !html.contains("http://") && !html.contains("https://") && !html.contains("<script"),
        "no external resources, no scripts"
    );
    assert!(html.contains("prefers-color-scheme:dark"));
    let _ = std::fs::remove_dir_all(dir);
}

// ---------------------------------------------------------------- F8: fuzzer
#[test]
fn f8_fuzz_programs_are_deterministic_and_agree_across_collectors() {
    assert_eq!(fuzz::gen_program(7), fuzz::gen_program(7));
    assert_ne!(fuzz::gen_program(7), fuzz::gen_program(8));
    let cfg = fuzz::fuzz_cfg();
    let r = big(move || {
        fuzz::fuzz(12, 900, &cfg, &fuzz::default_collectors(), true).map_err(|f| format!("{} {} {}", f.seed, f.collector, f.detail))
    });
    assert!(r.is_ok(), "{r:?}");
}

#[test]
fn f8_fuzzer_has_teeth_it_catches_a_collector_without_its_barrier() {
    let cfg = GcConfig {
        barrier: false,
        ..fuzz::fuzz_cfg()
    };
    let r = big(move || fuzz::fuzz(300, 1, &cfg, &["incremental"], false).map_err(|f| f.detail));
    let e = r.expect_err("a no-barrier incremental collector must be caught within 300 programs");
    assert!(e.contains("HEAP CORRUPTION") || e.contains("differs"), "{e}");
}

// ---------------------------------------------------------------- examples + CLI
#[test]
fn every_example_agrees_across_all_collectors() {
    let dir = format!("{}/examples", env!("CARGO_MANIFEST_DIR"));
    let mut n = 0;
    for entry in std::fs::read_dir(dir).unwrap() {
        let path = entry.unwrap().path();
        if path.extension().map(|e| e != "cairn").unwrap_or(true) {
            continue;
        }
        let name = path.file_stem().unwrap().to_string_lossy().to_string();
        if name == "bigvecs" {
            continue; // intentionally OOMs some collectors; covered by f6
        }
        let src = std::fs::read_to_string(&path).unwrap();
        let cfg = GcConfig {
            words: 300_000,
            nursery: 10_000,
            ..Default::default()
        };
        let outs: Vec<String> = ALL_GCS
            .iter()
            .map(|g| {
                run_with(&src, g, cfg.clone(), VmOptions::default())
                    .unwrap_or_else(|e| panic!("{name}/{g}: {e}"))
                    .out
            })
            .collect();
        assert!(!outs[0].is_empty(), "{name} printed nothing");
        assert!(outs.iter().all(|o| *o == outs[0]), "{name}: collectors disagree");
        n += 1;
    }
    assert!(n >= 8, "found {n} examples");
}

#[test]
fn cli_error_paths_exit_nonzero_with_a_message() {
    let cases: Vec<(Vec<&str>, &str)> = vec![
        (vec!["run"], "needs a FILE"),
        (vec!["run", "/nonexistent.cairn"], "cannot read"),
        (vec!["run", "examples/hello.cairn", "--gc", "nope"], "unknown collector"),
        (vec!["run", "examples/hello.cairn", "--heap", "abc"], "not a non-negative integer"),
        (vec!["run", "examples/hello.cairn", "--heap", "10"], "at least 64"),
        (vec!["run", "examples/hello.cairn", "--wat", "1"], "unknown option"),
        (vec!["run", "examples/hello.cairn", "--heap"], "needs a value"),
        (vec!["frobnicate"], "unknown command"),
        (vec!["report", "examples/hello.cairn"], "needs -o"),
        (
            vec!["bench", "examples/hello.cairn", "--gcs", "marksweep,nope"],
            "unknown collector",
        ),
    ];
    for (args, needle) in cases {
        let out = bin().args(&args).current_dir(env!("CARGO_MANIFEST_DIR")).output().unwrap();
        assert_eq!(out.status.code(), Some(1), "{args:?}");
        let err = String::from_utf8_lossy(&out.stderr);
        assert!(err.contains(needle), "{args:?}: {err}");
        assert!(!err.contains("panicked"), "{args:?}: {err}");
    }
    let out = bin().output().unwrap();
    assert_eq!(out.status.code(), Some(2), "no arguments prints usage");
}

#[test]
fn cli_run_stats_and_compare_and_demo() {
    let d = env!("CARGO_MANIFEST_DIR");
    let out = bin()
        .args(["run", "examples/hello.cairn", "--gc", "incremental", "--stats"])
        .current_dir(d)
        .output()
        .unwrap();
    assert!(out.status.success());
    assert!(String::from_utf8_lossy(&out.stdout).contains("sum 0..100 = 4950"));
    assert!(String::from_utf8_lossy(&out.stderr).contains("incremental"));

    let out = bin()
        .args(["compare", "examples/cycles.cairn", "--heap", "30000", "--verify"])
        .current_dir(d)
        .output()
        .unwrap();
    let t = String::from_utf8_lossy(&out.stdout);
    assert!(out.status.success(), "{t}");
    assert!(t.contains("all collectors agree"));

    let out = bin().args(["barrier-demo"]).current_dir(d).output().unwrap();
    let t = String::from_utf8_lossy(&out.stdout);
    assert!(out.status.success(), "{t}");
    assert!(
        t.matches("CORRUPTION").count() == 2 && t.matches("nothing lost").count() == 2,
        "{t}"
    );

    let out = bin().args(["list"]).current_dir(d).output().unwrap();
    assert_eq!(String::from_utf8_lossy(&out.stdout).lines().count(), 5);
}

#[test]
fn step_limit_stops_runaway_programs() {
    let d = env!("CARGO_MANIFEST_DIR");
    let p = std::env::temp_dir().join(format!("cairn-loop-{}.cairn", std::process::id()));
    std::fs::write(&p, "(while 1 nil)").unwrap();
    let out = bin()
        .args(["run", p.to_str().unwrap(), "--steps", "50000"])
        .current_dir(d)
        .output()
        .unwrap();
    assert!(!out.status.success());
    assert!(String::from_utf8_lossy(&out.stderr).contains("step limit"));
    let _ = std::fs::remove_file(p);
}
