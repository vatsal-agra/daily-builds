//! Screen renderers: plain text, ANSI re-serialisation, self-contained HTML, SVG and JSON.

use crate::cell::*;
use crate::json::Value;
use crate::screen::*;
use crate::term::sgr_string;

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Theme {
    Dark,
    Light,
    /// Follows `prefers-color-scheme` (HTML only; SVG falls back to dark).
    Auto,
}

#[derive(Clone, Debug)]
pub struct RenderOpts {
    pub theme: Theme,
    pub cursor: bool,
    /// Include scrollback lines above the visible screen.
    pub scrollback: bool,
    pub title: Option<String>,
}

impl Default for RenderOpts {
    fn default() -> Self {
        RenderOpts { theme: Theme::Auto, cursor: true, scrollback: false, title: None }
    }
}

/// Rows to render: optional scrollback followed by the visible lines. The second value is the
/// index (within the returned vec) of the first visible row.
fn rows_of<'a>(s: &'a Screen, scrollback: bool) -> (Vec<&'a Line>, usize) {
    let mut v: Vec<&Line> = Vec::new();
    if scrollback {
        v.extend(s.buf().scrollback.iter());
    }
    let first = v.len();
    v.extend(s.buf().lines.iter());
    (v, first)
}

// ---- plain text -------------------------------------------------------------------------------

/// Plain text; trailing blank lines are dropped.
pub fn to_text(s: &Screen, scrollback: bool) -> String {
    let (rows, _) = rows_of(s, scrollback);
    let mut lines: Vec<String> = rows.iter().map(|l| l.text()).collect();
    while lines.last().map(|l| l.is_empty()).unwrap_or(false) {
        lines.pop();
    }
    lines.join("\n")
}

// ---- ANSI -------------------------------------------------------------------------------------

/// Serialise the visible screen to escape sequences that reproduce it (cells, colours,
/// attributes, links, cursor position and visibility) when fed to a fresh terminal of the same size.
pub fn to_ansi(s: &Screen) -> Vec<u8> {
    let mut out = String::new();
    out.push_str("\x1b[0m\x1b[?25l\x1b[H\x1b[2J");
    let mut cur = Pen::default();
    let mut link = 0u32;
    for (y, line) in s.buf().lines.iter().enumerate() {
        // Rows that are entirely plain blanks need no output after the clear.
        let end = line.used_len();
        if end == 0 {
            continue;
        }
        out.push_str(&format!("\x1b[{};1H", y + 1));
        for cell in &line.cells[..end] {
            if cell.width == 0 {
                continue;
            }
            let pen = cell.pen();
            let style_changed = pen.fg != cur.fg || pen.bg != cur.bg || pen.ul != cur.ul || pen.attrs != cur.attrs;
            if style_changed {
                out.push_str(&format!("\x1b[{}m", sgr_string(&pen)));
                cur = Pen { link: cur.link, ..pen };
            }
            if pen.link != link {
                if pen.link == 0 {
                    out.push_str("\x1b]8;;\x1b\\");
                } else {
                    let l = &s.links[pen.link as usize];
                    if l.id.is_empty() {
                        out.push_str(&format!("\x1b]8;;{}\x1b\\", l.uri));
                    } else {
                        out.push_str(&format!("\x1b]8;id={};{}\x1b\\", l.id, l.uri));
                    }
                }
                link = pen.link;
            }
            cell.push_text(&mut out);
        }
        // Soft wrap fidelity: a full-width wrapped row leaves the cursor in the pending-wrap state,
        // so the explicit positioning of the next row is equivalent.
        if link != 0 {
            out.push_str("\x1b]8;;\x1b\\");
            link = 0;
        }
        out.push_str("\x1b[0m");
        cur = Pen::default();
    }
    out.push_str(&format!("\x1b[{};{}H", s.cy + 1, s.cx + 1));
    if s.modes.cursor_visible {
        out.push_str("\x1b[?25h");
    }
    out.into_bytes()
}

// ---- colours ----------------------------------------------------------------------------------

struct Palette {
    ansi: [(u8, u8, u8); 16],
    fg: (u8, u8, u8),
    bg: (u8, u8, u8),
    cursor: (u8, u8, u8),
}

