"""Generate a single self-contained HTML visualizer for the CDCL search.

The page embeds web/solver.js (the JS mirror of the engine) and replays the
solver's step trace: the assignment trail by decision level, the implication
graph that feeds each conflict, the growing list of learned clauses, VSIDS
activity, and — for Sudoku instances — the grid filling in live.
"""
from __future__ import annotations

import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_SOLVER_JS = os.path.join(os.path.dirname(_HERE), "web", "solver.js")


def _read_solver_js() -> str:
    with open(_SOLVER_JS, "r") as f:
        return f.read()


def generate_html() -> str:
    solver_js = _read_solver_js()
    return _TEMPLATE.replace("/*__SOLVER_JS__*/", solver_js)


def write_html(path: str) -> str:
    html = generate_html()
    with open(path, "w") as f:
        f.write(html)
    return path


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Conflux — a CDCL SAT solver, visualized</title>
<style>
  :root{
    --bg0:#0a0c14;--bg1:#11162a;--bg2:#171d36;--line:#243056;
    --ink:#e6ecff;--mut:#8b97c0;--acc:#5b9bff;--acc2:#7cf0c4;
    --dec:#ffb14e;--imp:#5b9bff;--conf:#ff5d6c;--learn:#c98bff;--uip:#7cf0c4;
    --t:#9be8b0;--f:#ff8a9b;
  }
  *{box-sizing:border-box}
  html,body{margin:0;height:100%}
  body{background:radial-gradient(1200px 700px at 80% -10%,#16204a 0%,#0a0c14 55%),
       #0a0c14;color:var(--ink);
       font:14px/1.5 ui-sans-serif,system-ui,Segoe UI,Roboto,Helvetica,Arial}
  code,.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
  header{padding:18px 22px 10px;border-bottom:1px solid var(--line)}
  h1{margin:0;font-size:22px;letter-spacing:.3px}
  h1 .x{color:var(--acc)}
  .sub{color:var(--mut);font-size:13px;margin-top:3px}
  .wrap{display:grid;grid-template-columns:300px 1fr 320px;gap:14px;padding:14px}
  @media(max-width:1100px){.wrap{grid-template-columns:1fr}}
  .card{background:linear-gradient(180deg,#11162a,#0e1326);border:1px solid var(--line);
        border-radius:12px;padding:14px;box-shadow:0 10px 30px rgba(0,0,0,.35)}
  .card h2{margin:0 0 10px;font-size:12px;letter-spacing:.14em;text-transform:uppercase;
           color:var(--mut)}
  label{display:block;font-size:12px;color:var(--mut);margin:10px 0 4px}
  select,input,textarea,button{font:inherit;color:var(--ink);background:#0c1124;
    border:1px solid var(--line);border-radius:8px;padding:8px 10px;width:100%}
  textarea{resize:vertical;min-height:70px}
  .row{display:flex;gap:8px}
  .row>*{flex:1}
  button{cursor:pointer;transition:.15s;background:#162143}
  button:hover{border-color:var(--acc);background:#1b2a55}
  button.primary{background:linear-gradient(180deg,#2a62d6,#244fb0);border-color:#3b73ea;
                 font-weight:600}
  button.primary:hover{filter:brightness(1.1)}
  button:disabled{opacity:.4;cursor:not-allowed}
  .transport{display:flex;gap:6px;margin-top:8px}
  .transport button{flex:1;padding:8px 0}
  .scrub{margin-top:10px}
  .stat{display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px dashed #1c2542}
  .stat b{color:var(--ink);font-variant-numeric:tabular-nums}
  .pill{display:inline-block;padding:2px 9px;border-radius:999px;font-size:12px;
        border:1px solid var(--line)}
  .verdict{font-size:18px;font-weight:700;letter-spacing:.06em;padding:8px 12px;border-radius:10px;
           text-align:center;margin-bottom:10px}
  .v-SAT{background:rgba(124,240,196,.12);color:var(--acc2);border:1px solid #2c7d63}
  .v-UNSAT{background:rgba(255,93,108,.12);color:#ff8a96;border:1px solid #8a2f39}
  .v-UNKNOWN{background:rgba(255,177,78,.12);color:var(--dec);border:1px solid #8a6a2f}
  .lvl{margin:8px 0}
  .lvl .h{font-size:11px;color:var(--mut);margin-bottom:3px}
  .chips{display:flex;flex-wrap:wrap;gap:5px}
  .chip{padding:2px 8px;border-radius:7px;font-size:12px;border:1px solid var(--line);
        font-family:ui-monospace,monospace;white-space:nowrap}
  .chip.dec{background:rgba(255,177,78,.14);border-color:#7a5a26;color:#ffd49a}
  .chip.imp{background:rgba(91,155,255,.12);border-color:#2c4d8a;color:#bcd4ff}
  .chip.uip{outline:2px solid var(--uip)}
  .chip.now{box-shadow:0 0 0 2px var(--acc)}
  svg{width:100%;display:block;background:#0a0e1f;border-radius:10px;border:1px solid var(--line)}
  .learned{max-height:240px;overflow:auto}
  .lc{font-family:ui-monospace,monospace;font-size:12px;padding:4px 6px;border-radius:6px;
      margin-bottom:4px;background:#0d1426;border:1px solid #1b2540}
  .lc.new{border-color:var(--learn);background:rgba(201,139,255,.08)}
  .bars{display:flex;flex-direction:column;gap:3px;max-height:230px;overflow:auto}
  .bar{display:flex;align-items:center;gap:6px;font-size:11px}
  .bar .n{width:30px;text-align:right;color:var(--mut);font-family:ui-monospace,monospace}
  .bar .t{height:9px;border-radius:4px;background:linear-gradient(90deg,#2a62d6,#7cf0c4)}
  .sudoku{display:grid;grid-template-columns:repeat(9,1fr);gap:1px;background:#243056;
          border:2px solid #3a4a7e;border-radius:8px;overflow:hidden;aspect-ratio:1}
  .sc{background:#0c1124;display:flex;align-items:center;justify-content:center;
      font-family:ui-monospace,monospace;font-size:15px;aspect-ratio:1}
  .sc.given{color:#9bb4ff;font-weight:700;background:#101935}
  .sc.fill{color:#7cf0c4}
  .sc.b{box-shadow:inset 0 0 0 1px #36488a}
  .legend{display:flex;gap:12px;flex-wrap:wrap;font-size:11px;color:var(--mut);margin-top:8px}
  .legend span{display:inline-flex;align-items:center;gap:5px}
  .dot{width:10px;height:10px;border-radius:3px;display:inline-block}
  .hide{display:none}
  .speed{display:flex;align-items:center;gap:8px}
  .speed input{flex:1}
  .err{color:#ff8a96;font-size:12px;margin-top:6px}
  .foot{color:var(--mut);font-size:11px;padding:6px 22px 22px}
</style>
</head>
<body>
<header>
  <h1>Con<span class="x">flux</span> — a CDCL SAT solver, visualized</h1>
  <div class="sub">Watch conflict-driven clause learning: decisions, unit
   propagation, the implication graph, 1-UIP analysis &amp; non-chronological backjumping.</div>
</header>

<div class="wrap">
  <!-- LEFT: controls -->
  <div class="card">
    <h2>Instance</h2>
    <label>Problem</label>
    <select id="kind">
      <option value="rand">Random 3-SAT</option>
      <option value="php">Pigeonhole (UNSAT)</option>
      <option value="color">Graph coloring</option>
      <option value="sudoku">Sudoku</option>
      <option value="dimacs">Paste DIMACS</option>
    </select>

    <div id="p-rand">
      <div class="row">
        <div><label>vars n</label><input id="r-n" type="number" value="16" min="2" max="60"></div>
        <div><label>ratio m/n</label><input id="r-ratio" type="number" value="3.2" step="0.1" min="1" max="8"></div>
      </div>
      <label>seed</label><input id="r-seed" type="number" value="7">
    </div>

    <div id="p-php" class="hide">
      <div class="row">
        <div><label>pigeons</label><input id="php-p" type="number" value="5" min="2" max="9"></div>
        <div><label>holes</label><input id="php-h" type="number" value="4" min="1" max="8"></div>
      </div>
    </div>

    <div id="p-color" class="hide">
      <label>graph</label>
      <select id="c-graph">
        <option value="petersen">Petersen (10 v, 15 e)</option>
        <option value="wheel6">Wheel W6 (7 v)</option>
        <option value="k4">K4 (complete, 4 v)</option>
        <option value="grid3">3×3 grid</option>
      </select>
      <label>colors k</label><input id="c-k" type="number" value="3" min="1" max="6">
    </div>

    <div id="p-sudoku" class="hide">
      <label>puzzle (81 cells, . = blank)</label>
      <textarea id="s-grid">53..7....6..195....98....6.8...6...34..8.3..17...2...6.6....28....419..5....8..79</textarea>
    </div>

    <div id="p-dimacs" class="hide">
      <label>DIMACS CNF</label>
      <textarea id="d-text" style="min-height:120px">p cnf 3 4
1 2 0
-1 2 0
1 -2 0
-1 -2 3 0</textarea>
    </div>

    <button class="primary" id="build" style="margin-top:12px">Solve &amp; trace ▸</button>
    <div id="err" class="err"></div>

    <h2 style="margin-top:18px">Playback</h2>
    <div class="transport">
      <button id="first">⏮</button>
      <button id="back">◀</button>
      <button id="play">▶</button>
      <button id="fwd">▶▶</button>
      <button id="last">⏭</button>
    </div>
    <div class="speed"><span style="font-size:11px;color:var(--mut)">slow</span>
      <input id="speed" type="range" min="1" max="60" value="22">
      <span style="font-size:11px;color:var(--mut)">fast</span></div>
    <div class="scrub"><input id="scrub" type="range" min="0" max="0" value="0"></div>
    <div style="text-align:center;color:var(--mut);font-size:12px" id="stepinfo">step 0 / 0</div>
  </div>

  <!-- CENTER: graph / sudoku + trail -->
  <div class="card">
    <h2>Search state</h2>
    <div id="verdict" class="verdict v-UNKNOWN">— build an instance —</div>
    <div id="event" class="mono" style="font-size:12px;color:var(--mut);min-height:18px"></div>

    <div id="sudoku-wrap" class="hide" style="max-width:420px;margin:10px auto">
      <div id="sudoku" class="sudoku"></div>
    </div>

    <div style="margin-top:10px">
      <h2>Implication graph (current conflict)</h2>
      <svg id="graph" viewBox="0 0 800 360" preserveAspectRatio="xMidYMid meet"></svg>
      <div class="legend">
        <span><i class="dot" style="background:var(--dec)"></i>decision</span>
        <span><i class="dot" style="background:var(--imp)"></i>implied</span>
        <span><i class="dot" style="background:var(--uip)"></i>1-UIP cut</span>
        <span><i class="dot" style="background:var(--conf)"></i>conflict κ</span>
      </div>
    </div>

    <div style="margin-top:12px">
      <h2>Assignment trail by decision level</h2>
      <div id="trail"></div>
    </div>
  </div>

  <!-- RIGHT: stats + learned + activity -->
  <div class="card">
    <h2>Statistics</h2>
    <div id="stats"></div>
    <h2 style="margin-top:16px">Learned clauses</h2>
    <div id="learned" class="learned"></div>
    <h2 style="margin-top:16px">VSIDS activity (top vars)</h2>
    <div id="bars" class="bars"></div>
  </div>
</div>
<div class="foot">Conflux · pure-from-scratch CDCL · the engine running here is the same JS mirror
that is checked for verdict parity against the Python solver. ·
keys: <b>space</b> play/pause, <b>←/→</b> step, <b>Home/End</b> jump.</div>

<script>
/*__SOLVER_JS__*/
</script>
<script>
"use strict";
const Cx = window.Conflux;
const $ = s => document.querySelector(s);

/* ---------- instance encoders (JS mirror of conflux/encoders.py) ---------- */
function mulberry32(seed){let a=seed>>>0;return function(){a|=0;a=a+0x6D2B79F5|0;
  let t=Math.imul(a^a>>>15,1|a);t=t+Math.imul(t^t>>>7,61|t)^t;return((t^t>>>14)>>>0)/4294967296;};}

function randomKSAT(n, ratio, seed){
  const rng=mulberry32(seed); const m=Math.max(1,Math.round(n*ratio)); const cls=[];
  for(let i=0;i<m;i++){const cl=new Set();
    while(cl.size<Math.min(3,2*n)){const v=1+Math.floor(rng()*n);const s=rng()<.5?1:-1;cl.add(s*v);}
    cls.push([...cl]);}
  return {numVars:n, clauses:cls, kind:"rand"};
}
function atMostOne(cls,lits){for(let i=0;i<lits.length;i++)for(let j=i+1;j<lits.length;j++)cls.push([-lits[i],-lits[j]]);}
function exactlyOne(cls,lits){cls.push([...lits]);atMostOne(cls,lits);}
function pigeonhole(p,h){const cls=[];const V=p*h;const X=(i,j)=>i*h+j+1;
  for(let i=0;i<p;i++){const r=[];for(let j=0;j<h;j++)r.push(X(i,j));cls.push(r);}
  for(let j=0;j<h;j++)for(let a=0;a<p;a++)for(let b=a+1;b<p;b++)cls.push([-X(a,j),-X(b,j)]);
  return {numVars:V, clauses:cls, kind:"php"};
}
const GRAPHS={
  petersen:{V:10,E:[[0,1],[1,2],[2,3],[3,4],[4,0],[0,5],[1,6],[2,7],[3,8],[4,9],[5,7],[7,9],[9,6],[6,8],[8,5]]},
  wheel6:{V:7,E:[[0,1],[1,2],[2,3],[3,4],[4,5],[5,1],[6,1],[6,2],[6,3],[6,4],[6,5]]},
  k4:{V:4,E:[[0,1],[0,2],[0,3],[1,2],[1,3],[2,3]]},
  grid3:{V:9,E:[[0,1],[1,2],[3,4],[4,5],[6,7],[7,8],[0,3],[3,6],[1,4],[4,7],[2,5],[5,8]]}
};
function coloring(name,k){const g=GRAPHS[name];const cls=[];const X=(v,c)=>v*k+c+1;
  for(let v=0;v<g.V;v++){const r=[];for(let c=0;c<k;c++)r.push(X(v,c));exactlyOne(cls,r);}
  for(const [u,v] of g.E)for(let c=0;c<k;c++)cls.push([-X(u,c),-X(v,c)]);
  return {numVars:g.V*k, clauses:cls, kind:"color"};
}
function sudoku(text){
  const ch=[...text].filter(c=>!/\s/.test(c));
  if(ch.length!==81) throw new Error("expected 81 cells, got "+ch.length);
  const g=ch.map(c=>(c==='.'||c==='0'||c==='_')?0:parseInt(c,10));
  const n=9,box=3,X=(r,c,d)=>r*n*n+c*n+(d-1)+1;const cls=[];
  for(let r=0;r<n;r++)for(let c=0;c<n;c++){const lits=[];for(let d=1;d<=n;d++)lits.push(X(r,c,d));exactlyOne(cls,lits);}
  for(let d=1;d<=n;d++){
    for(let r=0;r<n;r++){const L=[];for(let c=0;c<n;c++)L.push(X(r,c,d));atMostOne(cls,L);}
    for(let c=0;c<n;c++){const L=[];for(let r=0;r<n;r++)L.push(X(r,c,d));atMostOne(cls,L);}
    for(let br=0;br<n;br+=box)for(let bc=0;bc<n;bc+=box){const L=[];
      for(let i=0;i<box;i++)for(let j=0;j<box;j++)L.push(X(br+i,bc+j,d));atMostOne(cls,L);}
  }
  for(let r=0;r<n;r++)for(let c=0;c<n;c++)if(g[r*n+c])cls.push([X(r,c,g[r*n+c])]);
  return {numVars:n*n*n, clauses:cls, kind:"sudoku", givens:g};
}
function parseDimacs(text){let nv=0;const cls=[];let cur=[];
  for(const line of text.split(/\n/)){const t=line.trim();
    if(!t||t[0]==='c'||t[0]==='p'||t[0]==='%')continue;
    for(const tok of t.split(/\s+/)){const x=parseInt(tok,10);if(x===0){if(cur.length)cls.push(cur);cur=[];}
      else{cur.push(x);nv=Math.max(nv,Math.abs(x));}}}
  if(cur.length)cls.push(cur);
  return {numVars:nv, clauses:cls, kind:"dimacs"};
}

/* ---------- state ---------- */
let INST=null, TRACE=[], RESULT="UNKNOWN", SOLVER=null;
let idx=0, timer=null;

function buildInstance(){
  const k=$("#kind").value;
  if(k==="rand")  return randomKSAT(+$("#r-n").value, +$("#r-ratio").value, +$("#r-seed").value|0);
  if(k==="php")   return pigeonhole(+$("#php-p").value|0, +$("#php-h").value|0);
  if(k==="color") return coloring($("#c-graph").value, +$("#c-k").value|0);
  if(k==="sudoku")return sudoku($("#s-grid").value);
  if(k==="dimacs")return parseDimacs($("#d-text").value);
}

function run(){
  $("#err").textContent="";
  try{ INST=buildInstance(); }catch(e){ $("#err").textContent=e.message; return; }
  const s=new Cx.Solver(INST.numVars,{recordTrace:true, maxTrace:60000, restartBase:60});
  let ok=true; for(const cl of INST.clauses){ if(!s.addClause(cl)){ok=false;} }
  RESULT=s.solve(200000);
  SOLVER=s; TRACE=s.trace;
  idx=TRACE.length;                 // start at the end (final state)
  $("#scrub").max=TRACE.length;
  setupSudoku();
  render();
  setVerdict();
}

function setVerdict(){
  const v=$("#verdict"); v.className="verdict v-"+RESULT;
  let extra="";
  if(RESULT==="SAT" && INST) extra=" — model verified: "+Cx.isSatisfied(INST.numVars,INST.clauses,SOLVER.model());
  v.textContent=RESULT+extra;
}

/* ---------- state reconstruction ---------- */
function stateAt(k){
  const trail=[]; const levelStart=[0]; const learned=[]; let lastConflict=null;
  let lastLearn=null; let restarts=0;
  const removeAbove=(lvl)=>{ while(trail.length && trail[trail.length-1].level>lvl) trail.pop(); };
  for(let i=0;i<k;i++){
    const e=TRACE[i];
    if(e.t==="decide"){ trail.push({lit:e.lit,level:e.level,decision:true}); }
    else if(e.t==="imply"){ trail.push({lit:e.lit,level:e.level,decision:false,reason:e.reason}); }
    else if(e.t==="conflict"){ lastConflict=e; }
    else if(e.t==="learn"){ learned.push(e.clause); lastLearn=e; }
    else if(e.t==="backjump"){ removeAbove(e.to); trail.push({lit:e.lit,level:e.to,decision:false,asserted:true}); lastConflict=null; }
    else if(e.t==="restart"){ removeAbove(0); restarts++; lastConflict=null; }
  }
  return {trail,learned,lastConflict,lastLearn,restarts,cur:TRACE[k-1]||null};
}

/* ---------- rendering ---------- */
function render(){
  const k=Math.max(0,Math.min(idx,TRACE.length));
  $("#scrub").value=k; $("#stepinfo").textContent="step "+k+" / "+TRACE.length;
  const st=stateAt(k);
  renderEvent(st); renderTrail(st); renderGraph(st);
  renderLearned(st); renderStats(st); renderBars(st); renderSudoku(st);
}

function renderEvent(st){
  const e=st.cur; let txt="";
  if(!e) txt="initial state (level-0 propagation)";
  else if(e.t==="decide") txt="DECIDE  "+litStr(e.lit)+"  (open new level "+e.level+")";
  else if(e.t==="imply") txt="PROPAGATE  "+litStr(e.lit)+"  forced by "+clStr(e.reason);
  else if(e.t==="conflict") txt="CONFLICT  clause "+clStr(e.clause)+" is falsified at level "+e.level;
  else if(e.t==="learn") txt="LEARN  "+clStr(e.clause)+"   (1-UIP = "+litStr(e.uip)+", backjump → level "+e.bt+")";
  else if(e.t==="backjump") txt="BACKJUMP → level "+e.to+", assert "+litStr(e.lit);
  else if(e.t==="restart") txt="RESTART (keep learned clauses, drop to level 0)";
  $("#event").textContent=txt;
}
function litStr(l){return (l>0?"x"+l:"¬x"+(-l));}
function clStr(c){return "("+c.map(litStr).join(" ∨ ")+")";}

function renderTrail(st){
  const byLevel={}; let maxL=0;
  for(const a of st.trail){ (byLevel[a.level]=byLevel[a.level]||[]).push(a); maxL=Math.max(maxL,a.level); }
  let html="";
  const lastLit = st.cur && (st.cur.lit!==undefined)? st.cur.lit : null;
  const uip = st.lastConflict? null : (st.lastLearn? st.lastLearn.uip : null);
  for(let L=0;L<=maxL;L++){
    const arr=byLevel[L]||[];
    html+='<div class="lvl"><div class="h">level '+L+(L===0?' (forced)':'')+'</div><div class="chips">';
    for(const a of arr){
      let cls="chip "+(a.decision?"dec":"imp");
      if(lastLit===a.lit) cls+=" now";
      html+='<span class="'+cls+'" title="'+(a.decision?'decision':'implied')+'">'+litStr(a.lit)+'</span>';
    }
    html+='</div></div>';
  }
  if(st.trail.length===0) html='<div style="color:var(--mut)">— empty —</div>';
  $("#trail").innerHTML=html;
}

function renderGraph(st){
  const svg=$("#graph"); const e=st.lastConflict;
  if(!e || !e.graph){ svg.innerHTML='<text x="400" y="180" fill="#56618c" text-anchor="middle" font-size="14">no active conflict at this step</text>'; return; }
  const g=e.graph;
  // columns by level; conflict node κ on the far right
  const levels=[...new Set(g.nodes.map(n=>n.level))].sort((a,b)=>a-b);
  const colX={}; const W=800,H=360,pad=60;
  levels.forEach((L,i)=>{ colX[L]=pad + (levels.length<=1? (W-2*pad)/2 : i*(W-2*pad-120)/(levels.length-1)); });
  const kx=W-40;
  const pos={}; const perCol={};
  for(const n of g.nodes){ perCol[n.level]=(perCol[n.level]||0)+1; }
  const cnt={};
  for(const n of g.nodes){
    const L=n.level; cnt[L]=(cnt[L]||0); const total=perCol[L];
    const y= H/2 + (cnt[L]-(total-1)/2)*44; cnt[L]++;
    pos[n.lit]={x:colX[L], y:y, node:n};
  }
  const learnSet = st.lastLearn ? new Set(st.lastLearn.clause.map(x=>-x)) : new Set(); // UIP-side literals
  const uip = st.lastLearn? st.lastLearn.uip : null;
  let s='<defs><marker id="ar" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">'+
        '<path d="M0,0 L7,3 L0,6 Z" fill="#3a4a7e"/></marker></defs>';
  // edges
  for(const ed of g.edges){
    const a=pos[ed.from]; const b= ed.to==="K"? {x:kx,y:H/2} : pos[ed.to];
    if(!a||!b) continue;
    s+='<line x1="'+a.x+'" y1="'+a.y+'" x2="'+b.x+'" y2="'+b.y+'" stroke="#2b3763" stroke-width="1.3" marker-end="url(#ar)"/>';
  }
  // conflict node
  s+='<circle cx="'+kx+'" cy="'+(H/2)+'" r="16" fill="rgba(255,93,108,.18)" stroke="#ff5d6c" stroke-width="2"/>';
  s+='<text x="'+kx+'" y="'+(H/2+5)+'" fill="#ff8a96" text-anchor="middle" font-size="15">κ</text>';
  // literal nodes
  for(const n of g.nodes){
    const p=pos[n.lit]; let fill=n.decision?"var(--dec)":"var(--imp)";
    let stroke=n.decision?"#7a5a26":"#2c4d8a";
    if(n.lit===uip || -n.lit===uip){ stroke="var(--uip)"; }
    s+='<circle cx="'+p.x+'" cy="'+p.y+'" r="17" fill="rgba(91,155,255,.10)" stroke="'+stroke+'" stroke-width="'+((n.lit===uip||-n.lit===uip)?3:1.6)+'"/>';
    s+='<circle cx="'+p.x+'" cy="'+p.y+'" r="4" fill="'+fill+'"/>';
    s+='<text x="'+p.x+'" y="'+(p.y-22)+'" fill="#aebbe6" text-anchor="middle" font-size="11">'+litStr(n.lit)+'</text>';
    s+='<text x="'+p.x+'" y="'+(p.y+28)+'" fill="#56618c" text-anchor="middle" font-size="9">L'+n.level+'</text>';
  }
  if(uip!=null) s+='<text x="400" y="20" fill="#7cf0c4" text-anchor="middle" font-size="12">1-UIP: '+litStr(uip)+'  →  learn '+clStr(st.lastLearn.clause)+'</text>';
  svg.innerHTML=s;
}

function renderLearned(st){
  const box=$("#learned");
  if(st.learned.length===0){ box.innerHTML='<div style="color:var(--mut)">none yet</div>'; return; }
  const newest=st.learned.length-1;
  let h="";
  for(let i=st.learned.length-1;i>=0 && i>st.learned.length-40;i--){
    h+='<div class="lc'+(i===newest && st.cur && st.cur.t==="learn"?' new':'')+'">#'+(i+1)+'  '+clStr(st.learned[i])+'</div>';
  }
  box.innerHTML=h;
}

function renderStats(st){
  const s=SOLVER.stats; const assigned=st.trail.length;
  const rows=[["decisions",s.decisions],["propagations",s.propagations],["conflicts",s.conflicts],
    ["learned clauses",s.learned],["restarts",s.restarts],["max level",s.maxLevel],
    ["original clauses",INST.clauses.length],["variables",INST.numVars],
    ["assigned now",assigned+" / "+INST.numVars]];
  $("#stats").innerHTML=rows.map(r=>'<div class="stat"><span>'+r[0]+'</span><b>'+r[1]+'</b></div>').join("");
}

function renderBars(st){
  const act=SOLVER.activity; const arr=[];
  for(let v=1;v<act.length;v++) arr.push([v,act[v]]);
  arr.sort((a,b)=>b[1]-a[1]);
  const top=arr.slice(0,14); const mx=top.length?Math.max(top[0][1],1e-9):1;
  $("#bars").innerHTML=top.map(([v,a])=>
    '<div class="bar"><span class="n">x'+v+'</span><span class="t" style="width:'+(8+92*a/mx)+'%"></span></div>').join("");
}

/* ---------- sudoku view ---------- */
function setupSudoku(){
  const show = INST && INST.kind==="sudoku";
  $("#sudoku-wrap").classList.toggle("hide", !show);
  if(!show) return;
  const grid=$("#sudoku"); let h="";
  for(let r=0;r<9;r++)for(let c=0;c<9;c++){
    const border=((c%3===2&&c<8)||(r%3===2&&r<8))?" b":"";
    h+='<div class="sc'+border+'" id="sc'+(r*9+c)+'"></div>';
  }
  grid.innerHTML=h;
}
function renderSudoku(st){
  if(!INST || INST.kind!=="sudoku") return;
  const g=INST.givens; const val=new Array(81).fill(0);
  for(const a of st.trail){ if(a.lit>0){ const v=a.lit-1; const d=v%9+1; const cell=Math.floor(v/9); val[cell]=d; } }
  for(let i=0;i<81;i++){
    const el=document.getElementById('sc'+i); if(!el)continue;
    if(g[i]){ el.textContent=g[i]; el.className='sc given'+(borderCls(i)); }
    else if(val[i]){ el.textContent=val[i]; el.className='sc fill'+(borderCls(i)); }
    else { el.textContent=''; el.className='sc'+(borderCls(i)); }
  }
}
function borderCls(i){const r=Math.floor(i/9),c=i%9;return ((c%3===2&&c<8)||(r%3===2&&r<8))?' b':'';}

/* ---------- transport ---------- */
function stop(){ if(timer){clearInterval(timer);timer=null;$("#play").textContent="▶";} }
function play(){
  if(timer){stop();return;}
  if(idx>=TRACE.length) idx=0;
  $("#play").textContent="⏸";
  const fps=+$("#speed").value;
  timer=setInterval(()=>{ if(idx>=TRACE.length){stop();return;} idx++; render(); }, 1000/fps);
}
$("#build").onclick=()=>{ stop(); run(); };
$("#first").onclick=()=>{ stop(); idx=0; render(); };
$("#last").onclick=()=>{ stop(); idx=TRACE.length; render(); };
$("#back").onclick=()=>{ stop(); idx=Math.max(0,idx-1); render(); };
$("#fwd").onclick=()=>{ stop(); idx=Math.min(TRACE.length,idx+1); render(); };
$("#play").onclick=play;
$("#scrub").oninput=e=>{ stop(); idx=+e.target.value; render(); };

/* keyboard: space=play/pause, ←/→ step, home/end jump */
document.addEventListener("keydown", e=>{
  if(["INPUT","TEXTAREA","SELECT"].includes(document.activeElement.tagName)) return;
  if(e.key===" "){ e.preventDefault(); play(); }
  else if(e.key==="ArrowRight"){ stop(); idx=Math.min(TRACE.length,idx+1); render(); }
  else if(e.key==="ArrowLeft"){ stop(); idx=Math.max(0,idx-1); render(); }
  else if(e.key==="Home"){ stop(); idx=0; render(); }
  else if(e.key==="End"){ stop(); idx=TRACE.length; render(); }
});

/* show/hide param panels */
$("#kind").onchange=()=>{
  for(const k of ["rand","php","color","sudoku","dimacs"])
    $("#p-"+k).classList.toggle("hide", $("#kind").value!==k);
};

run();   // auto-run default instance
</script>
</body>
</html>
"""
