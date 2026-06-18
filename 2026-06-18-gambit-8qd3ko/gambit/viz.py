"""Generate a self-contained HTML viewer that replays an engine self-play game:
an interactive board, SAN move list, evaluation graph, and PV readout. No
external assets or libraries — everything is inlined."""

import json

from .engine import self_play, to_pgn
from .eval import MATE_THRESHOLD, MATE


def _eval_label(cp):
    if cp > MATE_THRESHOLD:
        return f"#{(MATE - cp + 1) // 2}"
    if cp < -MATE_THRESHOLD:
        return f"#-{(MATE + cp + 1) // 2}"
    return f"{cp/100:+.2f}"


def generate_viz(out_path, depth=4, max_moves=60, movetime=None):
    print(f"Playing a self-play game (depth {depth}, up to {max_moves} "
          f"moves)...")
    board, sans, result, reason, evals, fens = self_play(
        depth=depth, movetime=movetime, max_moves=max_moves, verbose=False)
    print(f"  game finished: {result} ({reason}), {len(sans)} plies")

    # clamp evals for the graph; keep mate scores as large signed values
    graph = []
    for e in evals:
        if e > MATE_THRESHOLD:
            graph.append(1000)
        elif e < -MATE_THRESHOLD:
            graph.append(-1000)
        else:
            graph.append(max(-1000, min(1000, e)))

    data = {
        "fens": fens,
        "sans": sans,
        "evals": evals,
        "labels": [_eval_label(e) for e in evals],
        "graph": graph,
        "result": result,
        "reason": reason,
        "pgn": to_pgn(sans, result),
    }
    html = _HTML_TEMPLATE.replace("/*DATA*/", json.dumps(data))
    with open(out_path, "w") as f:
        f.write(html)
    return out_path


