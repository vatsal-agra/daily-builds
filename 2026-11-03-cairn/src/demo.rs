//! Hand-built hazards that show *why* write barriers exist. Each scenario runs with the barrier
//! on and off; the oracle must stay silent for the former and complain for the latter.

use crate::heap::*;
use crate::incremental::{Incremental, Phase};
use crate::verify::{check_heap, snapshot};

pub struct Hazard {
    pub title: &'static str,
    pub barrier: bool,
    pub steps: Vec<String>,
    pub violations: Vec<String>,
}

/// Snapshot-at-the-beginning hazard: mid-cycle the mutator loads X out of H into a root and then
/// cuts the only heap reference to X. Only the deletion barrier can tell the collector about X.
pub fn satb_hazard(barrier: bool) -> Hazard {
    let mut steps = Vec::new();
    let mut gc = Incremental::new(4000);
    gc.barrier = barrier;
    gc.pace = 1;
    gc.trigger = 2.0;
    let mut roots = vec![Value::NIL; 4];
    let h = gc.alloc(Kind::Pair, 2, &mut roots).unwrap();
    roots[0] = h;
    let x = gc.alloc(Kind::Pair, 2, &mut roots).unwrap();
    gc.store(roots[0], 0, x);
    gc.store(x, 0, Value::int(42));
    steps.push("heap: root0 -> H -> X(42); root1 -> a 200-cell chain (so marking takes a while)".into());
    for _ in 0..200 {
        let c = gc.alloc(Kind::Pair, 2, &mut roots).unwrap();
        gc.store(c, 1, roots[1]);
        roots[1] = c;
    }
    gc.begin_cycle(&mut roots);
    assert_eq!(gc.phase(), Phase::Marking);
    steps.push(format!(
        "collector starts a cycle: roots are scanned now (phase = {:?}); H and the chain are grey",
        gc.phase()
    ));
    roots[2] = gc.load(roots[0], 0);
    steps.push("mutator: root2 = H.0   (X is now held by a root that the collector will never rescan)".into());
    gc.store(roots[0], 0, Value::NIL);
    steps.push(format!(
        "mutator: H.0 = nil   (deletion barrier {})",
        if barrier {
            "shades X grey"
        } else {
            "is OFF: nobody tells the collector"
        }
    ));
    gc.trigger = 2.0;
    let want = snapshot(&gc, &roots);
    let mut violations = check_heap(&gc, &roots);
    let mut allocs = 0;
    while gc.phase() != Phase::Idle && violations.is_empty() {
        gc.alloc(Kind::Pair, 2, &mut roots).unwrap();
        allocs += 1;
        violations.extend(check_heap(&gc, &roots));
        if violations.is_empty() && snapshot(&gc, &roots) != want {
            violations.push("reachable graph changed: a live object was freed and its memory reused".into());
        }
    }
    steps.push(format!(
        "mutator keeps allocating while the collector finishes ({allocs} allocations)"
    ));
    Hazard {
        title: "incremental SATB: hoist a child into a root, then delete the heap edge",
        barrier,
        steps,
        violations,
    }
}

/// Generational hazard: an old object is made to point at a nursery object. Without the
/// remembered-set barrier the next minor GC never sees that pointer and the young object is lost.
pub fn old_to_young_hazard(barrier: bool) -> Hazard {
    let mut steps = Vec::new();
    let mut gc = crate::generational::Generational::new(4000, 400);
    gc.barrier = barrier;
    let mut roots = vec![Value::NIL; 2];
    let old = gc.alloc(Kind::Vec, 3, &mut roots).unwrap();
    roots[0] = old;
    gc.collect(&mut roots, false).unwrap(); // promotes the vector: it is now old
    steps.push("a vector is allocated and survives a minor GC: it is now in the old generation".into());
    let young = gc.alloc(Kind::Pair, 2, &mut roots).unwrap();
    gc.store(young, 0, Value::int(7));
    gc.store(roots[0], 0, young); // old -> young
    steps.push(format!(
        "mutator stores a fresh nursery pair into the old vector (remembered-set barrier {})",
        if barrier { "ON" } else { "OFF" }
    ));
    let want = snapshot(&gc, &roots);
    let mut violations = check_heap(&gc, &roots);
    gc.collect(&mut roots, false).unwrap();
    steps.push("minor GC runs: it scans only the roots and the remembered set".into());
    if violations.is_empty() {
        violations.extend(check_heap(&gc, &roots));
    }
    let after = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| snapshot(&gc, &roots)));
    match after {
        Ok(s) if s == want => {}
        Ok(_) => violations.push("reachable graph changed across the minor GC".into()),
        Err(_) => violations.push("walking the heap after the minor GC hit garbage".into()),
    }
    Hazard {
        title: "generational: old object points at a nursery object",
        barrier,
        steps,
        violations,
    }
}