const DARK: Palette = Palette {
    ansi: [
        (0x1b, 0x1e, 0x28), (0xe0, 0x6c, 0x75), (0x98, 0xc3, 0x79), (0xe5, 0xc0, 0x7b), (0x61, 0xaf, 0xef), (0xc6, 0x78, 0xdd), (0x56, 0xb6, 0xc2), (0xab, 0xb2, 0xbf),
        (0x5c, 0x63, 0x70), (0xff, 0x7b, 0x86), (0xb1, 0xe0, 0x8b), (0xf5, 0xd5, 0x8f), (0x7c, 0xc2, 0xff), (0xe0, 0x8f, 0xf5), (0x6b, 0xd1, 0xdd), (0xf0, 0xf3, 0xf8),
    ],
    fg: (0xd7, 0xda, 0xe0),
    bg: (0x14, 0x16, 0x1c),
    cursor: (0xf5, 0xd5, 0x8f),
};

const LIGHT: Palette = Palette {
    ansi: [
        (0x23, 0x27, 0x32), (0xc9, 0x2f, 0x3c), (0x3a, 0x84, 0x2d), (0x9a, 0x6b, 0x00), (0x1f, 0x5f, 0xc6), (0x8f, 0x3a, 0xb0), (0x0f, 0x7f, 0x8c), (0x8a, 0x90, 0x9c),
        (0x5c, 0x63, 0x70), (0xe0, 0x4a, 0x57), (0x4f, 0xa0, 0x3f), (0xb8, 0x83, 0x10), (0x3a, 0x7b, 0xe0), (0xa8, 0x55, 0xc9), (0x22, 0x9a, 0xa8), (0xc5, 0xca, 0xd3),
    ],
    fg: (0x2b, 0x2f, 0x3a),
    bg: (0xfa, 0xfa, 0xf7),
    cursor: (0x1f, 0x5f, 0xc6),
};

fn hex(c: (u8, u8, u8)) -> String {
    format!("#{:02x}{:02x}{:02x}", c.0, c.1, c.2)
}

/// A colour as the renderers see it before CSS/SVG formatting.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum Css {
    Fg,
    Bg,
    Ansi(u8),
    Rgb(u8, u8, u8),
}

fn tok(s: &Screen, c: Color, is_fg: bool) -> Css {
    match c {
        Color::Default => {
            if is_fg {
                Css::Fg
            } else {
                Css::Bg
            }
        }
        Color::Idx(i) => {
            let p = s.palette[i as usize];
            if i < 16 && p == xterm_rgb(i) {
                Css::Ansi(i)
            } else {
                Css::Rgb(p.0, p.1, p.2)
            }
        }
        Color::Rgb(r, g, b) => Css::Rgb(r, g, b),
    }
}

/// Resolved drawing style of one cell.
#[derive(Clone, PartialEq, Eq, Debug)]
struct Style {
    fg: Css,
    bg: Css,
    attrs: u16,
    ul: Option<Css>,
    link: u32,
}

fn style_of(s: &Screen, c: &Cell) -> Style {
    let mut fg = tok(s, c.fg, true);
    let mut bg = tok(s, c.bg, false);
    let mut attrs = c.attrs;
    if attrs & INVERSE != 0 {
        std::mem::swap(&mut fg, &mut bg);
    }
    if s.modes.reverse_video {
        std::mem::swap(&mut fg, &mut bg);
    }
    if attrs & HIDDEN != 0 {
        fg = bg;
    }
    attrs &= !(INVERSE | HIDDEN);
    let ul = if c.ul == Color::Default { None } else { Some(tok(s, c.ul, true)) };
    Style { fg, bg, attrs, ul, link: c.link }
}

fn esc_html(t: &str, out: &mut String) {
    for ch in t.chars() {
        match ch {
            '&' => out.push_str("&amp;"),
            '<' => out.push_str("&lt;"),
            '>' => out.push_str("&gt;"),
            '"' => out.push_str("&quot;"),
            c => out.push(c),
        }
    }
}

fn safe_href(uri: &str) -> bool {
    let l = uri.to_ascii_lowercase();
    l.starts_with("http://") || l.starts_with("https://") || l.starts_with("mailto:") || l.starts_with("file://")
}

// ---- HTML -------------------------------------------------------------------------------------

