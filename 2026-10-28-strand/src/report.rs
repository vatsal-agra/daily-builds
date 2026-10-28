//! Self-contained HTML report: coverage tracks with called / true / missed variants, mapping
//! quality, genotype accuracy tables and (optionally) assembly statistics. Charts are inline
//! SVG generated here, so the page has no scripts, no network access and works offline.

use crate::asmeval::AsmEval;
use crate::dbg::{AsmStats, Contig};
use crate::mapper::{MapEval, SamFile};
use crate::vcf::{Evaluation, Kind, Variant};

pub struct ReportInput<'a> {
    pub title: String,
    pub contigs: Vec<(String, usize)>,
    pub coverage: Vec<Vec<u16>>,
    pub calls: &'a [Variant],
    pub evaluation: Option<&'a Evaluation>,
    pub sam: Option<&'a SamFile>,
    pub map_eval: Option<&'a MapEval>,
    pub assembly: Option<AssemblyInput<'a>>,
}

pub struct AssemblyInput<'a> {
    pub stats: &'a AsmStats,
    pub contigs: &'a [Contig],
    pub spectrum: Option<&'a [u64]>,
    pub eval: Option<&'a AsmEval>,
}

fn esc(s: &str) -> String {
    s.replace('&', "&amp;").replace('<', "&lt;").replace('>', "&gt;").replace('"', "&quot;")
}

