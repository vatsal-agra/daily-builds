"""Emit a self-contained, dependency-free HTML viewer for an annotated game.

The viewer renders the board from FEN in the browser (no engine logic needed),
animates a full engine-vs-engine game move by move, and shows an eval graph,
SAN movelist, captured-material tray and keyboard scrubbing.
"""

from __future__ import annotations

import json


def _build_positions(game: dict) -> list:
    """List of {fen, san, score_w, last} for each ply, position 0 = start."""
    positions = [{"fen": game["start_fen"], "san": None, "score_w": None,
                  "from": None, "to": None, "side": None}]
    for m in game["moves"]:
        score_w = m["score"] if m["side"] == "w" else -m["score"]
        positions.append({
            "fen": m["fen_after"],
            "san": m["san"],
            "score_w": score_w,
            "from": m["uci"][:2],
            "to": m["uci"][2:4],
            "side": m["side"],
            "depth": m["depth"],
            "nodes": m["nodes"],
        })
    return positions


def write_viz(game: dict, path: str = "game.html") -> str:
    data = {
        "result": game["result"],
        "positions": _build_positions(game),
    }
    html = _HTML.replace("/*__DATA__*/", json.dumps(data))
    with open(path, "w") as f:
        f.write(html)
    return path


_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Gambit — game viewer</title>
<style>
  :root{
    --bg:#11151c; --panel:#1b2230; --ink:#e8edf6; --muted:#8b97ad;
    --light:#e9e0cf; --dark:#7d9061; --accent:#f2c14e; --hi:#f6e58d;
    --good:#7bdc8a; --bad:#ef6f6c; --line:#2a3344;
  }
  *{box-sizing:border-box}
  body{margin:0;background:radial-gradient(1200px 700px at 70% -10%,#1d2740,#0c0f15);
    color:var(--ink);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;}
  .wrap{max-width:1040px;margin:0 auto;padding:28px 20px 60px}
  h1{font-weight:700;letter-spacing:.4px;margin:0 0 2px}
  h1 .q{color:var(--accent)}
  .sub{color:var(--muted);margin:0 0 22px}
  .grid{display:grid;grid-template-columns:auto 1fr;gap:26px;align-items:start}
  @media(max-width:820px){.grid{grid-template-columns:1fr}}
  .boardwrap{display:flex;gap:10px}
  .evalbar{width:16px;border-radius:8px;overflow:hidden;background:#0a0d12;
    border:1px solid var(--line);position:relative;height:480px}
  .evalbar .w{position:absolute;left:0;right:0;bottom:0;background:linear-gradient(#fff,#d8d8d8);transition:height .25s}
  .board{width:480px;height:480px;display:grid;grid-template-columns:repeat(8,1fr);
    grid-template-rows:repeat(8,1fr);border-radius:10px;overflow:hidden;
    box-shadow:0 14px 40px rgba(0,0,0,.5)}
  .sq{position:relative;display:flex;align-items:center;justify-content:center;
    font-size:40px;line-height:1;user-select:none}
  .sq.l{background:var(--light)} .sq.d{background:var(--dark)}
  .sq .pc{filter:drop-shadow(0 2px 1px rgba(0,0,0,.35))}
  .sq.wpiece .pc{color:#f7fbff;text-shadow:0 0 2px #000,0 1px 2px #0008}
  .sq.bpiece .pc{color:#141a22}
  .sq.hi::after{content:"";position:absolute;inset:0;background:var(--hi);opacity:.45;mix-blend-mode:multiply}
  .sq .co{position:absolute;font-size:10px;color:#0006;font-weight:700}
  .sq .co.f{right:3px;bottom:1px} .sq .co.r{left:3px;top:1px}
  .panel{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px 18px;margin-bottom:16px}
  .scoreline{display:flex;align-items:baseline;gap:12px;margin-bottom:8px}
  .scoreline .big{font-size:30px;font-weight:800}
  .scoreline .meta{color:var(--muted);font-size:13px}
  .controls{display:flex;gap:8px;margin:8px 0 4px}
  button{background:#243049;color:var(--ink);border:1px solid var(--line);
    border-radius:9px;padding:9px 13px;font-size:15px;cursor:pointer;transition:.12s}
  button:hover{background:#2e3c5a;border-color:#46587f}
  button:active{transform:translateY(1px)}
  .moves{max-height:230px;overflow:auto;font-variant-numeric:tabular-nums}
  .moves table{width:100%;border-collapse:collapse}
  .moves td{padding:3px 8px;border-radius:6px;cursor:pointer}
  .moves td.n{color:var(--muted);width:34px;text-align:right;cursor:default}
  .moves td.m:hover{background:#243049}
  .moves td.active{background:var(--accent);color:#12151b;font-weight:700}
  .trays{display:flex;justify-content:space-between;font-size:26px;line-height:1;margin-top:6px;min-height:30px}
  .trays .lbl{font-size:12px;color:var(--muted);display:block;margin-bottom:2px}
  svg{display:block;width:100%;height:120px}
  .legend{color:var(--muted);font-size:12px;margin-top:4px}
  code{background:#0c0f15;border:1px solid var(--line);padding:1px 6px;border-radius:6px;color:#cfe}
</style>
</head>
<body>
<div class="wrap">
  <h1>Gambit <span class="q">&#9819;</span> game viewer</h1>
  <p class="sub">Engine vs engine &mdash; result <b id="result"></b>. Use
     <code>&larr;</code> / <code>&rarr;</code>, <code>Home</code>/<code>End</code>,
     or <code>Space</code> to play.</p>
  <div class="grid">
    <div>
      <div class="boardwrap">
        <div class="evalbar"><div class="w" id="evalw" style="height:50%"></div></div>
        <div class="board" id="board"></div>
      </div>
      <div class="trays panel">
        <div><span class="lbl">White captured</span><span id="capW"></span></div>
        <div style="text-align:right"><span class="lbl">Black captured</span><span id="capB"></span></div>
      </div>
    </div>
    <div>
      <div class="panel">
        <div class="scoreline">
          <span class="big" id="score">--</span>
          <span class="meta" id="movemeta"></span>
        </div>
        <svg id="graph" viewBox="0 0 400 120" preserveAspectRatio="none"></svg>
        <div class="legend">Evaluation over the game (white&rsquo;s perspective, &plusmn;10 pawns clamped).</div>
        <div class="controls">
          <button onclick="go(0)">&#124;&laquo;</button>
          <button onclick="step(-1)">&laquo;</button>
          <button id="playbtn" onclick="toggle()">&#9654; play</button>
          <button onclick="step(1)">&raquo;</button>
          <button onclick="go(LAST)">&raquo;&#124;</button>
        </div>
      </div>
      <div class="panel">
        <div class="moves" id="moves"></div>
      </div>
    </div>
  </div>
</div>
<script>
const DATA = /*__DATA__*/;
const POS = DATA.positions;
const LAST = POS.length - 1;
const GLYPH = {p:'♟',n:'♞',b:'♝',r:'♜',q:'♛',k:'♚'};
let cur = 0, timer = null;

function parseFEN(fen){
  const rows = fen.split(' ')[0].split('/');
  const grid = [];           // grid[rank0..7][file0..7], rank0 = rank1
  for(let i=0;i<8;i++){
    const rank = 7 - i, row = rows[i]; let file = 0;
    grid[rank] = grid[rank] || [];
    for(const ch of row){
      if(/\d/.test(ch)){ for(let k=0;k<+ch;k++) grid[rank][file++] = null; }
      else { grid[rank][file++] = ch; }
    }
  }
  return grid;
}
function startCount(){
  const c={}; for(const k of 'pnbrq') c['w'+k]=0,c['b'+k]=0;
  const init='rnbqkbnrpppppppp'; // not used directly
  return c;
}
function pieceCounts(fen){
  const c={}; for(const ch of fen.split(' ')[0]) if(/[a-zA-Z]/.test(ch)){
    const col = ch===ch.toUpperCase()?'w':'b'; const t=col+ch.toLowerCase();
    c[t]=(c[t]||0)+1;
  } return c;
}
const FULL={p:8,n:2,b:2,r:2,q:1};
function captured(fen){
  const c=pieceCounts(fen); const out={w:'',b:''};
  for(const col of ['w','b']){
    for(const t of ['q','r','b','n','p']){
      const missing = FULL[t]-(c[col+t]||0);
      // captured BY the opponent of `col`: show under opponent tray
      for(let i=0;i<missing;i++) out[col==='w'?'b':'w']+=GLYPH[t];
    }
  }
  return out;
}

function render(){
  const p = POS[cur];
  const grid = parseFEN(p.fen);
  const b = document.getElementById('board'); b.innerHTML='';
  for(let i=0;i<8;i++){
    const rank = 7 - i;
    for(let file=0;file<8;file++){
      const sq=document.createElement('div');
      const light=(rank+file)%2===1;
      sq.className='sq '+(light?'l':'d');
      const name='abcdefgh'[file]+(rank+1);
      if(p.from===name||p.to===name) sq.classList.add('hi');
      const pc=grid[rank][file];
      if(pc){
        const col = pc===pc.toUpperCase()?'w':'b';
        sq.classList.add(col==='w'?'wpiece':'bpiece');
        const span=document.createElement('span'); span.className='pc';
        span.textContent=GLYPH[pc.toLowerCase()]; sq.appendChild(span);
      }
      if(file===0){const co=document.createElement('span');co.className='co r';co.textContent=rank+1;sq.appendChild(co);}
      if(rank===0){const co=document.createElement('span');co.className='co f';co.textContent='abcdefgh'[file];sq.appendChild(co);}
      b.appendChild(sq);
    }
  }
  // score + eval bar
  const sc = p.score_w;
  const scoreEl=document.getElementById('score');
  if(cur===0){scoreEl.textContent='start'; setBar(0);}
  else { scoreEl.textContent=fmt(sc); scoreEl.style.color = sc>30?'var(--good)':sc<-30?'var(--bad)':'var(--ink)'; setBar(sc); }
  document.getElementById('movemeta').textContent =
    cur===0 ? '' : `${moveLabel(cur)} ${p.san}  ·  depth ${p.depth} · ${p.nodes.toLocaleString()} nodes`;
  // captured trays
  const cap=captured(p.fen);
  document.getElementById('capW').textContent=cap.w||'—';
  document.getElementById('capB').textContent=cap.b||'—';
  // active move highlight
  document.querySelectorAll('.moves td.m').forEach(td=>td.classList.toggle('active',+td.dataset.ply===cur));
  const act=document.querySelector('.moves td.active'); if(act) act.scrollIntoView({block:'nearest'});
}
function setBar(sc){
  const clamped=Math.max(-1000,Math.min(1000,sc));
  const pct = 50 + clamped/20; // +-10 pawns -> 0..100
  document.getElementById('evalw').style.height=pct+'%';
}
function fmt(cp){
  if(cp>29000) return '#'+Math.ceil((30000-cp)/2+0.0001);
  if(cp<-29000) return '#-'+Math.ceil((30000+cp)/2+0.0001);
  return (cp>=0?'+':'')+(cp/100).toFixed(2);
}
function moveLabel(ply){
  const n=Math.floor((ply-1)/2)+1; return POS[ply].side==='w'?n+'.':n+'...';
}
function buildMoves(){
  const m=document.getElementById('moves'); let html='<table>';
  for(let i=1;i<POS.length;i+=2){
    const num=(i-1)/2+1;
    const w=POS[i], bk=POS[i+1];
    html+=`<tr><td class="n">${num}.</td>`+
      `<td class="m" data-ply="${i}" onclick="go(${i})">${w.san}</td>`+
      (bk?`<td class="m" data-ply="${i+1}" onclick="go(${i+1})">${bk.san}</td>`:'<td></td>')+
      '</tr>';
  }
  html+='</table>'; m.innerHTML=html;
}
function buildGraph(){
  const svg=document.getElementById('graph');
  const W=400,H=120,mid=H/2;
  const pts=[]; for(let i=1;i<POS.length;i++){
    const x = (i-1)/(Math.max(1,LAST-1))*W;
    const c=Math.max(-1000,Math.min(1000,POS[i].score_w));
    const y = mid - c/1000*(mid-4);
    pts.push([x,y]);
  }
  let path='', area='';
  pts.forEach((p,i)=>{ path+=(i?'L':'M')+p[0].toFixed(1)+' '+p[1].toFixed(1)+' '; });
  if(pts.length){ area='M0 '+mid+' '+pts.map(p=>'L'+p[0].toFixed(1)+' '+p[1].toFixed(1)).join(' ')+' L'+W+' '+mid+' Z'; }
  svg.innerHTML =
    `<line x1="0" y1="${mid}" x2="${W}" y2="${mid}" stroke="var(--line)"/>`+
    `<path d="${area}" fill="var(--accent)" opacity="0.10"/>`+
    `<path d="${path}" fill="none" stroke="var(--accent)" stroke-width="2"/>`+
    `<line id="cursor" x1="0" y1="0" x2="0" y2="${H}" stroke="#fff6" stroke-dasharray="3 3"/>`;
}
function moveCursor(){
  const c=document.getElementById('cursor'); if(!c) return;
  const x = cur<=1?0:(cur-1)/(Math.max(1,LAST-1))*400;
  c.setAttribute('x1',x); c.setAttribute('x2',x);
}
function go(i){ cur=Math.max(0,Math.min(LAST,i)); render(); moveCursor(); }
function step(d){ stop(); go(cur+d); }
function toggle(){ timer?stop():play(); }
function play(){ if(cur>=LAST) cur=0; document.getElementById('playbtn').innerHTML='&#10073;&#10073; pause';
  timer=setInterval(()=>{ if(cur>=LAST){stop();return;} go(cur+1); },650); }
function stop(){ if(timer){clearInterval(timer);timer=null;} document.getElementById('playbtn').innerHTML='&#9654; play'; }
document.addEventListener('keydown',e=>{
  if(e.key==='ArrowRight'){step(1);e.preventDefault();}
  else if(e.key==='ArrowLeft'){step(-1);e.preventDefault();}
  else if(e.key==='Home'){step(0);go(0);}
  else if(e.key==='End'){stop();go(LAST);}
  else if(e.key===' '){toggle();e.preventDefault();}
});
document.getElementById('result').textContent=DATA.result;
buildMoves(); buildGraph(); render();
</script>
</body>
</html>"""
