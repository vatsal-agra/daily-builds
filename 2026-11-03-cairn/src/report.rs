//! Text tables for stats (HTML report added in a later phase).
use crate::heap::Gc;

pub fn stats_table(rows: &[(String, &dyn Gc)]) -> String {
    let mut s = String::new();
    s.push_str(&format!(
        "{:<13} {:>7} {:>7} {:>8} {:>10} {:>10} {:>10} {:>10} {:>9} {:>9}\n",
        "collector", "gcs", "minor", "pauses", "alloc objs", "alloc wds", "max pause", "tot pause", "peak wds", "promoted"
    ));
    for (n, g) in rows {
        let st = g.stats();
        s.push_str(&format!(
            "{:<13} {:>7} {:>7} {:>8} {:>10} {:>10} {:>10} {:>10} {:>9} {:>9}\n",
            n,
            st.collections,
            st.minor_collections,
            st.pause_count(),
            st.alloc_objects,
            st.alloc_words,
            fmt_ns(st.max_pause_ns()),
            fmt_ns(st.total_pause_ns()),
            st.peak_used,
            st.promoted_words
        ));
    }
    s
}

pub fn fmt_ns(ns: u64) -> String {
    if ns >= 1_000_000 {
        format!("{:.2}ms", ns as f64 / 1e6)
    } else if ns >= 1000 {
        format!("{:.1}µs", ns as f64 / 1e3)
    } else {
        format!("{ns}ns")
    }
}
