"""The interactive HTML visualizer (stretch feature): real LaTeX-subset
typesetting (a small renderer this build wrote itself — no MathJax/KaTeX
CDN), an SVG plot of f(x) and f'(x) from genuine numeric sampling of the
symbolic tree, and a step-by-step differentiation trace with play/next/prev
controls — all computed by the real Python kernel, then embedded as data
for `generate_report()` (one expression, a static self-contained file), or
served live for arbitrary user input by `run_playground_server()` (a real
`http.server` backend, browser holds zero math logic — same
server-computes/browser-renders pattern this repo has used before, e.g.
Formulate/Faraday/Gambit).
"""

import html
import json
import math
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from .calculus import differentiate, integrate
from .errors import AxiomError
from .expr import RESERVED_CONSTANT_NAMES, sym
from .parser import parse as parse_expr
from .polynomial import expand, factor
from .simplify import simplify

PLOT_RANGE = 10.0
PLOT_SAMPLES = 400


def _infer_var(e):
    fs = e.free_symbols()
    non_constant = {s for s in fs if s.name not in RESERVED_CONSTANT_NAMES}
    candidates = non_constant or fs
    if not candidates:
        return sym("x")
    for s in candidates:
        if s.name == "x":
            return s
    return sorted(candidates, key=lambda s: s.name)[0]


