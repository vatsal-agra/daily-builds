"""Self-contained interactive HTML playground.

Galley compiles the paragraph to a box/glue/penalty node list in Python (using
real font metrics and Liang hyphenation), serialises it to JSON, and embeds a
faithful JavaScript port of the Knuth--Plass breaker.  Dragging the measure
slider re-breaks the *same* node list live in the browser and re-renders the
justified column, so you watch the optimal break set change in real time.
"""

from __future__ import annotations

import json

from .metrics import Font
from .model import build_paragraph
from .hyphen import Hyphenator


def _serialize_items(items):
    out = []
    for it in items:
        if it.is_box:
            out.append({"t": "b", "w": round(it.width, 4), "x": it.text})
        elif it.is_glue:
            out.append({"t": "g", "w": round(it.width, 4),
                        "y": round(it.stretch, 4), "z": round(it.shrink, 4)})
        else:
            out.append({"t": "p", "w": round(it.width, 4),
                        "p": it.penalty, "f": 1 if it.flagged else 0})
    return out


def algorithm_js() -> str:
    """Return just the pure JS line-breaking functions (no DOM, no rendering).

    Used by the Python<->JS parity test to run the browser breaker under Node.
    """
    start = _TEMPLATE.index("//__ALGO_START__") + len("//__ALGO_START__")
    end = _TEMPLATE.index("//__ALGO_END__")
    return _TEMPLATE[start:end]


