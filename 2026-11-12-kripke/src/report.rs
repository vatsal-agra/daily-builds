//! Terminal rendering of reports and traces.

use crate::check::{Trace, Verdict};
use crate::driver::{Report, SpecOutcome};
use crate::lang::SpecKind;

pub fn kind_name(k: SpecKind) -> &'static str {
    match k {
        SpecKind::Ctl => "CTL",
        SpecKind::Ltl => "LTL",
        SpecKind::Invar => "INVAR",
    }
}

/// Per step, the variables whose value changed w.r.t. the previous step (all variables for step 0).
pub fn step_changes(t: &Trace) -> Vec<Vec<(String, String, bool)>> {
    let mut out = vec![];
    for (i, s) in t.steps.iter().enumerate() {
        let mut row = vec![];
        for (k, (name, val)) in s.state.iter().enumerate() {
            let changed = i == 0 || t.steps[i - 1].state[k].1 != *val;
            row.push((name.clone(), val.clone(), changed));
        }
        out.push(row);
    }
    out
}

pub fn render_trace(t: &Trace, indent: &str) -> String {
    let mut s = String::new();
    let rows = step_changes(t);
    for (i, _step) in t.steps.iter().enumerate() {
        let mut head = format!("{}State {}", indent, i + 1);
        if i == 0 {
            head.push_str(" (initial)");
        }
        if t.loop_start == Some(i) {
            head.push_str("  <- loop starts here");
        }
        s.push_str(&head);
        s.push('\n');
        if i > 0 && !t.steps[i - 1].inputs.is_empty() {
            let inp: Vec<String> = t.steps[i - 1].inputs.iter().map(|(k, v)| format!("{}={}", k, v)).collect();
            s.push_str(&format!("{}  [inputs taken: {}]\n", indent, inp.join(", ")));
        }
        for (name, val, changed) in &rows[i] {
            if *changed {
                s.push_str(&format!("{}  {} = {}\n", indent, name, val));
            }
        }
    }
    if let Some(l) = t.loop_start {
        let last = t.steps.last().unwrap();
        if !last.inputs.is_empty() {
            let inp: Vec<String> = last.inputs.iter().map(|(k, v)| format!("{}={}", k, v)).collect();
            s.push_str(&format!("{}  [inputs taken: {}]\n", indent, inp.join(", ")));
        }
        s.push_str(&format!("{}-> back to State {} (the trace repeats this loop forever)\n", indent, l + 1));
    }
    s
}

pub fn fmt_count(n: u128) -> String {
    if n == u128::MAX {
        return ">= 2^128".to_string();
    }
    let s = n.to_string();
    let mut out = String::new();
    for (i, c) in s.chars().enumerate() {
        if i > 0 && (s.len() - i) % 3 == 0 {
            out.push(',');
        }
        out.push(c);
    }
    out
}

pub fn render_outcome(o: &SpecOutcome) -> String {
    let mut s = String::new();
    let mark = match &o.verdict {
        Verdict::Holds => "PASS",
        Verdict::Fails(_) => "FAIL",
    };
    s.push_str(&format!("[{}] {} {}: {}  ({:.1} ms)\n", mark, kind_name(o.kind), o.label, o.text, o.micros as f64 / 1000.0));
    if let Verdict::Fails(Some(t)) = &o.verdict {
        let kind = if t.loop_start.is_some() { "lasso counterexample" } else { "counterexample" };
        s.push_str(&format!("  {} ({} states):\n", kind, t.steps.len()));
        s.push_str(&render_trace(t, "    "));
    }
    s
}

pub fn render_report(r: &Report, verbose: bool) -> String {
    let i = &r.info;
    let mut s = String::new();
    s.push_str(&format!(
        "model: {} state vars ({} bits), {} input vars ({} bits), {} fairness constraint(s)\n",
        i.state_vars, i.state_bits, i.input_vars, i.input_bits, i.fair_constraints
    ));
    s.push_str(&format!(
        "states: {} initial, {} reachable (diameter {}), {} fair\n",
        fmt_count(i.init_states),
        fmt_count(i.reachable),
        i.diameter,
        fmt_count(i.fair_states)
    ));
    if i.deadlocks > 0 {
        s.push_str(&format!("WARNING: {} reachable deadlock state(s)\n", fmt_count(i.deadlocks)));
        if let Some(t) = &i.deadlock_example {
            s.push_str("  shortest path to a deadlock:\n");
            s.push_str(&render_trace(t, "    "));
        }
    }
    for w in &i.warnings {
        s.push_str(&format!("warning: {}\n", w));
    }
    if let Some((b, a, sw)) = i.reorder {
        s.push_str(&format!("reordering: shared DAG {} -> {} nodes ({} level swaps)\n", b, a, sw));
    }
    if verbose {
        s.push_str(&format!(
            "bdd: trans {} nodes, init {} nodes, reachable {} nodes; {} fixpoint iterations, {} images, {} GCs\n",
            i.trans_nodes, i.init_nodes, i.reach_nodes, i.stats.fixpoint_iterations, i.stats.images, i.gc_runs
        ));
        s.push_str(&format!("order: {}\n", i.order.join(" ")));
    }
    s.push('\n');
    for o in &r.outcomes {
        s.push_str(&render_outcome(o));
    }
    let pass = r.outcomes.iter().filter(|o| o.verdict == Verdict::Holds).count();
    s.push_str(&format!("\n{} of {} specifications hold ({:.1} ms total)\n", pass, r.outcomes.len(), i.total_micros as f64 / 1000.0));
    s
}