_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Gambit — Self-Play Replay</title>
<style>
  :root {
    --bg:#11131a; --panel:#1b1e29; --panel2:#232737; --ink:#e8ebf5;
    --muted:#8b93ad; --accent:#7aa2ff; --light:#e9e2cf; --dark:#7c6a52;
    --hl:#f6d365; --hl2:rgba(246,211,101,.35); --good:#5ad19a; --bad:#ff6b81;
    --line:#2c3146;
  }
  * { box-sizing:border-box; }
  body {
    margin:0; background:radial-gradient(1200px 600px at 30% -10%,#1a1f30,#0c0e15);
    color:var(--ink); font:15px/1.5 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
    min-height:100vh;
  }
  header { padding:22px 28px 8px; }
  h1 { margin:0; font-size:24px; letter-spacing:.3px; }
  h1 .g { color:var(--accent); }
  .sub { color:var(--muted); font-size:13px; margin-top:3px; }
  .wrap {
    display:grid; grid-template-columns:auto 360px; gap:24px;
    padding:14px 28px 40px; align-items:start; max-width:1100px;
  }
  @media (max-width:880px){ .wrap{ grid-template-columns:1fr; } }
  .boardcard { background:var(--panel); border-radius:16px; padding:18px;
    box-shadow:0 10px 40px rgba(0,0,0,.35); }
  .board { display:grid; grid-template-columns:repeat(8,1fr);
    width:min(72vw,520px); aspect-ratio:1/1; border-radius:8px; overflow:hidden;
    border:1px solid #0006; }
  .sq { display:flex; align-items:center; justify-content:center;
    position:relative; font-size:calc(min(72vw,520px)/11); line-height:1;
    user-select:none; }
  .sq.l { background:var(--light); } .sq.d { background:var(--dark); }
  .sq.from::after,.sq.to::after { content:""; position:absolute; inset:0;
    background:var(--hl2); }
  .sq .co { position:absolute; font-size:10px; color:#0007; font-weight:700; }
  .sq .co.f { right:3px; bottom:1px; } .sq .co.r { left:3px; top:1px; }
  .piece.w { color:#fff; text-shadow:0 1px 1px #0006,0 0 2px #0008; }
  .piece.b { color:#1a1a1a; text-shadow:0 1px 0 #fff3; }
  .controls { display:flex; gap:8px; margin-top:14px; align-items:center;
    justify-content:center; flex-wrap:wrap; }
  button { background:var(--panel2); color:var(--ink); border:1px solid var(--line);
    border-radius:9px; padding:8px 12px; font-size:15px; cursor:pointer;
    transition:.12s; }
  button:hover { background:#2c3247; border-color:var(--accent); }
  button:active { transform:translateY(1px); }
  .status { text-align:center; margin-top:10px; color:var(--muted); font-size:13px; }
  .panel { background:var(--panel); border-radius:16px; padding:16px;
    box-shadow:0 10px 40px rgba(0,0,0,.35); }
  .evalbox { display:flex; align-items:center; gap:14px; margin-bottom:14px; }
  .evalbar { width:26px; height:120px; background:var(--dark); border-radius:6px;
    overflow:hidden; display:flex; flex-direction:column-reverse; border:1px solid #0006; }
  .evalfill { background:var(--light); width:100%; transition:height .25s; }
  .evalnum { font-size:30px; font-weight:700; font-variant-numeric:tabular-nums; }
  .evalnum.good{ color:var(--good);} .evalnum.bad{ color:var(--bad);}
  .evalcap { color:var(--muted); font-size:12px; }
  .graph { width:100%; height:90px; display:block; margin:6px 0 12px;
    background:var(--panel2); border-radius:10px; }
  .moves { max-height:300px; overflow:auto; border-top:1px solid var(--line);
    padding-top:10px; }
  .mrow { display:flex; gap:6px; align-items:baseline; }
  .mno { color:var(--muted); width:30px; text-align:right; font-variant-numeric:tabular-nums; }
  .mv { padding:2px 7px; border-radius:6px; cursor:pointer; font-variant-numeric:tabular-nums; }
  .mv:hover { background:var(--panel2); }
  .mv.active { background:var(--accent); color:#0b1020; font-weight:700; }
  .tag { display:inline-block; background:var(--panel2); border:1px solid var(--line);
    border-radius:20px; padding:3px 11px; font-size:12px; color:var(--muted); }
  details { margin-top:14px; } summary { cursor:pointer; color:var(--muted); }
  pre { background:var(--panel2); border-radius:10px; padding:12px; overflow:auto;
    font-size:12px; color:var(--ink); white-space:pre-wrap; }
  .legend { color:var(--muted); font-size:11px; text-align:center; margin-top:-6px; }
</style>
</head>
<body>
<header>
  <h1><span class="g">Gambit</span> — self-play replay</h1>
  <div class="sub">A from-scratch chess engine playing itself. Use ← → to step,
    space to play, click any move.</div>
</header>
<div class="wrap">
  <div class="boardcard">
    <div class="board" id="board"></div>
    <div class="controls">
      <button id="first">⏮</button>
      <button id="prev">◀</button>
      <button id="play">▶ play</button>
      <button id="next">▶</button>
      <button id="last">⏭</button>
    </div>
    <div class="status" id="status"></div>
  </div>
  <div class="panel">
    <div class="evalbox">
      <div class="evalbar"><div class="evalfill" id="evalfill"></div></div>
      <div>
        <div class="evalnum" id="evalnum">0.00</div>
        <div class="evalcap">evaluation (White's view)</div>
      </div>
    </div>
    <canvas class="graph" id="graph" width="328" height="90"></canvas>
    <div class="legend">evaluation over the game — click to jump</div>
    <div style="margin:6px 0"><span class="tag" id="resulttag"></span></div>
    <div class="moves" id="moves"></div>
    <details>
      <summary>PGN</summary>
      <pre id="pgn"></pre>
    </details>
  </div>
</div>
<script>
const DATA = /*DATA*/;
const GLYPH = {P:'♙',N:'♘',B:'♗',R:'♖',Q:'♕',K:'♔',
               p:'♟',n:'♞',b:'♝',r:'♜',q:'♛',k:'♚'};
const FILES='abcdefgh';
let ply = 0;                       // 0 = start position; i = after move i
const NPLY = DATA.fens.length - 1; // number of half-moves
let timer = null;

function parseFen(fen){
  const rows = fen.split(' ')[0].split('/');
  const grid = [];                 // grid[rank0..7][file0..7], rank0 = rank1
  for(let i=0;i<8;i++){
    const rank = 7-i, cells = [];
    for(const ch of rows[i]){
      if(/\d/.test(ch)){ for(let k=0;k<+ch;k++) cells.push(''); }
      else cells.push(ch);
    }
    grid[rank] = cells;
  }
  return grid;
}
// the from/to squares of the move that LED to fens[ply] (i.e. move ply-1->ply)
function lastMoveSquares(){
  if(ply===0) return [null,null];
  const a = parseFen(DATA.fens[ply-1]), b = parseFen(DATA.fens[ply]);
  let changed=[];
  for(let r=0;r<8;r++) for(let f=0;f<8;f++){
    if(a[r][f]!==b[r][f]) changed.push([r,f]);
  }
  // 'from' is a square that became empty; 'to' a square that changed to a piece
  let from=null,to=null;
  for(const [r,f] of changed){
    if(b[r][f]==='' && a[r][f]!=='') from=[r,f];
    if(b[r][f]!=='') to=[r,f];
  }
  return [from,to];
}

function render(){
  const grid = parseFen(DATA.fens[ply]);
  const [from,to] = lastMoveSquares();
  const board = document.getElementById('board');
  board.innerHTML='';
  for(let i=0;i<8;i++){
    const rank = 7-i;
    for(let f=0;f<8;f++){
      const sq = document.createElement('div');
      const dark = (rank+f)%2===0;
      sq.className = 'sq '+(dark?'d':'l');
      if(from && from[0]===rank && from[1]===f) sq.classList.add('from');
      if(to && to[0]===rank && to[1]===f) sq.classList.add('to');
      const pc = grid[rank][f];
      if(pc){
        const sp = document.createElement('span');
        sp.className = 'piece '+(pc===pc.toUpperCase()?'w':'b');
        sp.textContent = GLYPH[pc];
        sq.appendChild(sp);
      }
      if(f===0){ const c=document.createElement('span'); c.className='co r';
        c.textContent=(rank+1); sq.appendChild(c); }
      if(i===7){ const c=document.createElement('span'); c.className='co f';
        c.textContent=FILES[f]; sq.appendChild(c); }
      board.appendChild(sq);
    }
  }
  // eval
  const ev = ply>0 ? DATA.evals[ply-1] : 0;
  const lab = ply>0 ? DATA.labels[ply-1] : '0.00';
  const num = document.getElementById('evalnum');
  num.textContent = lab;
  num.className = 'evalnum '+(ev>20?'good':ev<-20?'bad':'');
  let pct = 50 + Math.max(-1000,Math.min(1000,ev))/20; // map -1000..1000 -> 0..100
  document.getElementById('evalfill').style.height = pct+'%';
  // status
  const mv = ply>0 ? DATA.sans[ply-1] : '(start position)';
  const moveNo = Math.floor((ply-1)/2)+1;
  const who = ply===0 ? '' : (ply%2===1 ? `${moveNo}. ` : `${moveNo}... `);
  document.getElementById('status').textContent =
     ply===0 ? 'Starting position' : `Move ${ply}/${NPLY}:  ${who}${mv}`;
  // active move highlight
  document.querySelectorAll('.mv').forEach(e=>e.classList.remove('active'));
  const act = document.querySelector('.mv[data-ply="'+ply+'"]');
  if(act){ act.classList.add('active');
    act.scrollIntoView({block:'nearest'}); }
  drawGraph();
}

function drawGraph(){
  const c = document.getElementById('graph'), x = c.getContext('2d');
  const W=c.width,H=c.height; x.clearRect(0,0,W,H);
  const g = DATA.graph; if(!g.length){return;}
  // zero line
  x.strokeStyle='#39405a'; x.lineWidth=1;
  x.beginPath(); x.moveTo(0,H/2); x.lineTo(W,H/2); x.stroke();
  const xfor = i => g.length<2 ? W/2 : i*(W-1)/(g.length-1);
  const yfor = v => H/2 - (v/1000)*(H/2-4);
  // filled area
  x.beginPath(); x.moveTo(0,H/2);
  g.forEach((v,i)=>x.lineTo(xfor(i),yfor(v)));
  x.lineTo(xfor(g.length-1),H/2); x.closePath();
  x.fillStyle='rgba(122,162,255,.18)'; x.fill();
  // line
  x.beginPath();
  g.forEach((v,i)=>{ const X=xfor(i),Y=yfor(v); i?x.lineTo(X,Y):x.moveTo(X,Y); });
  x.strokeStyle='#7aa2ff'; x.lineWidth=2; x.stroke();
  // current marker
  if(ply>0){ const X=xfor(ply-1),Y=yfor(g[ply-1]);
    x.fillStyle='#f6d365'; x.beginPath(); x.arc(X,Y,3.5,0,7); x.fill(); }
}

function buildMoves(){
  const box = document.getElementById('moves'); box.innerHTML='';
  for(let i=0;i<DATA.sans.length;i+=2){
    const row = document.createElement('div'); row.className='mrow';
    const no = document.createElement('span'); no.className='mno';
    no.textContent=(i/2+1)+'.'; row.appendChild(no);
    for(let j=0;j<2;j++){
      if(i+j<DATA.sans.length){
        const mv=document.createElement('span'); mv.className='mv';
        mv.textContent=DATA.sans[i+j]; mv.dataset.ply=(i+j+1);
        mv.onclick=()=>{ ply=i+j+1; stop(); render(); };
        row.appendChild(mv);
      }
    }
    box.appendChild(row);
  }
  document.getElementById('resulttag').textContent =
     `Result: ${DATA.result} — ${DATA.reason}`;
  document.getElementById('pgn').textContent = DATA.pgn;
}

function go(p){ ply=Math.max(0,Math.min(NPLY,p)); render(); }
function stop(){ if(timer){clearInterval(timer);timer=null;
  document.getElementById('play').textContent='▶ play'; } }
function playPause(){
  if(timer){ stop(); return; }
  if(ply>=NPLY) ply=0;
  document.getElementById('play').textContent='❚❚ pause';
  timer=setInterval(()=>{ if(ply>=NPLY){ stop(); } else { go(ply+1); } }, 650);
}
document.getElementById('first').onclick=()=>{stop();go(0);};
document.getElementById('prev').onclick=()=>{stop();go(ply-1);};
document.getElementById('next').onclick=()=>{stop();go(ply+1);};
document.getElementById('last').onclick=()=>{stop();go(NPLY);};
document.getElementById('play').onclick=playPause;
document.getElementById('graph').onclick=(e)=>{
  const c=e.currentTarget, r=c.getBoundingClientRect();
  const frac=(e.clientX-r.left)/r.width;
  stop(); go(Math.round(frac*(DATA.graph.length-1))+1);
};
window.addEventListener('keydown',e=>{
  if(e.key==='ArrowLeft'){stop();go(ply-1);}
  else if(e.key==='ArrowRight'){stop();go(ply+1);}
  else if(e.key==='Home'){stop();go(0);}
  else if(e.key==='End'){stop();go(NPLY);}
  else if(e.key===' '){e.preventDefault();playPause();}
});
buildMoves(); render();
</script>
</body>
</html>
"""
