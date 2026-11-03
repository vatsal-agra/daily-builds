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

// ------------------------------------------------------------------ HTML report

use crate::bench::{mmu, row_of, RunResult};

const COLORS: [(&str, &str); 5] = [
    ("#2a7de1", "#6fa8ff"), // marksweep
    ("#d9822b", "#f0a65a"), // semispace
    ("#2fa56b", "#5fd197"), // generational
    ("#b455d6", "#d28cef"), // incremental
    ("#d94f6a", "#f08397"), // compact
];

fn esc(s: &str) -> String {
    s.replace('&', "&amp;").replace('<', "&lt;").replace('>', "&gt;").replace('"', "&quot;")
}

fn color_idx(name: &str) -> usize {
    crate::ALL_GCS.iter().position(|g| *g == name).unwrap_or(0)
}

fn occupancy_svg(r: &RunResult, cap: usize, idx: usize) -> String {
    let st = r.vm.gc.stats();
    let (w, h) = (520.0, 110.0);
    let end = (r.wall_ns as f64).max(1.0);
    let pts = &st.timeline;
    let mut path = String::new();
    if !pts.is_empty() {
        let step = (pts.len() / 500).max(1);
        let mut first = true;
        for (i, p) in pts.iter().enumerate() {
            if i % step != 0 && i + 1 != pts.len() {
                continue;
            }
            let x = 8.0 + (p.t_ns as f64 / end).min(1.0) * (w - 16.0);
            let y = h - 10.0 - (p.used as f64 / cap.max(1) as f64).min(1.0) * (h - 20.0);
            path.push_str(&format!("{}{:.1},{:.1} ", if first { "M" } else { "L" }, x, y));
            first = false;
        }
    }
    format!(
        r#"<svg viewBox="0 0 {w} {h}" role="img" aria-label="heap occupancy over time"><line class="grid" x1="8" y1="10" x2="{x2}" y2="10"/><line class="grid" x1="8" y1="{yb}" x2="{x2}" y2="{yb}"/><text x="10" y="8" class="lbl">capacity {cap} words</text><path d="{path}" fill="none" class="c{idx}" stroke-width="1.6"/></svg>"#,
        x2 = w - 8.0,
        yb = h - 10.0
    )
}