def _sample(expr, var):
    pts = []
    for i in range(-PLOT_SAMPLES // 2, PLOT_SAMPLES // 2 + 1):
        xv = i * (2 * PLOT_RANGE / PLOT_SAMPLES)
        try:
            yv = expr.evalf({var: xv})
        except (AxiomError, ZeroDivisionError, OverflowError, ValueError):
            continue
        if abs(yv.imag) > 1e-6:
            continue
        if not math.isfinite(yv.real) or abs(yv.real) > 1e4:
            continue
        pts.append([round(xv, 4), round(yv.real, 6)])
    return pts


def analyze(expr_str, var_str=None):
    """Run every Axiom feature on one expression and return a JSON-ready
    dict — the single source of truth for both the static report and the
    live playground's API response."""
    e = parse_expr(expr_str)
    var = parse_expr(var_str) if var_str else _infer_var(e)
    out = {"input": str(e), "input_latex": e.latex(), "var": str(var)}

    simp = simplify(e)
    out["simplified"] = str(simp)
    out["simplified_latex"] = simp.latex()

    trace = []
    deriv = differentiate(e, var, trace=trace)
    out["derivative"] = str(deriv)
    out["derivative_latex"] = deriv.latex()
    out["diff_steps"] = trace

    try:
        integ = integrate(e, var)
        out["integral"] = f"{integ} + C"
        out["integral_latex"] = integ.latex() + " + C"
    except AxiomError as ex:
        out["integral_error"] = str(ex)

    try:
        out["expanded"] = str(expand(e))
    except Exception:
        pass

    try:
        out["factored"] = str(factor(e, var))
    except AxiomError as ex:
        out["factor_error"] = str(ex)

    out["plot_f"] = _sample(e, var)
    out["plot_fprime"] = _sample(deriv, var)
    return out


_LATEX_JS = r"""
// A small, self-written renderer for exactly the LaTeX subset axiom/latex.py
// emits (\frac, \sqrt, ^{}, \left(\right), \cdot, \sin/\cos/..., \pi, ...).
// No MathJax/KaTeX/CDN — this is the whole renderer.
function renderLatex(src) {
  let i = 0;
  function peek() { return src[i]; }
  function eatCmd() {
    // consumes a backslash command name, e.g. "\frac" -> "frac"
    i++; let s = "";
    while (i < src.length && /[a-zA-Z]/.test(src[i])) s += src[i++];
    return s;
  }
  function eatGroup() {
    if (src[i] !== "{") return eatAtom();
    i++; // {
    let node = document.createElement("span");
    node.className = "grp";
    while (i < src.length && src[i] !== "}") {
      node.appendChild(term());
    }
    i++; // }
    return node;
  }
  function eatAtom() {
    let s = "";
    if (/[a-zA-Z0-9.]/.test(src[i])) {
      while (i < src.length && /[a-zA-Z0-9.]/.test(src[i])) s += src[i++];
    } else {
      s = src[i++] || "";
    }
    let span = document.createElement("span");
    span.textContent = s;
    return span;
  }
  const GREEK = {pi: "π", theta: "θ", alpha: "α", beta: "β",
                 gamma: "γ", delta: "δ", lambda: "λ", mu: "μ",
                 sigma: "σ", phi: "φ", omega: "ω"};
  const FUNCNAMES = {sin: "sin", cos: "cos", tan: "tan", ln: "ln", exp: "exp",
                      arcsin: "sin⁻¹", arccos: "cos⁻¹",
                      arctan: "tan⁻¹", sinh: "sinh", cosh: "cosh", tanh: "tanh"};

  function term() {
    while (i < src.length && src[i] === " ") i++;
    if (src[i] === "\\") {
      const start = i;
      const cmd = eatCmd();
      if (cmd === "frac") {
        const num = eatGroup(), den = eatGroup();
        const wrap = document.createElement("span");
        wrap.className = "frac";
        const n = document.createElement("span"); n.className = "num"; n.appendChild(num);
        const d = document.createElement("span"); d.className = "den"; d.appendChild(den);
        wrap.appendChild(n); wrap.appendChild(d);
        return wrap;
      }
      if (cmd === "sqrt") {
        const inner = eatGroup();
        const wrap = document.createElement("span");
        wrap.className = "sqrt";
        const rad = document.createElement("span"); rad.className = "radical"; rad.textContent = "√";
        const body = document.createElement("span"); body.className = "radicand"; body.appendChild(inner);
        wrap.appendChild(rad); wrap.appendChild(body);
        return wrap;
      }
      if (cmd === "left" || cmd === "right") {
        const delim = src[i++] || "";
        const span = document.createElement("span");
        span.className = "delim";
        span.textContent = delim === "(" ? "(" : delim === ")" ? ")" : delim;
        return span;
      }
      if (cmd === "cdot") {
        const span = document.createElement("span");
        span.className = "op"; span.textContent = "·";
        return span;
      }
      if (cmd === "operatorname") {
        const inner = eatGroup();
        const span = document.createElement("span");
        span.className = "fname"; span.appendChild(inner);
        return span;
      }
      if (GREEK[cmd]) {
        const span = document.createElement("span"); span.textContent = GREEK[cmd];
        return span;
      }
      if (FUNCNAMES[cmd]) {
        const span = document.createElement("span");
        span.className = "fname"; span.textContent = FUNCNAMES[cmd];
        return span;
      }
      const span = document.createElement("span"); span.textContent = src.slice(start, i);
      return span;
    }
    let base = src[i] === "{" ? eatGroup() : eatAtom();
    if (src[i] === "^") {
      i++;
      const exp = eatGroup();
      const wrap = document.createElement("span"); wrap.className = "sup-wrap";
      wrap.appendChild(base);
      const sup = document.createElement("span"); sup.className = "sup"; sup.appendChild(exp);
      wrap.appendChild(sup);
      return wrap;
    }
    return base;
  }

  const root = document.createElement("span");
  root.className = "mathexpr";
  while (i < src.length) root.appendChild(term());
  return root;
}
"""

_PLAYER_JS = r"""
function initStepPlayer(container, steps) {
  let idx = 0;
  const list = container.querySelector(".steps-list");
  const counter = container.querySelector(".steps-counter");
  function render() {
    list.innerHTML = "";
    for (let k = 0; k <= idx && k < steps.length; k++) {
      const li = document.createElement("li");
      li.textContent = steps[k];
      li.className = k === idx ? "current" : "past";
      list.appendChild(li);
    }
    counter.textContent = steps.length ? `${idx + 1} / ${steps.length}` : "0 / 0";
  }
  container.querySelector(".step-next").onclick = () => { if (idx < steps.length - 1) idx++; render(); };
  container.querySelector(".step-prev").onclick = () => { if (idx > 0) idx--; render(); };
  render();
}
"""

_PLOT_JS = r"""
function drawPlot(svg, ptsF, ptsFPrime) {
  const W = 560, H = 300, PAD = 30;
  const allPts = ptsF.concat(ptsFPrime);
  if (!allPts.length) { svg.innerHTML = '<text x="10" y="20" class="axis-label">no real values in range</text>'; return; }
  const xs = allPts.map(p => p[0]), ys = allPts.map(p => p[1]);
  const xMin = Math.min(...xs), xMax = Math.max(...xs);
  let yMin = Math.min(...ys, 0), yMax = Math.max(...ys, 0);
  if (yMin === yMax) { yMin -= 1; yMax += 1; }
  const sx = x => PAD + (x - xMin) / (xMax - xMin || 1) * (W - 2 * PAD);
  const sy = y => H - PAD - (y - yMin) / (yMax - yMin || 1) * (H - 2 * PAD);
  function path(pts) {
    return pts.map((p, k) => `${k === 0 ? "M" : "L"}${sx(p[0]).toFixed(2)},${sy(p[1]).toFixed(2)}`).join(" ");
  }
  let s = `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg">`;
  s += `<line x1="${PAD}" y1="${sy(0)}" x2="${W - PAD}" y2="${sy(0)}" class="axis"/>`;
  s += `<line x1="${sx(0)}" y1="${PAD}" x2="${sx(0)}" y2="${H - PAD}" class="axis"/>`;
  if (ptsF.length) s += `<path d="${path(ptsF)}" class="curve-f" fill="none"/>`;
  if (ptsFPrime.length) s += `<path d="${path(ptsFPrime)}" class="curve-fp" fill="none"/>`;
  s += "</svg>";
  svg.innerHTML = s;
}
"""

_CSS = r"""
:root {
  --bg: #ffffff; --panel: #f6f7fb; --text: #1b1e28; --muted: #6b7280;
  --border: #e2e5ec; --accent: #4f46e5; --accent2: #dc2626; --code-bg: #eef0f7;
}
@media (prefers-color-scheme: dark) {
  :root { --bg: #14151b; --panel: #1c1e27; --text: #e9eaf0; --muted: #9096a8;
          --border: #2c2f3a; --accent: #818cf8; --accent2: #f87171; --code-bg: #23252f; }
}
* { box-sizing: border-box; }
body { background: var(--bg); color: var(--text); font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
       margin: 0; padding: 2rem 1.25rem 4rem; }
.wrap { max-width: 880px; margin: 0 auto; }
h1 { font-size: 1.5rem; margin-bottom: 0.25rem; }
.sub { color: var(--muted); margin-top: 0; margin-bottom: 1.5rem; }
.card { background: var(--panel); border: 1px solid var(--border); border-radius: 12px;
        padding: 1.25rem 1.5rem; margin-bottom: 1.25rem; }
.card h2 { font-size: 1rem; text-transform: uppercase; letter-spacing: 0.04em;
           color: var(--muted); margin: 0 0 0.75rem; }
.mathrow { font-size: 1.3rem; padding: 0.5rem 0; overflow-x: auto; }
.mathexpr { display: inline-flex; align-items: center; white-space: nowrap; }
.frac { display: inline-flex; flex-direction: column; align-items: center; vertical-align: middle;
        margin: 0 0.15em; }
.frac .num { border-bottom: 1.5px solid var(--text); padding: 0 0.2em 0.1em; }
.frac .den { padding: 0.1em 0.2em 0; }
.sqrt { display: inline-flex; align-items: flex-start; }
.sqrt .radical { font-size: 1.1em; margin-right: 0.05em; }
.sqrt .radicand { border-top: 1.5px solid var(--text); padding: 0 0.15em; }
.sup-wrap { display: inline-flex; position: relative; }
.sup { font-size: 0.65em; vertical-align: super; margin-left: 0.05em; }
.fname { font-style: italic; margin-right: 0.05em; }
.delim { opacity: 0.6; }
code, .mono { font-family: "SF Mono", Menlo, Consolas, monospace; background: var(--code-bg);
              padding: 0.15rem 0.4rem; border-radius: 6px; font-size: 0.92em; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 1.25rem; }
@media (max-width: 640px) { .grid2 { grid-template-columns: 1fr; } }
.steps-list { list-style: none; margin: 0; padding: 0; font-size: 0.92rem; }
.steps-list li { padding: 0.35rem 0; border-bottom: 1px dashed var(--border); }
.steps-list li.past { color: var(--muted); }
.steps-list li.current { color: var(--text); font-weight: 600; }
.step-controls { margin-top: 0.75rem; display: flex; align-items: center; gap: 0.75rem; }
button { background: var(--accent); color: white; border: none; border-radius: 8px;
         padding: 0.4rem 0.9rem; cursor: pointer; font-size: 0.85rem; }
button:hover { opacity: 0.88; }
.steps-counter { color: var(--muted); font-size: 0.85rem; }
svg { width: 100%; height: auto; }
.axis { stroke: var(--muted); stroke-width: 1; }
.curve-f { stroke: var(--accent); stroke-width: 2.25; }
.curve-fp { stroke: var(--accent2); stroke-width: 2; stroke-dasharray: 5 4; }
.axis-label { fill: var(--muted); font-size: 12px; }
.legend { display: flex; gap: 1.25rem; margin-top: 0.5rem; font-size: 0.85rem; color: var(--muted); }
.legend span.dot { display: inline-block; width: 0.75em; height: 0.75em; border-radius: 50%; margin-right: 0.35em; }
.dot.f { background: var(--accent); }
.dot.fp { background: var(--accent2); }
.err { color: var(--accent2); font-size: 0.9rem; }
input[type=text] { width: 100%; padding: 0.6rem 0.75rem; border-radius: 8px; border: 1px solid var(--border);
       background: var(--bg); color: var(--text); font-size: 1rem; font-family: monospace; }
.playground-form { display: flex; gap: 0.6rem; flex-wrap: wrap; }
.playground-form input { flex: 1 1 240px; }
.examples { display: flex; flex-wrap: wrap; align-items: center; gap: 0.4rem; margin-top: 0.75rem; }
.examples-label { color: var(--muted); font-size: 0.8rem; margin-right: 0.15rem; }
.chip { background: var(--code-bg); color: var(--text); border: 1px solid var(--border);
        border-radius: 999px; padding: 0.25rem 0.7rem; font-size: 0.82rem; font-family: monospace; }
.chip:hover { border-color: var(--accent); opacity: 1; }
footer { text-align: center; color: var(--muted); font-size: 0.8rem; margin-top: 2rem; }
"""


def _render_card_html(data):
    steps_json = json.dumps(data.get("diff_steps", []))
    plot_f = json.dumps(data.get("plot_f", []))
    plot_fp = json.dumps(data.get("plot_fprime", []))
    integral_html = (f'<div class="mathrow" data-latex="{html.escape(data["integral_latex"])}"></div>'
                      if "integral_latex" in data
                      else f'<p class="err">{html.escape(data.get("integral_error", "n/a"))}</p>')
    factor_html = (f'<code>{html.escape(data["factored"])}</code>'
                   if "factored" in data
                   else f'<p class="err">{html.escape(data.get("factor_error", "n/a"))}</p>')
    return f"""
<div class="card">
  <h2>Expression</h2>
  <div class="mathrow" data-latex="{html.escape(data['input_latex'])}"></div>
  <p class="sub">variable: <code>{html.escape(data['var'])}</code> &middot; simplified: <code>{html.escape(data['simplified'])}</code></p>
</div>

<div class="grid2">
  <div class="card">
    <h2>Derivative</h2>
    <div class="mathrow" data-latex="{html.escape(data['derivative_latex'])}"></div>
    <div class="step-player">
      <ol class="steps-list"></ol>
      <div class="step-controls">
        <button class="step-prev">&larr; prev</button>
        <button class="step-next">next &rarr;</button>
        <span class="steps-counter"></span>
      </div>
    </div>
  </div>
  <div class="card">
    <h2>Integral</h2>
    {integral_html}
    <h2 style="margin-top:1.25rem">Factored</h2>
    {factor_html}
  </div>
</div>

<div class="card">
  <h2>Plot: f(x) and f&prime;(x)</h2>
  <div class="plot-svg"></div>
  <div class="legend">
    <span><span class="dot f"></span>f(x) = {html.escape(data['input'])}</span>
    <span><span class="dot fp"></span>f&prime;(x) = {html.escape(data['derivative'])}</span>
  </div>
</div>

<script>
(function() {{
  document.currentScript.parentElement.querySelectorAll(".mathrow").forEach(function(el) {{
    el.appendChild(renderLatex(el.dataset.latex));
  }});
  var stepPlayer = document.currentScript.parentElement.querySelector(".step-player");
  if (stepPlayer) initStepPlayer(stepPlayer, {steps_json});
  var plotDiv = document.currentScript.parentElement.querySelector(".plot-svg");
  if (plotDiv) drawPlot(plotDiv, {plot_f}, {plot_fp});
}})();
</script>
"""


def generate_report(expr, var, out_path):
    """Static, self-contained single-expression HTML report."""
    data = analyze(str(expr), str(var))
    body = _render_card_html(data)
    page = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Axiom — {html.escape(data['input'])}</title>
<style>{_CSS}</style>
<script>{_LATEX_JS}</script>
<script>{_PLAYER_JS}</script>
<script>{_PLOT_JS}</script>
</head>
<body>
<div class="wrap">
  <h1>Axiom</h1>
  <p class="sub">a from-scratch computer algebra system &mdash; report for
    <code>{html.escape(data['input'])}</code></p>
  {body}
  <footer>generated by <code>axiom viz</code></footer>
</div>
</body></html>
"""
    with open(out_path, "w") as f:
        f.write(page)
    return out_path


_PLAYGROUND_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Axiom Playground</title>
<style>__CSS__</style></head>
<body>
<div class="wrap">
  <h1>Axiom Playground</h1>
  <p class="sub">type any expression &mdash; a real Python CAS backend computes everything below, live</p>
  <div class="card">
    <form class="playground-form" id="form">
      <input type="text" id="expr" value="x^2 * sin(x)" autocomplete="off">
      <button type="submit">Analyze</button>
    </form>
    <div class="examples">
      <span class="examples-label">try:</span>
      <button type="button" class="chip" data-expr="x^2*sin(x)">x&sup2;&middot;sin(x)</button>
      <button type="button" class="chip" data-expr="x/(x^2+1)">x/(x&sup2;+1)</button>
      <button type="button" class="chip" data-expr="x^3-6*x^2+11*x-6">x&sup3;-6x&sup2;+11x-6</button>
      <button type="button" class="chip" data-expr="sqrt(x^2+4)">&radic;(x&sup2;+4)</button>
      <button type="button" class="chip" data-expr="x*exp(-x^2)">x&middot;e<sup>-x&sup2;</sup></button>
    </div>
  </div>
  <div id="results"></div>
  <footer>server-backed &mdash; the browser holds zero symbolic-math logic</footer>
</div>
<script>__LATEX_JS__</script>
<script>__PLAYER_JS__</script>
<script>__PLOT_JS__</script>
<script>
async function analyze(expr) {
  const res = await fetch("/api/analyze?expr=" + encodeURIComponent(expr));
  const data = await res.json();
  const results = document.getElementById("results");
  if (data.error) {
    // data.error can embed the raw user input verbatim (a parse error's
    // caret diagnostic repeats the offending text) — build this with DOM
    // methods, not string-concatenated innerHTML, so a submitted expression
    // like "<img src=x onerror=...>" is inert text, never executed markup.
    results.innerHTML = "";
    const card = document.createElement("div");
    card.className = "card";
    const p = document.createElement("p");
    p.className = "err";
    p.style.whiteSpace = "pre-wrap";
    p.textContent = data.error;
    card.appendChild(p);
    results.appendChild(card);
    return;
  }
  results.innerHTML = "";
  results.appendChild(__RENDER_CARD__(data));
}
document.getElementById("form").addEventListener("submit", function(e) {
  e.preventDefault();
  analyze(document.getElementById("expr").value);
});
document.querySelectorAll(".chip").forEach(function(btn) {
  btn.addEventListener("click", function() {
    document.getElementById("expr").value = btn.dataset.expr;
    analyze(btn.dataset.expr);
  });
});
analyze(document.getElementById("expr").value);
</script>
</body></html>
"""


def _render_card_js_function():
    # A JS re-implementation of _render_card_html's *templating* only (no math
    # logic — every value it inserts came from the real Python /api/analyze
    # response), so the playground can re-render without a page reload.
    return r"""
function renderCard(data) {
  function esc(s) {
    const d = document.createElement("div"); d.textContent = s; return d.innerHTML;
  }
  const integralHtml = data.integral_latex
    ? '<div class="mathrow" data-latex="' + esc(data.integral_latex) + '"></div>'
    : '<p class="err">' + esc(data.integral_error || "n/a") + '</p>';
  const factorHtml = data.factored
    ? '<code>' + esc(data.factored) + '</code>'
    : '<p class="err">' + esc(data.factor_error || "n/a") + '</p>';
  const html = `
    <div class="card">
      <h2>Expression</h2>
      <div class="mathrow" data-latex="${esc(data.input_latex)}"></div>
      <p class="sub">variable: <code>${esc(data.var)}</code> &middot; simplified: <code>${esc(data.simplified)}</code></p>
    </div>
    <div class="grid2">
      <div class="card">
        <h2>Derivative</h2>
        <div class="mathrow" data-latex="${esc(data.derivative_latex)}"></div>
        <div class="step-player">
          <ol class="steps-list"></ol>
          <div class="step-controls">
            <button class="step-prev">&larr; prev</button>
            <button class="step-next">next &rarr;</button>
            <span class="steps-counter"></span>
          </div>
        </div>
      </div>
      <div class="card">
        <h2>Integral</h2>
        ${integralHtml}
        <h2 style="margin-top:1.25rem">Factored</h2>
        ${factorHtml}
      </div>
    </div>
    <div class="card">
      <h2>Plot: f(x) and f&prime;(x)</h2>
      <div class="plot-svg"></div>
      <div class="legend">
        <span><span class="dot f"></span>f(x) = ${esc(data.input)}</span>
        <span><span class="dot fp"></span>f&prime;(x) = ${esc(data.derivative)}</span>
      </div>
    </div>`;
  const wrap = document.createElement("div");
  wrap.innerHTML = html;
  wrap.querySelectorAll(".mathrow").forEach(el => el.appendChild(renderLatex(el.dataset.latex)));
  const stepPlayer = wrap.querySelector(".step-player");
  if (stepPlayer) initStepPlayer(stepPlayer, data.diff_steps || []);
  const plotDiv = wrap.querySelector(".plot-svg");
  if (plotDiv) drawPlot(plotDiv, data.plot_f || [], data.plot_fprime || []);
  return wrap;  // a live DOM node, not a string — innerHTML would drop the
                // event listeners initStepPlayer() just attached above.
}
"""


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # keep test/demo output quiet

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            page = (_PLAYGROUND_PAGE
                    .replace("__CSS__", _CSS)
                    .replace("__LATEX_JS__", _LATEX_JS)
                    .replace("__PLAYER_JS__", _PLAYER_JS)
                    .replace("__PLOT_JS__", _PLOT_JS)
                    .replace("__RENDER_CARD__", "renderCard"))
            page = page.replace("</script>\n</body>",
                                 _render_card_js_function() + "</script>\n</body>", 1)
            self._send(200, "text/html", page.encode())
            return
        if parsed.path == "/api/analyze":
            qs = parse_qs(parsed.query)
            expr_s = (qs.get("expr") or [""])[0]
            var_s = (qs.get("var") or [None])[0]
            try:
                data = analyze(expr_s, var_s)
            except AxiomError as ex:
                data = {"error": str(ex)}
            except Exception as ex:  # never leak a raw traceback to the browser
                data = {"error": f"internal error: {ex}"}
            self._send(200, "application/json", json.dumps(data).encode())
            return
        self._send(404, "text/plain", b"not found")

    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run_playground_server(port=8765):
    server = HTTPServer(("127.0.0.1", port), _Handler)
    print(f"Axiom playground: http://127.0.0.1:{port}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