fn css_vars(p: &Palette) -> String {
    let mut s = format!("--bg:{};--fg:{};--cur:{};", hex(p.bg), hex(p.fg), hex(p.cursor));
    for (i, c) in p.ansi.iter().enumerate() {
        s.push_str(&format!("--c{}:{};", i, hex(*c)));
    }
    s
}

fn css_color(c: Css) -> String {
    match c {
        Css::Fg => "var(--fg)".into(),
        Css::Bg => "var(--bg)".into(),
        Css::Ansi(i) => format!("var(--c{})", i),
        Css::Rgb(r, g, b) => hex((r, g, b)),
    }
}

fn class_and_style(st: &Style, is_cursor: bool) -> (String, String) {
    let mut cls: Vec<String> = Vec::new();
    let mut style = String::new();
    match st.fg {
        Css::Fg => {}
        Css::Ansi(i) => cls.push(format!("f{}", i)),
        other => style.push_str(&format!("color:{};", css_color(other))),
    }
    match st.bg {
        Css::Bg => {}
        Css::Ansi(i) => cls.push(format!("b{}", i)),
        other => style.push_str(&format!("background:{};", css_color(other))),
    }
    // inverse/hidden were folded into fg/bg already; an Fg-coloured background needs an explicit rule.
    if st.fg == Css::Bg && !style.contains("color:") && !cls.iter().any(|c| c.starts_with('f')) {
        style.push_str("color:var(--bg);");
    }
    if st.bg == Css::Fg {
        style.push_str("background:var(--fg);");
    }
    let flags: [(u16, &str); 9] = [
        (BOLD, "bo"),
        (DIM, "di"),
        (ITALIC, "it"),
        (UNDERLINE, "ul"),
        (BLINK, "bl"),
        (STRIKE, "st"),
        (DOUBLE_UL, "u2"),
        (CURLY_UL, "uc"),
        (OVERLINE, "ol"),
    ];
    for (f, n) in flags {
        if st.attrs & f != 0 {
            cls.push(n.to_string());
        }
    }
    if st.attrs & DOTTED_UL != 0 {
        cls.push("ud".into());
    }
    if st.attrs & DASHED_UL != 0 {
        cls.push("ud2".into());
    }
    if let Some(u) = st.ul {
        style.push_str(&format!("text-decoration-color:{};", css_color(u)));
    }
    if is_cursor {
        cls.push("cur".into());
    }
    (cls.join(" "), style)
}

/// One `<div class="r">` per rendered row (scrollback first when requested).
pub fn html_rows(s: &Screen, opts: &RenderOpts) -> Vec<String> {
    let (rows, first_visible) = rows_of(s, opts.scrollback);
    let cursor_row = first_visible + s.cy;
    let show_cursor = opts.cursor && s.modes.cursor_visible;
    rows.iter().enumerate().map(|(ry, line)| html_row(s, line, show_cursor && ry == cursor_row)).collect()
}

fn html_row(s: &Screen, line: &Line, cursor_here: bool) -> String {
    let mut body = String::new();
    body.push_str("<div class=\"r\">");
    let n = {
        let mut n = line.used_len();
        if cursor_here {
            n = n.max(s.cx + 1);
        }
        n.min(line.cells.len())
    };
    let mut x = 0;
    let mut run = String::new();
    let mut run_style: Option<(Style, bool)> = None;
    let flush = |body: &mut String, run: &mut String, rs: &mut Option<(Style, bool)>| {
        if let Some((st, is_cur)) = rs.take() {
            let (cls, style) = class_and_style(&st, is_cur);
            let link = if st.link != 0 && safe_href(&s.links[st.link as usize].uri) { Some(&s.links[st.link as usize].uri) } else { None };
            if let Some(u) = link {
                body.push_str("<a href=\"");
                esc_html(u, body);
                body.push_str("\" rel=\"noopener\">");
            }
            if cls.is_empty() && style.is_empty() {
                body.push_str(run);
            } else {
                body.push_str("<span");
                if !cls.is_empty() {
                    body.push_str(&format!(" class=\"{}\"", cls));
                }
                if !style.is_empty() {
                    body.push_str(&format!(" style=\"{}\"", style));
                }
                body.push('>');
                body.push_str(run);
                body.push_str("</span>");
            }
            if link.is_some() {
                body.push_str("</a>");
            }
        }
        run.clear();
    };
    while x < n {
        let c = &line.cells[x];
        if c.width == 0 {
            x += 1;
            continue;
        }
        let is_cur = cursor_here && x == s.cx;
        let st = style_of(s, c);
        let key = (st.clone(), is_cur);
        if run_style.as_ref() != Some(&key) {
            flush(&mut body, &mut run, &mut run_style);
            run_style = Some(key);
        }
        let mut txt = String::new();
        c.push_text(&mut txt);
        if c.width == 2 {
            run.push_str("<span class=\"w\">");
            esc_html(&txt, &mut run);
            run.push_str("</span>");
        } else {
            esc_html(&txt, &mut run);
        }
        x += 1;
    }
    flush(&mut body, &mut run, &mut run_style);
    if n == 0 {
        body.push(' ');
    }
    body.push_str("</div>");
    body
}

