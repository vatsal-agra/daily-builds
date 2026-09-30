//! Human-readable summaries (terminal) for a finished simulation.

use crate::sim::{Outcome, Sim};
use crate::tcp::Event;
use crate::units::{fmt_bytes, fmt_rate};

/// Peak congestion window observed (bytes).
pub fn max_cwnd(sim: &Sim) -> u64 {
    sim.a.samples.iter().map(|s| s.cwnd).max().unwrap_or(0)
}

pub fn count_events(sim: &Sim, pred: impl Fn(&Event) -> bool) -> usize {
    sim.a.events.iter().filter(|(_, e)| pred(e)).count()
}

pub fn summary(sim: &Sim, o: &Outcome) -> String {
    let (ab, ba) = sim.link_stats();
    let a = &sim.a.stats;
    let b = &sim.b.stats;
    let link_rate = sim.sc.link_ab.rate_bps as f64;
    let mut s = String::new();
    s += &format!(
        "tcplab · {} · scenario \"{}\": {} one-way, {} ms delay, queue {} pkts, loss {:.2}%\n",
        o.algo.name(),
        o.name,
        fmt_rate(link_rate),
        sim.sc.link_ab.delay_us as f64 / 1e3,
        sim.sc.link_ab.queue_pkts,
        sim.sc.link_ab.loss * 100.0
    );
    match o.delivered_us {
        Some(t) => s += &format!(
            "  transfer   {} in {:.3} s → goodput {} ({:.0}% of link)   {}\n",
            fmt_bytes(o.bytes as u64),
            t as f64 / 1e6,
            fmt_rate(o.goodput_bps),
            100.0 * o.goodput_bps / link_rate,
            if o.verified { "VERIFIED byte-exact" } else { "DATA MISMATCH" }
        ),
        None if o.bytes == 0 => s += &format!("  transfer   (no payload)   {}\n", if o.verified { "OK" } else { "FAILED" }),
        None => s += &format!("  transfer   INCOMPLETE — {} of {} delivered\n", fmt_bytes(sim.recv_b.len() as u64), fmt_bytes(o.bytes as u64)),
    }
    s += &format!(
        "  sender     {} data segs, {} retransmits ({} fast, {} RTO), {} dupacks, {} zero-window probes\n",
        a.data_segs_tx, a.retransmits, a.fast_retransmits, a.timeouts, a.dupacks_rx, a.zero_window_probes
    );
    s += &format!(
        "             srtt {} ms, rto {} ms, peak cwnd {} segs\n",
        sim.a.srtt_us().map_or("-".into(), |v| format!("{:.1}", v as f64 / 1e3)),
        sim.a.rto_us as f64 / 1e3,
        max_cwnd(sim) / sim.a.mss as u64
    );
    s += &format!(
        "  receiver   {} out-of-order, {} duplicate, {} corrupt discarded, {} window updates\n",
        b.ooo_segs, b.dup_segs, b.bad_checksum + a.bad_checksum, b.window_updates
    );
    s += &format!(
        "  network    A→B sent {} delivered {} | dropped: {} queue, {} random, {} scripted | corrupted {}, dup {}, reordered {} | peak queue {}\n",
        ab.sent, ab.delivered, ab.dropped_queue, ab.dropped_loss, ab.dropped_scripted, ab.corrupted, ab.duplicated, ab.reordered, ab.max_queue
    );
    s += &format!("             B→A sent {} delivered {} | dropped: {} queue, {} random\n", ba.sent, ba.delivered, ba.dropped_queue, ba.dropped_loss);
    s += &format!(
        "  final      A {} · B {}{}{}\n",
        o.a_state.name(),
        o.b_state.name(),
        o.a_error.map(|e| format!(" · A error: {}", e.name())).unwrap_or_default(),
        o.b_error.map(|e| format!(" · B error: {}", e.name())).unwrap_or_default()
    );
    if o.timed_out {
        s += "  WARNING: simulation hit its time limit\n";
    }
    s
}

pub fn compare_table(rows: &[(Outcome, &Sim)]) -> String {
    let mut s = String::new();
    s += &format!(
        "{:<8} {:>9} {:>12} {:>8} {:>6} {:>5} {:>9} {:>9}  {}\n",
        "algo", "time", "goodput", "retx", "fast", "RTO", "peak cwnd", "q-drops", "verified"
    );
    for (o, sim) in rows {
        s += &format!(
            "{:<8} {:>8.2}s {:>12} {:>8} {:>6} {:>5} {:>6} seg {:>9}  {}\n",
            o.algo.name(),
            o.delivered_us.map_or(o.end_us, |t| t) as f64 / 1e6,
            fmt_rate(o.goodput_bps),
            sim.a.stats.retransmits,
            sim.a.stats.fast_retransmits,
            sim.a.stats.timeouts,
            max_cwnd(sim) / sim.a.mss as u64,
            sim.link_ab.stats.dropped_queue,
            if o.verified { "yes" } else { "NO" }
        );
    }
    s
}
