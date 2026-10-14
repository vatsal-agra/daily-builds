use plinth::fuzz::*;
use plinth::journal::Bug;

#[test]
fn crash_fuzz_correct_journal_is_clean() {
    for seed in 1..=3 {
        let o = CrashOpts { seed, ops: 40, ..Default::default() };
        let r = crash_fuzz(&o);
        eprintln!("seed {seed}: events={} writes={} flushes={} states={} replays={} nested={} torn={} failures={}", r.events, r.writes, r.flushes, r.states_checked, r.replays, r.nested_states, r.torn_states, r.failures.len());
        assert!(r.workload_errors.is_empty(), "{:?}", r.workload_errors);
        assert!(r.failures.is_empty(), "{:#?}", r.failures);
        assert!(r.replays > 0);
    }
}

#[test]
fn every_mutant_is_killed() {
    for bug in Bug::ALL_MUTANTS {
        let mut killed = false;
        for seed in 1..=3 {
            let o = CrashOpts { seed, ops: 40, bug, ..Default::default() };
            let r = crash_fuzz(&o);
            assert!(r.workload_errors.is_empty(), "{:?}", r.workload_errors);
            if !r.failures.is_empty() {
                eprintln!("mutant {} killed (seed {seed}): {}", bug.name(), r.failures[0].what);
                killed = true;
                break;
            }
        }
        assert!(killed, "mutant {} survived", bug.name());
    }
}