fn pause_svg(r: &RunResult, idx: usize) -> String {
    let st = r.vm.gc.stats();
    let (w, h) = (520.0, 110.0);
    let end = (r.wall_ns as f64).max(1.0);
    const B: usize = 160;
    let mut maxes = vec![0u64; B];
    for p in &st.pauses {
        let b = (((p.start_ns as f64 / end) * B as f64) as usize).min(B - 1);
        maxes[b] = maxes[b].max(p.dur_ns);
    }
    let top = maxes.iter().copied().max().unwrap_or(1).max(1) as f64;
    let mut bars = String::new();
    for (i, m) in maxes.iter().enumerate() {
        if *m == 0 {
            continue;
        }
        let bh = (*m as f64 / top) * (h - 26.0);
        let x = 8.0 + i as f64 * (w - 16.0) / B as f64;
        bars.push_str(&format!(r#"<rect x="{x:.1}" y="{:.1}" width="{:.1}" height="{bh:.1}" class="f{idx}"/>"#, h - 10.0 - bh, ((w - 16.0) / B as f64 - 0.6).max(1.0)));
    }
    format!(
        r#"<svg viewBox="0 0 {w} {h}" role="img" aria-label="longest pause per time slice"><line class="grid" x1="8" y1="{yb}" x2="{x2}" y2="{yb}"/><text x="10" y="10" class="lbl">longest pause per slice (peak {})</text>{bars}</svg>"#,
        fmt_ns(top as u64),
        x2 = w - 8.0,
        yb = h - 10.0
    )
}

fn heapmap_html(r: &RunResult) -> String {
    let gc = r.vm.gc.as_ref();
    let total = gc.mem().len().max(1);
    const CELLS: usize = 120;
    let mut used = vec![0usize; CELLS];
    let mut free = vec![0usize; CELLS];
    for (a, t, is_free) in gc.walk() {
        // spread the block over the cells it covers
        let (mut s, e) = (a, a + t);
        while s < e {
            let c = (s * CELLS / total).min(CELLS - 1);
            let cell_end = ((c + 1) * total).div_ceil(CELLS);
            let n = e.min(cell_end.max(s + 1)) - s;
            if is_free {
                free[c] += n;
            } else {
                used[c] += n;
            }
            s += n;
        }
    }
    let per = (total as f64 / CELLS as f64).max(1.0);
    let mut out = String::from(r#"<div class="map" role="img" aria-label="final heap layout">"#);
    for c in 0..CELLS {
        let u = (used[c] as f64 / per).min(1.0);
        let f = (free[c] as f64 / per).min(1.0);
        let cls = if u + f < 0.05 { "unmapped" } else { "" };
        out.push_str(&format!(r#"<i class="{cls}" style="--u:{u:.2}" title="cells {c}: {:.0}% used, {:.0}% free"></i>"#, u * 100.0, f * 100.0));
    }
    out.push_str("</div>");
    out
}

pub fn html_report(title: &str, source: &str, results: &[RunResult], cfg: &crate::GcConfig) -> String {
    let rows: Vec<_> = results.iter().map(row_of).collect();
    let mut css_colors = String::new();
    let mut css_dark = String::new();
    for (i, (l, d)) in COLORS.iter().enumerate() {
        css_colors.push_str(&format!("--c{i}:{l};"));
        css_dark.push_str(&format!("--c{i}:{d};"));
    }
    let mut cards = String::new();
    for r in results {
        let idx = color_idx(&r.name);
        let row = row_of(r);
        let verdict = if row.ok { String::from(r#"<span class="ok">completed</span>"#) } else { format!(r#"<span class="bad">failed: {}</span>"#, esc(&row.note)) };
        cards.push_str(&format!(
            r#"<section class="card"><h3><span class="dot f{idx}"></span>{}</h3><p class="sub">{verdict} · {} collections · {} pauses · max pause {} · peak {} words</p><div class="charts"><figure>{}<figcaption>heap occupancy, sampled after each collection step</figcaption></figure><figure>{}<figcaption>pause lengths over the run</figcaption></figure></div><div class="maplabel">final heap layout — blue = allocated (live or not yet collected), grey = free, hatched = outside the managed region</div>{}</section>"#,
            r.name,
            row.collections,
            row.pauses,
            fmt_ns(row.max_pause_ns),
            row.peak_words,
            occupancy_svg(r, r.vm.gc.capacity_words().max(1), idx),
            pause_svg(r, idx),
            heapmap_html(r)
        ));
    }
    // MMU chart: windows 10µs .. 1s, log scale
    let (w, h) = (640.0f64, 240.0f64);
    let wins: Vec<f64> = (0..=40).map(|i| 10f64.powf(4.0 + i as f64 * 5.0 / 40.0)).collect();
    let mut lines = String::new();
    let mut legend = String::new();
    for r in results {
        let idx = color_idx(&r.name);
        let st = r.vm.gc.stats();
        let mut d = String::new();
        for (k, win) in wins.iter().enumerate() {
            let m = mmu(&st.pauses, r.wall_ns, *win as u64);
            let x = 40.0 + (k as f64 / 40.0) * (w - 60.0);
            let y = h - 30.0 - m * (h - 50.0);
            d.push_str(&format!("{}{:.1},{:.1} ", if k == 0 { "M" } else { "L" }, x, y));
        }
        lines.push_str(&format!(r#"<path d="{d}" fill="none" class="c{idx}" stroke-width="2"/>"#));
        legend.push_str(&format!(r#"<span><i class="dot f{idx}"></i>{}</span>"#, r.name));
    }
    let mut ticks = String::new();
    for (k, lab) in ["10µs", "100µs", "1ms", "10ms", "100ms", "1s"].iter().enumerate() {
        let x = 40.0 + (k as f64 / 5.0) * (w - 60.0);
        ticks.push_str(&format!(r#"<line class="grid" x1="{x}" y1="20" x2="{x}" y2="{}"/><text x="{x}" y="{}" class="lbl" text-anchor="middle">{lab}</text>"#, h - 30.0, h - 12.0));
    }
    for (v, y) in [(0.0, h - 30.0), (0.5, h - 30.0 - 0.5 * (h - 50.0)), (1.0, 20.0)] {
        ticks.push_str(&format!(r#"<line class="grid" x1="40" y1="{y}" x2="{}" y2="{y}"/><text x="34" y="{}" class="lbl" text-anchor="end">{v}</text>"#, w - 20.0, y + 3.0));
    }
    let out_text: String = results.iter().find_map(|r| r.outcome.as_ref().ok()).map(|s| s.chars().take(3000).collect()).unwrap_or_default();
    let table = crate::bench::table(&rows);
    format!(
        r#"<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Cairn report — {t}</title>
<style>
:root{{--bg:#f7f6f2;--fg:#1d1f24;--mut:#6a6e78;--card:#ffffff;--line:#dcdad2;--accent:#2a7de1;--ok:#1f8a4c;--bad:#c23b3b;{css_colors}}}
@media (prefers-color-scheme:dark){{:root:not([data-theme=light]){{--bg:#14161a;--fg:#e8e9ec;--mut:#9a9eaa;--card:#1c1f25;--line:#2f333c;--ok:#4cc783;--bad:#ff7a7a;{css_dark}}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:1120px;margin:0 auto;padding:28px 16px 60px}}h1{{font-size:28px;margin:0 0 4px;letter-spacing:-.02em}}h2{{margin:34px 0 10px;font-size:18px}}
.sub{{color:var(--mut);margin:2px 0 10px;font-size:13.5px}}.lead{{color:var(--mut);margin:0 0 18px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin:14px 0}}.card h3{{margin:0;font-size:17px;display:flex;align-items:center;gap:8px}}
.charts{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}}figure{{margin:0}}figcaption{{color:var(--mut);font-size:12px;text-align:center}}
svg{{width:100%;height:auto;display:block}}.grid{{stroke:var(--line);stroke-width:1}}.lbl{{fill:var(--mut);font-size:10px}}
{svg_classes}
.dot{{display:inline-block;width:10px;height:10px;border-radius:50%}}
.map{{display:grid;grid-template-columns:repeat(120,1fr);gap:1px;height:26px;margin-top:4px}}.map i{{background:color-mix(in srgb,var(--accent) calc(var(--u)*100%),var(--line))}}
.map i.unmapped{{background:repeating-linear-gradient(45deg,transparent 0 3px,var(--line) 3px 4px)}}.maplabel{{color:var(--mut);font-size:12px;margin-top:8px}}
pre{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;overflow:auto;font:12.5px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace}}
.ok{{color:var(--ok);font-weight:600}}.bad{{color:var(--bad);font-weight:600}}.legend{{display:flex;gap:16px;flex-wrap:wrap;font-size:13px;margin:6px 0}}.legend span{{display:inline-flex;align-items:center;gap:6px}}
</style></head><body><main>
<h1>Cairn GC report</h1><p class="lead">{t} · heap {heap} words · nursery {nursery} · same program, same output, five collectors.</p>
<h2>Summary</h2><pre>{table}</pre>
<h2>Minimum mutator utilisation</h2><p class="sub">For a window of the given length, the worst fraction of time the program (not the collector) got to run. Higher and further left is better: a stop-the-world collector drops to 0 once the window is shorter than its longest pause.</p>
<div class="legend">{legend}</div><div class="card"><svg viewBox="0 0 {w} {h}" role="img" aria-label="MMU curves">{ticks}{lines}</svg></div>
<h2>Per collector</h2>{cards}
<h2>Program output</h2><pre>{out}</pre>
<h2>Program source</h2><pre>{src}</pre>
</main></body></html>"#,
        t = esc(title),
        heap = cfg.words,
        nursery = cfg.nursery,
        svg_classes = (0..5).map(|i| format!("svg .c{i}{{stroke:var(--c{i})}}svg .f{i}{{fill:var(--c{i})}}.dot.f{i}{{background:var(--c{i})}}")).collect::<Vec<_>>().join(""),
        out = esc(&out_text),
        src = esc(source),
    )
}
