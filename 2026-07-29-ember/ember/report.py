"""Self-contained HTML report: source / AST / real objdump disassembly
side by side for each example program, plus a genuine measured
interpreter-vs-JIT benchmark. No client-side compiler logic -- every
number and every listing is computed in Python ahead of time and baked
into the page as static HTML; the only JavaScript is expand/collapse UI
chrome.
"""

import html as html_mod

from .ast_print import format_fn
from .disasm import format_listing, objdump_available
from .bench import benchmark

_STYLE = """
<style>
  :root { color-scheme: light; }
  .viz-root {
    --surface-1:      #fcfcfb;
    --page-plane:     #f9f9f7;
    --text-primary:   #0b0b0b;
    --text-secondary: #52514e;
    --text-muted:     #898781;
    --gridline:       #e1e0d9;
    --border:         rgba(11,11,11,0.10);
    --series-1:       #2a78d6; /* JIT */
    --series-2:       #eb6834; /* interpreter */
    --code-bg:        #f4f3ef;
  }
  @media (prefers-color-scheme: dark) {
    :root:where(:not([data-theme="light"])) .viz-root {
      color-scheme: dark;
      --surface-1:      #1a1a19;
      --page-plane:     #0d0d0d;
      --text-primary:   #ffffff;
      --text-secondary: #c3c2b7;
      --text-muted:     #898781;
      --gridline:       #2c2c2a;
      --border:         rgba(255,255,255,0.10);
      --series-1:       #3987e5;
      --series-2:       #d95926;
      --code-bg:        #212120;
    }
  }
  :root[data-theme="dark"] .viz-root {
    color-scheme: dark;
    --surface-1:      #1a1a19;
    --page-plane:     #0d0d0d;
    --text-primary:   #ffffff;
    --text-secondary: #c3c2b7;
    --text-muted:     #898781;
    --gridline:       #2c2c2a;
    --border:         rgba(255,255,255,0.10);
    --series-1:       #3987e5;
    --series-2:       #d95926;
    --code-bg:        #212120;
  }
  .viz-root {
    background: var(--page-plane);
    color: var(--text-primary);
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    padding: 2rem clamp(1rem, 4vw, 3rem) 4rem;
    max-width: 980px;
    margin: 0 auto;
  }
  .viz-root h1 { font-size: 1.6rem; margin: 0 0 0.25rem; }
  .viz-root .subtitle { color: var(--text-secondary); margin: 0 0 2rem; }
  .card {
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 1.25rem 1.5rem;
    margin-bottom: 1.5rem;
  }
  .card h2 { font-size: 1.1rem; margin: 0 0 0.75rem; }
  .card h3 { font-size: 0.95rem; margin: 1rem 0 0.4rem; color: var(--text-secondary); }
  pre {
    background: var(--code-bg);
    border-radius: 8px;
    padding: 0.85rem 1rem;
    overflow-x: auto;
    font-size: 0.82rem;
    line-height: 1.5;
    margin: 0;
  }
  details > summary { cursor: pointer; color: var(--text-secondary); font-size: 0.85rem; margin-top: 0.5rem; }
  .stat-row { display: flex; gap: 1rem; flex-wrap: wrap; margin: 0.5rem 0 1rem; }
  .stat-tile {
    flex: 1 1 160px;
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 0.75rem 1rem;
  }
  .stat-tile .label { font-size: 0.78rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.03em; }
  .stat-tile .value { font-size: 1.5rem; font-weight: 600; margin-top: 0.15rem; }
  .stat-tile.jit .value { color: var(--series-1); }
  .stat-tile.interp .value { color: var(--series-2); }
  .hero { font-size: 2.4rem; font-weight: 700; margin: 0.25rem 0; }
  .hero-sub { color: var(--text-secondary); font-size: 0.95rem; }
  .bars { margin-top: 0.75rem; }
  .bar-row { display: grid; grid-template-columns: 90px 1fr 90px; align-items: center; gap: 0.6rem; margin: 0.35rem 0; }
  .bar-row .name { font-size: 0.8rem; color: var(--text-secondary); text-align: right; }
  .bar-row .val { font-size: 0.8rem; color: var(--text-muted); font-variant-numeric: tabular-nums; }
  .bar-track { background: var(--gridline); border-radius: 4px; height: 14px; overflow: hidden; }
  .bar-fill { height: 100%; border-radius: 4px; }
  .bar-fill.jit { background: var(--series-1); }
  .bar-fill.interp { background: var(--series-2); }
  .legend { display: flex; gap: 1.25rem; font-size: 0.8rem; color: var(--text-secondary); margin-top: 0.5rem; }
  .legend .swatch { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 0.4rem; vertical-align: middle; }
  .oracle-badge { display: inline-block; font-size: 0.72rem; padding: 0.15rem 0.5rem; border-radius: 999px; border: 1px solid var(--border); color: var(--text-secondary); margin-left: 0.4rem; }
</style>
"""


