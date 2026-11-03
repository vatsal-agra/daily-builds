mod common;
use cairn::heap::*;
use cairn::incremental::{Incremental, Phase};

/// The classic snapshot-at-the-beginning hazard, constructed by hand:
/// a cycle has started (roots scanned), the mutator loads X out of H into a root, then deletes
/// the only heap reference to X. Without the deletion barrier the collector never sees X.
fn scenario(barrier: bool) -> (Vec<String>, Phase) {
    let mut gc = Incremental::new(4000);
    gc.barrier = barrier;
    gc.trigger = 0.0; // start a cycle on the very first allocation after we have data
    gc.pace = 1;
    let mut roots = vec![Value::NIL; 4];
    // H -> X
    gc.trigger = 2.0; // no cycle yet
    let h = gc.alloc(Kind::Pair, 2, &mut roots).unwrap();
    roots[0] = h;
    let x = gc.alloc(Kind::Pair, 2, &mut roots).unwrap();
    gc.store(roots[0], 0, x);
    gc.store(x, 0, Value::int(42));
    // a long chain so marking takes many increments
    for _ in 0..200 {
        let c = gc.alloc(Kind::Pair, 2, &mut roots).unwrap();
        gc.store(c, 1, roots[1]);
        roots[1] = c;
    }
    gc.trigger = 0.0;
    let junk = gc.alloc(Kind::Pair, 2, &mut roots).unwrap(); // starts the cycle (roots scanned now)
    let _ = junk;
    assert_eq!(gc.phase(), Phase::Marking, "cycle should be in flight");
    // mutator: hoist X into a root, then cut it out of the heap
    roots[2] = gc.load(roots[0], 0);
    gc.store(roots[0], 0, Value::NIL);
    gc.trigger = 2.0;
    // let the collector finish its cycle
    let mut all = cairn::verify::check_heap(&gc, &roots);
    let want = cairn::verify::snapshot(&gc, &roots);
    while gc.phase() != Phase::Idle {
        let _ = gc.alloc(Kind::Pair, 2, &mut roots).unwrap();
        all.extend(cairn::verify::check_heap(&gc, &roots));
        if cairn::verify::snapshot(&gc, &roots) != want {
            all.push("reachable graph changed: a live object was freed and its memory reused".into());
            break;
        }
    }
    if hdr_kind(gc.header(roots[2].addr())) == Kind::Free {
        all.push("X was freed".into());
    }
    (all, gc.phase())
}

#[test]
fn with_the_deletion_barrier_the_hoisted_object_survives() {
    let (errs, _) = scenario(true);
    assert!(errs.is_empty(), "{errs:?}");
}

#[test]
fn without_the_barrier_the_oracle_catches_the_lost_object() {
    let (errs, _) = scenario(false);
    assert!(!errs.is_empty(), "the hazard should have lost X");
    assert!(errs.iter().any(|e| e.contains("lost object") || e.contains("freed")), "{errs:?}");
}