/// Stylesheet shared by the standalone page and the cast player.
pub fn html_css(theme: Theme) -> String {
    let (light_dark, root_vars) = match theme {
        Theme::Dark => (String::new(), css_vars(&DARK)),
        Theme::Light => (String::new(), css_vars(&LIGHT)),
        Theme::Auto => (format!("@media (prefers-color-scheme:light){{:root{{{}}}}}", css_vars(&LIGHT)), css_vars(&DARK)),
    };
    let mut ansi_css = String::new();
    for i in 0..16 {
        ansi_css.push_str(&format!(".f{i}{{color:var(--c{i})}}.b{i}{{background:var(--c{i})}}"));
    }
    format!(
        ":root{{{root_vars}color-scheme:dark light}}{light_dark}\n\
*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px 16px;background:radial-gradient(1200px 600px at 50% -10%,#232838 0,#0c0e13 70%);font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,\"DejaVu Sans Mono\",monospace}}\n\
@media (prefers-color-scheme:light){{body{{background:radial-gradient(1200px 600px at 50% -10%,#ffffff 0,#dfe3ec 70%)}}}}\n\
.term{{max-width:100%;border-radius:10px;overflow:hidden;background:var(--bg);box-shadow:0 18px 50px rgba(0,0,0,.45),0 0 0 1px rgba(128,128,128,.25)}}\n\
.bar{{display:flex;align-items:center;gap:8px;padding:9px 14px;font:12px/1 system-ui,sans-serif;color:var(--fg);background:color-mix(in srgb,var(--fg) 7%,var(--bg));border-bottom:1px solid rgba(128,128,128,.25)}}\n\
.dots i{{display:inline-block;width:11px;height:11px;border-radius:50%;margin-right:6px;background:var(--c1)}}.dots i:nth-child(2){{background:var(--c3)}}.dots i:nth-child(3){{background:var(--c2)}}\n\
.ttl{{flex:1;text-align:center;opacity:.75;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}.sz{{opacity:.5;font-variant-numeric:tabular-nums}}\n\
.screen{{margin:0;padding:12px 14px;overflow:auto;color:var(--fg);font-size:14px;line-height:1.25;font-variant-ligatures:none}}\n\
.r{{white-space:pre;min-height:1.25em}}.w{{display:inline-block;width:2ch;overflow:visible}}\n\
a{{color:inherit;text-decoration:underline dotted}}a:hover{{text-decoration:underline solid}}\n\
{ansi_css}.bo{{font-weight:700}}.di{{opacity:.6}}.it{{font-style:italic}}.ul{{text-decoration:underline}}.u2{{text-decoration:underline double}}.uc{{text-decoration:underline wavy}}.ud{{text-decoration:underline dotted}}.ud2{{text-decoration:underline dashed}}.st{{text-decoration:line-through}}.ol{{text-decoration:overline}}\n\
.ul.st{{text-decoration:underline line-through}}\n\
.bl{{animation:blink 1.1s steps(2,start) infinite}}@keyframes blink{{to{{visibility:hidden}}}}@media (prefers-reduced-motion:reduce){{.bl{{animation:none}}}}\n\
.cur{{outline:1.5px solid var(--cur);outline-offset:-1px;background:color-mix(in srgb,var(--cur) 55%,transparent)}}\n"
    )
}

