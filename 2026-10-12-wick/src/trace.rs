//! Execution profiler / tracer: per-function and per-opcode counts, call graph, depth timeline,
//! bounded instruction trace, rendered as text or a self-contained HTML report.
use crate::ast::{Instr, Module};
use crate::disasm::{instr_text, mnemonic};
use std::collections::HashMap;
use std::fmt::Write;

#[derive(Default, Clone)]
pub struct FuncStat {
    pub calls: u64,
    pub instrs: u64,
}

pub struct TraceLine {
    pub step: u64,
    pub func: u32,
    pub pc: usize,
    pub depth: usize,
    pub text: String,
    pub call: Option<u32>,
}

#[derive(Default)]
pub struct Profile {
    pub total: u64,
    pub funcs: HashMap<u32, FuncStat>,
    pub ops: HashMap<&'static str, u64>,
    pub edges: HashMap<(Option<u32>, u32), u64>,
    pub max_depth: usize,
    pub max_stack: usize,
    pub trace: Vec<TraceLine>,
    pub trace_limit: usize,
    /// (step, call depth) samples, thinned so the vector stays bounded.
    pub timeline: Vec<(u64, usize)>,
    stride: u64,
    pub host_calls: u64,
}

impl Profile {
    pub fn new(trace_limit: usize) -> Profile {
        Profile { trace_limit, stride: 1, ..Default::default() }
    }

    pub fn on_call(&mut self, caller: Option<u32>, callee: u32, host: bool, depth: usize) {
        self.funcs.entry(callee).or_default().calls += 1;
        *self.edges.entry((caller, callee)).or_default() += 1;
        if host {
            self.host_calls += 1;
        }
        self.max_depth = self.max_depth.max(depth);
    }

    pub fn on_instr(&mut self, func: u32, pc: usize, ins: &Instr, depth: usize, sp: usize) {
        self.total += 1;
        self.funcs.entry(func).or_default().instrs += 1;
        *self.ops.entry(mnemonic(ins)).or_default() += 1;
        self.max_stack = self.max_stack.max(sp);
        self.max_depth = self.max_depth.max(depth);
        if self.total % self.stride == 0 {
            self.timeline.push((self.total, depth));
            if self.timeline.len() >= 2048 {
                // thin by half and double the stride
                let kept: Vec<_> = self.timeline.iter().step_by(2).copied().collect();
                self.timeline = kept;
                self.stride *= 2;
            }
        }
        if self.trace.len() < self.trace_limit {
            self.trace.push(TraceLine { step: self.total, func, pc, depth, text: instr_text(ins, &|f| format!("#{f}")), call: if let Instr::Call(f) = ins { Some(*f) } else { None } });
        }
    }