def build_playground(text: str, font_family: str = "times", size: float = 14.0) -> str:
    font = Font(font_family, size)
    h = Hyphenator()
    para = build_paragraph(text, font, hyphenate=h.hyphenate)
    data = {
        "items": _serialize_items(para.items),
        "size": font.size,
        "css": font.css,
        "family": font.psname,
        "text": text,
    }
    payload = json.dumps(data, separators=(",", ":"))
    return _TEMPLATE.replace("/*__DATA__*/", payload)


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Galley — interactive Knuth–Plass playground</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin:0; background:#100f0d; color:#eae7e0;
    font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif; }
  .wrap { max-width: 1000px; margin: 0 auto; padding: 2rem 1.4rem 4rem; }
  h1 { font-size: 1.6rem; margin:0 0 .2rem; letter-spacing:-.02em; }
  h1 .a { color:#f0b429; }
  p.sub { color:#9c968a; margin:0 0 1.6rem; }
  .panel { background:#1b1916; border:1px solid #2c2a25; border-radius:14px;
    padding:1.1rem 1.2rem; margin-bottom:1.3rem; }
  .controls { display:flex; gap:1.6rem; flex-wrap:wrap; align-items:center; }
  .ctl { display:flex; flex-direction:column; gap:.3rem; min-width:220px; flex:1; }
  .ctl label { font-size:.82rem; color:#9c968a; display:flex; justify-content:space-between; }
  .ctl label b { color:#f0b429; font-variant-numeric:tabular-nums; }
  input[type=range] { width:100%; accent-color:#f0b429; }
  .toggles { display:flex; gap:1.1rem; align-items:center; font-size:.85rem; }
  .toggles label { display:flex; gap:.35rem; align-items:center; cursor:pointer; }
  .stats { display:flex; gap:1.5rem; flex-wrap:wrap; margin-top:.4rem; }
  .stat b { display:block; font-size:1.3rem; color:#f0b429; font-variant-numeric:tabular-nums; }
  .stat span { color:#9c968a; font-size:.8rem; }
  .stage { background:#fbfaf7; border-radius:10px; padding:0; overflow:auto; }
  .stage svg { display:block; }
  .legend { display:flex; gap:.7rem; flex-wrap:wrap; font-size:.76rem; color:#9c968a;
    margin-top:.7rem; align-items:center; }
  .sw { width:13px; height:13px; border-radius:3px; display:inline-block; vertical-align:-2px; margin-right:3px;}
  footer { color:#6f6a60; font-size:.8rem; margin-top:1.5rem; }
  code { background:#2a2722; padding:.1rem .35rem; border-radius:4px; }
</style>
</head>
<body>
<div class="wrap">
  <h1>Galley · <span class="a">interactive</span> line breaking</h1>
  <p class="sub">Drag the measure. The paragraph re-breaks with the Knuth–Plass
     total-fit algorithm running live in your browser — switch to greedy to see
     the difference.</p>

  <div class="panel">
    <div class="controls">
      <div class="ctl">
        <label>measure (column width) <b><span id="mval">320</span> pt</b></label>
        <input type="range" id="measure" min="120" max="720" value="320" step="2">
      </div>
      <div class="ctl">
        <label>tolerance <b><span id="tval">100</span></b></label>
        <input type="range" id="tol" min="10" max="1000" value="100" step="10">
      </div>
      <div class="toggles">
        <label><input type="checkbox" id="heat" checked> heat</label>
        <label><input type="checkbox" id="greedy"> greedy</label>
        <label><input type="checkbox" id="rule" checked> margin rule</label>
      </div>
    </div>
    <div class="stats" id="stats"></div>
  </div>

  <div class="panel">
    <div class="stage" id="stage"></div>
    <div class="legend"><span>line badness:</span>
      <span><span class="sw" style="background:#1a9850"></span>≤15</span>
      <span><span class="sw" style="background:#a6d96a"></span>≤40</span>
      <span><span class="sw" style="background:#fee08b"></span>≤80</span>
      <span><span class="sw" style="background:#fdae61"></span>≤150</span>
      <span><span class="sw" style="background:#f46d43"></span>≤400</span>
      <span><span class="sw" style="background:#d73027"></span>overfull</span>
    </div>
  </div>
  <footer>Node list (boxes · glue · penalties) compiled in Python from real AFM
    metrics + Liang hyphenation; broken live in JS. — Galley</footer>
</div>

<script>
const DATA = /*__DATA__*/;
const ITEMS = DATA.items, SIZE = DATA.size, CSS = DATA.css;
//__ALGO_START__
const INF = 10000, INF_BAD = 1e12, LINE_PEN = 10, FLAG_DEM = 3000, FIT_DEM = 3000;

function isBox(i){return i.t==='b';}
function isGlue(i){return i.t==='g';}
function isPen(i){return i.t==='p';}
function legal(items,i){
  const it=items[i];
  if(isPen(it)) return it.p < INF;
  if(isGlue(it)) return i>0 && isBox(items[i-1]);
  return false;
}
function fitness(r){ if(r<-0.5)return 0; if(r<=0.5)return 1; if(r<=1.0)return 2; return 3; }
function badness(r){ return 100*Math.pow(Math.abs(r),3); }

function naturalWidth(items,a,b){
  let w=0,i=a;
  while(i<b && isGlue(items[i])) i++;
  for(;i<b;i++){ const it=items[i]; if(isBox(it)||isGlue(it)) w+=it.w; }
  if(b<items.length && isPen(items[b])) w+=items[b].w;
  return w;
}
function stretchShrink(items,a,b){
  let Y=0,Z=0,i=a;
  while(i<b && isGlue(items[i])) i++;
  for(;i<b;i++){ const it=items[i]; if(isGlue(it)){ Y+=it.y; Z+=it.z; } }
  return [Y,Z];
}

// One Knuth–Plass pass at a fixed tolerance.
function breakOnce(items, measure, tol){
  const n=items.length;
  let active=[{pos:0,line:0,fit:1,tw:0,ts:0,tz:0,dem:0,ratio:0,prev:null}];
  let run={w:0,s:0,z:0};
  function totalsAfter(b){
    let s={w:run.w,s:run.s,z:run.z}, i=b;
    while(i<n){ const it=items[i];
      if(isBox(it)) break;
      if(isGlue(it)){ s.w+=it.w; s.s+=it.y; s.z+=it.z; }
      else if(isPen(it) && it.p<=-INF && i>b) break;
      i++;
    }
    return s;
  }
  function consider(b){
    const item=items[b];
    const forced = isPen(item) && item.p<=-INF;
    const bpen = isPen(item)?item.p:0;
    const bflag = isPen(item)&&item.f;
    const extra = isPen(item)?item.w:0;
    let best=[null,null,null,null], bdem=[Infinity,Infinity,Infinity,Infinity], bratio=[0,0,0,0];
    let infPrev=null, infDem=Infinity, infRatio=0, infFit=1;
    let ai=0;
    while(ai<active.length){
      const a=active[ai];
      const li=a.line;
      const L=(run.w-a.tw)+extra;
      const avail=measure;
      let r;
      if(L<avail){ const Y=run.s-a.ts; r=Y>1e-9?(avail-L)/Y:INF_BAD; }
      else if(L>avail){ const Z=run.z-a.tz; r=Z>1e-9?(avail-L)/Z:-INF_BAD; }
      else r=0;
      const remove=(r<-1)||forced;
      if(remove) active.splice(ai,1); else ai++;
      const bbad = r>-1 ? badness(r) : INF_BAD;
      const infeasible = (r<-1)||(bbad>tol);
      if(infeasible && !forced){
        const cand=a.dem+Math.pow(LINE_PEN+Math.min(bbad,INF_BAD),2);
        if(cand<infDem){ infDem=cand; infPrev=a; infRatio=r; infFit=fitness(Math.max(r,-1)); }
        continue;
      }
      const lp=LINE_PEN+bbad;
      let d;
      if(bpen>=0&&bpen<INF) d=lp*lp+bpen*bpen;
      else if(bpen>-INF) d=lp*lp-bpen*bpen;
      else d=lp*lp;
      if(bflag && a.pos>0 && isPen(items[a.pos]) && items[a.pos].f) d+=FLAG_DEM;
      const fc=fitness(r);
      if(Math.abs(fc-a.fit)>1) d+=FIT_DEM;
      const tot=a.dem+d;
      if(tot<bdem[fc]){ bdem[fc]=tot; best[fc]=a; bratio[fc]=r; }
    }
    let added=false;
    if(best.some(x=>x!==null)){
      const t=totalsAfter(b);
      for(let fc=0;fc<4;fc++){ if(!best[fc])continue;
        active.push({pos:b,line:best[fc].line+1,fit:fc,tw:t.w,ts:t.s,tz:t.z,
          dem:bdem[fc],ratio:bratio[fc],prev:best[fc]});
        added=true;
      }
    }
    if(active.length===0 && !added && infPrev){
      const t=totalsAfter(b);
      active.push({pos:b,line:infPrev.line+1,fit:infFit,tw:t.w,ts:t.s,tz:t.z,
        dem:infDem+INF_BAD,ratio:infRatio,prev:infPrev});
    }
  }
  for(let b=0;b<n;b++){
    const it=items[b];
    if(isBox(it)) run.w+=it.w;
    else if(isGlue(it)){ if(legal(items,b)) consider(b); run.w+=it.w; run.s+=it.y; run.z+=it.z; }
    else if(isPen(it)){ if(legal(items,b)) consider(b); }
    if(active.length===0) return null;
  }
  let bestNode=active[0];
  for(const nd of active) if(nd.dem<bestNode.dem) bestNode=nd;
  // reconstruct
  let chain=[],cur=bestNode;
  while(cur){ chain.push(cur); cur=cur.prev; }
  chain.reverse();
  let lines=[];
  for(let i=1;i<chain.length;i++){
    const a=chain[i-1], bnode=chain[i];
    const start=a.pos, end=bnode.pos, r=bnode.ratio;
    const it=items[end];
    lines.push({start,end,ratio:r,
      badness: r>-1?badness(r):INF_BAD,
      flagged: !!(it&&isPen(it)&&it.f),
      forced: !!(it&&isPen(it)&&it.p<=-INF)});
  }
  const feasible = lines.every(l=>l.badness<INF_BAD);
  return {lines, dem:bestNode.dem, feasible};
}

function breakKP(items, measure, tol){
  let res=breakOnce(items,measure,tol);
  let t=tol;
  while(res && !res.feasible && t<1e7){ t*=4; res=breakOnce(items,measure,t); }
  return res;
}

// Greedy first-fit on the node list.
function breakGreedy(items, measure){
  const n=items.length, legalPts=[];
  for(let i=0;i<n;i++) if(legal(items,i)) legalPts.push(i);
  let lines=[], start=0, idx=0;
  while(idx<legalPts.length){
    while(idx<legalPts.length && legalPts[idx]<=start) idx++;
    if(idx>=legalPts.length) break;
    let chosen=null,j=idx;
    while(j<legalPts.length){
      const bp=legalPts[j], forced=isPen(items[bp])&&items[bp].p<=-INF;
      const w=naturalWidth(items,start,bp);
      if(w<=measure){ chosen=bp; if(forced) break; j++; }
      else { if(chosen===null) chosen=bp; break; }
    }
    if(chosen===null) break;
    const forcedHere=isPen(items[chosen])&&items[chosen].p<=-INF;
    const nat=naturalWidth(items,start,chosen);
    const [Y,Z]=stretchShrink(items,start,chosen);
    let r; if(nat<measure) r=Y>1e-9?(measure-nat)/Y:INF_BAD;
    else if(nat>measure) r=Z>1e-9?(measure-nat)/Z:-INF_BAD; else r=0;
    const it=items[chosen];
    lines.push({start,end:chosen,ratio:r,badness:r>-1?badness(r):INF_BAD,
      flagged:!!(it&&isPen(it)&&it.f), forced:forcedHere});
    if(forcedHere) break;
    start=chosen;
  }
  const feasible=lines.every(l=>l.badness<INF_BAD);
  return {lines, dem:0, feasible};
}

function adjGlue(it,r){ r=Math.max(r,-1); return r>=0? it.w+r*it.y : it.w+r*it.z; }
//__ALGO_END__

const HEAT=[[0,'#1a9850'],[15,'#66bd63'],[40,'#a6d96a'],[80,'#fee08b'],
            [150,'#fdae61'],[400,'#f46d43'],[1e11,'#d73027']];
function heatColor(b){ for(const [t,c] of HEAT) if(b<=t) return c; return '#d73027'; }

const SVGNS='http://www.w3.org/2000/svg';
function render(items, lines, measure, opts){
  const margin=16, leading=SIZE*1.32;
  const W=measure+2*margin, H=2*margin+lines.length*leading;
  const svg=document.createElementNS(SVGNS,'svg');
  svg.setAttribute('width',W); svg.setAttribute('height',H);
  svg.setAttribute('viewBox',`0 0 ${W} ${H}`);
  svg.setAttribute('font-family',CSS);
  const bg=document.createElementNS(SVGNS,'rect');
  bg.setAttribute('width',W); bg.setAttribute('height',H); bg.setAttribute('fill','#fbfaf7');
  svg.appendChild(bg);
  if(opts.rule){
    for(const rx of [margin, margin+measure]){
      const ln=document.createElementNS(SVGNS,'line');
      ln.setAttribute('x1',rx); ln.setAttribute('x2',rx);
      ln.setAttribute('y1',margin); ln.setAttribute('y2',H-margin);
      ln.setAttribute('stroke','#d8d2c4'); svg.appendChild(ln);
    }
  }
  lines.forEach((line,li)=>{
    const baseline=margin+SIZE+li*leading;
    if(opts.heat){
      const r=document.createElementNS(SVGNS,'rect');
      r.setAttribute('x',margin); r.setAttribute('y',baseline-SIZE);
      r.setAttribute('width',measure); r.setAttribute('height',leading);
      r.setAttribute('fill',heatColor(line.badness)); r.setAttribute('opacity','0.18');
      svg.appendChild(r);
    }
    let x=0,i=line.start;
    while(i<line.end && isGlue(items[i])) i++;
    for(;i<line.end;i++){
      const it=items[i];
      if(isBox(it)){
        if(it.x){ const t=document.createElementNS(SVGNS,'text');
          t.setAttribute('x',margin+x); t.setAttribute('y',baseline);
          t.setAttribute('font-size',SIZE); t.setAttribute('fill','#1a1a1a');
          t.setAttribute('textLength',it.w); t.setAttribute('lengthAdjust','spacingAndGlyphs');
          t.setAttribute('xml:space','preserve'); t.textContent=it.x; svg.appendChild(t); }
        x+=it.w;
      } else if(isGlue(it)) x+=adjGlue(it,line.ratio);
    }
    if(line.flagged && !line.forced && isPen(items[line.end])){
      const t=document.createElementNS(SVGNS,'text');
      t.setAttribute('x',margin+x); t.setAttribute('y',baseline);
      t.setAttribute('font-size',SIZE); t.setAttribute('fill','#1a1a1a');
      t.textContent='-'; svg.appendChild(t);
      x+=items[line.end].w;
    }
  });
  return svg;
}

const $=id=>document.getElementById(id);
function update(){
  const measure=+$('measure').value, tol=+$('tol').value;
  $('mval').textContent=measure; $('tval').textContent=tol;
  const greedy=$('greedy').checked;
  const res = greedy ? breakGreedy(ITEMS,measure) : breakKP(ITEMS,measure,tol);
  const stage=$('stage'); stage.innerHTML='';
  stage.appendChild(render(ITEMS,res.lines,measure,{heat:$('heat').checked,rule:$('rule').checked}));
  let rs=res.lines.slice(0,-1).map(l=>Math.abs(Math.max(l.ratio,-1)));
  const avg=rs.length?rs.reduce((a,b)=>a+b,0)/rs.length:0;
  const overfull=res.lines.filter(l=>l.ratio<-1.0001).length;
  const hyph=res.lines.filter(l=>l.flagged).length;
  const demTxt = res.feasible ? Math.round(res.dem).toLocaleString() : '∞';
  $('stats').innerHTML =
    stat(res.lines.length,'lines')+
    stat(greedy?'—':demTxt,'demerits')+
    stat(avg.toFixed(2),'avg |r|')+
    stat(hyph,'hyphen lines')+
    stat(overfull,'overfull');
}
function stat(v,l){ return `<div class="stat"><b>${v}</b><span>${l}</span></div>`; }

['measure','tol','heat','greedy','rule'].forEach(id=>{
  $(id).addEventListener('input',update);
});
update();
</script>
</body>
</html>
"""
