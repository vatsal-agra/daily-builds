"""Standalone HTML visualizers for Cotangent.

Two artifacts, both single self-contained HTML files (no external assets, no
build step, open directly in a browser):

1. ``graph_html`` — renders a computation DAG with each node's forward value and
   backward gradient. Custom layered layout in pure Python → SVG/JS (no Graphviz).
2. ``playground_html`` — an interactive training playground: scrub a timeline to
   watch a real-trained decision boundary morph, alongside the loss/accuracy curve.
"""

from __future__ import annotations

import html
import json

from engine import Value


# --------------------------------------------------------------------------- #
# Computation-graph layout                                                     #
# --------------------------------------------------------------------------- #
def _layered_layout(root: Value) -> dict:
    """Assign each node a layer (longest path from any leaf) for left→right flow."""
    order = root.topo()  # inputs first
    depth: dict[int, int] = {}
    for v in order:
        if not v._prev:
            depth[id(v)] = 0
        else:
            depth[id(v)] = 1 + max(depth[id(c)] for c in v._prev)
    # group nodes by layer
    layers: dict[int, list[Value]] = {}
    for v in order:
        layers.setdefault(depth[id(v)], []).append(v)
    return {"order": order, "depth": depth, "layers": layers}


def graph_to_dict(root: Value) -> dict:
    """Serialize the graph (with values/grads) to a JSON-able dict for the page."""
    root.backward()  # ensure grads are populated
    info = _layered_layout(root)
    order = info["order"]
    depth = info["depth"]
    layers = info["layers"]

    idmap = {id(v): i for i, v in enumerate(order)}
    n_layers = max(layers) + 1
    col_w = 200
    row_h = 90
    nodes = []
    for L in range(n_layers):
        col = layers.get(L, [])
        for row, v in enumerate(col):
            label = v.label or (v._op if v._op else "const")
            nodes.append({
                "id": idmap[id(v)],
                "x": 90 + L * col_w,
                "y": 70 + row * row_h,
                "data": round(v.data, 4),
                "grad": round(v.grad, 4),
                "op": v._op or "",
                "label": label,
                "leaf": not v._prev,
            })
    edges = []
    for v in order:
        for c in v._prev:
            edges.append({"from": idmap[id(c)], "to": idmap[id(v)]})

    width = 180 + n_layers * col_w
    max_rows = max((len(c) for c in layers.values()), default=1)
    height = 140 + max_rows * row_h
    return {"nodes": nodes, "edges": edges, "width": width, "height": height}


def graph_html(root: Value, title: str = "Cotangent — computation graph",
               expr: str = "") -> str:
    data = graph_to_dict(root)
    payload = json.dumps(data)
    return _GRAPH_TEMPLATE.replace("__TITLE__", html.escape(title)) \
                          .replace("__EXPR__", html.escape(expr)) \
                          .replace("__DATA__", payload)


# --------------------------------------------------------------------------- #
# Training playground                                                          #
# --------------------------------------------------------------------------- #
def playground_html(history: dict, X, y, box, dataset: str, model_repr: str,
                    title: str = "Cotangent — training playground") -> str:
    payload = json.dumps({
        "snapshots": history["snapshots"],
        "snapshot_epochs": history["snapshot_epochs"],
        "loss": history["loss"],
        "acc": history["acc"],
        "points": [{"x": p[0], "y": p[1], "c": int(c)} for p, c in zip(X, y)],
        "box": list(box),
        "dataset": dataset,
        "model": model_repr,
    })
    return _PLAY_TEMPLATE.replace("__TITLE__", html.escape(title)) \
                         .replace("__DATA__", payload)


