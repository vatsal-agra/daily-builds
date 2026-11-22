"""Self-contained HTML gallery of the catalog: drawings + invariants, light/dark aware."""
from html import escape
from . import catalog, poly as P
from .alexander import colorings
from .draw import render_svg
from .identify import table
from .jones import fmt_jones

CSS = """
:root{--bg:#fbf7ef;--card:#fffdf8;--ink:#2a2623;--muted:#8a7f72;--line:#e6dccb;--accent:#c8452c;--chip:#f1e8d6}
@media (prefers-color-scheme:dark){:root{--bg:#16181d;--card:#1d2027;--ink:#ece7dd;--muted:#8d93a0;--line:#2b2f38;--accent:#ff7a59;--chip:#272b34}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 Georgia,'Times New Roman',serif}
header{padding:48px 24px 8px;max-width:1100px;margin:0 auto}
h1{font-size:2.4rem;margin:0;letter-spacing:.04em}
header p{color:var(--muted);max-width:60ch;margin:.4rem 0 1.2rem}
.bar{max-width:1100px;margin:0 auto;padding:0 24px 16px;display:flex;gap:12px;flex-wrap:wrap;align-items:center}
input{font:inherit;padding:8px 12px;border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:8px;min-width:220px}
.count{color:var(--muted);font-size:.9rem}
main{max-width:1100px;margin:0 auto;padding:0 24px 64px;display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:20px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px;display:flex;flex-direction:column;gap:8px}
.card h2{margin:0;font-size:1.3rem;display:flex;justify-content:space-between;align-items:baseline;gap:8px}
.chip{font:600 .7rem/1 system-ui,sans-serif;background:var(--chip);color:var(--muted);padding:4px 8px;border-radius:99px;letter-spacing:.04em;text-transform:uppercase;white-space:nowrap}
.card svg{width:100%;height:auto;max-height:340px;border-radius:8px}
.dk{display:none}
@media (prefers-color-scheme:dark){.lt{display:none}.dk{display:block}}
dl{margin:0;display:grid;grid-template-columns:auto 1fr;gap:2px 12px;font-size:.88rem}
dt{color:var(--muted)} dd{margin:0;overflow-wrap:anywhere;font-family:ui-monospace,Menlo,monospace;font-size:.82rem}
.none{padding:48px;text-align:center;color:var(--muted);grid-column:1/-1}
"""

JS = """
const q=document.getElementById('q'),cards=[...document.querySelectorAll('.card')],c=document.getElementById('count');
function f(){const s=q.value.trim().toLowerCase();let n=0;cards.forEach(k=>{const m=!s||k.dataset.s.includes(s);k.style.display=m?'':'none';n+=m});
c.textContent=n+' of '+cards.length;document.getElementById('none').style.display=n?'none':'block'}
q.addEventListener('input',f);f();
"""


def build_gallery():
    cards = []
    for name, nx, inv in table():
        L = catalog.get(name)
        if not L.braid or not L.braid[1]:
            continue
        A = inv["alexander"]
        kind = "knot" if L.is_knot() else f"{L.num_components}-comp. link"
        cols = [f"p={p}: " + (str(colorings(L, p)["nontrivial"]) if colorings(L, p)["colorable"] else "no")
                for p in (3, 5, 7)]
        chiral = "chiral" if inv["variants"] and L.is_knot() and inv.get("chiral") else ""
        svgs = "".join(f'<div class="{c}">{render_svg(L, theme=t, bg=b)}</div>'
                       for c, t, b in (("lt", "light", "#fffdf8"), ("dk", "dark", "#1d2027")))
        search = f"{name} {kind} det {inv['determinant']}".lower()
        cards.append(
            f'<article class="card" data-s="{escape(search)}"><h2>{escape(name)}'
            f'<span class="chip">{escape(kind)}</span></h2>{svgs}<dl>'
            f'<dt>braid crossings</dt><dd>{L.n}</dd>'
            f'<dt>determinant</dt><dd>{inv["determinant"]}</dd>'
            f'<dt>Jones</dt><dd>{escape(fmt_jones(inv["jones"]))}</dd>'
            f'<dt>Alexander</dt><dd>{escape(P.fmt(A) if A else "0")}</dd>'
            f'<dt>Fox colorings</dt><dd>{escape("; ".join(cols))}</dd></dl></article>')
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>Tangle Gallery</title>'
            f'<style>{CSS}</style></head><body><header><h1>Tangle</h1>'
            f'<p>Every knot and link in the catalog, drawn from its braid word, with invariants computed live by '
            f'this library (not looked up). Handedness follows the braid word found by search; '
            f'names match up to mirror image.</p></header>'
            f'<div class="bar"><input id="q" placeholder="filter: 5_2, link, det 13 ..." aria-label="filter">'
            f'<span class="count" id="count"></span></div>'
            f'<main>{"".join(cards)}<div class="none" id="none" style="display:none">No match.</div></main>'
            f'<script>{JS}</script></body></html>')