pub fn to_html(s: &Screen, opts: &RenderOpts) -> String {
    let body = html_rows(s, opts).join("\n");
    let title = opts.title.clone().unwrap_or_else(|| if s.title.is_empty() { "terminal".to_string() } else { s.title.clone() });
    let mut t = String::new();
    esc_html(&title, &mut t);
    let css = html_css(opts.theme);
    format!(
        "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">\n<title>{t} — cathode</title>\n<style>\n{css}</style></head><body>\n<div class=\"term\"><div class=\"bar\"><span class=\"dots\"><i></i><i></i><i></i></span><span class=\"ttl\">{t}</span><span class=\"sz\">{cols}×{rows}</span></div>\n<pre class=\"screen\">{body}</pre></div>\n</body></html>\n",
        cols = s.cols,
        rows = s.rows,
    )
}

// ---- SVG --------------------------------------------------------------------------------------

pub fn to_svg(s: &Screen, opts: &RenderOpts) -> String {
    let pal = if opts.theme == Theme::Light { &LIGHT } else { &DARK };
    let (cw, lh) = (9.0f64, 19.0f64);
    let (rows, first_visible) = rows_of(s, opts.scrollback);
    let pad = 12.0;
    let w = s.cols as f64 * cw + pad * 2.0;
    let h = rows.len() as f64 * lh + pad * 2.0;
    let col = |c: Css| -> String {
        match c {
            Css::Fg => hex(pal.fg),
            Css::Bg => hex(pal.bg),
            Css::Ansi(i) => hex(pal.ansi[i as usize]),
            Css::Rgb(r, g, b) => hex((r, g, b)),
        }
    };
    let mut out = String::new();
    out.push_str(&format!(
        "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"{w}\" height=\"{h}\" viewBox=\"0 0 {w} {h}\" font-family=\"ui-monospace,SFMono-Regular,Menlo,Consolas,'DejaVu Sans Mono',monospace\" font-size=\"15\">\n"
    ));
    out.push_str(&format!("<rect width=\"100%\" height=\"100%\" rx=\"8\" fill=\"{}\"/>\n", hex(pal.bg)));
    let cursor_row = first_visible + s.cy;
    for (ry, line) in rows.iter().enumerate() {
        let y0 = pad + ry as f64 * lh;
        // backgrounds
        let mut x = 0;
        while x < line.cells.len() {
            let c = &line.cells[x];
            let st = style_of(s, c);
            let mut e = x + 1;
            while e < line.cells.len() && style_of(s, &line.cells[e]).bg == st.bg {
                e += 1;
            }
            if st.bg != Css::Bg {
                out.push_str(&format!(
                    "<rect x=\"{}\" y=\"{}\" width=\"{}\" height=\"{}\" fill=\"{}\"/>\n",
                    pad + x as f64 * cw,
                    y0,
                    (e - x) as f64 * cw,
                    lh,
                    col(st.bg)
                ));
            }
            x = e;
        }
        if opts.cursor && s.modes.cursor_visible && ry == cursor_row {
            out.push_str(&format!(
                "<rect x=\"{}\" y=\"{}\" width=\"{}\" height=\"{}\" fill=\"{}\" fill-opacity=\"0.55\" stroke=\"{}\"/>\n",
                pad + s.cx as f64 * cw,
                y0,
                cw,
                lh,
                hex(pal.cursor),
                hex(pal.cursor)
            ));
        }
        // text runs
        let n = line.used_len();
        let mut x = 0;
        while x < n {
            let c = &line.cells[x];
            if c.width == 0 || (c.ch == ' ' && c.comb.is_none()) {
                x += 1;
                continue;
            }
            let st = style_of(s, c);
            let mut text = String::new();
            let mut cells = 0usize;
            let mut e = x;
            // gather a run of same-style, narrow cells (spaces inside the run are kept)
            while e < n {
                let ce = &line.cells[e];
                if ce.width == 2 {
                    if e == x {
                        ce.push_text(&mut text);
                        cells = 2;
                        e += 2;
                    }
                    break;
                }
                if ce.width == 0 || style_of(s, ce) != st {
                    break;
                }
                ce.push_text(&mut text);
                cells += 1;
                e += 1;
            }
            let mut esc = String::new();
            esc_html(&text, &mut esc);
            let mut attrs = String::new();
            if st.attrs & BOLD != 0 {
                attrs.push_str(" font-weight=\"700\"");
            }
            if st.attrs & ITALIC != 0 {
                attrs.push_str(" font-style=\"italic\"");
            }
            if st.attrs & DIM != 0 {
                attrs.push_str(" fill-opacity=\"0.6\"");
            }
            let mut deco = Vec::new();
            if st.attrs & ANY_UL != 0 {
                deco.push("underline");
            }
            if st.attrs & STRIKE != 0 {
                deco.push("line-through");
            }
            if st.attrs & OVERLINE != 0 {
                deco.push("overline");
            }
            if !deco.is_empty() {
                attrs.push_str(&format!(" text-decoration=\"{}\"", deco.join(" ")));
            }
            let blink_free = attrs;
            out.push_str(&format!(
                "<text x=\"{}\" y=\"{}\" fill=\"{}\" textLength=\"{}\" lengthAdjust=\"spacing\" xml:space=\"preserve\"{}>{}</text>\n",
                pad + x as f64 * cw,
                y0 + lh - 5.0,
                col(st.fg),
                cells as f64 * cw,
                blink_free,
                esc
            ));
            x = e.max(x + 1);
        }
    }
    out.push_str("</svg>\n");
    out
}

