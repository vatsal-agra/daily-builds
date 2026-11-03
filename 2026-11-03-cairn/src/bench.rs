//! Run one program under several collectors and compare: pauses, MMU, throughput, footprint.

use crate::heap::*;
use crate::lang::Program;
use crate::vm::{Vm, VmOptions};
use crate::{make_gc, GcConfig};
use std::time::Instant;

pub struct RunResult {
    pub name: String,
    /// program output, or the error text (e.g. out of memory)
    pub outcome: Result<String, String>,
    pub wall_ns: u64,
    pub vm: Vm,
}

pub fn run_one(prog: &Program, name: &str, cfg: &GcConfig, opts: VmOptions) -> Result<RunResult, String> {
    let gc = make_gc(name, cfg)?;
    let mut vm = Vm::new(gc, opts);
    let t = Instant::now();
    let r = vm.run(prog);
    let wall_ns = t.elapsed().as_nanos() as u64;
    let outcome = match r {
        Ok(()) => Ok(String::from_utf8_lossy(&vm.out).into_owned()),
        Err(e) => Err(e.to_string()),
    };
    Ok(RunResult {
        name: name.to_string(),
        outcome,
        wall_ns,
        vm,
    })
}

/// Minimum mutator utilisation for windows of `w` ns: the worst fraction of any window of that
/// length not spent paused. Candidate windows start at a pause start or end at a pause end.
pub fn mmu(pauses: &[Pause], total_ns: u64, w: u64) -> f64 {
    if pauses.is_empty() || total_ns == 0 {
        return 1.0;
    }
    let w = w.min(total_ns).max(1);
    // prefix[i] = total paused ns in pauses[..i]
    let mut prefix = Vec::with_capacity(pauses.len() + 1);
    prefix.push(0u64);
    for p in pauses {
        prefix.push(prefix.last().unwrap() + p.dur_ns);
    }
    let overlap = |a: u64, b: u64| -> u64 {
        // pauses are time-ordered and non-overlapping
        let lo = pauses.partition_point(|p| p.start_ns + p.dur_ns <= a);
        let hi = pauses.partition_point(|p| p.start_ns < b);
        if lo >= hi {
            return 0;
        }
        let mut sum = prefix[hi] - prefix[lo];
        let first = &pauses[lo];
        sum -= a.saturating_sub(first.start_ns).min(first.dur_ns);
        let last = &pauses[hi - 1];
        sum -= (last.start_ns + last.dur_ns).saturating_sub(b).min(last.dur_ns);
        sum
    };
    let mut worst = 0u64;
    for p in pauses {
        let s = p.start_ns.min(total_ns.saturating_sub(w));
        worst = worst.max(overlap(s, s + w));
        let e = (p.start_ns + p.dur_ns).max(w).min(total_ns.max(w));
        worst = worst.max(overlap(e - w, e));
    }
    1.0 - (worst.min(w) as f64 / w as f64)
}

pub struct Row {
    pub name: String,
    pub ok: bool,
    pub note: String,
    pub wall_ns: u64,
    pub gc_ns: u64,
    pub collections: u64,
    pub pauses: u64,
    pub max_pause_ns: u64,
    pub p99_pause_ns: u64,
    pub mmu_1ms: f64,
    pub mmu_10ms: f64,
    pub mmu_100ms: f64,
    pub peak_words: usize,
    pub mwords_per_s: f64,
    pub largest_free: usize,
    pub free_words: usize,
}

pub fn row_of(r: &RunResult) -> Row {
    let st = r.vm.gc.stats();
    let mut durs: Vec<u64> = st.pauses.iter().map(|p| p.dur_ns).collect();
    durs.sort_unstable();
    let p99 = if durs.is_empty() {
        0
    } else {
        durs[((durs.len() - 1) as f64 * 0.99) as usize]
    };
    let cap = r.vm.gc.capacity_words();
    let used = r.vm.gc.used_words();
    let secs = (r.wall_ns as f64 / 1e9).max(1e-9);
    Row {
        name: r.name.clone(),
        ok: r.outcome.is_ok(),
        note: match &r.outcome {
            Ok(_) => String::new(),
            Err(e) => e.clone(),
        },
        wall_ns: r.wall_ns,
        gc_ns: st.total_pause_ns(),
        collections: st.collections,
        pauses: st.pause_count(),
        max_pause_ns: st.max_pause_ns(),
        p99_pause_ns: p99,
        mmu_1ms: mmu(&st.pauses, r.wall_ns, 1_000_000),
        mmu_10ms: mmu(&st.pauses, r.wall_ns, 10_000_000),
        mmu_100ms: mmu(&st.pauses, r.wall_ns, 100_000_000),
        peak_words: st.peak_used,
        mwords_per_s: st.alloc_words as f64 / 1e6 / secs,
        largest_free: r.vm.gc.largest_free(),
        free_words: cap.saturating_sub(used),
    }
}

pub fn table(rows: &[Row]) -> String {
    use crate::report::fmt_ns;
    let mut s = format!(
        "{:<13} {:>8} {:>7} {:>8} {:>10} {:>10} {:>10} {:>7} {:>7} {:>8} {:>10} {:>8}\n",
        "collector", "wall", "gc %", "gcs", "pauses", "max pause", "p99 pause", "MMU1ms", "MMU10ms", "peak wds", "Mwords/s", "frag"
    );
    for r in rows {
        if !r.ok {
            s.push_str(&format!("{:<13} FAILED: {}\n", r.name, r.note));
            continue;
        }
        let frag = if r.free_words == 0 {
            0.0
        } else {
            1.0 - r.largest_free as f64 / r.free_words as f64
        };
        s.push_str(&format!(
            "{:<13} {:>8} {:>6.1}% {:>8} {:>10} {:>10} {:>10} {:>7.3} {:>7.3} {:>8} {:>10.1} {:>7.0}%\n",
            r.name,
            fmt_ns(r.wall_ns),
            100.0 * r.gc_ns as f64 / r.wall_ns.max(1) as f64,
            r.collections,
            r.pauses,
            fmt_ns(r.max_pause_ns),
            fmt_ns(r.p99_pause_ns),
            r.mmu_1ms,
            r.mmu_10ms,
            r.peak_words,
            r.mwords_per_s,
            frag * 100.0
        ));
    }
    s
}