fn fmt_n(n: usize) -> String {
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

fn pct(x: f64) -> String {
    format!("{:.1}%", 100.0 * x)
}

const W: f64 = 1000.0;

fn coverage_svg(name: &str, len: usize, cov: &[u16], calls: &[&Variant], tp: &[usize], fp: &[usize], fnv: &[usize]) -> String {
    let (h_cov, h_var) = (110.0, 34.0);
    let h = h_cov + h_var + 22.0;
    let bins = (len.min(900)).max(1);
    let mut binned = vec![0f64; bins];
    for (b, slot) in binned.iter_mut().enumerate() {
        let (s, e) = (b * len / bins, ((b + 1) * len / bins).max(b * len / bins + 1).min(len));
        let sum: u64 = cov[s..e].iter().map(|&x| x as u64).sum();
        *slot = sum as f64 / (e - s) as f64;
    }
    let mut sorted = binned.clone();
    sorted.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let top = (sorted[(sorted.len() as f64 * 0.995) as usize % sorted.len()] * 1.15).max(1.0);
    let x = |pos: usize| 40.0 + (W - 50.0) * pos as f64 / len.max(1) as f64;
    let y = |v: f64| 8.0 + h_cov * (1.0 - (v / top).min(1.0));
    let mut path = format!("M{:.1},{:.1}", x(0), y(0.0));
    for (b, v) in binned.iter().enumerate() {
        path.push_str(&format!(" L{:.1},{:.1}", x(b * len / bins), y(*v)));
    }
    path.push_str(&format!(" L{:.1},{:.1} Z", x(len), y(0.0)));
    let mut s = format!(
        "<svg viewBox=\"0 0 {w} {h}\" role=\"img\" aria-label=\"Coverage and variants on {n}\" class=\"track\">",
        w = W,
        h = h,
        n = esc(name)
    );
    // grid + axis
    for frac in [0.0, 0.5, 1.0] {
        let v = top * frac / 1.15;
        s.push_str(&format!(
            "<line x1=\"40\" x2=\"{x2}\" y1=\"{y:.1}\" y2=\"{y:.1}\" class=\"grid\"/><text x=\"34\" y=\"{ty:.1}\" class=\"axis\" text-anchor=\"end\">{v:.0}×</text>",
            x2 = W - 10.0,
            y = y(v * 1.15),
            ty = y(v * 1.15) + 3.5,
            v = v
        ));
    }
    s.push_str(&format!("<path d=\"{}\" class=\"area\"/>", path));
    let base = 8.0 + h_cov + 10.0;
    s.push_str(&format!("<line x1=\"40\" x2=\"{}\" y1=\"{:.1}\" y2=\"{:.1}\" class=\"grid\"/>", W - 10.0, base + 14.0, base + 14.0));
    let tick = |s: &mut String, pos: usize, cls: &str, label: String| {
        let px = x(pos);
        match cls {
            "fn" => s.push_str(&format!("<path d=\"M{x:.1},{a:.1} l4,6 l-4,6 l-4,-6 z\" class=\"{c}\"><title>{t}</title></path>", x = px, a = base + 8.0, c = cls, t = esc(&label))),
            "fp" => s.push_str(&format!("<line x1=\"{x:.1}\" x2=\"{x:.1}\" y1=\"{a:.1}\" y2=\"{b:.1}\" class=\"{c}\"><title>{t}</title></line>", x = px, a = base - 6.0, b = base + 14.0, c = cls, t = esc(&label))),
            _ => s.push_str(&format!("<line x1=\"{x:.1}\" x2=\"{x:.1}\" y1=\"{a:.1}\" y2=\"{b:.1}\" class=\"{c}\"><title>{t}</title></line>", x = px, a = base + 2.0, b = base + 14.0, c = cls, t = esc(&label))),
        }
    };
    for (i, v) in calls.iter().enumerate() {
        let label = format!("{}:{} {}→{} {}", v.chrom, v.pos + 1, String::from_utf8_lossy(&v.ref_a), String::from_utf8_lossy(&v.alt), v.gt_string());
        if fp.contains(&i) {
            tick(&mut s, v.pos, "fp", format!("false call {}", label));
        } else if tp.contains(&i) {
            tick(&mut s, v.pos, "tp", format!("true positive {}", label));
        } else {
            tick(&mut s, v.pos, "call", label);
        }
    }
    for &p in fnv {
        tick(&mut s, p, "fn", format!("missed variant at {}:{}", name, p + 1));
    }
    // x axis labels
    for frac in [0.0, 0.25, 0.5, 0.75, 1.0] {
        let pos = (len as f64 * frac) as usize;
        s.push_str(&format!(
            "<text x=\"{:.1}\" y=\"{:.1}\" class=\"axis\" text-anchor=\"{}\">{}</text>",
            x(pos),
            h - 4.0,
            if frac == 0.0 { "start" } else if frac == 1.0 { "end" } else { "middle" },
            if pos >= 1_000_000 { format!("{:.2} Mb", pos as f64 / 1e6) } else { format!("{:.0} kb", pos as f64 / 1e3) }
        ));
    }
    s.push_str("</svg>");
    s
}

fn bar_chart(rows: &[(String, f64, String)], max: f64, unit: &str) -> String {
    let mut s = String::from("<div class=\"bars\">");
    for (label, v, note) in rows {
        let w = if max > 0.0 { (100.0 * v / max).clamp(0.0, 100.0) } else { 0.0 };
        s.push_str(&format!(
            "<div class=\"bar-row\"><span class=\"bar-label\">{}</span><span class=\"bar-track\"><span class=\"bar-fill\" style=\"width:{:.2}%\"></span></span><span class=\"bar-val\">{}{} <small>{}</small></span></div>",
            esc(label),
            w,
            fmt_n(*v as usize),
            unit,
            esc(note)
        ));
    }
    s.push_str("</div>");
    s
}

fn line_svg(points: &[(f64, f64)], marker_x: Option<f64>, x_label: &str, y_label: &str, log_y: bool) -> String {
    let (w, h, l, b) = (560.0, 220.0, 52.0, 34.0);
    let xmax = points.iter().map(|p| p.0).fold(1.0, f64::max);
    let ty = |v: f64| if log_y { (v + 1.0).ln() } else { v };
    let ymax = points.iter().map(|p| ty(p.1)).fold(1e-9, f64::max);
    let px = |v: f64| l + (w - l - 12.0) * v / xmax;
    let py = |v: f64| 10.0 + (h - b - 10.0) * (1.0 - ty(v) / ymax);
    let mut d = String::new();
    for (i, p) in points.iter().enumerate() {
        d.push_str(&format!("{}{:.1},{:.1} ", if i == 0 { "M" } else { "L" }, px(p.0), py(p.1)));
    }
    let mut s = format!("<svg viewBox=\"0 0 {w} {h}\" class=\"chart\" role=\"img\" aria-label=\"{} versus {}\">", esc(y_label), esc(x_label), w = w, h = h);
    s.push_str(&format!("<line x1=\"{l}\" x2=\"{x2}\" y1=\"{y:.1}\" y2=\"{y:.1}\" class=\"grid\"/>", l = l, x2 = w - 12.0, y = h - b));
    s.push_str(&format!("<line x1=\"{l}\" x2=\"{l}\" y1=\"10\" y2=\"{y:.1}\" class=\"grid\"/>", l = l, y = h - b));
    s.push_str(&format!("<path d=\"{}\" class=\"curve\"/>", d));
    if let Some(m) = marker_x {
        s.push_str(&format!("<line x1=\"{x:.1}\" x2=\"{x:.1}\" y1=\"10\" y2=\"{y:.1}\" class=\"marker\"/><text x=\"{tx:.1}\" y=\"22\" class=\"axis\">cut-off {m:.0}</text>", x = px(m), y = h - b, tx = px(m) + 5.0, m = m));
    }
    s.push_str(&format!("<text x=\"{:.1}\" y=\"{:.1}\" class=\"axis\" text-anchor=\"middle\">{}</text>", (w + l) / 2.0, h - 8.0, esc(x_label)));
    s.push_str(&format!("<text x=\"12\" y=\"{:.1}\" class=\"axis\" transform=\"rotate(-90 12 {:.1})\" text-anchor=\"middle\">{}</text>", h / 2.0 - 10.0, h / 2.0 - 10.0, esc(y_label)));
    s.push_str(&format!("<text x=\"{l}\" y=\"{y:.1}\" class=\"axis\">0</text><text x=\"{x2:.1}\" y=\"{y:.1}\" class=\"axis\" text-anchor=\"end\">{xm:.0}</text>", l = l, y = h - b + 13.0, x2 = w - 12.0, xm = xmax));
    s.push_str("</svg>");
    s
}

const CSS: &str = r#"
:root{--bg:#f6f7f9;--card:#fff;--ink:#14181f;--mute:#5b6472;--line:#e3e6eb;--accent:#2a6fdb;--area:#9db9ea;--area-line:#2a6fdb;--tp:#12906b;--fp:#d03b2f;--fn:#c07a00;--call:#6b7686}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#0e1116;--card:#171b22;--ink:#e8ebf0;--mute:#9aa4b2;--line:#2a313c;--accent:#6aa1ff;--area:#27406e;--area-line:#6aa1ff;--tp:#3ccf9f;--fp:#ff7b6e;--fn:#f0b43c;--call:#8b97a8}}
:root[data-theme=dark]{--bg:#0e1116;--card:#171b22;--ink:#e8ebf0;--mute:#9aa4b2;--line:#2a313c;--accent:#6aa1ff;--area:#27406e;--area-line:#6aa1ff;--tp:#3ccf9f;--fp:#ff7b6e;--fn:#f0b43c;--call:#8b97a8}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1080px;margin:0 auto;padding:28px 16px 64px}
h1{font-size:26px;margin:0 0 4px;letter-spacing:-.01em}
h2{font-size:17px;margin:34px 0 12px;letter-spacing:-.005em}
.sub{color:var(--mute);margin:0 0 22px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.kpi b{display:block;font-size:26px;letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.kpi span{color:var(--mute);font-size:13px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin-bottom:14px;overflow:hidden}
.card h3{font-size:14px;margin:0 0 8px;font-weight:600}
.card h3 small{color:var(--mute);font-weight:400;margin-left:8px}
svg{display:block;width:100%;height:auto}
.track .grid,.chart .grid{stroke:var(--line);stroke-width:1}
.axis{fill:var(--mute);font-size:11px}
.area{fill:var(--area);stroke:var(--area-line);stroke-width:1.2;fill-opacity:.7}
.tp{stroke:var(--tp);stroke-width:2}.fp{stroke:var(--fp);stroke-width:2.4}.call{stroke:var(--call);stroke-width:2}
.fn{fill:var(--fn);stroke:none}
.curve{fill:none;stroke:var(--area-line);stroke-width:2}.marker{stroke:var(--fp);stroke-dasharray:4 3;stroke-width:1.4}
.legend{display:flex;flex-wrap:wrap;gap:14px;color:var(--mute);font-size:13px;margin:0 0 10px}
.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;vertical-align:-1px}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
th,td{text-align:right;padding:8px 10px;border-bottom:1px solid var(--line)}
th:first-child,td:first-child{text-align:left}
th{color:var(--mute);font-weight:500;font-size:13px}
.bars{display:grid;gap:7px}
.bar-row{display:grid;grid-template-columns:90px 1fr 170px;gap:10px;align-items:center;font-size:13px}
.bar-track{background:var(--line);border-radius:5px;height:12px;overflow:hidden;display:block}
.bar-fill{display:block;height:100%;background:var(--accent);border-radius:5px}
.bar-val{text-align:right;font-variant-numeric:tabular-nums}.bar-val small{color:var(--mute)}
.two{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}
footer{color:var(--mute);font-size:12px;margin-top:36px}
@media(max-width:560px){.bar-row{grid-template-columns:64px 1fr 120px}.kpi b{font-size:22px}}
"#;

pub fn render(inp: &ReportInput) -> String {
    let mut h = String::new();
    let total_len: usize = inp.contigs.iter().map(|c| c.1).sum();
    h.push_str(&format!(
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>{}</title><style>{}</style></head><body><main>",
        esc(&inp.title),
        CSS
    ));
    h.push_str(&format!(
        "<h1>{}</h1><p class=\"sub\">{} reference sequence{} · {} bp</p>",
        esc(&inp.title),
        inp.contigs.len(),
        if inp.contigs.len() == 1 { "" } else { "s" },
        fmt_n(total_len)
    ));

    // KPIs
    let mut kpis: Vec<(String, String)> = Vec::new();
    if let Some(m) = inp.map_eval {
        kpis.push((pct(m.mapped as f64 / m.total.max(1) as f64), format!("of {} reads mapped", fmt_n(m.total))));
        if m.total > m.unparseable {
            kpis.push((pct(m.correct as f64 / m.mapped.max(1) as f64), "mapped at the true locus".into()));
        }
    } else if let Some(s) = inp.sam {
        let mapped = s.records.iter().filter(|r| r.is_mapped()).count();
        kpis.push((pct(mapped as f64 / s.records.len().max(1) as f64), format!("of {} reads mapped", fmt_n(s.records.len()))));
    }
    let cov_sum: u64 = inp.coverage.iter().flatten().map(|&x| x as u64).sum();
    kpis.push((format!("{:.1}×", cov_sum as f64 / total_len.max(1) as f64), "mean depth".into()));
    kpis.push((fmt_n(inp.calls.len()), "variants called".into()));
    if let Some(e) = inp.evaluation {
        kpis.push((format!("{:.3}", e.snp.f1()), "SNP F1".into()));
        kpis.push((format!("{:.3}", e.indel.f1()), "indel F1".into()));
    }
    if let Some(a) = &inp.assembly {
        kpis.push((fmt_n(a.stats.n50), "assembly N50 (bp)".into()));
    }
    h.push_str("<div class=\"kpis\">");
    for (v, l) in &kpis {
        h.push_str(&format!("<div class=\"kpi\"><b>{}</b><span>{}</span></div>", esc(v), esc(l)));
    }
    h.push_str("</div>");

    // coverage & variant tracks
    h.push_str("<h2>Coverage and variants</h2>");
    h.push_str("<div class=\"legend\"><span><i style=\"background:var(--area-line)\"></i>read depth</span>");
    if inp.evaluation.is_some() {
        h.push_str("<span><i style=\"background:var(--tp)\"></i>true positive</span><span><i style=\"background:var(--fp)\"></i>false call</span><span><i style=\"background:var(--fn);transform:rotate(45deg)\"></i>missed</span>");
    } else {
        h.push_str("<span><i style=\"background:var(--call)\"></i>called variant</span>");
    }
    h.push_str("</div>");
    for (ci, (name, len)) in inp.contigs.iter().enumerate() {
        let calls: Vec<&Variant> = inp.calls.iter().filter(|v| &v.chrom == name).collect();
        let (mut tp, mut fp, mut fnv) = (vec![], vec![], vec![]);
        if let Some(e) = inp.evaluation {
            // `calls` is the per-contig subset of inp.calls, so classify via the global index
            let mut local = 0;
            for (gi, v) in inp.calls.iter().enumerate() {
                if &v.chrom != name {
                    continue;
                }
                match e.call_class.get(gi).copied().flatten() {
                    Some(true) => tp.push(local),
                    Some(false) => fp.push(local),
                    None => {}
                }
                local += 1;
            }
            fnv = e.missed.iter().filter(|v| &v.chrom == name).map(|v| v.pos).collect();
        }
        let ins = calls.iter().filter(|v| v.kind() == Kind::Ins).count();
        let del = calls.iter().filter(|v| v.kind() == Kind::Del).count();
        h.push_str(&format!(
            "<div class=\"card\"><h3>{}<small>{} bp · {} variants ({} SNP, {} ins, {} del)</small></h3>{}</div>",
            esc(name),
            fmt_n(*len),
            calls.len(),
            calls.len() - ins - del,
            ins,
            del,
            coverage_svg(name, *len, &inp.coverage[ci], &calls, &tp, &fp, &fnv)
        ));
    }

    // accuracy
    if let Some(e) = inp.evaluation {
        h.push_str("<h2>Variant accuracy against the truth set</h2><div class=\"card\"><table><tr><th>class</th><th>TP</th><th>FP</th><th>FN</th><th>precision</th><th>recall</th><th>F1</th><th>genotype concordance</th></tr>");
        for (n, c) in [("SNP", &e.snp), ("indel", &e.indel)] {
            h.push_str(&format!(
                "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{:.4}</td><td>{:.4}</td><td>{:.4}</td><td>{}</td></tr>",
                n,
                c.tp,
                c.fp,
                c.fn_,
                c.precision(),
                c.recall(),
                c.f1(),
                if c.tp == 0 { "–".to_string() } else { format!("{:.4}", c.gt_concordance()) }
            ));
        }
        h.push_str("</table></div>");
    }

    // mapping quality
    if let Some(m) = inp.map_eval {
        h.push_str("<h2>Mapping quality</h2><div class=\"card\"><h3>Reads by minimum MAPQ <small>accuracy = placed within tolerance of the simulated origin</small></h3>");
        let rows: Vec<(String, f64, String)> = m
            .by_mapq
            .iter()
            .map(|&(q, n, c)| (format!("≥ {}", q), n as f64, if n == 0 { String::new() } else { format!("{:.3}% correct", 100.0 * c as f64 / n as f64) }))
            .collect();
        h.push_str(&bar_chart(&rows, m.mapped as f64, ""));
        h.push_str("</div>");
    }

    // assembly
    if let Some(a) = &inp.assembly {
        h.push_str("<h2>Assembly</h2><div class=\"two\">");
        h.push_str("<div class=\"card\"><h3>Contigs</h3><table>");
        let s = a.stats;
        for (k, v) in [
            ("contigs", fmt_n(s.contigs)),
            ("total length", format!("{} bp", fmt_n(s.total_len))),
            ("largest", format!("{} bp", fmt_n(s.largest))),
            ("N50 / L50", format!("{} / {}", fmt_n(s.n50), s.l50)),
            ("N90", fmt_n(s.n90)),
            ("tips clipped", fmt_n(s.tips_removed)),
            ("bubbles popped", fmt_n(s.bubbles_popped)),
            ("error k-mer cut-off", format!("{}{}", s.cutoff, if s.cutoff_auto { " (auto)" } else { "" })),
        ] {
            h.push_str(&format!("<tr><td>{}</td><td>{}</td></tr>", k, v));
        }
        h.push_str("</table></div>");
        if let Some(sp) = a.spectrum {
            let pts: Vec<(f64, f64)> = sp.iter().enumerate().skip(1).take(80).map(|(c, &n)| (c as f64, n as f64)).collect();
            h.push_str(&format!(
                "<div class=\"card\"><h3>k-mer spectrum <small>log scale · peak ≈ {}×</small></h3>{}</div>",
                s.coverage_peak,
                line_svg(&pts, Some(s.cutoff as f64), "k-mer multiplicity", "distinct k-mers", true)
            ));
        }
        h.push_str("</div>");
        if let Some(e) = a.eval {
            h.push_str("<div class=\"card\"><h3>Against the truth sequence</h3><table>");
            for (k, v) in [
                ("genome fraction", pct(e.genome_fraction)),
                ("duplication ratio", format!("{:.3}", e.duplication_ratio)),
                ("misassemblies", e.misassemblies.to_string()),
                ("mismatches / 100 kb", format!("{:.1}", e.mismatches_per_100kb)),
                ("indels / 100 kb", format!("{:.1}", e.indels_per_100kb)),
                ("NGA50", fmt_n(e.nga50)),
                ("unaligned bases", fmt_n(e.unaligned_bases)),
            ] {
                h.push_str(&format!("<tr><td>{}</td><td>{}</td></tr>", k, v));
            }
            h.push_str("</table></div>");
        }
        let top: Vec<(String, f64, String)> = a.contigs.iter().take(12).enumerate().map(|(i, c)| (format!("contig {}", i + 1), c.seq.len() as f64, format!("{:.0}× cov", c.cov))).collect();
        if !top.is_empty() {
            let max = top[0].1;
            h.push_str("<div class=\"card\"><h3>Longest contigs <small>bp</small></h3>");
            h.push_str(&bar_chart(&top, max, " bp"));
            h.push_str("</div>");
        }
    }

    h.push_str("<footer>Generated by Strand — a from-scratch genomics toolkit. Charts are inline SVG; this file has no external dependencies.</footer></main></body></html>");
    h
}

#[cfg(test)]
mod tests {
    use super::*;

    fn variant(pos: usize) -> Variant {
        let mut v = Variant::new("chr1", pos, b"A", b"G");
        v.gt = Some((0, 1));
        v
    }

    #[test]
    fn renders_self_contained_html_with_escaping() {
        let calls = vec![variant(100), variant(900)];
        let cov: Vec<u16> = (0..1000).map(|i| (20 + (i % 7)) as u16).collect();
        let inp = ReportInput {
            title: "Run <1> & \"x\"".into(),
            contigs: vec![("chr1".into(), 1000)],
            coverage: vec![cov],
            calls: &calls,
            evaluation: None,
            sam: None,
            map_eval: None,
            assembly: None,
        };
        let html = render(&inp);
        assert!(html.starts_with("<!doctype html>"));
        assert!(html.contains("Run &lt;1&gt; &amp; &quot;x&quot;"));
        assert!(!html.contains("<script"), "report must contain no scripts");
        assert!(!html.contains("http://") && !html.contains("https://"), "report must not reference the network");
        assert!(html.matches("<svg").count() == 1);
        assert!(html.contains("2 variants"));
    }

    #[test]
    fn zero_length_and_flat_coverage_do_not_panic() {
        let inp = ReportInput { title: "t".into(), contigs: vec![("c".into(), 5)], coverage: vec![vec![0; 5]], calls: &[], evaluation: None, sam: None, map_eval: None, assembly: None };
        let html = render(&inp);
        assert!(html.contains("</html>"));
    }

    #[test]
    fn number_formatting() {
        assert_eq!(fmt_n(0), "0");
        assert_eq!(fmt_n(1234567), "1,234,567");
        assert_eq!(fmt_n(999), "999");
    }
}
