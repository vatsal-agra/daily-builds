//! Self-contained HTML report (no external resources; light and dark themes).

use crate::check::{Trace, Verdict};
use crate::driver::{Report, SpecOutcome};
use crate::report::{fmt_count, kind_name};

fn esc(s: &str) -> String {
    s.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
}

const CSS: &str = r#"
:root{--bg:#f6f7f9;--card:#fff;--ink:#14181f;--mute:#5b6573;--line:#dfe3e8;--accent:#3b5bdb;--ok:#14803c;--okbg:#e3f6ea;--bad:#b4231a;--badbg:#fde8e6;--warn:#8a5a00;--warnbg:#fff4d6;--chg:#fff0b3;--loop:#e5ecff;--code:#f0f2f5}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#0f1218;--card:#171b23;--ink:#e6e9ef;--mute:#9aa4b2;--line:#2a303b;--accent:#8ea2ff;--ok:#5fd38a;--okbg:#12301f;--bad:#ff8d85;--badbg:#3a1613;--warn:#f0c15a;--warnbg:#33290d;--chg:#4a3f12;--loop:#202a4a;--code:#1d222c}}
:root[data-theme=dark]{--bg:#0f1218;--card:#171b23;--ink:#e6e9ef;--mute:#9aa4b2;--line:#2a303b;--accent:#8ea2ff;--ok:#5fd38a;--okbg:#12301f;--bad:#ff8d85;--badbg:#3a1613;--warn:#f0c15a;--warnbg:#33290d;--chg:#4a3f12;--loop:#202a4a;--code:#1d222c}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1040px;margin:0 auto;padding:28px 16px 64px}
h1{font-size:26px;margin:0 0 4px;letter-spacing:-.01em}h2{font-size:17px;margin:34px 0 12px}
.sub{color:var(--mute);margin:0 0 20px}.mono,code,pre,td.v,th.v{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:13px}
.banner{display:flex;align-items:center;gap:14px;padding:16px 18px;border-radius:12px;border:1px solid var(--line);background:var(--card)}
.banner b{font-size:20px}.banner.ok{background:var(--okbg);border-color:var(--ok)}.banner.bad{background:var(--badbg);border-color:var(--bad)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-top:14px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px}.stat .k{color:var(--mute);font-size:12px;text-transform:uppercase;letter-spacing:.04em}.stat .n{font-size:20px;font-weight:650;font-variant-numeric:tabular-nums}
.warn{background:var(--warnbg);color:var(--warn);border-radius:10px;padding:10px 14px;margin:10px 0;font-size:14px}
.spec{background:var(--card);border:1px solid var(--line);border-radius:12px;margin:12px 0;overflow:hidden}.spec>header{display:flex;flex-wrap:wrap;gap:8px 12px;align-items:baseline;padding:12px 16px}
.badge{font-weight:700;font-size:12px;padding:2px 9px;border-radius:99px;letter-spacing:.04em}.badge.ok{background:var(--okbg);color:var(--ok)}.badge.bad{background:var(--badbg);color:var(--bad)}
.chip{font-size:11px;color:var(--mute);border:1px solid var(--line);border-radius:6px;padding:1px 6px}.name{font-weight:650}.formula{width:100%;background:var(--code);padding:6px 10px;border-radius:8px;overflow-x:auto;white-space:pre}
.ms{margin-left:auto;color:var(--mute);font-size:12px}.trace{border-top:1px solid var(--line);padding:12px 16px;overflow-x:auto}.trace .cap{color:var(--mute);font-size:13px;margin-bottom:8px}
table{border-collapse:collapse;font-variant-numeric:tabular-nums}th,td{padding:3px 10px;border-bottom:1px solid var(--line);white-space:nowrap;text-align:left}
th.v{position:sticky;left:0;background:var(--card);color:var(--mute);font-weight:500}thead th{font-size:12px;color:var(--mute);font-weight:600}
td.chg{background:var(--chg);font-weight:650}td.loop,th.loop{background:var(--loop)}tr.inp td,tr.inp th{color:var(--accent);font-style:italic}
.loopnote{margin-top:8px;color:var(--accent);font-size:13px}svg{width:100%;height:auto;display:block}
.order{display:flex;flex-wrap:wrap;gap:4px}.order span{background:var(--code);border-radius:6px;padding:1px 7px;font-size:12px}
details{margin-top:28px}summary{cursor:pointer;color:var(--accent)}pre.src{background:var(--code);padding:12px;border-radius:10px;overflow:auto;line-height:1.45}
@media (max-width:560px){h1{font-size:22px}.ms{margin-left:0}}
"#;

fn trace_table(t: &Trace) -> String {
    let n = t.steps.len();
    // abbreviate very long traces: keep the head and tail columns
    let (head, tail) = (24usize, 12usize);
    let keep: Vec<usize> = if n > head + tail + 1 {
        (0..head).chain(n - tail..n).collect()
    } else {
        (0..n).collect()
    };
    let gap_at = if n > head + tail + 1 {
        Some(head)
    } else {
        None
    };
    let mut h = String::from("<table><thead><tr><th class=\"v\">state</th>");
    for (c, &i) in keep.iter().enumerate() {
        if gap_at == Some(c) {
            h.push_str(&format!("<th>… {} omitted …</th>", n - head - tail));
        }
        let lp = t.loop_start == Some(i);
        h.push_str(&format!(
            "<th class=\"{}\">{}{}</th>",
            if lp { "loop" } else { "" },
            i + 1,
            if lp { " ↻" } else { "" }
        ));
    }
    h.push_str("</tr></thead><tbody>");
    let nvars = t.steps[0].state.len();
    for k in 0..nvars {
        h.push_str(&format!(
            "<tr><th class=\"v\">{}</th>",
            esc(&t.steps[0].state[k].0)
        ));
        for (c, &i) in keep.iter().enumerate() {
            if gap_at == Some(c) {
                h.push_str("<td>…</td>");
            }
            let val = &t.steps[i].state[k].1;
            let changed = i == 0 || t.steps[i - 1].state[k].1 != *val;
            let after_gap = gap_at == Some(c);
            let mut cls = String::from("v");
            if changed || after_gap {
                cls.push_str(" chg");
            }
            if t.loop_start.map(|l| i >= l).unwrap_or(false) && !changed && !after_gap {
                cls.push_str(" loop");
            }
            h.push_str(&format!("<td class=\"{}\">{}</td>", cls, esc(val)));
        }
        h.push_str("</tr>");
    }
    if t.steps.iter().any(|s| !s.inputs.is_empty()) {
        let names: Vec<String> = t
            .steps
            .iter()
            .find(|s| !s.inputs.is_empty())
            .unwrap()
            .inputs
            .iter()
            .map(|(k, _)| k.clone())
            .collect();
        for (k, name) in names.iter().enumerate() {
            h.push_str(&format!(
                "<tr class=\"inp\"><th class=\"v\">in: {}</th>",
                esc(name)
            ));
            for (c, &i) in keep.iter().enumerate() {
                if gap_at == Some(c) {
                    h.push_str("<td>…</td>");
                }
                let v = t.steps[i].inputs.get(k).map(|x| x.1.as_str()).unwrap_or("");
                h.push_str(&format!("<td class=\"v\">{}</td>", esc(v)));
            }
            h.push_str("</tr>");
        }
    }
    h.push_str("</tbody></table>");
    if let Some(l) = t.loop_start {
        h.push_str(&format!("<div class=\"loopnote\">↻ the last state steps back to state {}; the execution repeats states {}–{} forever.</div>", l + 1, l + 1, n));
    }
    h
}

fn spec_card(o: &SpecOutcome) -> String {
    let ok = o.verdict == Verdict::Holds;
    let mut s = format!(
        "<section class=\"spec\"><header><span class=\"badge {}\">{}</span><span class=\"chip\">{}</span><span class=\"name\">{}</span><span class=\"ms\">{:.1} ms</span><code class=\"formula\">{}</code>",
        if ok { "ok" } else { "bad" },
        if ok { "PASS" } else { "FAIL" },
        kind_name(o.kind),
        esc(&o.label),
        o.micros as f64 / 1000.0,
        esc(&o.text)
    );
    if ok && o.vacuous {
        s.push_str("<span class=\"warn\" style=\"margin:0;width:100%\">Holds vacuously: no fair infinite path starts in an initial state.</span>");
    }
    s.push_str("</header>");
    if let Verdict::Fails(Some(t)) = &o.verdict {
        let kind = if t.loop_start.is_some() {
            "Lasso counterexample"
        } else {
            "Counterexample"
        };
        s.push_str(&format!("<div class=\"trace\"><div class=\"cap\">{} — {} states. Highlighted cells changed since the previous state.</div>{}</div>", kind, t.steps.len(), trace_table(t)));
    }
    s.push_str("</section>");
    s
}

fn profile_svg(pts: &[(usize, u128)]) -> String {
    if pts.len() < 2 {
        return String::new();
    }
    let max = pts.iter().map(|p| p.1).max().unwrap().max(1) as f64;
    let maxd = pts.last().unwrap().0.max(1) as f64;
    let (w, h, pad) = (960.0, 150.0, 6.0);
    let mut path = format!("M{:.1},{:.1}", pad, h - pad);
    for &(d, c) in pts {
        let x = pad + (w - 2.0 * pad) * d as f64 / maxd;
        let y = h - pad - (h - 2.0 * pad) * (c as f64 / max);
        path.push_str(&format!(" L{:.1},{:.1}", x, y));
    }
    let area = format!("{} L{:.1},{:.1} Z", path, w - pad, h - pad);
    format!(
        "<svg viewBox=\"0 0 {w} {h}\" role=\"img\" aria-label=\"New states per BFS depth\"><path d=\"{area}\" fill=\"var(--accent)\" opacity=\".18\"/><path d=\"{path}\" fill=\"none\" stroke=\"var(--accent)\" stroke-width=\"2\"/><text x=\"{pad}\" y=\"14\" fill=\"var(--mute)\" font-size=\"12\">peak {peak} new states / step</text><text x=\"{r}\" y=\"{b}\" text-anchor=\"end\" fill=\"var(--mute)\" font-size=\"12\">depth {md}</text></svg>",
        w = w,
        h = h,
        area = area,
        path = path,
        pad = pad,
        peak = fmt_count(max as u128),
        r = w - pad,
        b = h - 10.0,
        md = maxd as usize
    )
}

pub fn render_html(r: &Report, file: &str, src: &str) -> String {
    let i = &r.info;
    let pass = r
        .outcomes
        .iter()
        .filter(|o| o.verdict == Verdict::Holds)
        .count();
    let total = r.outcomes.len();
    let all = pass == total;
    let mut s = String::new();
    s.push_str("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">");
    s.push_str(&format!(
        "<title>Kripke report — {}</title><style>{}</style></head><body><main>",
        esc(file),
        CSS
    ));
    s.push_str(&format!(
        "<h1>Kripke report</h1><p class=\"sub mono\">{}</p>",
        esc(file)
    ));
    s.push_str(&format!(
        "<div class=\"banner {}\"><b>{}</b><span>{} of {} specifications hold · checked in {:.1} ms</span></div>",
        if all { "ok" } else { "bad" },
        if all { "All properties hold" } else { "Counterexamples found" },
        pass,
        total,
        i.total_micros as f64 / 1000.0
    ));
    for w in &i.warnings {
        s.push_str(&format!("<div class=\"warn\">⚠ {}</div>", esc(w)));
    }
    if i.deadlocks > 0 {
        s.push_str(&format!(
            "<div class=\"warn\">⚠ {} reachable deadlock state(s). CTL/LTL quantify over infinite paths only, so violations inside a deadlock are invisible to them; INVARSPEC does see them. Re-run with <code>--stutter</code> to give deadlocks a self-loop.</div>",
            fmt_count(i.deadlocks)
        ));
    }
    let stat = |k: &str, v: String| {
        format!(
            "<div class=\"stat\"><div class=\"k\">{}</div><div class=\"n\">{}</div></div>",
            k, v
        )
    };
    s.push_str("<h2>Model</h2><div class=\"grid\">");
    s.push_str(&stat(
        "state variables",
        format!(
            "{} <span class=\"sub\">({} bits)</span>",
            i.state_vars, i.state_bits
        ),
    ));
    s.push_str(&stat(
        "input variables",
        format!(
            "{} <span class=\"sub\">({} bits)</span>",
            i.input_vars, i.input_bits
        ),
    ));
    s.push_str(&stat("initial states", fmt_count(i.init_states)));
    s.push_str(&stat("reachable states", fmt_count(i.reachable)));
    s.push_str(&stat("diameter", i.diameter.to_string()));
    s.push_str(&stat("fair states", fmt_count(i.fair_states)));
    s.push_str(&stat("deadlocks", fmt_count(i.deadlocks)));
    s.push_str(&stat(
        "fairness constraints",
        i.fair_constraints.to_string(),
    ));
    s.push_str(&stat("transition BDD", format!("{} nodes", i.trans_nodes)));
    s.push_str(&stat("reachable BDD", format!("{} nodes", i.reach_nodes)));
    s.push_str(&stat(
        "fixpoint iterations",
        i.stats.fixpoint_iterations.to_string(),
    ));
    s.push_str(&stat("garbage collections", i.gc_runs.to_string()));
    s.push_str("</div>");
    if let Some((b, a, sw)) = i.reorder {
        s.push_str(&format!("<div class=\"warn\" style=\"background:var(--code);color:var(--ink)\">Variable reordering (sifting): shared BDD {} → {} nodes after {} level swaps.</div>", b, a, sw));
    }
    let prof = profile_svg(&i.layer_counts);
    if !prof.is_empty() {
        s.push_str("<h2>Reachability profile</h2>");
        s.push_str(&prof);
    }
    s.push_str("<h2>Specifications</h2>");
    if r.outcomes.is_empty() {
        s.push_str("<p class=\"sub\">The model has no specifications.</p>");
    }
    for o in &r.outcomes {
        s.push_str(&spec_card(o));
    }
    s.push_str("<h2>BDD variable order</h2><div class=\"order\">");
    for v in &i.order {
        s.push_str(&format!("<span class=\"mono\">{}</span>", esc(v)));
    }
    s.push_str("</div>");
    s.push_str("<details><summary>Model source</summary><pre class=\"src\">");
    for (n, line) in src.lines().enumerate() {
        s.push_str(&format!("{:>4}  {}\n", n + 1, esc(line)));
    }
    s.push_str("</pre></details></main></body></html>");
    s
}
