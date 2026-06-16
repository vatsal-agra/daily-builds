"""Render the implication graph captured at a conflict into a self-contained,
dependency-free HTML page (inline SVG + a little JS for pan/zoom/hover). No
Graphviz, no CDN — a custom layered layout grouped by decision level."""
from __future__ import annotations

import html
import json
from typing import Dict, List, Tuple


def _lit_label(lit: int) -> str:
    return f"x{abs(lit)}=1" if lit > 0 else f"x{abs(lit)}=0"


def build_graph(cg: dict) -> Tuple[set, List[Tuple[int, object, list]]]:
    """From a captured conflict graph, return (relevant_literals, edges) where each
    edge is (src_lit, dst_lit_or_'K', clause). Walks backward from the conflict."""
    nodes: Dict[int, dict] = {int(k): v for k, v in cg["nodes"].items()}
    edges: List[Tuple[int, object, list]] = []
    relevant: set = set()
    stack: List[int] = []
    for q in cg["conflict_clause"]:
        src = -q
        edges.append((src, "K", cg["conflict_clause"]))
        if src not in relevant:
            relevant.add(src)
            stack.append(src)
    while stack:
        lit = stack.pop()
        info = nodes.get(lit)
        if info is None or info["decision"] or info["reason"] is None:
            continue
        for q in info["reason"]:
            if q == lit:
                continue
            src = -q
            edges.append((src, lit, info["reason"]))
            if src not in relevant:
                relevant.add(src)
                stack.append(src)
    return relevant, edges


def render_html(cg: dict, title: str = "Resolvent — implication graph") -> str:
    nodes: Dict[int, dict] = {int(k): v for k, v in cg["nodes"].items()}
    relevant, edges = build_graph(cg)
    learnt = cg["learnt"]
    uip_lit = learnt[0] if learnt else None
    uip_var = abs(uip_lit) if uip_lit is not None else None
    learnt_vars = {abs(l) for l in learnt}

    # layout: x by decision level, y stacked by trail order within level
    by_level: Dict[int, List[int]] = {}
    trail_index = {lit: i for i, lit in enumerate(cg["trail"])}
    for lit in relevant:
        info = nodes.get(lit)
        lvl = info["level"] if info else 0
        by_level.setdefault(lvl, []).append(lit)
    for lvl in by_level:
        by_level[lvl].sort(key=lambda l: trail_index.get(l, 0))

    levels = sorted(by_level)
    col_w = 200
    row_h = 78
    pad = 60
    pos: Dict[object, Tuple[float, float]] = {}
    max_rows = max((len(v) for v in by_level.values()), default=1)
    for ci, lvl in enumerate(levels):
        col = by_level[lvl]
        for ri, lit in enumerate(col):
            x = pad + ci * col_w
            y = pad + ri * row_h + (max_rows - len(col)) * row_h / 2
            pos[lit] = (x, y)
    # conflict node at far right
    kx = pad + len(levels) * col_w
    ky = pad + (max_rows - 1) * row_h / 2
    pos["K"] = (kx, ky)

    width = kx + 160
    height = pad * 2 + max_rows * row_h

    svg_edges = []
    for (src, dst, clause) in edges:
        if src not in pos or dst not in pos:
            continue
        x1, y1 = pos[src]
        x2, y2 = pos[dst]
        x1 += 46
        x2 -= 46
        cls = "edge cut" if (abs(src) in learnt_vars) else "edge"
        cl_txt = " ".join(str(l) for l in clause)
        svg_edges.append(
            f'<g class="{cls}" data-from="{src}"><path d="M{x1:.0f},{y1:.0f} '
            f'C{(x1+x2)/2:.0f},{y1:.0f} {(x1+x2)/2:.0f},{y2:.0f} {x2:.0f},{y2:.0f}" '
            f'marker-end="url(#arrow)"><title>clause: ({cl_txt})</title></path></g>'
        )

    svg_nodes = []
    for lit, (x, y) in pos.items():
        if lit == "K":
            svg_nodes.append(
                f'<g class="node conflict"><ellipse cx="{x:.0f}" cy="{y:.0f}" rx="40" ry="26"/>'
                f'<text x="{x:.0f}" y="{y+5:.0f}">⊥ conflict</text></g>'
            )
            continue
        info = nodes.get(lit, {})
        classes = ["node"]
        if info.get("decision"):
            classes.append("decision")
        if abs(lit) == uip_var:
            classes.append("uip")
        if abs(lit) in learnt_vars:
            classes.append("incut")
        sub = f'@{info.get("level", 0)}'
        kind = "decision" if info.get("decision") else "implied"
        svg_nodes.append(
            f'<g class="{" ".join(classes)}" data-lit="{lit}">'
            f'<ellipse cx="{x:.0f}" cy="{y:.0f}" rx="44" ry="24"/>'
            f'<text class="lbl" x="{x:.0f}" y="{y-2:.0f}">{_lit_label(lit)}</text>'
            f'<text class="sub" x="{x:.0f}" y="{y+13:.0f}">{kind} {sub}</text></g>'
        )

    level_labels = []
    for ci, lvl in enumerate(levels):
        x = pad + ci * col_w
        level_labels.append(
            f'<text class="levellabel" x="{x:.0f}" y="26">decision level {lvl}</text>'
        )

    learnt_txt = "  ∨  ".join(_lit_label(l) for l in learnt) if learnt else "(empty)"
    stats = (
        f"conflict at decision level {cg['decision_level']} · "
        f"{len(relevant)} nodes in the conflict cone · "
        f"learned a {len(learnt)}-literal clause"
    )

    return _PAGE.format(
        title=html.escape(title),
        width=width,
        height=height,
        edges="\n".join(svg_edges),
        nodes="\n".join(svg_nodes),
        levels="\n".join(level_labels),
        learnt=html.escape(learnt_txt),
        stats=html.escape(stats),
        data=json.dumps({"learnt": learnt, "uip": uip_lit}),
    )


_PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{
    --bg:#0d1117; --panel:#161b22; --ink:#e6edf3; --dim:#8b949e;
    --edge:#3d4451; --cut:#f0883e; --decision:#58a6ff; --implied:#2ea043;
    --uip:#bc8cff; --conflict:#f85149; --line:#21262d;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
    font:14px/1.5 ui-sans-serif,-apple-system,Segoe UI,Roboto,Helvetica,Arial; }}
  header {{ padding:18px 24px; border-bottom:1px solid var(--line);
    display:flex; align-items:baseline; gap:16px; flex-wrap:wrap; }}
  header h1 {{ font-size:18px; margin:0; letter-spacing:.3px; }}
  header .stats {{ color:var(--dim); }}
  .wrap {{ display:flex; height:calc(100vh - 63px); }}
  .stage {{ flex:1; overflow:hidden; position:relative; cursor:grab; }}
  .stage.grabbing {{ cursor:grabbing; }}
  aside {{ width:300px; border-left:1px solid var(--line); background:var(--panel);
    padding:20px; overflow:auto; }}
  aside h2 {{ font-size:13px; text-transform:uppercase; letter-spacing:.08em;
    color:var(--dim); margin:0 0 8px; }}
  .learnt {{ background:#0d1117; border:1px solid var(--cut); border-radius:8px;
    padding:12px; font-family:ui-monospace,Menlo,Consolas,monospace; color:var(--cut);
    word-break:break-word; margin-bottom:22px; }}
  .legend div {{ display:flex; align-items:center; gap:10px; margin:7px 0; }}
  .swatch {{ width:26px; height:18px; border-radius:5px; border:2px solid transparent; }}
  .note {{ color:var(--dim); margin-top:18px; font-size:13px; }}
  svg {{ display:block; }}
  .edge path {{ fill:none; stroke:var(--edge); stroke-width:1.6; opacity:.8; }}
  .edge.cut path {{ stroke:var(--cut); stroke-width:2.2; opacity:.95; }}
  .node ellipse {{ fill:#1c2330; stroke:var(--implied); stroke-width:2.4; }}
  .node.decision ellipse {{ stroke:var(--decision); fill:#10243d; }}
  .node.uip ellipse {{ stroke:var(--uip); stroke-width:3.4; }}
  .node.incut ellipse {{ filter:drop-shadow(0 0 6px rgba(240,136,62,.55)); }}
  .node.conflict ellipse {{ fill:#2d1416; stroke:var(--conflict); stroke-width:3; }}
  .node text {{ text-anchor:middle; fill:var(--ink); font-weight:600; pointer-events:none; }}
  .node .sub {{ font-size:10.5px; font-weight:400; fill:var(--dim); }}
  .node.conflict text {{ fill:var(--conflict); font-weight:700; }}
  .levellabel {{ fill:var(--dim); font-size:12px; text-anchor:start; }}
  .node.hl ellipse {{ filter:drop-shadow(0 0 8px rgba(88,166,255,.8)); }}
  .edge.hl path {{ stroke:#fff !important; opacity:1; }}
</style></head>
<body>
<header>
  <h1>Resolvent · implication graph</h1>
  <span class="stats">{stats}</span>
</header>
<div class="wrap">
  <div class="stage" id="stage">
    <svg id="svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
      <defs>
        <marker id="arrow" markerWidth="9" markerHeight="9" refX="7" refY="3"
          orient="auto" markerUnits="userSpaceOnUse">
          <path d="M0,0 L7,3 L0,6 Z" fill="var(--edge)"/>
        </marker>
      </defs>
      <g id="scene">
        {levels}
        {edges}
        {nodes}
      </g>
    </svg>
  </div>
  <aside>
    <h2>Learned clause (1-UIP)</h2>
    <div class="learnt">{learnt}</div>
    <h2>Legend</h2>
    <div class="legend">
      <div><span class="swatch" style="border-color:var(--decision)"></span>decision</div>
      <div><span class="swatch" style="border-color:var(--implied)"></span>implied (propagated)</div>
      <div><span class="swatch" style="border-color:var(--uip)"></span>1-UIP (asserting var)</div>
      <div><span class="swatch" style="border-color:var(--conflict)"></span>conflict ⊥</div>
      <div><span class="swatch" style="border-color:var(--cut)"></span>edge on the cut</div>
    </div>
    <p class="note">Each node is a literal forced true on the trail. An arrow
      <b>a → b</b> means the clause labelling it (hover an edge) forced <b>b</b>
      once <b>a</b> (and its siblings) were set. The orange cut is the frontier of
      the 1-UIP learned clause — the new constraint that forbids this conflict.</p>
    <p class="note">Drag to pan · scroll to zoom · hover a node to trace it.</p>
  </aside>
</div>
<script>
const data = {data};
const svg = document.getElementById('svg');
const scene = document.getElementById('scene');
const stage = document.getElementById('stage');
let tx=0, ty=0, scale=1;
function apply() {{ scene.setAttribute('transform', `translate(${{tx}},${{ty}}) scale(${{scale}})`); }}
let dragging=false, sx=0, sy=0;
stage.addEventListener('mousedown', e => {{ dragging=true; sx=e.clientX-tx; sy=e.clientY-ty; stage.classList.add('grabbing'); }});
window.addEventListener('mouseup', () => {{ dragging=false; stage.classList.remove('grabbing'); }});
window.addEventListener('mousemove', e => {{ if(dragging){{ tx=e.clientX-sx; ty=e.clientY-sy; apply(); }} }});
stage.addEventListener('wheel', e => {{ e.preventDefault();
  const f = e.deltaY<0 ? 1.1 : 0.9; scale=Math.max(0.2,Math.min(4,scale*f)); apply(); }}, {{passive:false}});
document.querySelectorAll('.node[data-lit]').forEach(n => {{
  n.addEventListener('mouseenter', () => {{
    const lit = n.getAttribute('data-lit');
    n.classList.add('hl');
    document.querySelectorAll(`.edge[data-from="${{lit}}"]`).forEach(e=>e.classList.add('hl'));
  }});
  n.addEventListener('mouseleave', () => {{
    n.classList.remove('hl');
    document.querySelectorAll('.edge.hl').forEach(e=>e.classList.remove('hl'));
  }});
}});
</script>
</body></html>
"""