def _esc(s):
    return html_mod.escape(s)


def _bench_section(program, fn_name, args):
    stats = benchmark(program, fn_name, args)
    i, j = stats["interpreter"], stats["jit"]
    i_us, j_us = i["per_call"] * 1e6, j["per_call"] * 1e6
    max_us = max(i_us, j_us)
    i_pct = 100.0 * i_us / max_us
    j_pct = 100.0 * j_us / max_us
    call_desc = f"{fn_name}({', '.join(map(str, args))}) = {stats['result']}"
    return f"""
    <div class="card">
      <h2>Real, measured benchmark</h2>
      <p class="hero-sub">{_esc(call_desc)} &mdash; {i['iters']:,} interpreter calls,
         {j['iters']:,} JIT calls, timed with <code>time.perf_counter()</code>. Not a projected number.</p>
      <div class="hero">{stats['speedup']:.1f}&times; faster</div>
      <div class="hero-sub">native machine code vs. the tree-walking interpreter, same function, same input</div>
      <div class="bars">
        <div class="bar-row">
          <span class="name">JIT</span>
          <div class="bar-track"><div class="bar-fill jit" style="width:{j_pct:.1f}%"></div></div>
          <span class="val">{j_us:.2f} &micro;s</span>
        </div>
        <div class="bar-row">
          <span class="name">Interpreter</span>
          <div class="bar-track"><div class="bar-fill interp" style="width:{i_pct:.1f}%"></div></div>
          <span class="val">{i_us:.2f} &micro;s</span>
        </div>
      </div>
      <div class="legend">
        <span><span class="swatch" style="background:var(--series-1)"></span>JIT (native x86-64)</span>
        <span><span class="swatch" style="background:var(--series-2)"></span>Interpreter (tree-walk)</span>
      </div>
    </div>
    """


def _example_section(label, source, program, disasm_ok):
    fn_blocks = []
    for fn in program.functions:
        ast_txt = format_fn(fn)
        fn_blocks.append(f"""
        <h3>fn {_esc(fn.name)}</h3>
        <details>
          <summary>AST</summary>
          <pre>{_esc(ast_txt)}</pre>
        </details>
        """)
    disasm_html = ""
    if disasm_ok:
        from .codegen_x64 import compile_program
        compiled = compile_program(program)
        listing = format_listing(compiled.code_bytes)
        disasm_html = f"""
        <details>
          <summary>x86-64 disassembly (via real <code>objdump</code>) <span class="oracle-badge">independent oracle</span></summary>
          <pre>{_esc(listing)}</pre>
        </details>
        """
    return f"""
    <div class="card">
      <h2>{_esc(label)}</h2>
      <pre>{_esc(source)}</pre>
      {''.join(fn_blocks)}
      {disasm_html}
    </div>
    """


def generate_report(main_path, program, bench_fn=None, bench_args=None, extra_examples=None):
    """extra_examples: optional list of (label, source, program) shown
    alongside the primary file -- used by demo.py to build one report
    covering every example program."""
    disasm_ok = objdump_available()
    sections = []
    with open(main_path) as f:
        main_source = f.read()
    sections.append(_example_section(main_path, main_source, program, disasm_ok))
    for label, source, prog in (extra_examples or []):
        sections.append(_example_section(label, source, prog, disasm_ok))

    bench_html = ""
    if bench_fn:
        bench_html = _bench_section(program, bench_fn, bench_args or [])

    body = f"""
    <div class="viz-root">
      <h1>Ember</h1>
      <p class="subtitle">A from-scratch JIT compiler: source &rarr; AST &rarr; real x86-64 machine code,
      executed on the CPU via <code>mmap(PROT_EXEC)</code> + <code>ctypes</code>.</p>
      {bench_html}
      {''.join(sections)}
    </div>
    """
    return f"<!doctype html><html><head><meta charset='utf-8'><title>Ember report</title>{_STYLE}</head><body>{body}</body></html>"
