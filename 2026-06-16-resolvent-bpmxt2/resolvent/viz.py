"""Self-contained HTML visualizer for the CDCL solver.

Runs the solver while recording every conflict's implication-graph data, then
emits a single dependency-free HTML file: an interactive implication graph
(decision nodes, propagated literals, the conflict node, and the 1-UIP cut that
becomes the learned clause), a decision-trail timeline, the list of learned
clauses, and live solver statistics. No Graphviz, no JS libraries — the layered
layout and SVG rendering are hand-rolled.
"""
from __future__ import annotations

import html
import json
from typing import Dict, List, Optional

from .cnf import CNF
from .solver import Solver


def _build_conflict_payload(rec, name_of) -> dict:
    """Turn a ConflictRecord into a layout-ready node/edge graph."""
    assignment = rec.assignment          # var -> (value, level, reason_lits|None)
    trail = rec.trail
    pos = {abs(l): i for i, l in enumerate(trail)}
    learned_vars = {abs(l) for l in rec.learned_clause}

    nodes = []
    for lit in trail:
        v = abs(lit)
        value, level, reason = assignment[v]
        nodes.append({
            "id": v,
            "label": name_of(v if value else -v),
            "lit": v if value else -v,
            "level": level,
            "order": pos[v],
            "decision": reason is None,
            "learned": v in learned_vars,
        })

    edges = []
    for lit in trail:
        v = abs(lit)
        _, _, reason = assignment[v]
        if reason is None:
            continue
        for q in reason:
            if abs(q) == v:
                continue
            edges.append({"src": abs(q), "dst": v, "kind": "imp"})

    # conflict node kappa
    for q in rec.conflict_clause:
        edges.append({"src": abs(q), "dst": "kappa", "kind": "confl"})

    return {
        "nodes": nodes,
        "edges": edges,
        "conflict_clause": [name_of(l) for l in rec.conflict_clause],
        "learned_clause": [name_of(l) for l in rec.learned_clause],
        "backjump_level": rec.backjump_level,
        "decision_level": rec.decision_level,
        "num_assigned": len(trail),
    }


