"""Generate a self-contained HTML visualizer for Cinch.

Two panels, no external assets or network:
  * LZ77 — animates the sliding window over a sample string, highlighting each
    emitted literal or back-reference (length, distance) and the source it copies.
  * Huffman — draws the canonical Huffman tree for the sample's byte frequencies,
    with every leaf's code; clicking the LZ77 literals lights up their codes.

The Python side computes the tokens and codes; the embedded JS just renders and
animates them, so what you see is the real output of the real codecs.
"""
from __future__ import annotations

import json

import huffman
import lz77


def _build_payload(text: str) -> dict:
    data = text.encode("utf-8")
    tokens = lz77.tokenize(data)
    steps = []
    for tok in tokens:
        if isinstance(tok, int):
            steps.append({"t": "lit", "b": tok})
        else:
            length, dist = tok
            steps.append({"t": "match", "len": length, "dist": dist})

    freqs: dict[int, int] = {}
    for b in data:
        freqs[b] = freqs.get(b, 0) + 1
    codes_lengths = {}
    code_strings = {}
    if freqs:
        codes, lengths = huffman.build_codes(freqs)
        for sym, (code, ln) in codes.items():
            code_strings[sym] = format(code, f"0{ln}b") if ln else ""
            codes_lengths[sym] = ln

    return {
        "bytes": list(data),
        "steps": steps,
        "codes": {str(k): v for k, v in code_strings.items()},
        "lengths": {str(k): v for k, v in codes_lengths.items()},
        "freqs": {str(k): v for k, v in freqs.items()},
    }


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cinch — LZ77 &amp; Huffman visualizer</title>
<style>
  :root{
    --bg:#0d1117; --panel:#161b22; --line:#30363d; --txt:#e6edf3;
    --dim:#8b949e; --lit:#3fb950; --match:#d29922; --src:#58a6ff;
    --accent:#a371f7;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--txt);
       font-family:'SF Mono',ui-monospace,'Cascadia Code',Menlo,Consolas,monospace;
       line-height:1.5}
  header{padding:22px 28px;border-bottom:1px solid var(--line)}
  h1{margin:0;font-size:20px;letter-spacing:.3px}
  h1 span{color:var(--accent)}
  .sub{color:var(--dim);font-size:13px;margin-top:4px}
  .wrap{display:grid;grid-template-columns:1fr;gap:20px;padding:24px 28px;max-width:1100px}
  .panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:18px 20px}
  .panel h2{margin:0 0 12px;font-size:14px;color:var(--dim);text-transform:uppercase;letter-spacing:1px}
  .tape{display:flex;flex-wrap:wrap;gap:3px;font-size:15px}
  .cell{min-width:20px;height:28px;display:flex;align-items:center;justify-content:center;
        border-radius:4px;background:#0d1117;border:1px solid #21262d;padding:0 4px;
        transition:background .15s,border-color .15s,transform .15s}
  .cell.done{opacity:.55}
  .cell.cursor{border-color:var(--txt)}
  .cell.lit{background:rgba(63,185,80,.22);border-color:var(--lit)}
  .cell.match{background:rgba(210,153,34,.22);border-color:var(--match)}
  .cell.src{background:rgba(88,166,255,.25);border-color:var(--src);transform:translateY(-2px)}
  .controls{display:flex;align-items:center;gap:10px;margin:16px 0 4px;flex-wrap:wrap}
  button{background:#21262d;color:var(--txt);border:1px solid var(--line);
         border-radius:6px;padding:6px 14px;cursor:pointer;font:inherit}
  button:hover{border-color:var(--accent)}
  button:disabled{opacity:.4;cursor:default}
  input[type=range]{accent-color:var(--accent)}
  .status{font-size:13px;color:var(--dim);margin-top:8px;min-height:20px}
  .status b{color:var(--txt)}
  .legend{display:flex;gap:18px;font-size:12px;color:var(--dim);margin-top:10px;flex-wrap:wrap}
  .dot{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;vertical-align:middle}
  .stats{display:flex;gap:26px;font-size:13px;color:var(--dim);margin-top:14px;flex-wrap:wrap}
  .stats b{color:var(--txt);font-size:15px}
  svg{width:100%;height:auto;display:block}
  .node circle{fill:#21262d;stroke:var(--line)}
  .leaf circle{fill:rgba(163,113,247,.25);stroke:var(--accent)}
  .leaf.hot circle{fill:var(--accent);stroke:#fff}
  .nlabel{fill:var(--txt);font-size:12px}
  .edge{stroke:var(--line)}
  .ebit{fill:var(--dim);font-size:10px}
  .codetbl{font-size:12px;color:var(--dim);margin-top:8px}
  .codetbl span{display:inline-block;margin:2px 8px 2px 0}
  .codetbl b{color:var(--src)}
  footer{color:var(--dim);font-size:12px;padding:0 28px 30px}
</style>
</head>
<body>
<header>
  <h1><span>Cinch</span> — LZ77 dictionary &amp; canonical Huffman, visualized</h1>
  <div class="sub">Real tokens from the real codec. Green = literal, amber =
     back-reference, blue = the bytes it copies from.</div>
</header>

<div class="wrap">
  <div class="panel">
    <h2>LZ77 sliding window</h2>
    <div id="tape" class="tape"></div>
    <div class="controls">
      <button id="play">▶ Play</button>
      <button id="step">Step ▸</button>
      <button id="reset">⟲ Reset</button>
      <label style="font-size:12px;color:var(--dim)">speed
        <input id="speed" type="range" min="1" max="60" value="18"></label>
    </div>
    <div id="status" class="status"></div>
    <div class="legend">
      <span><i class="dot" style="background:var(--lit)"></i>literal</span>
      <span><i class="dot" style="background:var(--match)"></i>match (copy)</span>
      <span><i class="dot" style="background:var(--src)"></i>copy source</span>
    </div>
    <div class="stats">
      <div>tokens <b id="s-tok">0</b></div>
      <div>literals <b id="s-lit">0</b></div>
      <div>matches <b id="s-mat">0</b></div>
      <div>bytes covered by matches <b id="s-cov">0</b></div>
    </div>
  </div>

  <div class="panel">
    <h2>Canonical Huffman tree</h2>
    <div id="tree"></div>
    <div id="codetbl" class="codetbl"></div>
  </div>
</div>

<footer>Self-contained — generated by <code>cinch viz</code>. No network, no dependencies.</footer>

<script>
const DATA = __DATA__;
const bytesArr = DATA.bytes;
const steps = DATA.steps;
const codes = DATA.codes;

function chShow(b){
  if(b===32) return '␣';
  if(b===10) return '⏎';
  if(b>=33 && b<127) return String.fromCharCode(b);
  return b.toString(16).padStart(2,'0');
}

// ---- LZ77 animation ----
const tape = document.getElementById('tape');
const cells = [];
bytesArr.forEach((b,i)=>{
  const c=document.createElement('div');
  c.className='cell'; c.textContent=chShow(b); c.dataset.i=i;
  tape.appendChild(c); cells.push(c);
});

let outPos=0, stepIdx=0, timer=null;
let cLit=0,cMat=0,cCov=0;
const elStatus=document.getElementById('status');

function clearHi(){ cells.forEach(c=>c.classList.remove('cursor','lit','match','src')); }

function reset(){
  if(timer){clearInterval(timer);timer=null;document.getElementById('play').textContent='▶ Play';}
  outPos=0;stepIdx=0;cLit=0;cMat=0;cCov=0;
  cells.forEach(c=>{c.className='cell';});
  elStatus.innerHTML='Ready — '+steps.length+' tokens to replay.';
  updateStats();
}

function updateStats(){
  document.getElementById('s-tok').textContent=stepIdx;
  document.getElementById('s-lit').textContent=cLit;
  document.getElementById('s-mat').textContent=cMat;
  document.getElementById('s-cov').textContent=cCov;
}

function doStep(){
  if(stepIdx>=steps.length){
    if(timer){clearInterval(timer);timer=null;document.getElementById('play').textContent='▶ Play';}
    elStatus.innerHTML='<b>Done.</b> Whole string reconstructed from '+steps.length+' tokens.';
    return false;
  }
  clearHi();
  const s=steps[stepIdx];
  for(let i=0;i<outPos;i++) cells[i].classList.add('done');
  if(s.t==='lit'){
    cells[outPos].classList.remove('done');
    cells[outPos].classList.add('cursor','lit');
    elStatus.innerHTML='token '+(stepIdx+1)+': <b style="color:var(--lit)">literal</b> '+
        '“'+chShow(s.b)+'” → emit byte, advance 1';
    highlightCode(s.b);
    outPos+=1; cLit++;
  } else {
    const start=outPos-s.dist, end=outPos+s.len;
    for(let i=start;i<start+s.len;i++) if(cells[i]) cells[i].classList.add('src');
    for(let i=outPos;i<end;i++){ if(cells[i]){cells[i].classList.remove('done');cells[i].classList.add('match');} }
    elStatus.innerHTML='token '+(stepIdx+1)+': <b style="color:var(--match)">match</b> '+
        '(length <b>'+s.len+'</b>, distance <b>'+s.dist+'</b>) → copy '+s.len+
        ' bytes from '+s.dist+' back';
    outPos=end; cMat++; cCov+=s.len;
  }
  stepIdx++; updateStats();
  return true;
}

document.getElementById('step').onclick=()=>{ if(timer){clearInterval(timer);timer=null;document.getElementById('play').textContent='▶ Play';} doStep(); };
document.getElementById('reset').onclick=reset;
function speedMs(){ return 1000/ +document.getElementById('speed').value; }
document.getElementById('play').onclick=function(){
  if(timer){clearInterval(timer);timer=null;this.textContent='▶ Play';return;}
  if(stepIdx>=steps.length) reset();
  this.textContent='⏸ Pause';
  timer=setInterval(()=>{ if(!doStep()){} },speedMs());
};
document.getElementById('speed').oninput=function(){
  if(timer){clearInterval(timer);timer=setInterval(()=>{doStep();},speedMs());}
};

// ---- Huffman tree ----
// Build tree from canonical code strings: each code is a root->leaf bit path.
function buildTree(){
  const root={children:{}};
  for(const sym in codes){
    const code=codes[sym];
    let node=root;
    if(code===''){ root.sym=+sym; continue; }
    for(const bit of code){
      if(!node.children[bit]) node.children[bit]={children:{}};
      node=node.children[bit];
    }
    node.sym=+sym; node.code=code;
  }
  return root;
}
function layout(node,depth,xref){
  node.depth=depth;
  const kids=Object.keys(node.children);
  if(kids.length===0){ node.x=xref.x++; node.y=depth; return; }
  kids.sort();
  let sum=0;
  for(const k of kids){ layout(node.children[k],depth+1,xref); sum+=node.children[k].x; }
  node.x=sum/kids.length; node.y=depth;
}
const leafEls={};
function renderTree(){
  const root=buildTree();
  const xref={x:0};
  layout(root,0,xref);
  let maxDepth=0,maxX=0;
  (function walk(n){ maxDepth=Math.max(maxDepth,n.y); maxX=Math.max(maxX,n.x);
     for(const k in n.children) walk(n.children[k]); })(root);
  const padX=30, padY=30, stepX=Math.max(46,Math.min(70,820/(maxX+1))), stepY=64;
  const W=padX*2+maxX*stepX+40, H=padY*2+maxDepth*stepY+20;
  const NS='http://www.w3.org/2000/svg';
  const svg=document.createElementNS(NS,'svg');
  svg.setAttribute('viewBox','0 0 '+W+' '+H);
  function px(n){return padX+n.x*stepX;}
  function py(n){return padY+n.y*stepY;}
  (function edges(n){
    for(const bit in n.children){ const c=n.children[bit];
      const e=document.createElementNS(NS,'line');
      e.setAttribute('x1',px(n));e.setAttribute('y1',py(n));
      e.setAttribute('x2',px(c));e.setAttribute('y2',py(c));
      e.setAttribute('class','edge'); svg.appendChild(e);
      const t=document.createElementNS(NS,'text');
      t.setAttribute('x',(px(n)+px(c))/2 + (bit==='0'?-7:7));
      t.setAttribute('y',(py(n)+py(c))/2);
      t.setAttribute('class','ebit'); t.textContent=bit; svg.appendChild(t);
      edges(c);
    }
  })(root);
  (function nodes(n){
    const g=document.createElementNS(NS,'g');
    const isLeaf=Object.keys(n.children).length===0;
    g.setAttribute('class',isLeaf?'leaf node':'node');
    const circ=document.createElementNS(NS,'circle');
    circ.setAttribute('cx',px(n));circ.setAttribute('cy',py(n));
    circ.setAttribute('r',isLeaf?13:5); g.appendChild(circ);
    if(isLeaf && n.sym!==undefined){
      const t=document.createElementNS(NS,'text');
      t.setAttribute('x',px(n));t.setAttribute('y',py(n)+4);
      t.setAttribute('text-anchor','middle');t.setAttribute('class','nlabel');
      t.textContent=chShow(n.sym); g.appendChild(t);
      leafEls[n.sym]=g;
    }
    svg.appendChild(g);
    for(const k in n.children) nodes(n.children[k]);
  })(root);
  document.getElementById('tree').appendChild(svg);

  // code table
  const tbl=document.getElementById('codetbl');
  const syms=Object.keys(codes).map(Number).sort((a,b)=>codes[a].length-codes[b].length||a-b);
  tbl.innerHTML=syms.map(s=>'<span>'+chShow(s)+' <b>'+(codes[s]||'·')+'</b></span>').join('');
}
let hotLeaf=null;
function highlightCode(sym){
  if(hotLeaf) hotLeaf.classList.remove('hot');
  const g=leafEls[sym];
  if(g){ g.classList.add('hot'); hotLeaf=g; }
}
renderTree();
reset();
</script>
</body>
</html>
"""


def render(text: str) -> str:
    if not text:
        text = "abracadabra"
    # Keep the tape legible.
    sample = text[:420]
    payload = _build_payload(sample)
    return _TEMPLATE.replace("__DATA__", json.dumps(payload))
