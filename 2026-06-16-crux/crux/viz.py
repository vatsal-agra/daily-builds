"""Generate a self-contained interactive HTML visualizer of CDCL conflict
analysis.

The page embeds the *real* conflict snapshots recorded by the solver (the trail,
each literal's reason clause, the conflicting clause, the 1-UIP and the learned
clause) and a small amount of JavaScript that:

  * reconstructs the **implication graph** for each conflict (the cone of
    antecedents that actually produced it),
  * lays it out left-to-right by decision level,
  * highlights the conflict node (κ), the 1-UIP, the conflict-side cut and the
    learned clause, and
  * lets you step through every conflict the solver hit.

No external libraries, no network — one file you can open in any browser.
"""

from __future__ import annotations

import json
from typing import Optional

from .cnf import CNF
from .solver import Solver


def build_visualizer(cnf: CNF, title: str = "Crux — CDCL conflict analysis",
                     subtitle: str = "", max_conflicts: int = 60) -> str:
    solver = Solver(cnf, record_conflicts=True, max_conflict_snaps=max_conflicts)
    result = solver.solve(max_conflicts=max(max_conflicts * 50, 5000))
    data = {
        "title": title,
        "subtitle": subtitle or _auto_subtitle(cnf, result),
        "nvars": cnf.nvars,
        "nclauses": cnf.nclauses,
        "status": result.status,
        "stats": result.stats.as_dict(),
        "snaps": solver.conflict_snaps,
    }
    payload = json.dumps(data, separators=(",", ":"))
    return _HTML_TEMPLATE.replace("/*__DATA__*/", payload)


def _auto_subtitle(cnf: CNF, result) -> str:
    return (f"{cnf.nvars} vars · {cnf.nclauses} clauses · result "
            f"{result.status} · {result.stats.conflicts} conflicts")


