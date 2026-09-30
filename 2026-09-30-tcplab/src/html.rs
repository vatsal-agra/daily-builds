//! Self-contained HTML report: inline SVG charts (cwnd/ssthresh sawtooth, tcptrace-style
//! time-sequence graph, RTT/RTO, flight vs receiver window) plus an algorithm comparison.

use crate::report::max_cwnd;
use crate::sim::{Outcome, Sim};
use crate::tcp::Event;
use crate::units::{fmt_bytes, fmt_rate};
use std::fmt::Write;

const W: f64 = 760.0;
const H: f64 = 300.0;
const ML: f64 = 58.0;
const MR: f64 = 16.0;
const MT: f64 = 14.0;
const MB: f64 = 38.0;

fn nice_ticks(min: f64, max: f64, target: usize) -> Vec<f64> {
    let span = (max - min).max(1e-9);
    let raw = span / target.max(1) as f64;
    let mag = 10f64.powf(raw.log10().floor());
    let step = [1.0, 2.0, 2.5, 5.0, 10.0].iter().map(|m| m * mag).find(|s| *s >= raw).unwrap_or(10.0 * mag);
    let mut v = Vec::new();
    let mut t = (min / step).ceil() * step;
    while t <= max + step * 1e-6 {
        v.push(t);
        t += step;
    }
    v
}

fn fmt_tick(v: f64) -> String {
    if v.abs() >= 1000.0 && (v / 1000.0).fract().abs() < 1e-9 {
        format!("{}k", (v / 1000.0) as i64)
    } else if v.fract().abs() < 1e-9 {
        format!("{}", v as i64)
    } else {
        format!("{:.1}", v)
    }
}

struct Chart {
    x0: f64,
    x1: f64,
    y0: f64,
    y1: f64,
    body: String,
    legend: Vec<(String, String)>,
}

