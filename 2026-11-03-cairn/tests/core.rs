mod common;
use cairn::*;
use common::*;

const LIST_PROG: &str = r#"
(fn (range a b) (if (>= a b) nil (cons a (range (+ a 1) b))))
(fn (sum xs) (if (nil? xs) 0 (+ (car xs) (sum (cdr xs)))))
(def keep (range 0 40))
(def i 0)
(while (< i 200) (let ((junk (range 0 25))) (set! i (+ i 1))))
(print "sum" (sum keep) (digest keep))
"#;

#[test]
fn every_collector_runs_a_program_and_reclaims_garbage() {
    for g in ALL_GCS {
        let s = run_verified(LIST_PROG, g).unwrap_or_else(|e| panic!("{g}: {e}"));
        assert_eq!(s.out.lines().next().unwrap().split(' ').nth(1).unwrap(), "780", "{g}: {}", s.out);
        // allocated ~ 5000 pairs * 3 words in a 6000-word heap: only possible if garbage is reclaimed
        assert!(s.alloc_objects > 5000, "{g}");
        assert!(s.collections >= 2, "{g} collected {} times", s.collections);
        assert!(s.checks > 1000, "oracle ran {} times under {g}", s.checks);
    }
}

#[test]
fn all_collectors_produce_identical_output_including_digests() {
    let outs: Vec<String> = ALL_GCS.iter().map(|g| run_verified(LIST_PROG, g).unwrap().out).collect();
    for o in &outs[1..] {
        assert_eq!(*o, outs[0]);
    }
}

#[test]
fn live_data_that_does_not_fit_is_a_clean_oom_not_a_crash() {
    let prog = "(def x nil) (def n 0) (while (< n 100000) (set! x (cons n x)) (set! n (+ n 1))) (print 1)";
    for g in ALL_GCS {
        let e = run(prog, g).expect_err(g);
        assert!(e.contains("out of memory"), "{g}: {e}");
    }
}

#[test]
fn semispace_moves_objects_and_marksweep_does_not() {
    // `eq` compares raw addresses at one instant; observe movement via the heap directly
    use cairn::heap::*;
    for (name, moves) in [("semispace", true), ("marksweep", false), ("compact", false), ("generational", true)] {
        let mut gc = make_gc(name, &small_cfg()).unwrap();
        let mut roots = vec![Value::NIL];
        // allocate garbage first so compaction has something to slide over
        for _ in 0..10 {
            let junk = gc.alloc(Kind::Pair, 2, &mut roots).unwrap();
            let _ = junk;
        }
        let p = gc.alloc(Kind::Pair, 2, &mut roots).unwrap();
        roots[0] = p;
        gc.store(p, 0, Value::int(7));
        let before = roots[0];
        gc.collect(&mut roots, true).unwrap();
        let after = roots[0];
        assert_eq!(gc.load(after, 0), Value::int(7), "{name}");
        if name == "compact" {
            assert_ne!(before, after, "compaction slides survivors over the garbage");
        } else {
            assert_eq!(before != after, moves, "{name}: {before:?} -> {after:?}");
        }
    }
}

#[test]
fn compaction_leaves_no_holes_and_marksweep_reports_fragmentation() {
    use cairn::heap::*;
    let mut gc = make_gc("compact", &small_cfg()).unwrap();
    let mut roots = vec![Value::NIL; 20];
    for i in 0..200 {
        let p = gc.alloc(Kind::Pair, 2, &mut roots).unwrap();
        if i % 10 == 0 {
            roots[i / 10] = p;
        }
    }
    gc.collect(&mut roots, true).unwrap();
    assert_eq!(gc.used_words(), 20 * 3, "exactly the 20 survivors remain, packed");
    assert_eq!(gc.largest_free(), gc.capacity_words() - 60);

    let mut ms = make_gc("marksweep", &small_cfg()).unwrap();
    let mut roots = vec![Value::NIL; 20];
    for i in 0..200 {
        let p = ms.alloc(Kind::Pair, 2, &mut roots).unwrap();
        if i % 10 == 0 {
            roots[i / 10] = p;
        }
    }
    ms.collect(&mut roots, true).unwrap();
    assert_eq!(ms.used_words(), 60);
    assert!(ms.largest_free() < ms.capacity_words() - 60, "survivors split the free space");
}

#[test]
fn strings_vectors_and_zero_length_objects_survive_every_collector() {
    let prog = r#"
    (def v (vector 3 nil)) (def e (vector 0)) (def s (strcat "gc-" (str 42)))
    (vset! v 0 (str 1)) (vset! v 1 (cons s e)) (vset! v 2 (substr "abcdefghij" 2 9))
    (def i 0)
    (while (< i 500) (let ((j (vector 7 i))) (set! i (+ i 1))))
    (gc)
    (print v e s (vlen e) (strlen (vref v 2)))
    "#;
    let want = run_verified(prog, "marksweep").unwrap().out;
    assert_eq!(want, "#(\"1\" (\"gc-42\" . #()) \"cdefghi\") #() gc-42 0 7\n");
    for g in ALL_GCS {
        assert_eq!(run_verified(prog, g).unwrap().out, want, "{g}");
    }
}
