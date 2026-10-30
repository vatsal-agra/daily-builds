package main

// explorerHTML is a self-contained page: no network, no dependencies.
const explorerHTML = `<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title><!--TITLE--></title>
<style>
:root{--bg:#f6f4ef;--panel:#fffdf8;--ink:#1d1b16;--mute:#6d675b;--line:#ded8c9;--accent:#b3541e;--ok:#2f7d4f;--bad:#b3261e;
--finder:#3b6ea8;--timing:#7a5ca8;--align:#2d8a84;--format:#c0872a;--version:#a8467a;--data:#d9d3c3;--ecc:#e58b4b;--dark:#1d1b16;--light:#fffdf8}
@media (prefers-color-scheme:dark){:root{--bg:#171512;--panel:#1f1c18;--ink:#ece6d8;--mute:#a09886;--line:#38332b;--accent:#e0824a;--ok:#5fc08a;--bad:#ff7b72;
--finder:#6a9fd8;--timing:#a98ad8;--align:#5cc2bb;--format:#e0b050;--version:#d878ac;--data:#4a443a;--ecc:#d4733a;--dark:#ece6d8;--light:#1f1c18}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
header{padding:20px 16px 4px;max-width:1100px;margin:0 auto}
h1{font:600 22px/1.2 ui-serif,Georgia,serif;margin:0 0 4px;letter-spacing:.2px}
h1 span{color:var(--accent)}
.sub{color:var(--mute);margin:0 0 10px;word-break:break-all}
main{display:grid;grid-template-columns:minmax(300px,560px) 1fr;gap:20px;max-width:1100px;margin:0 auto;padding:8px 16px 40px}
@media (max-width:820px){main{grid-template-columns:1fr}}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px}
.tabs{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px}
.tabs button{border:1px solid var(--line);background:transparent;color:var(--ink);border-radius:999px;padding:5px 12px;font:inherit;font-size:13px;cursor:pointer}
.tabs button[aria-pressed=true]{background:var(--ink);color:var(--bg);border-color:var(--ink)}
svg#sym{width:100%;height:auto;display:block;border-radius:6px;background:var(--light);touch-action:manipulation}
svg#sym rect{shape-rendering:crispEdges}
svg#sym .hit{stroke:var(--bad);stroke-width:.18;fill:none}
svg#sym .hl{stroke:var(--accent);stroke-width:.2;fill:none}
.legend{display:flex;flex-wrap:wrap;gap:4px 12px;margin:10px 0 0;font-size:12.5px;color:var(--mute)}
.legend i{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:5px;vertical-align:-1px;border:1px solid var(--line)}
.verdict{border-radius:10px;padding:10px 12px;margin-bottom:12px;font-weight:600}
.verdict.ok{background:color-mix(in srgb,var(--ok) 16%,transparent);color:var(--ok)}
.verdict.bad{background:color-mix(in srgb,var(--bad) 16%,transparent);color:var(--bad)}
.verdict small{display:block;font-weight:400;color:var(--mute)}
h2{font:600 13px/1 ui-sans-serif,system-ui;text-transform:uppercase;letter-spacing:.08em;color:var(--mute);margin:16px 0 8px}
h2:first-child{margin-top:0}
.blocks{display:grid;gap:6px}
.blk{display:grid;grid-template-columns:44px 1fr 58px;gap:8px;align-items:center;font-size:13px}
.bar{height:14px;border-radius:7px;background:var(--line);position:relative;overflow:hidden}
.bar b{position:absolute;left:0;top:0;bottom:0;background:var(--ok);transition:width .15s}
.bar.over b{background:var(--bad)}
.bar u{position:absolute;top:0;bottom:0;width:2px;background:var(--ink);opacity:.55}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{text-align:right;padding:3px 6px;border-bottom:1px solid var(--line)}
th:first-child,td:first-child{text-align:left}
tr.chosen td{font-weight:700;color:var(--accent)}
button.act{border:1px solid var(--line);background:var(--panel);color:var(--ink);border-radius:8px;padding:6px 12px;font:inherit;font-size:13px;cursor:pointer;margin:0 6px 6px 0}
button.act:hover{border-color:var(--accent)}
#info{min-height:2.6em;font-size:13px;color:var(--mute)}
code{font:12.5px ui-monospace,SFMono-Regular,Menlo,monospace}
.note{font-size:12.5px;color:var(--mute);margin-top:8px}
</style></head><body>
<header><h1>Quiet<span>zone</span> anatomy explorer</h1>
<p class="sub" id="sub"></p></header>
<main>
<section class="card">
<div class="tabs" role="group" aria-label="colour view" id="tabs"></div>
<svg id="sym" role="img" aria-label="QR code module map"></svg>
<div class="legend" id="legend"></div>
<p id="info">Hover a module to see its role. <b>Click</b> modules to damage them and watch the error budget.</p>
</section>
<section class="card">
<div class="verdict ok" id="verdict"></div>
<h2>Damage controls</h2>
<button class="act" id="rnd">Flip 10 random data modules</button>
<button class="act" id="burst">Smear a 4×4 patch</button>
<button class="act" id="clear">Repair everything</button>
<h2>Reed–Solomon blocks · damaged codewords / repairable</h2>
<div class="blocks" id="blocks"></div>
<p class="note">A block is guaranteed repairable while its damaged codewords are ≤ ⌊parity/2⌋. A single flipped module damages one whole codeword (8 modules share it), so clustered damage is cheaper than scattered damage.</p>
<h2>Bit budget</h2><div id="bits"></div>
<h2>Segments</h2><div id="segs"></div>
<h2>Mask penalties</h2>
<table id="pen"></table>
</section>
</main>
<script>
const D=/*DATA*/null;
const N=D.n, SVGNS="http://www.w3.org/2000/svg";
const KN=["data","finder","separator","timing","alignment","format","version","dark module"];
const flipped=new Set();
let view="final", pinned=-1;
const $=id=>document.getElementById(id);
$("sub").textContent=D.text.length>120?D.text.slice(0,120)+"…":D.text;
let VC={};function cssVar(n){return VC[n]||(VC[n]=getComputedStyle(document.documentElement).getPropertyValue(n).trim())}
const views={final:"Final",role:"Roles",block:"RS blocks",ecc:"Data vs parity",bit:"Codeword order"};
function colour(i){
  const k=+D.kinds[i], cw=D.cw[i];
  const dark=(D.dark[i]==="1")!==flipped.has(i);
  if(view==="final")return dark?cssVar("--dark"):cssVar("--light");
  if(view==="role"){
    const m=["--data","--finder","--light","--timing","--align","--format","--version","--ink"][k];
    return k===0?cssVar(dark?"--ink":"--data"):cssVar(m);
  }
  if(k!==0)return cssVar("--line");
  if(cw<0)return cssVar("--line");
  if(view==="ecc")return D.cwIsEcc[cw]?cssVar("--ecc"):cssVar("--finder");
  if(view==="block"){const b=D.cwBlock[cw];return "hsl("+((b*137.5)%360)+",55%,"+(D.cwIsEcc[cw]?"62%":"46%")+")"}
  if(view==="bit"){const t=cw/(D.cwBlock.length-1);return "hsl("+(30+260*t)+",60%,52%)"}
  return cssVar("--data");
}
const svg=$("sym");svg.setAttribute("viewBox","-1 -1 "+(N+2)+" "+(N+2));
const cells=[];
const bg=document.createElementNS(SVGNS,"rect");bg.setAttribute("x",-1);bg.setAttribute("y",-1);bg.setAttribute("width",N+2);bg.setAttribute("height",N+2);bg.setAttribute("fill","var(--light)");svg.appendChild(bg);
for(let y=0;y<N;y++)for(let x=0;x<N;x++){
  const r=document.createElementNS(SVGNS,"rect");r.setAttribute("x",x);r.setAttribute("y",y);r.setAttribute("width",1.02);r.setAttribute("height",1.02);
  r.dataset.i=y*N+x;svg.appendChild(r);cells.push(r);
}
const overlay=document.createElementNS(SVGNS,"g");svg.appendChild(overlay);
function paint(){VC={};cells.forEach((r,i)=>r.setAttribute("fill",colour(i)));drawOverlay();analyse()}
const CWM=D.cwBlock.map(()=>[]);for(let i=0;i<N*N;i++)if(+D.kinds[i]===0&&D.cw[i]>=0)CWM[D.cw[i]].push(i);
function cwModules(cw){return CWM[cw]||[]}
function drawOverlay(){
  overlay.textContent="";
  const damaged=damagedCW();
  for(const cw of damaged)for(const i of cwModules(cw)){
    const r=document.createElementNS(SVGNS,"rect");r.setAttribute("x",i%N+.08);r.setAttribute("y",Math.floor(i/N)+.08);r.setAttribute("width",.86);r.setAttribute("height",.86);r.setAttribute("class","hit");overlay.appendChild(r);
  }
  if(pinned>=0)for(const i of cwModules(pinned)){
    const r=document.createElementNS(SVGNS,"rect");r.setAttribute("x",i%N);r.setAttribute("y",Math.floor(i/N));r.setAttribute("width",1);r.setAttribute("height",1);r.setAttribute("class","hl");overlay.appendChild(r);
  }
}
function damagedCW(){const s=new Set();for(const i of flipped){const cw=D.cw[i];if(+D.kinds[i]===0&&cw>=0)s.add(cw)}return s}
function functionDamage(){let n=0;for(const i of flipped)if(+D.kinds[i]!==0)n++;return n}
function analyse(){
  const dm=damagedCW(), per=D.blocks.map(()=>0);
  dm.forEach(cw=>per[D.cwBlock[cw]]++);
  let ok=true;D.blocks.forEach((b,i)=>{if(per[i]>b[2])ok=false});
  const fd=functionDamage();
  const v=$("verdict");
  v.className="verdict "+(ok?"ok":"bad");
  v.innerHTML=(ok?"Still scans — guaranteed":"Beyond repair — the decoder gives up")+
   "<small>"+flipped.size+" module(s) flipped → "+dm.size+" of "+D.cwBlock.length+" codewords damaged"+(fd?"; "+fd+" in function patterns (format info has 2 copies and its own BCH code; finders/timing are not covered by Reed–Solomon)":"")+"</small>";
  const bl=$("blocks");bl.textContent="";
  D.blocks.forEach((b,i)=>{
    const row=document.createElement("div");row.className="blk";
    const cap=b[2],max=Math.max(cap*1.6,per[i],1);
    row.innerHTML="<span>#"+i+"</span><div class='bar"+(per[i]>cap?" over":"")+"'><b style='width:"+(100*per[i]/max)+"%'></b><u style='left:"+(100*cap/max)+"%'></u></div><span>"+per[i]+" / "+cap+"</span>";
    bl.appendChild(row);
  });
}
function fillStatic(){
  $("tabs").innerHTML="";
  for(const k in views){const b=document.createElement("button");b.textContent=views[k];b.setAttribute("aria-pressed",k===view);b.onclick=()=>{view=k;fillStatic();paint();legend()};$("tabs").appendChild(b)}
}
function legend(){
  const L={final:[],role:[["--finder","finder"],["--timing","timing"],["--align","alignment"],["--format","format"],["--version","version"],["--data","data (light)"],["--ink","data (dark)"]],
   ecc:[["--finder","data codeword"],["--ecc","parity codeword"],["--line","function pattern"]],
   block:[["--line","function pattern"]],bit:[["--line","function pattern"]]}[view];
  const extra={block:"Each hue is one Reed–Solomon block; darker = data, lighter = its parity. The interleaving spreads every block across the whole symbol.",
   bit:"Hue runs along the codeword stream: the zig-zag placement order, starting at the bottom-right corner."}[view]||"";
  $("legend").innerHTML=L.map(e=>"<span><i style='background:"+cssVar(e[0])+"'></i>"+e[1]+"</span>").join("")+(extra?"<span>"+extra+"</span>":"");
}
svg.addEventListener("mousemove",e=>{
  const t=e.target;if(!t.dataset||t.dataset.i===undefined)return;
  const i=+t.dataset.i,k=+D.kinds[i],cw=D.cw[i],x=i%N,y=Math.floor(i/N);
  let s="("+x+","+y+") "+KN[k];
  if(k===0&&cw>=0){const b=D.cwBlock[cw];s+=" · codeword "+cw+" bit "+D.bit[i]+" · block #"+b+" "+(D.cwIsEcc[cw]?"parity":"data")}
  else if(k===0)s+=" · remainder bit";
  $("info").textContent=s;
  const np=(k===0&&cw>=0)?cw:-1;if(np!==pinned){pinned=np;drawOverlay()}
});
svg.addEventListener("mouseleave",()=>{pinned=-1;drawOverlay()});
function toggle(i){flipped.has(i)?flipped.delete(i):flipped.add(i)}
svg.addEventListener("click",e=>{const t=e.target;if(t.dataset&&t.dataset.i!==undefined){toggle(+t.dataset.i);paint()}});
function dataModules(){const a=[];for(let i=0;i<N*N;i++)if(+D.kinds[i]===0&&D.cw[i]>=0)a.push(i);return a}
$("rnd").onclick=()=>{const a=dataModules();for(let k=0;k<10;k++)toggle(a[Math.floor(Math.random()*a.length)]);paint()};
$("burst").onclick=()=>{const a=dataModules();const c=a[Math.floor(Math.random()*a.length)];const cx=c%N,cy=Math.floor(c/N);
  for(let dy=0;dy<4;dy++)for(let dx=0;dx<4;dx++){const x=cx+dx,y=cy+dy;if(x<N&&y<N)flipped.add(y*N+x)}paint()};
$("clear").onclick=()=>{flipped.clear();paint()};
$("bits").innerHTML=D.bits[0]+" bits of segments + "+D.bits[2]+" bits of terminator/padding = "+D.bits[1]+" bit capacity ("+(D.bits[1]/8)+" data codewords); "+D.bits[3]+" remainder bit(s) after the codewords.";
$("segs").innerHTML=D.segments.map(s=>"<div><code>"+s.Mode+"</code> · "+s.Chars+" chars · "+s.Bits+" bits</div>").join("");
$("pen").innerHTML="<tr><th>mask</th><th>N1</th><th>N2</th><th>N3</th><th>N4</th><th>total</th></tr>"+D.pen.map((p,m)=>{const t=p[0]+p[1]+p[2]+p[3];return "<tr class='"+(m===D.mask?"chosen":"")+"'><td>"+m+(m===D.mask?" ← chosen":"")+"</td><td>"+p[0]+"</td><td>"+p[1]+"</td><td>"+p[2]+"</td><td>"+p[3]+"</td><td>"+t+"</td></tr>"}).join("");
document.querySelector("h1").insertAdjacentHTML("afterend","<p class='sub'>Version "+D.version+" · "+N+"×"+N+" modules · ECC "+D.ecc+" · mask "+D.mask+"</p>");
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change",()=>{paint();legend()});
window.__qz={flip:i=>{toggle(i);paint()},flipAll:a=>{a.forEach(toggle);paint()},reset:()=>{flipped.clear();paint()},verdict:()=>$("verdict").classList.contains("ok"),data:D};
fillStatic();paint();legend();
</script></body></html>
`