impl Chart {
    fn new(x1: f64, y1: f64) -> Chart {
        Chart { x0: 0.0, x1: x1.max(1e-6), y0: 0.0, y1: (y1 * 1.06).max(1e-6), body: String::new(), legend: Vec::new() }
    }
    fn px(&self, x: f64) -> f64 {
        ML + (x - self.x0) / (self.x1 - self.x0) * (W - ML - MR)
    }
    fn py(&self, y: f64) -> f64 {
        H - MB - (y - self.y0) / (self.y1 - self.y0) * (H - MT - MB)
    }
    fn axes(&mut self, xlabel: &str, ylabel: &str) {
        let mut g = String::new();
        for t in nice_ticks(self.y0, self.y1, 5) {
            let y = self.py(t);
            let _ = write!(g, r#"<line class="grid" x1="{ML}" x2="{}" y1="{y:.1}" y2="{y:.1}"/><text class="tick" x="{}" y="{:.1}" text-anchor="end">{}</text>"#, W - MR, ML - 6.0, y + 4.0, fmt_tick(t));
        }
        for t in nice_ticks(self.x0, self.x1, 8) {
            let x = self.px(t);
            let _ = write!(g, r#"<line class="grid v" x1="{x:.1}" x2="{x:.1}" y1="{MT}" y2="{}"/><text class="tick" x="{x:.1}" y="{}" text-anchor="middle">{}</text>"#, H - MB, H - MB + 16.0, fmt_tick(t));
        }
        let _ = write!(g, r#"<line class="axis" x1="{ML}" x2="{}" y1="{}" y2="{}"/><line class="axis" x1="{ML}" x2="{ML}" y1="{MT}" y2="{}"/>"#, W - MR, H - MB, H - MB, H - MB);
        let _ = write!(g, r#"<text class="lbl" x="{}" y="{}" text-anchor="middle">{}</text>"#, (ML + W - MR) / 2.0, H - 6.0, xlabel);
        let _ = write!(g, r#"<text class="lbl" transform="translate(13 {}) rotate(-90)" text-anchor="middle">{}</text>"#, (MT + H - MB) / 2.0, ylabel);
        self.body.insert_str(0, &g);
    }
    fn legend(&mut self, cls: &str, name: &str) {
        self.legend.push((cls.to_string(), name.to_string()));
    }
    /// Polyline; `step` draws horizontal-then-vertical (value holds until the next sample).
    fn line(&mut self, pts: &[(f64, f64)], cls: &str, step: bool) {
        if pts.is_empty() {
            return;
        }
        let mut d = String::new();
        let mut prev_y = 0.0;
        for (i, (x, y)) in pts.iter().enumerate() {
            let (px, py) = (self.px(*x), self.py(*y));
            if i == 0 {
                let _ = write!(d, "M{px:.1} {py:.1}");
            } else if step {
                let _ = write!(d, "H{px:.1}V{py:.1}");
            } else {
                let _ = write!(d, "L{px:.1} {py:.1}");
            }
            prev_y = py;
        }
        let _ = prev_y;
        let _ = write!(self.body, r#"<path class="ln {cls}" d="{d}"/>"#);
    }
    fn vline(&mut self, x: f64, cls: &str, title: &str) {
        let px = self.px(x);
        let _ = write!(self.body, r#"<line class="mk {cls}" x1="{px:.1}" x2="{px:.1}" y1="{MT}" y2="{}"><title>{title}</title></line>"#, H - MB);
    }
    fn cross(&mut self, x: f64, y: f64, cls: &str) {
        let (px, py) = (self.px(x), self.py(y));
        let _ = write!(self.body, r#"<path class="x {cls}" d="M{:.1} {:.1}l6 6m0 -6l-6 6"/>"#, px - 3.0, py - 3.0);
    }
    fn finish(self) -> String {
        let mut leg = String::new();
        for (c, n) in &self.legend {
            let _ = write!(leg, r#"<span class="key"><i class="sw {c}"></i>{n}</span>"#);
        }
        format!(r#"<svg viewBox="0 0 {W} {H}" role="img" preserveAspectRatio="xMidYMid meet">{}</svg><div class="legend">{leg}</div>"#, self.body)
    }
}

/// Keep at most ~`max` points, preserving each bucket's extremes so sawtooth peaks survive.
fn decimate(pts: Vec<(f64, f64)>, max: usize) -> Vec<(f64, f64)> {
    if pts.len() <= max {
        return pts;
    }
    let bucket = pts.len().div_ceil(max / 3);
    let mut out = Vec::new();
    for c in pts.chunks(bucket) {
        let mut lo = c[0];
        let mut hi = c[0];
        for p in c {
            if p.1 < lo.1 {
                lo = *p;
            }
            if p.1 > hi.1 {
                hi = *p;
            }
        }
        let mut v = vec![c[0], lo, hi, *c.last().unwrap()];
        v.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap());
        v.dedup();
        out.extend(v);
    }
    out
}

fn secs(us: u64) -> f64 {
    us as f64 / 1e6
}

fn end_time(sim: &Sim) -> f64 {
    let last_tx = sim.a.tx_log.last().map_or(0, |r| r.t);
    let last_ack = sim.a.ack_log.last().map_or(0, |a| a.0);
    secs(sim.delivered_us.unwrap_or(0).max(last_tx).max(last_ack)).max(0.05) * 1.02
}

fn chart_cwnd(sim: &Sim) -> String {
    let mss = sim.a.mss as f64;
    let t1 = end_time(sim);
    let cw: Vec<(f64, f64)> = sim.a.samples.iter().filter(|s| secs(s.t) <= t1).map(|s| (secs(s.t), s.cwnd as f64 / mss)).collect();
    let peak = cw.iter().map(|p| p.1).fold(1.0, f64::max);
    // ssthresh is "infinite" until the first loss: only draw once finite, clipped to the chart.
    let ss: Vec<(f64, f64)> = sim.a.samples.iter().filter(|s| secs(s.t) <= t1 && s.ssthresh < u64::MAX / 8).map(|s| (secs(s.t), (s.ssthresh as f64 / mss).min(peak * 1.05))).collect();
    let mut c = Chart::new(t1, peak);
    c.legend("c-cwnd", "cwnd");
    c.legend("c-ssthresh", "ssthresh");
    c.legend("mk-rto", "RTO");
    c.legend("mk-fast", "fast retransmit");
    c.legend("c-drop", "packet dropped");
    for (t, e) in &sim.a.events {
        match e {
            Event::Timeout { .. } => c.vline(secs(*t), "mk-rto", "RTO fired"),
            Event::FastRetransmit => c.vline(secs(*t), "mk-fast", "fast retransmit"),
            _ => {}
        }
    }
    c.line(&decimate(ss, 1800), "c-ssthresh", true);
    c.line(&decimate(cw, 2400), "c-cwnd", true);
    for (t, _, _) in sim.drops.iter().take(400) {
        let x = secs(*t);
        if x <= t1 {
            let y = c.y0;
            c.cross(x, y + 0.02 * (c.y1 - c.y0), "c-drop");
        }
    }
    c.axes("time (s)", "congestion window (segments)");
    c.finish()
}

fn chart_timeseq(sim: &Sim) -> String {
    let t1 = end_time(sim);
    let kb = |off: u32| off as f64 / 1000.0;
    let total = sim.sc.bytes_a_to_b as f64 / 1000.0;
    let mut c = Chart::new(t1, total.max(1.0));
    c.legend("c-tx", "data sent");
    c.legend("c-rtx", "retransmission");
    c.legend("c-ack", "cumulative ACK");
    c.legend("c-drop", "dropped in network");
    let (mut fresh, mut rtx) = (String::new(), String::new());
    let n = sim.a.tx_log.len();
    let stride = (n / 5000).max(1);
    let seg_h = |len: u32| (len as f64 / 1000.0).max(total * 0.002);
    for (i, r) in sim.a.tx_log.iter().enumerate() {
        if r.retx {
            let _ = write!(rtx, "M{:.1} {:.1}v{:.1}", c.px(secs(r.t)), c.py(kb(r.off)), -(c.py(0.0) - c.py(seg_h(r.len))));
        } else if i % stride == 0 {
            let _ = write!(fresh, "M{:.1} {:.1}v{:.1}", c.px(secs(r.t)), c.py(kb(r.off)), -(c.py(0.0) - c.py(seg_h(r.len))));
        }
    }
    let acks: Vec<(f64, f64)> = sim.a.ack_log.iter().map(|(t, o)| (secs(*t), kb(*o))).collect();
    c.line(&decimate(acks, 2400), "c-ack", true);
    let _ = write!(c.body, r#"<path class="seg c-tx" d="{fresh}"/><path class="seg c-rtx" d="{rtx}"/>"#);
    for (t, off, _) in sim.drops.iter().take(600) {
        c.cross(secs(*t), kb(*off) + 0.5, "c-drop");
    }
    c.axes("time (s)", "stream offset (KB)");
    c.finish()
}

fn chart_rtt(sim: &Sim) -> String {
    let t1 = end_time(sim);
    let srtt: Vec<(f64, f64)> = sim.a.samples.iter().filter(|s| s.srtt_us > 0 && secs(s.t) <= t1).map(|s| (secs(s.t), s.srtt_us as f64 / 1e3)).collect();
    let rto: Vec<(f64, f64)> = sim.a.samples.iter().filter(|s| s.srtt_us > 0 && secs(s.t) <= t1).map(|s| (secs(s.t), s.rto_us as f64 / 1e3)).collect();
    let peak = rto.iter().chain(srtt.iter()).map(|p| p.1).fold(1.0, f64::max);
    let mut c = Chart::new(t1, peak);
    c.legend("c-rto", "RTO (ms)");
    c.legend("c-srtt", "smoothed RTT (ms)");
    c.line(&decimate(rto, 1800), "c-rto", true);
    c.line(&decimate(srtt, 1800), "c-srtt", true);
    c.axes("time (s)", "milliseconds");
    c.finish()
}

fn chart_flight(sim: &Sim) -> String {
    let t1 = end_time(sim);
    let kb = |b: u64| b as f64 / 1024.0;
    let cap = kb(sim.sc.cfg_b.rcv_buf as u64);
    let fl: Vec<(f64, f64)> = sim.a.samples.iter().filter(|s| secs(s.t) <= t1).map(|s| (secs(s.t), kb(s.flight))).collect();
    let wnd: Vec<(f64, f64)> = sim.a.samples.iter().filter(|s| secs(s.t) <= t1 && s.peer_wnd > 0).map(|s| (secs(s.t), kb(s.peer_wnd).min(cap * 1.05))).collect();
    let peak = fl.iter().chain(wnd.iter()).map(|p| p.1).fold(1.0, f64::max);
    let mut c = Chart::new(t1, peak);
    c.legend("c-peerwnd", "receiver window (KiB)");
    c.legend("c-flight", "bytes in flight (KiB)");
    c.line(&decimate(wnd, 1800), "c-peerwnd", true);
    c.line(&decimate(fl, 2400), "c-flight", true);
    c.axes("time (s)", "KiB");
    c.finish()
}

fn tile(label: &str, value: &str, sub: &str) -> String {
    format!(r#"<div class="tile"><div class="tv">{value}</div><div class="tl">{label}</div><div class="ts">{sub}</div></div>"#)
}

fn tiles(o: &Outcome, sim: &Sim) -> String {
    let a = &sim.a.stats;
    let link = sim.sc.link_ab.rate_bps as f64;
    let t = o.delivered_us.map_or("—".to_string(), |t| format!("{:.2} s", secs(t)));
    let verdict = if o.bytes == 0 { "no payload" } else if o.verified { "byte-exact ✓" } else { "MISMATCH ✗" };
    let mut s = String::new();
    s += &tile("completion time", &t, verdict);
    s += &tile("goodput", &fmt_rate(o.goodput_bps), &format!("{:.0}% of {}", 100.0 * o.goodput_bps / link, fmt_rate(link)));
    s += &tile("retransmits", &a.retransmits.to_string(), &format!("{} fast · {} RTO", a.fast_retransmits, a.timeouts));
    s += &tile("peak cwnd", &format!("{} seg", max_cwnd(sim) / sim.a.mss as u64), &format!("srtt {} ms", sim.a.srtt_us().map_or("—".into(), |v| format!("{:.0}", v as f64 / 1e3))));
    s += &tile("network drops", &(sim.link_ab.stats.dropped_queue + sim.link_ab.stats.dropped_loss + sim.link_ab.stats.dropped_scripted).to_string(), &format!("{} queue · {} random · peak queue {}", sim.link_ab.stats.dropped_queue, sim.link_ab.stats.dropped_loss, sim.link_ab.stats.max_queue));
    s
}

fn run_section(o: &Outcome, sim: &Sim, open: bool) -> String {
    format!(
        r#"<details class="run" {}><summary><span class="badge a-{name}">{name}</span> {}</summary>
<div class="tiles">{}</div>
<div class="grid2">
<section class="card"><h3>Congestion window</h3><p class="cap">Slow start, then the AIMD sawtooth. Dashed verticals: timeouts (red) and fast retransmits (amber).</p>{}</section>
<section class="card"><h3>Time–sequence graph</h3><p class="cap">Every data segment as it left the sender (tcptrace style). Red = retransmitted; ✕ = lost in the network; green = cumulative ACK frontier.</p>{}</section>
<section class="card"><h3>RTT estimator</h3><p class="cap">RFC 6298 smoothed RTT and the retransmission timeout derived from it (with backoff spikes).</p>{}</section>
<section class="card"><h3>Flow control</h3><p class="cap">Bytes in flight versus the window the receiver advertised.</p>{}</section>
</div></details>"#,
        if open { "open" } else { "" },
        if o.verified || o.bytes == 0 { "" } else { "— transfer incomplete" },
        tiles(o, sim),
        chart_cwnd(sim),
        chart_timeseq(sim),
        chart_rtt(sim),
        chart_flight(sim),
        name = o.algo.name()
    )
}

fn compare_section(runs: &[(&Outcome, &Sim)]) -> String {
    // Overlay of cwnd curves + goodput bars + table.
    let t1 = runs.iter().map(|(_, s)| end_time(s)).fold(0.05, f64::max);
    let peak = runs.iter().map(|(_, s)| max_cwnd(s) as f64 / s.a.mss as f64).fold(1.0, f64::max);
    let mut c = Chart::new(t1, peak);
    for (o, s) in runs {
        let mss = s.a.mss as f64;
        let pts: Vec<(f64, f64)> = s.a.samples.iter().map(|x| (secs(x.t), x.cwnd as f64 / mss)).collect();
        c.legend(&format!("a-{}", o.algo.name()), o.algo.name());
        c.line(&decimate(pts, 1600), &format!("a-{}", o.algo.name()), true);
    }
    c.axes("time (s)", "congestion window (segments)");
    let overlay = c.finish();

    let best = runs.iter().map(|(o, _)| o.goodput_bps).fold(1.0, f64::max);
    let mut bars = String::new();
    for (o, _) in runs {
        let w = 100.0 * o.goodput_bps / best;
        let _ = write!(bars, r#"<div class="bar"><span class="bn">{}</span><span class="bt"><b class="a-{}" style="width:{w:.1}%"></b></span><span class="bv">{}</span></div>"#, o.algo.name(), o.algo.name(), fmt_rate(o.goodput_bps));
    }
    let mut rows = String::new();
    for (o, s) in runs {
        let _ = write!(
            rows,
            "<tr><td><span class=\"badge a-{n}\">{n}</span></td><td>{:.2} s</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{} seg</td><td>{}</td><td>{}</td></tr>",
            o.delivered_us.map_or(secs(o.end_us), secs),
            fmt_rate(o.goodput_bps),
            s.a.stats.retransmits,
            s.a.stats.fast_retransmits,
            s.a.stats.timeouts,
            s.link_ab.stats.dropped_queue + s.link_ab.stats.dropped_loss,
            max_cwnd(s) / s.a.mss as u64,
            s.a.stats.dupacks_rx,
            if o.verified { "✓" } else { "✗" },
            n = o.algo.name()
        );
    }
    format!(
        r#"<section class="card wide"><h2>Algorithm comparison</h2>
<div class="grid2"><div><h3>Goodput</h3>{bars}</div><div><h3>cwnd over time</h3>{overlay}</div></div>
<div class="scroll"><table><thead><tr><th>algo</th><th>time</th><th>goodput</th><th>retx</th><th>fast</th><th>RTO</th><th>net drops</th><th>peak cwnd</th><th>dupacks</th><th>exact</th></tr></thead><tbody>{rows}</tbody></table></div></section>"#
    )
}

const CSS: &str = r#"
:root{--bg:#f6f7f9;--card:#fff;--ink:#1a1f2b;--mute:#667085;--line:#e4e7ec;--grid:#eceff3;
--cwnd:#2563eb;--ssth:#8b5cf6;--rto:#dc2626;--fast:#f59e0b;--ack:#059669;--tx:#3b82f6;--drop:#a21caf;--srtt:#0891b2;--wnd:#d97706;
--tahoe:#dc2626;--reno:#f59e0b;--newreno:#2563eb;--cubic:#059669;--shadow:0 1px 2px rgba(16,24,40,.06),0 4px 12px rgba(16,24,40,.05)}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#0d1117;--card:#161b22;--ink:#e6edf3;--mute:#8b949e;--line:#30363d;--grid:#222a33;
--cwnd:#58a6ff;--ssth:#b392f0;--rto:#ff7b72;--fast:#e3b341;--ack:#3fb950;--tx:#79c0ff;--drop:#f0abfc;--srtt:#39c5cf;--wnd:#f0883e;
--tahoe:#ff7b72;--reno:#e3b341;--newreno:#58a6ff;--cubic:#3fb950;--shadow:none}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:28px 16px 60px}
header h1{margin:0 0 4px;font-size:26px;letter-spacing:-.02em}header p{margin:0;color:var(--mute)}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0 22px}.chip{background:var(--card);border:1px solid var(--line);border-radius:999px;padding:3px 12px;font-size:13px;color:var(--mute)}
.chip b{color:var(--ink);font-weight:600}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 18px;box-shadow:var(--shadow);min-width:0}
.card h2{margin:0 0 10px;font-size:19px}.card h3{margin:0 0 2px;font-size:15px}.cap{margin:0 0 8px;color:var(--mute);font-size:13px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}@media(max-width:900px){.grid2{grid-template-columns:1fr}}
details.run{margin:18px 0;background:transparent}details.run>summary{cursor:pointer;font-weight:600;font-size:17px;padding:6px 2px;list-style:none}
details.run>summary::-webkit-details-marker{display:none}details.run>summary::before{content:"▸ ";color:var(--mute)}details.run[open]>summary::before{content:"▾ "}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:8px 0 16px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;box-shadow:var(--shadow)}
.tv{font-size:24px;font-weight:650;letter-spacing:-.02em}.tl{font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--mute)}.ts{font-size:12.5px;color:var(--mute);margin-top:2px}
svg{width:100%;height:auto;display:block}.grid{stroke:var(--grid);stroke-width:1}.grid.v{stroke-dasharray:2 4}.axis{stroke:var(--mute);stroke-width:1}
.tick{fill:var(--mute);font-size:11px}.lbl{fill:var(--mute);font-size:12px}
.ln{fill:none;stroke-width:2;stroke-linejoin:round}.c-cwnd{stroke:var(--cwnd);background:var(--cwnd)}.c-ssthresh{stroke:var(--ssth);background:var(--ssth);stroke-dasharray:5 3;stroke-width:1.6}
.c-rto{stroke:var(--rto);background:var(--rto)}.c-srtt{stroke:var(--srtt);background:var(--srtt)}.c-ack{stroke:var(--ack);background:var(--ack);stroke-width:1.6}
.c-peerwnd{stroke:var(--wnd);background:var(--wnd);stroke-dasharray:5 3}.c-flight{stroke:var(--cwnd);background:var(--cwnd)}
.seg{fill:none;stroke-width:2.2}.c-tx{stroke:var(--tx);background:var(--tx)}.c-rtx{stroke:var(--rto);background:var(--rto);stroke-width:2.6}
.x{fill:none;stroke-width:1.8}.c-drop{stroke:var(--drop);background:var(--drop)}
.mk{stroke-width:1.2;stroke-dasharray:3 3;opacity:.75}.mk-rto{stroke:var(--rto);background:var(--rto)}.mk-fast{stroke:var(--fast);background:var(--fast)}
.a-tahoe{stroke:var(--tahoe);background:var(--tahoe)}.a-reno{stroke:var(--reno);background:var(--reno)}.a-newreno{stroke:var(--newreno);background:var(--newreno)}.a-cubic{stroke:var(--cubic);background:var(--cubic)}
.legend{display:flex;flex-wrap:wrap;gap:4px 14px;margin-top:4px;font-size:12.5px;color:var(--mute)}.key{display:inline-flex;align-items:center;gap:6px}
.sw{display:inline-block;width:14px;height:3px;border-radius:2px}
.badge{display:inline-block;padding:1px 10px;border-radius:999px;color:#fff;font-size:13px;font-weight:600;stroke:none}
.wide{margin-bottom:8px}.bar{display:grid;grid-template-columns:70px 1fr 100px;gap:10px;align-items:center;margin:9px 0;font-size:14px}
.bt{background:var(--grid);border-radius:6px;height:16px;overflow:hidden;display:block}.bt b{display:block;height:100%;border-radius:6px}.bv{text-align:right;font-variant-numeric:tabular-nums}
.scroll{overflow-x:auto;margin-top:14px}table{border-collapse:collapse;width:100%;font-size:14px;font-variant-numeric:tabular-nums}
th,td{padding:7px 10px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}th:first-child,td:first-child{text-align:left}th{color:var(--mute);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.05em}
footer{margin-top:30px;color:var(--mute);font-size:13px}
"#;

pub fn report(runs: &[(&Outcome, &Sim)], title: &str) -> String {
    let sc = &runs[0].1.sc;
    let mut chips = String::new();
    let mut chip = |k: &str, v: String| {
        let _ = write!(chips, r#"<span class="chip">{k} <b>{v}</b></span>"#);
    };
    chip("payload", fmt_bytes(sc.bytes_a_to_b as u64));
    chip("link", format!("{} · {} ms one-way", fmt_rate(sc.link_ab.rate_bps as f64), sc.link_ab.delay_us as f64 / 1e3));
    chip("queue", format!("{} pkts", sc.link_ab.queue_pkts));
    if sc.link_ab.loss > 0.0 {
        chip("random loss", format!("{:.2}%", sc.link_ab.loss * 100.0));
    }
    if sc.link_ab.reorder > 0.0 || sc.link_ab.dup > 0.0 || sc.link_ab.corrupt > 0.0 {
        chip("reorder/dup/corrupt", format!("{:.0}%/{:.0}%/{:.0}%", sc.link_ab.reorder * 100.0, sc.link_ab.dup * 100.0, sc.link_ab.corrupt * 100.0));
    }
    if !sc.link_ab.drop_data.is_empty() {
        chip("scripted drops", format!("{:?}", sc.link_ab.drop_data));
    }
    chip("receive buffer", fmt_bytes(sc.cfg_b.rcv_buf as u64));
    chip("seed", sc.seed.to_string());
    let mut body = String::new();
    if runs.len() > 1 {
        body += &compare_section(runs);
    }
    for (i, (o, s)) in runs.iter().enumerate() {
        body += &run_section(o, s, runs.len() == 1 || i == 0);
    }
    format!(
        r#"<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>tcplab — {title}</title><style>{CSS}</style></head><body><div class="wrap">
<header><h1>tcplab · {title}</h1><p>A from-scratch TCP stack over a deterministic simulated network. Everything below was measured inside the simulation; re-running with the same seed reproduces it exactly.</p></header>
<div class="chips">{chips}</div>{body}
<footer>Generated by tcplab. Charts are inline SVG; no external requests.</footer></div></body></html>"#
    )
}