    fn sorted_funcs(&self) -> Vec<(u32, FuncStat)> {
        let mut v: Vec<(u32, FuncStat)> = self.funcs.iter().map(|(k, v)| (*k, v.clone())).collect();
        v.sort_by(|a, b| b.1.instrs.cmp(&a.1.instrs).then(a.0.cmp(&b.0)));
        v
    }
    fn sorted_ops(&self) -> Vec<(&'static str, u64)> {
        let mut v: Vec<(&'static str, u64)> = self.ops.iter().map(|(k, v)| (*k, *v)).collect();
        v.sort_by(|a, b| b.1.cmp(&a.1).then(a.0.cmp(b.0)));
        v
    }

    pub fn text_report(&self, m: &Module) -> String {
        let mut o = String::new();
        writeln!(o, "instructions executed : {}", self.total).unwrap();
        writeln!(o, "max call depth        : {}", self.max_depth).unwrap();
        writeln!(o, "max value-stack slots : {}", self.max_stack).unwrap();
        writeln!(o, "host calls            : {}", self.host_calls).unwrap();
        writeln!(o, "\nfunctions (by instructions executed):").unwrap();
        for (f, s) in self.sorted_funcs() {
            let pct = if self.total == 0 { 0.0 } else { s.instrs as f64 * 100.0 / self.total as f64 };
            writeln!(o, "  {:<24} calls {:>8}  instrs {:>10}  {:>5.1}%", m.func_label(f), s.calls, s.instrs, pct).unwrap();
        }
        writeln!(o, "\ntop opcodes:").unwrap();
        for (op, n) in self.sorted_ops().into_iter().take(12) {
            writeln!(o, "  {:<22} {:>10}", op, n).unwrap();
        }
        o
    }

    pub fn html_report(&self, m: &Module, title: &str) -> String {
        fn esc(s: &str) -> String {
            s.replace('&', "&amp;").replace('<', "&lt;").replace('>', "&gt;")
        }
        let funcs = self.sorted_funcs();
        let ops = self.sorted_ops();
        let max_f = funcs.iter().map(|f| f.1.instrs).max().unwrap_or(1).max(1);
        let max_o = ops.iter().map(|f| f.1).max().unwrap_or(1).max(1);
        let mut h = String::new();
        h.push_str("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">");
        write!(h, "<title>Wick profile — {}</title>", esc(title)).unwrap();
        h.push_str(CSS);
        h.push_str("</head><body><main>");
        write!(h, "<header><div class=\"logo\">wick</div><h1>{}</h1><p class=\"sub\">execution profile</p></header>", esc(title)).unwrap();
        h.push_str("<section class=\"cards\">");
        for (k, v) in [("instructions", self.total.to_string()), ("max call depth", self.max_depth.to_string()), ("peak stack slots", self.max_stack.to_string()), ("functions run", funcs.len().to_string()), ("host calls", self.host_calls.to_string())] {
            write!(h, "<div class=\"card\"><div class=\"v\">{v}</div><div class=\"k\">{k}</div></div>").unwrap();
        }
        h.push_str("</section>");

        // call-depth timeline (SVG)
        h.push_str("<section><h2>Call depth over time</h2>");
        if self.timeline.len() > 1 {
            let (w, ht) = (900.0, 120.0);
            let maxd = self.max_depth.max(1) as f64;
            let last = self.timeline.last().unwrap().0 as f64;
            let mut pts = String::new();
            for (s, d) in &self.timeline {
                write!(pts, "{:.1},{:.1} ", *s as f64 / last * w, ht - (*d as f64 / maxd) * (ht - 8.0) - 2.0).unwrap();
            }
            write!(h, "<svg viewBox=\"0 0 {w} {ht}\" class=\"tl\" role=\"img\" aria-label=\"call depth timeline\"><polyline points=\"{pts}\" fill=\"none\" stroke=\"var(--accent)\" stroke-width=\"1.6\" stroke-linejoin=\"round\"/></svg>").unwrap();
            write!(h, "<p class=\"muted\">0 → {} instructions · peak depth {}</p>", self.total, self.max_depth).unwrap();
        } else {
            h.push_str("<p class=\"muted\">Too few instructions executed to plot.</p>");
        }
        h.push_str("</section>");

        h.push_str("<section><h2>Functions</h2><table><thead><tr><th>function</th><th class=\"n\">calls</th><th class=\"n\">instructions</th><th class=\"n\">%</th><th>share</th></tr></thead><tbody>");
        for (f, s) in &funcs {
            let pct = s.instrs as f64 * 100.0 / self.total.max(1) as f64;
            write!(h, "<tr><td><code>{}</code></td><td class=\"n\">{}</td><td class=\"n\">{}</td><td class=\"n\">{:.1}%</td><td><div class=\"bar\"><i style=\"width:{:.1}%\"></i></div></td></tr>", esc(&m.func_label(*f)), s.calls, s.instrs, pct, s.instrs as f64 / max_f as f64 * 100.0).unwrap();
        }
        h.push_str("</tbody></table></section>");

        h.push_str("<section><h2>Opcode mix</h2><table><tbody>");
        for (op, n) in ops.iter().take(16) {
            write!(h, "<tr><td><code>{op}</code></td><td class=\"n\">{n}</td><td><div class=\"bar alt\"><i style=\"width:{:.1}%\"></i></div></td></tr>", *n as f64 / max_o as f64 * 100.0).unwrap();
        }
        h.push_str("</tbody></table></section>");

        h.push_str("<section><h2>Call graph edges</h2><table><thead><tr><th>caller</th><th>callee</th><th class=\"n\">count</th></tr></thead><tbody>");
        let mut edges: Vec<_> = self.edges.iter().collect();
        edges.sort_by(|a, b| b.1.cmp(a.1).then(a.0.cmp(b.0)));
        for ((c, d), n) in edges.into_iter().take(40) {
            let cn = c.map(|c| m.func_label(c)).unwrap_or_else(|| "(host)".into());
            write!(h, "<tr><td><code>{}</code></td><td><code>{}</code></td><td class=\"n\">{n}</td></tr>", esc(&cn), esc(&m.func_label(*d))).unwrap();
        }
        h.push_str("</tbody></table></section>");

        if !self.trace.is_empty() {
            write!(h, "<section><h2>First {} instructions</h2><pre class=\"trace\">", self.trace.len()).unwrap();
            for t in &self.trace {
                writeln!(h, "<span class=\"mu\">{:>6} {:<10}</span>{}{}", t.step, esc(&m.func_label(t.func)), "  ".repeat(t.depth.saturating_sub(1).min(12)), esc(&match t.call { Some(f) => format!("call {}", m.func_label(f)), None => t.text.clone() })).unwrap();
            }
            h.push_str("</pre></section>");
        }
        h.push_str("<footer>generated by wick</footer></main></body></html>");
        h
    }
}

const CSS: &str = r#"<style>
:root{--bg:#0f1115;--panel:#171a21;--line:#262b36;--fg:#e6e9ef;--mu:#8b93a7;--accent:#ffb454;--accent2:#59c2ff}
@media (prefers-color-scheme:light){:root{--bg:#f6f4ef;--panel:#fff;--line:#e4e0d6;--fg:#1d2330;--mu:#6b7384;--accent:#c76a00;--accent2:#0b6fb8}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:980px;margin:0 auto;padding:32px 16px 64px}
header{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;margin-bottom:24px}
.logo{font:700 14px ui-monospace,Menlo,monospace;letter-spacing:.14em;text-transform:uppercase;color:var(--bg);background:var(--accent);padding:3px 9px;border-radius:4px}
h1{font-size:24px;margin:0;font-weight:650}.sub{color:var(--mu);margin:0}
h2{font-size:13px;letter-spacing:.1em;text-transform:uppercase;color:var(--mu);margin:0 0 10px;font-weight:600}
section{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:18px 18px 14px;margin-bottom:16px;overflow-x:auto}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;background:none;border:0;padding:0}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.card .v{font:650 26px ui-monospace,Menlo,monospace;color:var(--accent)}.card .k{color:var(--mu);font-size:12px;text-transform:uppercase;letter-spacing:.08em}
table{width:100%;border-collapse:collapse}th{text-align:left;color:var(--mu);font-weight:600;font-size:12px;padding:4px 8px;border-bottom:1px solid var(--line)}
td{padding:6px 8px;border-bottom:1px solid var(--line)}tr:last-child td{border:0}.n{text-align:right;font-variant-numeric:tabular-nums}
code,pre{font:13px ui-monospace,Menlo,Consolas,monospace}
.bar{position:relative;height:16px;background:var(--line);border-radius:3px;min-width:140px}.bar i{display:block;height:100%;background:var(--accent);border-radius:3px}
.bar.alt i{background:var(--accent2)}.bar span{position:absolute;right:6px;top:0;font-size:11px;line-height:16px;color:var(--fg);mix-blend-mode:difference;filter:invert(1)}
.tl{width:100%;height:auto;background:linear-gradient(var(--line) 1px,transparent 1px) 0 0/100% 30px}.muted{color:var(--mu);margin:6px 0 0;font-size:13px}
pre.trace{margin:0;max-height:420px;overflow:auto;line-height:1.45}.mu{color:var(--mu)}
footer{color:var(--mu);font-size:12px;text-align:center;margin-top:24px}
@media (max-width:560px){main{padding:20px 16px 48px}h1{font-size:20px}}
</style>"#;