// ---- JSON -------------------------------------------------------------------------------------

fn color_json(c: Color) -> Value {
    match c {
        Color::Default => Value::Null,
        Color::Idx(i) => Value::Num(i as f64),
        Color::Rgb(r, g, b) => Value::Str(format!("#{:02x}{:02x}{:02x}", r, g, b)),
    }
}

fn attr_names(a: u16) -> Vec<Value> {
    let names: [(u16, &str); 13] = [
        (BOLD, "bold"),
        (DIM, "dim"),
        (ITALIC, "italic"),
        (UNDERLINE, "underline"),
        (BLINK, "blink"),
        (INVERSE, "inverse"),
        (HIDDEN, "hidden"),
        (STRIKE, "strike"),
        (DOUBLE_UL, "double-underline"),
        (CURLY_UL, "curly-underline"),
        (OVERLINE, "overline"),
        (DOTTED_UL, "dotted-underline"),
        (DASHED_UL, "dashed-underline"),
    ];
    names.iter().filter(|(f, _)| a & f != 0).map(|(_, n)| Value::Str(n.to_string())).collect()
}

/// Machine-readable snapshot: size, cursor, modes, title and rows as style runs.
pub fn to_json(s: &Screen) -> Value {
    let mut lines = Vec::new();
    for line in &s.buf().lines {
        let mut runs: Vec<Value> = Vec::new();
        let mut x = 0;
        let n = line.used_len();
        while x < n {
            let c = &line.cells[x];
            let mut text = String::new();
            let start = x;
            let pen = c.pen();
            while x < n {
                let ce = &line.cells[x];
                if ce.pen() != pen {
                    break;
                }
                if ce.width != 0 {
                    ce.push_text(&mut text);
                }
                x += 1;
            }
            let mut kv = vec![("x".to_string(), Value::Num(start as f64)), ("text".to_string(), Value::Str(text))];
            if pen.fg != Color::Default {
                kv.push(("fg".into(), color_json(pen.fg)));
            }
            if pen.bg != Color::Default {
                kv.push(("bg".into(), color_json(pen.bg)));
            }
            if pen.attrs != 0 {
                kv.push(("attrs".into(), Value::Arr(attr_names(pen.attrs))));
            }
            if pen.link != 0 {
                kv.push(("link".into(), Value::Str(s.links[pen.link as usize].uri.clone())));
            }
            runs.push(Value::Obj(kv));
        }
        lines.push(Value::Obj(vec![("wrapped".into(), Value::Bool(line.wrapped)), ("runs".into(), Value::Arr(runs))]));
    }
    Value::Obj(vec![
        ("cols".into(), Value::Num(s.cols as f64)),
        ("rows".into(), Value::Num(s.rows as f64)),
        (
            "cursor".into(),
            Value::Obj(vec![
                ("x".into(), Value::Num(s.cx as f64)),
                ("y".into(), Value::Num(s.cy as f64)),
                ("visible".into(), Value::Bool(s.modes.cursor_visible)),
                ("pending_wrap".into(), Value::Bool(s.pending_wrap)),
            ]),
        ),
        ("title".into(), Value::Str(s.title.clone())),
        ("alt_screen".into(), Value::Bool(s.alt_active)),
        ("scrollback".into(), Value::Num(s.scrollback_len() as f64)),
        ("lines".into(), Value::Arr(lines)),
    ])
}