# --------------------------------------------------------------------------- #
# Templates                                                                    #
# --------------------------------------------------------------------------- #
_GRAPH_TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
  :root{--bg:#0d1117;--panel:#161b22;--ink:#e6edf3;--mut:#8b949e;
        --val:#58a6ff;--grad:#f778ba;--leaf:#1f6feb;--op:#238636;--edge:#30363d;}
  *{box-sizing:border-box}
  body{margin:0;background:radial-gradient(1200px 600px at 20% -10%,#16202c,#0d1117);
       color:var(--ink);font:15px/1.5 ui-sans-serif,system-ui,Segoe UI,Roboto,Helvetica,Arial}
  header{padding:18px 26px;border-bottom:1px solid var(--edge);
         display:flex;align-items:baseline;gap:16px;flex-wrap:wrap}
  h1{font-size:18px;margin:0;letter-spacing:.3px}
  .expr{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--mut);
        background:var(--panel);padding:4px 10px;border-radius:6px;border:1px solid var(--edge)}
  .legend{margin-left:auto;display:flex;gap:16px;color:var(--mut);font-size:13px}
  .legend b{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:5px;vertical-align:-1px}
  .wrap{overflow:auto;padding:18px}
  svg{display:block}
  .node rect{rx:10;ry:10;stroke-width:1.5}
  .node .lbl{font:600 13px ui-monospace,Menlo,monospace;fill:var(--ink)}
  .node .op{font:11px ui-sans-serif;fill:var(--mut)}
  .node .v{font:12px ui-monospace,Menlo,monospace;fill:var(--val)}
  .node .g{font:12px ui-monospace,Menlo,monospace;fill:var(--grad)}
  .edge{stroke:var(--edge);stroke-width:1.6;fill:none;marker-end:url(#arrow)}
  .hint{color:var(--mut);font-size:13px;padding:0 26px 18px}
</style></head>
<body>
<header>
  <h1>Cotangent · computation graph</h1>
  <span class="expr">__EXPR__</span>
  <div class="legend">
    <span><b style="background:var(--val)"></b>forward value</span>
    <span><b style="background:var(--grad)"></b>gradient ∂out/∂node</span>
    <span><b style="background:var(--leaf)"></b>leaf / input</span>
  </div>
</header>
<div class="wrap"><div id="canvas"></div></div>
<div class="hint">Each box is a node: top line is its label/op, blue is the forward
value, pink is the gradient computed by the reverse pass. Arrows point inputs → output.</div>
<script>
const G = __DATA__;
function draw(){
  const xmlns="http://www.w3.org/2000/svg";
  const svg=document.createElementNS(xmlns,"svg");
  svg.setAttribute("width",G.width); svg.setAttribute("height",G.height);
  svg.innerHTML=`<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5"
     markerWidth="7" markerHeight="7" orient="auto-start-end">
     <path d="M0,0 L10,5 L0,10 z" fill="#30363d"/></marker></defs>`;
  const pos={}; G.nodes.forEach(n=>pos[n.id]=n);
  const W=150,H=58;
  // edges first
  G.edges.forEach(e=>{
    const a=pos[e.from], b=pos[e.to];
    const x1=a.x+W, y1=a.y+H/2, x2=b.x, y2=b.y+H/2;
    const mx=(x1+x2)/2;
    const p=document.createElementNS(xmlns,"path");
    p.setAttribute("class","edge");
    p.setAttribute("d",`M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`);
    svg.appendChild(p);
  });
  // nodes
  G.nodes.forEach(n=>{
    const g=document.createElementNS(xmlns,"g"); g.setAttribute("class","node");
    const r=document.createElementNS(xmlns,"rect");
    r.setAttribute("x",n.x); r.setAttribute("y",n.y);
    r.setAttribute("width",W); r.setAttribute("height",H);
    r.setAttribute("rx",10); r.setAttribute("ry",10);
    r.setAttribute("fill",n.leaf?"#10243e":"#161b22");
    r.setAttribute("stroke",n.leaf?"#1f6feb":"#30363d");
    g.appendChild(r);
    const head=n.label + (n.op&&n.op!==n.label?`  (${n.op})`:"");
    const t1=document.createElementNS(xmlns,"text");
    t1.setAttribute("class","lbl"); t1.setAttribute("x",n.x+12); t1.setAttribute("y",n.y+20);
    t1.textContent=head; g.appendChild(t1);
    const t2=document.createElementNS(xmlns,"text");
    t2.setAttribute("class","v"); t2.setAttribute("x",n.x+12); t2.setAttribute("y",n.y+37);
    t2.textContent="val "+n.data; g.appendChild(t2);
    const t3=document.createElementNS(xmlns,"text");
    t3.setAttribute("class","g"); t3.setAttribute("x",n.x+12); t3.setAttribute("y",n.y+52);
    t3.textContent="grad "+n.grad; g.appendChild(t3);
    svg.appendChild(g);
  });
  document.getElementById("canvas").appendChild(svg);
}
draw();
</script>
</body></html>"""


_PLAY_TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
  :root{--bg:#0d1117;--panel:#161b22;--ink:#e6edf3;--mut:#8b949e;--acc:#58a6ff;
        --c0:#f778ba;--c1:#3fb950;--edge:#30363d;}
  *{box-sizing:border-box}
  body{margin:0;background:radial-gradient(1200px 700px at 80% -10%,#161f2c,#0d1117);
       color:var(--ink);font:15px/1.5 ui-sans-serif,system-ui,Segoe UI,Roboto,Arial}
  header{padding:18px 26px;border-bottom:1px solid var(--edge)}
  h1{font-size:18px;margin:0 0 4px}
  .sub{color:var(--mut);font-size:13px}
  .grid{display:grid;grid-template-columns:minmax(360px,1fr) 360px;gap:22px;padding:22px;align-items:start}
  @media(max-width:820px){.grid{grid-template-columns:1fr}}
  .card{background:var(--panel);border:1px solid var(--edge);border-radius:12px;padding:16px}
  .card h2{font-size:13px;margin:0 0 10px;color:var(--mut);text-transform:uppercase;letter-spacing:.6px}
  canvas{width:100%;height:auto;display:block;border-radius:8px;background:#0b0f14}
  .controls{display:flex;align-items:center;gap:12px;margin-top:14px}
  button{background:#21262d;color:var(--ink);border:1px solid var(--edge);
         border-radius:8px;padding:8px 14px;cursor:pointer;font-size:14px}
  button:hover{border-color:var(--acc)}
  input[type=range]{flex:1;accent-color:var(--acc)}
  .stat{display:flex;justify-content:space-between;font-family:ui-monospace,Menlo,monospace;
        font-size:13px;padding:3px 0;border-bottom:1px dashed var(--edge)}
  .stat span:last-child{color:var(--acc)}
  .legend{display:flex;gap:18px;font-size:13px;color:var(--mut);margin-top:8px}
  .legend b{display:inline-block;width:11px;height:11px;border-radius:50%;margin-right:6px;vertical-align:-1px}
</style></head>
<body>
<header>
  <h1>Cotangent · training playground</h1>
  <div class="sub" id="sub"></div>
</header>
<div class="grid">
  <div class="card">
    <h2>Decision boundary</h2>
    <canvas id="board" width="520" height="520"></canvas>
    <div class="controls">
      <button id="play">▶ Play</button>
      <input type="range" id="scrub" min="0" value="0" step="1">
      <span id="epoch" style="font-family:ui-monospace,Menlo,monospace;color:var(--acc)"></span>
    </div>
    <div class="legend">
      <span><b style="background:var(--c0)"></b>class 0</span>
      <span><b style="background:var(--c1)"></b>class 1</span>
      <span>shaded = model confidence</span>
    </div>
  </div>
  <div class="card">
    <h2>Metrics</h2>
    <canvas id="curve" width="320" height="200"></canvas>
    <div id="stats"></div>
  </div>
</div>
<script>
const D = __DATA__;
document.getElementById('sub').textContent =
  `dataset: ${D.dataset}  ·  ${D.model}  ·  ${D.snapshots.length} snapshots over ${D.loss.length} epochs`;

const board=document.getElementById('board'), bx=board.getContext('2d');
const curve=document.getElementById('curve'), cx=curve.getContext('2d');
const scrub=document.getElementById('scrub'); scrub.max=D.snapshots.length-1;
const epEl=document.getElementById('epoch');
const [xmin,xmax,ymin,ymax]=D.box;
const W=board.width,H=board.height;

function lerp(a,b,t){return a+(b-a)*t;}
// blend between class0 (pink) and class1 (green) by probability p (=P(class1))
function shade(p){
  const c0=[247,120,186], c1=[63,185,80];
  const r=Math.round(lerp(c0[0],c1[0],p));
  const g=Math.round(lerp(c0[1],c1[1],p));
  const b=Math.round(lerp(c0[2],c1[2],p));
  const a=0.18+0.30*Math.abs(p-0.5)*2; // stronger where confident
  return `rgba(${r},${g},${b},${a})`;
}
function toPx(x,y){
  return [ (x-xmin)/(xmax-xmin)*W, H-(y-ymin)/(ymax-ymin)*H ];
}
function drawBoard(k){
  bx.clearRect(0,0,W,H);
  const grid=D.snapshots[k]; const res=grid.length;
  const cw=W/res, ch=H/res;
  for(let j=0;j<res;j++)for(let i=0;i<res;i++){
    bx.fillStyle=shade(grid[j][i]);
    bx.fillRect(i*cw, H-(j+1)*ch, cw+1, ch+1);
  }
  // decision boundary contour at p=0.5 (simple threshold cell edges)
  // points
  D.points.forEach(pt=>{
    const [px,py]=toPx(pt.x,pt.y);
    bx.beginPath(); bx.arc(px,py,4,0,7);
    bx.fillStyle = pt.c? '#3fb950':'#f778ba';
    bx.strokeStyle='rgba(0,0,0,.6)'; bx.lineWidth=1.2;
    bx.fill(); bx.stroke();
  });
  const ep=D.snapshot_epochs[k];
  epEl.textContent=`epoch ${ep}`;
  // metrics up to this epoch
  const li=Math.min(ep, D.loss.length-1);
  drawCurve(li);
  const acc=(D.acc[li]*100).toFixed(1), loss=D.loss[li].toFixed(4);
  document.getElementById('stats').innerHTML=
    `<div class="stat"><span>epoch</span><span>${ep}</span></div>`+
    `<div class="stat"><span>loss</span><span>${loss}</span></div>`+
    `<div class="stat"><span>accuracy</span><span>${acc}%</span></div>`+
    `<div class="stat"><span>final accuracy</span><span>${(D.acc[D.acc.length-1]*100).toFixed(1)}%</span></div>`;
}
function drawCurve(upto){
  const w=curve.width,h=curve.height,pad=24;
  cx.clearRect(0,0,w,h);
  const n=D.loss.length;
  const maxLoss=Math.max(...D.loss,1e-6);
  // axes
  cx.strokeStyle='#30363d'; cx.lineWidth=1;
  cx.beginPath(); cx.moveTo(pad,4); cx.lineTo(pad,h-pad); cx.lineTo(w-4,h-pad); cx.stroke();
  function plot(arr,scaleMax,color){
    cx.strokeStyle=color; cx.lineWidth=2; cx.beginPath();
    for(let i=0;i<n;i++){
      const x=pad+(w-pad-6)*i/Math.max(n-1,1);
      const y=(h-pad)-(h-pad-6)*(arr[i]/scaleMax);
      i?cx.lineTo(x,y):cx.moveTo(x,y);
    }
    cx.stroke();
  }
  plot(D.loss,maxLoss,'#f778ba');
  plot(D.acc,1.0,'#58a6ff');
  // marker at current epoch
  if(upto>=0){
    const x=pad+(w-pad-6)*upto/Math.max(n-1,1);
    cx.strokeStyle='rgba(255,255,255,.35)'; cx.setLineDash([3,3]);
    cx.beginPath(); cx.moveTo(x,4); cx.lineTo(x,h-pad); cx.stroke(); cx.setLineDash([]);
  }
  cx.fillStyle='#8b949e'; cx.font='10px ui-monospace';
  cx.fillText('loss',pad+4,12); cx.fillStyle='#58a6ff'; cx.fillText('acc',pad+34,12);
}
scrub.oninput=()=>{ stop(); drawBoard(+scrub.value); };
let timer=null;
function stop(){ if(timer){clearInterval(timer);timer=null; document.getElementById('play').textContent='▶ Play';} }
document.getElementById('play').onclick=()=>{
  if(timer){stop();return;}
  document.getElementById('play').textContent='⏸ Pause';
  timer=setInterval(()=>{
    let k=+scrub.value+1;
    if(k>=D.snapshots.length){ k=0; }
    scrub.value=k; drawBoard(k);
    if(k===D.snapshots.length-1){ stop(); }
  },220);
};
drawBoard(0);
</script>
</body></html>"""
