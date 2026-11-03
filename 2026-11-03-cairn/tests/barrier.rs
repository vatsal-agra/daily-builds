use cairn::demo::*;

#[test]
fn with_the_deletion_barrier_the_hoisted_object_survives() {
    let h = satb_hazard(true);
    assert!(h.violations.is_empty(), "{:?}", h.violations);
}

#[test]
fn without_the_barrier_the_oracle_catches_the_lost_object() {
    let h = satb_hazard(false);
    assert!(!h.violations.is_empty(), "the hazard should have lost X");
    assert!(
        h.violations
            .iter()
            .any(|e| e.contains("lost object") || e.contains("freed") || e.contains("changed")),
        "{:?}",
        h.violations
    );
}

#[test]
fn remembered_set_barrier_keeps_young_objects_reachable_from_old_ones() {
    let h = old_to_young_hazard(true);
    assert!(h.violations.is_empty(), "{:?}", h.violations);
}

#[test]
fn without_the_remembered_set_the_young_object_is_lost() {
    let h = old_to_young_hazard(false);
    assert!(!h.violations.is_empty(), "minor GC should have missed the old->young pointer");
}