def render_report(cnf: CNF, title: str = "Resolvent",
                  max_conflicts: int = 24,
                  names: Optional[Dict[int, str]] = None) -> str:
    names = names or {}

    def name_of(lit: int) -> str:
        v = abs(lit)
        base = names.get(v, f"x{v}")
        return ("¬" if lit < 0 else "") + base

    # Solve with restarts/reduce disabled so the implication graphs are clean
    # and reason indices are stable while we capture records.
    s = Solver(cnf, record_conflicts=True, restarts=False, reduce_db=False)
    result = s.solve(max_conflicts=max_conflicts + 4)
    records = s.conflict_records[:max_conflicts]
    conflicts = [_build_conflict_payload(r, name_of) for r in records]

    if result is True:
        verdict = "SATISFIABLE"
    elif result is False:
        verdict = "UNSATISFIABLE"
    else:
        verdict = f"stopped after {max_conflicts} conflicts (graph capture limit)"

    st = s.stats
    stats = {
        "decisions": st.decisions,
        "conflicts": st.conflicts,
        "propagations": st.propagations,
        "learned": st.learned,
        "max_level": st.max_decision_level,
        "nvars": cnf.nvars,
        "nclauses": len(cnf.clauses),
    }

    payload = json.dumps({
        "title": title,
        "verdict": verdict,
        "stats": stats,
        "conflicts": conflicts,
    })

    return _TEMPLATE.replace("/*__DATA__*/null", payload).replace(
        "__TITLE__", html.escape(title))


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Resolvent · __TITLE__</title>
<style>
  :root{
    --bg:#0c0f16; --panel:#141925; --panel2:#1b2233; --ink:#e8edf7;
    --muted:#8a96b0; --line:#2a3346; --accent:#5bc0ff; --gold:#ffcf5b;
    --red:#ff6b81; --green:#4fd6a3; --blue:#6f8bff;
  }
  *{box-sizing:border-box}
  html,body{margin:0;height:100%}
  body{background:radial-gradient(1200px 700px at 70% -10%,#1a2236 0%,var(--bg) 60%);
    color:var(--ink);font:14px/1.5 ui-sans-serif,system-ui,Segoe UI,Roboto,Helvetica,Arial}
  header{padding:18px 24px;border-bottom:1px solid var(--line);
    display:flex;align-items:baseline;gap:16px;flex-wrap:wrap}
  header h1{font-size:18px;margin:0;letter-spacing:.3px}
  header h1 b{color:var(--accent)}
  .verdict{font-weight:700;padding:3px 10px;border-radius:999px;font-size:12px}
  .verdict.sat{background:rgba(79,214,163,.15);color:var(--green);border:1px solid rgba(79,214,163,.4)}
  .verdict.unsat{background:rgba(255,107,129,.15);color:var(--red);border:1px solid rgba(255,107,129,.4)}
  .verdict.other{background:rgba(255,207,91,.12);color:var(--gold);border:1px solid rgba(255,207,91,.35)}
  .sub{color:var(--muted);font-size:12px}
  main{display:grid;grid-template-columns:300px 1fr;gap:0;height:calc(100% - 64px)}
  aside{background:var(--panel);border-right:1px solid var(--line);padding:16px;overflow:auto}
  section.stage{position:relative;overflow:hidden}
  .card{background:var(--panel2);border:1px solid var(--line);border-radius:12px;
    padding:12px 14px;margin-bottom:14px}
  .card h3{margin:0 0 8px;font-size:12px;text-transform:uppercase;letter-spacing:.8px;color:var(--muted)}
  .stat{display:flex;justify-content:space-between;padding:2px 0;font-variant-numeric:tabular-nums}
  .stat b{color:var(--ink)}
  .controls{display:flex;align-items:center;gap:8px;margin-bottom:10px}
  button{background:var(--panel2);color:var(--ink);border:1px solid var(--line);
    border-radius:8px;padding:6px 12px;cursor:pointer;font:inherit}
  button:hover{border-color:var(--accent)}
  button:disabled{opacity:.4;cursor:default}
  select{background:var(--panel2);color:var(--ink);border:1px solid var(--line);
    border-radius:8px;padding:6px;font:inherit}
  .clause{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;
    background:#0e1422;border:1px solid var(--line);border-radius:8px;padding:8px;
    word-break:break-word}
  .lrn{color:var(--gold)}
  .legend{display:flex;flex-direction:column;gap:6px;font-size:12px;color:var(--muted)}
  .legend i{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:8px;vertical-align:-1px}
  svg{width:100%;height:100%;display:block;cursor:grab}
  svg.drag{cursor:grabbing}
  .node rect{rx:7;stroke-width:1.5}
  .node text{font-family:ui-monospace,Menlo,monospace;font-size:12px;fill:var(--ink);
    text-anchor:middle;dominant-baseline:central;pointer-events:none}
  .levelband text{fill:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:1px}
  .tooltip{position:absolute;pointer-events:none;background:#0a0e18;border:1px solid var(--line);
    border-radius:8px;padding:8px 10px;font-size:12px;max-width:260px;opacity:0;
    transition:opacity .1s;box-shadow:0 8px 30px rgba(0,0,0,.5);z-index:5}
  .hint{position:absolute;left:14px;bottom:12px;color:var(--muted);font-size:11px;
    background:rgba(10,14,24,.7);padding:6px 10px;border-radius:8px;border:1px solid var(--line)}
  .empty{display:flex;align-items:center;justify-content:center;height:100%;color:var(--muted)}
</style>
</head>
<body>
<header>
  <h1><b>Resolvent</b> · __TITLE__</h1>
  <span id="verdict"></span>
  <span class="sub" id="subline"></span>
</header>
<main>
  <aside>
    <div class="card">
      <h3>Solver statistics</h3>
      <div id="stats"></div>
    </div>
    <div class="card">
      <h3>Conflict</h3>
      <div class="controls">
        <button id="prev">‹</button>
        <select id="pick"></select>
        <button id="next">›</button>
      </div>
      <div class="sub" id="confmeta"></div>
    </div>
    <div class="card">
      <h3>Conflicting clause</h3>
      <div class="clause" id="confl"></div>
    </div>
    <div class="card">
      <h3>Learned clause (1-UIP)</h3>
      <div class="clause lrn" id="learned"></div>
      <div class="sub" id="bj" style="margin-top:8px"></div>
    </div>
    <div class="card">
      <h3>Legend</h3>
      <div class="legend">
        <span><i style="background:#6f8bff"></i>decision literal</span>
        <span><i style="background:#1b2233;border:1px solid #2a3346"></i>propagated literal</span>
        <span><i style="background:#ffcf5b"></i>in learned clause (UIP cut)</span>
        <span><i style="background:#ff6b81"></i>conflict κ</span>
      </div>
    </div>
  </aside>
  <section class="stage">
    <svg id="svg"></svg>
    <div class="tooltip" id="tip"></div>
    <div class="hint">drag to pan · scroll to zoom · hover a node</div>
  </section>
</main>
<script>
const DATA = /*__DATA__*/null;
const SVGNS="http://www.w3.org/2000/svg";
const svg=document.getElementById("svg");
const tip=document.getElementById("tip");
let idx=0, view={x:0,y:0,k:1};

function el(tag,attrs){const e=document.createElementNS(SVGNS,tag);
  for(const k in attrs)e.setAttribute(k,attrs[k]);return e;}

// ---- header / stats ----
(function init(){
  const v=document.getElementById("verdict");
  const cls = DATA.verdict.startsWith("SAT")?"sat":DATA.verdict.startsWith("UNSAT")?"unsat":"other";
  v.className="verdict "+cls; v.textContent=DATA.verdict;
  document.getElementById("subline").textContent =
    `${DATA.stats.nvars} vars · ${DATA.stats.nclauses} clauses · ${DATA.conflicts.length} conflict graphs captured`;
  const s=DATA.stats, S=document.getElementById("stats");
  const rows=[["decisions",s.decisions],["conflicts",s.conflicts],
    ["propagations",s.propagations],["learned clauses",s.learned],
    ["max decision level",s.max_level]];
  S.innerHTML=rows.map(r=>`<div class="stat"><span>${r[0]}</span><b>${r[1]}</b></div>`).join("");
  const pick=document.getElementById("pick");
  if(DATA.conflicts.length===0){
    svg.outerHTML='<div class="empty">No conflicts — the formula was solved without backtracking.</div>';
  }
  DATA.conflicts.forEach((c,i)=>{const o=document.createElement("option");
    o.value=i;o.textContent=`#${i+1} · level ${c.decision_level} → ${c.backjump_level}`;pick.appendChild(o);});
  pick.onchange=()=>{idx=+pick.value;render();};
  document.getElementById("prev").onclick=()=>{idx=Math.max(0,idx-1);pick.value=idx;render();};
  document.getElementById("next").onclick=()=>{idx=Math.min(DATA.conflicts.length-1,idx+1);pick.value=idx;render();};
})();

function fmtClause(arr){return arr.length?arr.join("  ∨  "):"⊥ (empty clause)";}

function layout(c){
  // columns by decision level; rows by trail order within a level
  const byLevel={};
  let maxLevel=0;
  c.nodes.forEach(n=>{(byLevel[n.level]=byLevel[n.level]||[]).push(n);maxLevel=Math.max(maxLevel,n.level);});
  const colW=190, rowH=64, padX=90, padY=70;
  const pos={};
  Object.keys(byLevel).forEach(L=>{
    byLevel[L].sort((a,b)=>a.order-b.order);
    byLevel[L].forEach((n,i)=>{pos[n.id]={x:padX+L*colW,y:padY+i*rowH,level:+L};});
  });
  // conflict node placed past the last column, vertically centered on its sources
  const confSources=c.edges.filter(e=>e.dst==="kappa").map(e=>e.src);
  let ky=padY, kx=padX+(maxLevel+1)*colW;
  if(confSources.length){
    const ys=confSources.map(s=>pos[s]?pos[s].y:padY);
    ky=ys.reduce((a,b)=>a+b,0)/ys.length;
    kx=padX+(maxLevel+1)*colW;
  }
  pos["kappa"]={x:kx,y:ky,level:maxLevel+1};
  return {pos,maxLevel,colW,rowH,padX,padY,
    width:kx+padX, height:padY+Math.max(...Object.values(byLevel).map(a=>a.length),1)*rowH+padY};
}

function render(){
  const c=DATA.conflicts[idx];
  if(!c)return;
  document.getElementById("confmeta").textContent=
    `decision level ${c.decision_level}, ${c.num_assigned} literals assigned`;
  document.getElementById("confl").textContent=fmtClause(c.conflict_clause);
  document.getElementById("learned").textContent=fmtClause(c.learned_clause);
  document.getElementById("bj").innerHTML=
    `backjump to level <b style="color:var(--ink)">${c.backjump_level}</b> · asserting literal <b style="color:var(--gold)">${c.learned_clause[0]||""}</b>`;

  const L=layout(c);
  while(svg.firstChild)svg.removeChild(svg.firstChild);
  const root=el("g",{}); svg.appendChild(root);
  window._root=root;

  // level bands
  for(let lv=0;lv<=L.maxLevel;lv++){
    const g=el("g",{class:"levelband"});
    const x=L.padX+lv*L.colW;
    g.appendChild(el("line",{x1:x,y1:30,x2:x,y2:L.height-30,stroke:"#1d2738","stroke-dasharray":"3 6"}));
    const t=el("text",{x:x,y:24}); t.textContent=lv===0?"level 0 (facts)":"level "+lv;
    t.setAttribute("text-anchor","middle"); g.appendChild(t);
    root.appendChild(g);
  }

  // edges
  const defs=el("defs",{});
  defs.innerHTML=`<marker id="ah" markerWidth="9" markerHeight="9" refX="8" refY="3" orient="auto">
    <path d="M0,0 L8,3 L0,6 Z" fill="#3b465f"/></marker>
    <marker id="ahr" markerWidth="9" markerHeight="9" refX="8" refY="3" orient="auto">
    <path d="M0,0 L8,3 L0,6 Z" fill="#ff6b81"/></marker>`;
  root.appendChild(defs);
  c.edges.forEach(e=>{
    const a=L.pos[e.src], b=L.pos[e.dst];
    if(!a||!b)return;
    const x1=a.x+34,y1=a.y, x2=b.x-34,y2=b.y;
    const mx=(x1+x2)/2;
    const red=e.kind==="confl";
    root.appendChild(el("path",{d:`M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`,
      fill:"none",stroke:red?"#ff6b81":"#3b465f","stroke-width":red?1.6:1.2,
      "marker-end":red?"url(#ahr)":"url(#ah)","opacity":red?.9:.7}));
  });

  // nodes
  c.nodes.forEach(n=>{
    const p=L.pos[n.id];
    const g=el("g",{class:"node"});
    g.setAttribute("transform",`translate(${p.x},${p.y})`);
    let fill="#1b2233",stroke="#2a3346";
    if(n.decision){fill="#26305a";stroke="#6f8bff";}
    if(n.learned){fill="#3a3214";stroke="#ffcf5b";}
    const r=el("rect",{x:-34,y:-16,width:68,height:32,rx:8,fill:fill,stroke:stroke,"stroke-width":n.learned?2:1.5});
    const t=el("text",{}); t.textContent=n.label;
    g.appendChild(r);g.appendChild(t);
    g.addEventListener("mousemove",ev=>showTip(ev,n,c));
    g.addEventListener("mouseleave",()=>{tip.style.opacity=0;});
    root.appendChild(g);
  });
  // conflict node
  const kp=L.pos["kappa"];
  const kg=el("g",{class:"node"});
  kg.setAttribute("transform",`translate(${kp.x},${kp.y})`);
  kg.appendChild(el("circle",{r:20,fill:"#3a1622",stroke:"#ff6b81","stroke-width":2}));
  const kt=el("text",{}); kt.textContent="κ"; kt.setAttribute("font-size","16"); kg.appendChild(kt);
  root.appendChild(kg);

  fit(L);
  applyView();
}

function showTip(ev,n,c){
  const reasonEdges=c.edges.filter(e=>e.dst===n.id);
  const reason = n.decision ? "decision" :
    "implied by clause ("+reasonEdges.map(e=>{
      const src=c.nodes.find(x=>x.id===e.src); return src?(src.lit<0?"":"¬")+ "x"+e.src:"?";
    }).concat([n.label]).join(" ∨ ")+")";
  tip.innerHTML=`<b>${n.label}</b> &nbsp;<span style="color:var(--muted)">level ${n.level}</span><br>${reason}`;
  const rect=svg.getBoundingClientRect();
  tip.style.left=(ev.clientX-rect.left+14)+"px";
  tip.style.top=(ev.clientY-rect.top+14)+"px";
  tip.style.opacity=1;
}

function fit(L){
  const rect=svg.getBoundingClientRect();
  const k=Math.min(1,(rect.width-40)/L.width,(rect.height-40)/L.height);
  view.k=k>0?k:1;
  view.x=(rect.width-L.width*view.k)/2;
  view.y=20;
}
function applyView(){
  if(window._root)window._root.setAttribute("transform",
    `translate(${view.x},${view.y}) scale(${view.k})`);
}

// pan + zoom
let dragging=false,last=null;
svg.addEventListener("mousedown",e=>{dragging=true;last=[e.clientX,e.clientY];svg.classList.add("drag");});
window.addEventListener("mouseup",()=>{dragging=false;svg.classList.remove("drag");});
window.addEventListener("mousemove",e=>{if(!dragging)return;
  view.x+=e.clientX-last[0];view.y+=e.clientY-last[1];last=[e.clientX,e.clientY];applyView();});
svg.addEventListener("wheel",e=>{e.preventDefault();
  const rect=svg.getBoundingClientRect();const mx=e.clientX-rect.left,my=e.clientY-rect.top;
  const f=e.deltaY<0?1.1:1/1.1;
  view.x=mx-(mx-view.x)*f;view.y=my-(my-view.y)*f;view.k*=f;applyView();},{passive:false});

if(DATA.conflicts.length)render();
</script>
</body>
</html>
"""