_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Crux — CDCL conflict analysis</title>
<style>
  :root{
    --bg:#0e1116; --panel:#161b22; --panel2:#1c232d; --ink:#e6edf3;
    --muted:#8b949e; --line:#30363d; --accent:#58a6ff; --gold:#f2cc60;
    --red:#ff6b6b; --green:#3fb950; --learn:#a371f7;
  }
  *{box-sizing:border-box}
  html,body{margin:0;height:100%}
  body{background:var(--bg);color:var(--ink);
    font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
  header{padding:18px 24px;border-bottom:1px solid var(--line);
    background:linear-gradient(180deg,#11161d,#0e1116)}
  header h1{margin:0;font-size:20px;letter-spacing:.2px}
  header .sub{color:var(--muted);margin-top:4px;font-size:13px}
  .wrap{display:flex;height:calc(100vh - 78px);min-height:480px}
  .left{flex:1 1 auto;position:relative;overflow:auto}
  .right{flex:0 0 360px;border-left:1px solid var(--line);
    background:var(--panel);overflow:auto;padding:18px}
  svg{display:block}
  .controls{position:sticky;top:0;z-index:5;display:flex;gap:10px;
    align-items:center;padding:10px 16px;background:rgba(14,17,22,.85);
    backdrop-filter:blur(6px);border-bottom:1px solid var(--line)}
  button{background:var(--panel2);color:var(--ink);border:1px solid var(--line);
    border-radius:7px;padding:6px 12px;cursor:pointer;font-size:13px}
  button:hover{border-color:var(--accent)}
  button:disabled{opacity:.4;cursor:not-allowed}
  input[type=range]{flex:1 1 auto;accent-color:var(--accent)}
  .pill{font-size:12px;color:var(--muted);white-space:nowrap}
  h2{font-size:13px;text-transform:uppercase;letter-spacing:.6px;
    color:var(--muted);margin:18px 0 8px}
  .clause{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:13px;
    background:var(--panel2);border:1px solid var(--line);border-radius:7px;
    padding:8px 10px;margin:6px 0;word-break:break-word}
  .lit{display:inline-block;padding:1px 6px;border-radius:5px;margin:1px;
    background:#23303f;border:1px solid #2d3b4d}
  .lit.uip{background:#4a3c12;border-color:var(--gold);color:var(--gold);font-weight:700}
  .lit.learn{background:#2c2050;border-color:var(--learn);color:#cfb6ff}
  .kv{display:flex;justify-content:space-between;padding:3px 0;
    border-bottom:1px dashed var(--line)}
  .kv span:first-child{color:var(--muted)}
  .legend{display:grid;grid-template-columns:auto 1fr;gap:6px 10px;
    align-items:center;font-size:12px;color:var(--muted);margin-top:8px}
  .swatch{width:16px;height:16px;border-radius:4px;border:1px solid var(--line)}
  .empty{padding:40px;color:var(--muted);text-align:center}
  .statbar{display:flex;flex-wrap:wrap;gap:14px;padding:10px 24px;
    border-bottom:1px solid var(--line);color:var(--muted);font-size:12px;
    background:var(--panel)}
  .statbar b{color:var(--ink);font-weight:600}
  code{font-family:ui-monospace,Menlo,monospace}
  .node-label{font:600 12px ui-monospace,Menlo,monospace}
  .tip{font-size:12px;color:var(--muted);margin-top:6px}
</style>
</head>
<body>
<header>
  <h1 id="title">Crux — CDCL conflict analysis</h1>
  <div class="sub" id="subtitle"></div>
</header>
<div class="statbar" id="statbar"></div>
<div class="wrap">
  <div class="left">
    <div class="controls">
      <button id="prev">◀ Prev</button>
      <span class="pill" id="conflbl">conflict –</span>
      <button id="next">Next ▶</button>
      <input type="range" id="slider" min="0" max="0" value="0">
      <span class="pill" id="kpill"></span>
    </div>
    <svg id="graph" width="1200" height="600"></svg>
  </div>
  <div class="right">
    <div id="panel"></div>
  </div>
</div>
<script>
const DATA = /*__DATA__*/;
const SVGNS = "http://www.w3.org/2000/svg";

document.getElementById('title').textContent = DATA.title;
document.getElementById('subtitle').textContent = DATA.subtitle;
(function(){
  const s = DATA.stats;
  const bar = document.getElementById('statbar');
  const items = [
    ['result', DATA.status],['vars', DATA.nvars],['clauses', DATA.nclauses],
    ['decisions', s.decisions],['conflicts', s.conflicts],
    ['propagations', s.propagations],['learned', s.learned],
    ['restarts', s.restarts],['max level', s.max_decision_level]
  ];
  bar.innerHTML = items.map(([k,v])=>`<span>${k}: <b>${v}</b></span>`).join('');
})();

const litLabel = (lit)=> (lit>0? "x"+lit : "¬x"+(-lit));
// palette by decision level
const LEVELS = ["#3fb950","#58a6ff","#d29922","#db61a2","#a371f7","#39c5bb",
                "#f0883e","#6cb6ff","#e3b341","#ff7b72"];
const levelColor = (lvl)=> LEVELS[lvl % LEVELS.length];

function buildGraph(snap){
  // map var -> trail entry {lit, level, reason}
  const byVar = new Map();
  snap.trail.forEach((t,i)=>{ byVar.set(Math.abs(t.lit), {...t, order:i}); });

  // antecedents of a literal `lit` from its reason clause:
  // reason = (lit OR -a OR -b ...) -> antecedents are a,b (true literals)
  function antecedents(lit){
    const e = byVar.get(Math.abs(lit));
    if(!e || !e.reason) return [];
    return e.reason.filter(q=>q!==lit).map(q=>-q);
  }
  // BFS the cone that feeds the conflict
  const inGraph = new Set();
  const queue = [];
  // conflict node 'kappa' is fed by antecedents of the conflict clause
  const confAnte = snap.conflict.map(q=>-q);
  confAnte.forEach(l=>{ if(byVar.has(Math.abs(l))){ queue.push(l); }});
  while(queue.length){
    const l = queue.shift();
    const v = Math.abs(l);
    if(inGraph.has(v)) continue;
    inGraph.add(v);
    antecedents(l).forEach(a=>{ if(!inGraph.has(Math.abs(a))) queue.push(a); });
  }
  // nodes
  const nodes = [];
  inGraph.forEach(v=>{
    const e = byVar.get(v);
    nodes.push({v, lit:e.lit, level:e.level, order:e.order, reason:e.reason});
  });
  // edges
  const edges = [];
  nodes.forEach(n=>{
    antecedents(n.lit).forEach(a=>{
      if(inGraph.has(Math.abs(a))) edges.push({from:Math.abs(a), to:n.v});
    });
  });
  // conflict edges -> kappa
  confAnte.forEach(a=>{ if(inGraph.has(Math.abs(a))) edges.push({from:Math.abs(a), to:'K'}); });
  return {nodes, edges, byVar};
}

function layout(graph, snap){
  // x by decision level, y by trail order within level
  const levels = {};
  graph.nodes.forEach(n=>{ (levels[n.level] ||= []).push(n); });
  const maxLevel = Math.max(0, ...graph.nodes.map(n=>n.level));
  const colW = 200, rowH = 64, padX = 80, padY = 70;
  const pos = new Map();
  Object.keys(levels).forEach(lv=>{
    levels[lv].sort((a,b)=>a.order-b.order);
    levels[lv].forEach((n,i)=>{
      pos.set(n.v, {x: padX + n.level*colW, y: padY + i*rowH, node:n});
    });
  });
  // kappa to the far right, vertically centered on conflict antecedents
  const confVars = snap.conflict.map(q=>Math.abs(q)).filter(v=>pos.has(v));
  let ky = padY;
  if(confVars.length){
    ky = confVars.reduce((s,v)=>s+pos.get(v).y,0)/confVars.length;
  }
  pos.set('K', {x: padX + (maxLevel+1)*colW, y: ky, kappa:true});
  const width = padX*2 + (maxLevel+1)*colW + 60;
  let maxRows = 1;
  Object.values(levels).forEach(a=>maxRows=Math.max(maxRows,a.length));
  const height = padY*2 + Math.max(maxRows, confVars.length+1)*rowH;
  return {pos, width, height, maxLevel};
}

function render(idx){
  const snap = DATA.snaps[idx];
  const svg = document.getElementById('graph');
  svg.innerHTML = "";
  if(!snap){ return; }
  const graph = buildGraph(snap);
  const lay = layout(graph, snap);
  svg.setAttribute('width', lay.width);
  svg.setAttribute('height', lay.height);

  const learnSet = new Set(snap.learned.map(l=>Math.abs(l)));
  const uipVar = Math.abs(snap.uip);

  // defs: arrowheads
  const defs = el('defs');
  defs.appendChild(marker('arrow', '#5b6673'));
  defs.appendChild(marker('arrowK', '#ff6b6b'));
  defs.appendChild(marker('arrowL', '#a371f7'));
  svg.appendChild(defs);

  // level bands + labels
  for(let lv=0; lv<=lay.maxLevel; lv++){
    const x = 80 + lv*200;
    const t = text(x, 30, "level "+lv, "#6b7686", 12);
    t.setAttribute('text-anchor','middle');
    svg.appendChild(t);
    const ln = line(x, 44, x, lay.height-20, "#1f2630", 1);
    ln.setAttribute('stroke-dasharray','3 6');
    svg.appendChild(ln);
  }

  // edges
  graph.edges.forEach(e=>{
    const a = lay.pos.get(e.from), b = lay.pos.get(e.to);
    if(!a||!b) return;
    const toK = (e.to==='K');
    const inLearn = learnSet.has(e.from) && (toK || learnSet.has(e.to));
    const col = toK ? "#7d3b3b" : (inLearn? "#5a3f86" : "#39414d");
    const mk = toK ? "arrowK" : (inLearn? "arrowL":"arrow");
    const p = path(a.x+58, a.y, b.x-(toK?26:58), b.y, col, mk);
    svg.appendChild(p);
  });

  // nodes
  graph.nodes.forEach(n=>{
    const p = lay.pos.get(n.v);
    const g = el('g');
    const w=116,h=34;
    const r = rect(p.x-w/2, p.y-h/2, w, h, 9);
    const isDecision = !n.reason;
    r.setAttribute('fill', isDecision ? shade(levelColor(n.level),0.22)
                                      : shade(levelColor(n.level),0.13));
    r.setAttribute('stroke', n.v===uipVar ? "#f2cc60"
                    : (learnSet.has(n.v) ? "#a371f7"
                    : (isDecision? levelColor(n.level) : "#2c3744")));
    r.setAttribute('stroke-width', n.v===uipVar ? 3 : (isDecision?2.4:1.4));
    g.appendChild(r);
    const lbl = text(p.x, p.y+4, litLabel(n.lit), "#e6edf3", 13);
    lbl.setAttribute('text-anchor','middle');
    lbl.setAttribute('class','node-label');
    g.appendChild(lbl);
    if(isDecision){
      const d = text(p.x, p.y-h/2-5, "decision", "#6b7686", 10);
      d.setAttribute('text-anchor','middle'); g.appendChild(d);
    }
    if(n.v===uipVar){
      const d = text(p.x, p.y+h/2+13, "1-UIP", "#f2cc60", 10);
      d.setAttribute('text-anchor','middle'); g.appendChild(d);
    }
    const tt = el('title');
    tt.textContent = `${litLabel(n.lit)} @level ${n.level}` +
      (n.reason? `\nreason: (${n.reason.map(litLabel).join(' ∨ ')})` : '\ndecision');
    g.appendChild(tt);
    svg.appendChild(g);
  });

  // kappa (conflict) node
  const k = lay.pos.get('K');
  const kg = el('g');
  const kr = rect(k.x-26, k.y-26, 52, 52, 26);
  kr.setAttribute('fill', '#3a1d1d'); kr.setAttribute('stroke', '#ff6b6b');
  kr.setAttribute('stroke-width', 3);
  kg.appendChild(kr);
  const kt = text(k.x, k.y+7, "⊥", "#ff6b6b", 22);
  kt.setAttribute('text-anchor','middle'); kg.appendChild(kt);
  const kl = text(k.x, k.y+44, "conflict", "#ff6b6b", 11);
  kl.setAttribute('text-anchor','middle'); kg.appendChild(kl);
  svg.appendChild(kg);

  renderPanel(idx, snap, graph);
  // controls
  document.getElementById('conflbl').textContent =
    `conflict ${idx+1} / ${DATA.snaps.length}`;
  document.getElementById('kpill').textContent =
    `decision level ${snap.decision_level} → backjump to ${snap.btlevel}`;
  document.getElementById('slider').value = idx;
  document.getElementById('prev').disabled = idx<=0;
  document.getElementById('next').disabled = idx>=DATA.snaps.length-1;
}

function renderPanel(idx, snap, graph){
  const litSpan = (lit, cls)=>`<span class="lit ${cls||''}">${litLabel(lit)}</span>`;
  const learnSet = new Set(snap.learned.map(Math.abs));
  const conflictHtml = snap.conflict.map(l=>litSpan(l)).join(' ∨ ');
  const learnedHtml = snap.learned.map(l=>{
    const cls = (Math.abs(l)===Math.abs(snap.uip))? 'uip' : 'learn';
    return litSpan(l, cls);
  }).join(' ∨ ');
  const decisions = graph.nodes.filter(n=>!n.reason)
    .sort((a,b)=>a.level-b.level)
    .map(n=>`L${n.level}: ${litLabel(n.lit)}`).join(' &nbsp;·&nbsp; ') || '—';
  document.getElementById('panel').innerHTML = `
    <h2>This conflict</h2>
    <div class="kv"><span>conflict #</span><span>${idx+1} of ${DATA.snaps.length}</span></div>
    <div class="kv"><span>decision level</span><span>${snap.decision_level}</span></div>
    <div class="kv"><span>graph nodes</span><span>${graph.nodes.length}</span></div>
    <div class="kv"><span>backjump to</span><span>level ${snap.btlevel}</span></div>

    <h2>Conflicting clause</h2>
    <div class="clause">${conflictHtml}</div>
    <div class="tip">Every literal here is false under the current trail — that's
      the contradiction (⊥).</div>

    <h2>Decisions on the path</h2>
    <div class="clause">${decisions}</div>

    <h2>1-UIP learned clause</h2>
    <div class="clause">${learnedHtml}</div>
    <div class="tip">The single literal at the current decision level is the
      <b style="color:var(--gold)">1-UIP</b>. After backjumping to level
      ${snap.btlevel}, this clause becomes unit and forces
      ${litLabel(snap.learned[0])}.</div>

    <h2>Legend</h2>
    <div class="legend">
      <span class="swatch" style="border-color:var(--gold);border-width:2px"></span><span>1-UIP variable</span>
      <span class="swatch" style="border-color:var(--learn)"></span><span>in learned clause</span>
      <span class="swatch" style="background:#3a1d1d;border-color:var(--red)"></span><span>⊥ conflict node</span>
      <span class="swatch" style="border-width:2px;border-color:#58a6ff"></span><span>decision (thick border)</span>
    </div>
  `;
}

// ---- tiny SVG helpers -------------------------------------------------
function el(n){return document.createElementNS(SVGNS,n);}
function rect(x,y,w,h,r){const e=el('rect');e.setAttribute('x',x);e.setAttribute('y',y);
  e.setAttribute('width',w);e.setAttribute('height',h);e.setAttribute('rx',r);return e;}
function text(x,y,t,fill,size){const e=el('text');e.setAttribute('x',x);e.setAttribute('y',y);
  e.setAttribute('fill',fill);e.setAttribute('font-size',size||12);e.textContent=t;return e;}
function line(x1,y1,x2,y2,stroke,w){const e=el('line');e.setAttribute('x1',x1);
  e.setAttribute('y1',y1);e.setAttribute('x2',x2);e.setAttribute('y2',y2);
  e.setAttribute('stroke',stroke);e.setAttribute('stroke-width',w||1);return e;}
function path(x1,y1,x2,y2,stroke,marker){
  const dx=Math.max(40,(x2-x1)*0.5);
  const d=`M ${x1} ${y1} C ${x1+dx} ${y1}, ${x2-dx} ${y2}, ${x2} ${y2}`;
  const e=el('path');e.setAttribute('d',d);e.setAttribute('fill','none');
  e.setAttribute('stroke',stroke);e.setAttribute('stroke-width',1.8);
  e.setAttribute('marker-end',`url(#${marker})`);return e;}
function marker(id,color){const m=el('marker');m.setAttribute('id',id);
  m.setAttribute('viewBox','0 0 10 10');m.setAttribute('refX','9');m.setAttribute('refY','5');
  m.setAttribute('markerWidth','7');m.setAttribute('markerHeight','7');
  m.setAttribute('orient','auto-start-reverse');
  const p=el('path');p.setAttribute('d','M 0 0 L 10 5 L 0 10 z');p.setAttribute('fill',color);
  m.appendChild(p);return m;}
function shade(hex,a){const c=hex.replace('#','');
  const r=parseInt(c.slice(0,2),16),g=parseInt(c.slice(2,4),16),b=parseInt(c.slice(4,6),16);
  return `rgba(${r},${g},${b},${a})`;}

// ---- controls ---------------------------------------------------------
let cur = 0;
const slider = document.getElementById('slider');
if(DATA.snaps.length===0){
  document.querySelector('.left').innerHTML =
    '<div class="empty">This instance produced no conflicts — it was solved by '+
    'pure unit propagation (or was trivially UNSAT). Try a harder instance, e.g. '+
    '<code>crux viz --problem pigeonhole -m 5 -n 4</code>.</div>';
  document.getElementById('panel').innerHTML =
    '<h2>No conflicts</h2><div class="tip">Nothing to analyze — the search never '+
    'hit a contradiction.</div>';
} else {
  slider.max = DATA.snaps.length-1;
  document.getElementById('prev').onclick=()=>{ if(cur>0){cur--;render(cur);} };
  document.getElementById('next').onclick=()=>{ if(cur<DATA.snaps.length-1){cur++;render(cur);} };
  slider.oninput=(e)=>{ cur=+e.target.value; render(cur); };
  document.addEventListener('keydown',(e)=>{
    if(e.key==='ArrowLeft'&&cur>0){cur--;render(cur);}
    if(e.key==='ArrowRight'&&cur<DATA.snaps.length-1){cur++;render(cur);}
  });
  render(0);
}
</script>
</body>
</html>
"""
