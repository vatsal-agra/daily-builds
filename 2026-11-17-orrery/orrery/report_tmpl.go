package orrery

const reportTemplate = `<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Orrery — %%TITLE%%</title>
<style>
:root{--bg:#0b0e17;--panel:#121726;--line:#232b42;--ink:#e6e9f5;--mute:#8d96b3;--accent:#ffb454;--grid:#1b2237;
--c0:#ffb454;--c1:#59c2ff;--c2:#ff7a90;--c3:#9be564;--c4:#c792ea;--c5:#4ee3c1;--c6:#f2d96b}
@media (prefers-color-scheme:light){:root{--bg:#f4f1ea;--panel:#fffdf8;--line:#ddd6c6;--ink:#1d2030;--mute:#6b6f82;--accent:#c4620a;--grid:#ece6d8;
--c0:#c4620a;--c1:#1676b8;--c2:#cc3355;--c3:#4a9a1c;--c4:#8a4fc0;--c5:#0f9d85;--c6:#a68a0b}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
header{padding:22px 24px 8px;max-width:1280px;margin:auto}
h1{margin:0;font-size:26px;letter-spacing:.01em}
h1 small{font-weight:400;color:var(--mute);font-size:14px;margin-left:10px}
.params{color:var(--mute);font:13px ui-monospace,SFMono-Regular,Menlo,monospace;margin-top:4px}
main{max-width:1280px;margin:auto;padding:12px 24px 40px;display:grid;grid-template-columns:minmax(0,1.1fr) minmax(0,1fr);gap:18px}
@media (max-width:900px){main{grid-template-columns:1fr;padding:12px 16px 32px}header{padding:18px 16px 4px}}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:14px 16px}
.card h2{margin:0 0 10px;font-size:13px;text-transform:uppercase;letter-spacing:.09em;color:var(--mute);font-weight:600}
canvas{width:100%;display:block;border-radius:10px;background:var(--bg)}
#orbit{aspect-ratio:1/1}
#chart{aspect-ratio:16/9}
.controls{display:flex;gap:10px;align-items:center;margin-top:10px;flex-wrap:wrap}
button{background:transparent;color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:5px 12px;font:inherit;cursor:pointer}
button:hover{border-color:var(--accent);color:var(--accent)}
button[aria-pressed=true]{border-color:var(--accent);color:var(--accent)}
input[type=range]{flex:1;min-width:120px;accent-color:var(--accent)}
.readout{font:13px ui-monospace,Menlo,monospace;color:var(--mute);min-width:9ch}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th,td{text-align:right;padding:6px 8px;border-bottom:1px solid var(--line);white-space:nowrap}
th:first-child,td:first-child{text-align:left}
th{color:var(--mute);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.06em}
td.num{font-family:ui-monospace,Menlo,monospace}
.sw{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:8px;vertical-align:middle}
.tag{font-size:10.5px;border:1px solid var(--line);border-radius:6px;padding:0 5px;margin-left:6px;color:var(--mute)}
.tag.sym{color:var(--c3);border-color:var(--c3)}
.bad{color:var(--c2)}
.note{color:var(--mute);font-size:13px;margin:10px 2px 0}
.right{display:flex;flex-direction:column;gap:18px;min-width:0}
.tablewrap{overflow-x:auto}
</style></head><body>
<header><h1>Orrery<small id="ttl"></small></h1><div class="params" id="params"></div></header>
<main>
<section class="card"><h2>Orbits <span id="viewm" style="text-transform:none;letter-spacing:0"></span></h2>
<canvas id="orbit"></canvas>
<div class="controls">
<button id="play" aria-label="play or pause">❚❚ pause</button>
<input id="scrub" type="range" min="0" value="0" step="1" aria-label="time">
<span class="readout" id="tlabel"></span>
<button id="scale" aria-pressed="false" title="compress large radii so inner orbits stay visible">sqrt radius</button>
<button id="trails" aria-pressed="true">trails</button>
</div>
<div class="note" id="omit"></div>
</section>
<div class="right">
<section class="card"><h2>Relative energy error |ΔE/E₀| (log scale)</h2>
<canvas id="chart"></canvas>
<div class="note" id="hover">Symplectic schemes wobble but stay bounded; non-symplectic ones drift away secularly.</div></section>
<section class="card"><h2>Integrator comparison</h2><div class="tablewrap"><table id="tbl"></table></div></section>
</div>
</main>
<script id="data" type="application/json">%%DATA%%</script>
<script>
(function(){
var D=JSON.parse(document.getElementById('data').textContent);
var css=function(n){return getComputedStyle(document.documentElement).getPropertyValue(n).trim()};
document.getElementById('ttl').textContent=D.title;
document.getElementById('params').textContent=D.params;
document.getElementById('viewm').textContent='· integrated with '+D.view;
if(D.omitted)document.getElementById('omit').textContent='Showing '+D.names.length+' of '+(D.names.length+D.omitted)+' bodies (evenly sampled).';
var N=D.names.length,F=D.frames,K=D.times.length;
var pal=['--c0','--c1','--c2','--c3','--c4','--c5','--c6'];
function fmt(x){if(x===0)return '0';if(x>=1e29)return '∞ (blew up)';return x.toExponential(2)}
// ---- table
var tbl=document.getElementById('tbl');
var h='<tr><th>method</th><th>max |ΔE/E|</th><th>max |ΔL/L|</th><th>force evals</th><th>ms</th></tr>';
var best=Infinity;D.series.forEach(function(s){if(!s.err&&s.maxE<best)best=s.maxE});
D.series.forEach(function(s,i){
 h+='<tr><td><span class="sw" style="background:var('+pal[i%7]+')"></span>'+s.method+(s.symplectic?'<span class="tag sym">symplectic</span>':'')+'</td>'+
 '<td class="num'+(s.err?' bad':'')+'">'+(s.err?'failed':fmt(s.maxE))+(!s.err&&s.maxE===best?' ★':'')+'</td><td class="num">'+(s.err?'—':fmt(s.maxL))+'</td><td class="num">'+s.evals.toLocaleString()+'</td><td class="num">'+s.ms.toFixed(1)+'</td></tr>';
 if(s.err)h+='<tr><td colspan="5" class="bad" style="text-align:left;white-space:normal">'+s.err.replace(/</g,'&lt;')+'</td></tr>';
});
tbl.innerHTML=h;
// ---- orbit view
var cv=document.getElementById('orbit'),cx=cv.getContext('2d');
var scrub=document.getElementById('scrub');scrub.max=K-1;
var frame=0,playing=true,sq=false,trails=true,W=0,H2=0;
var R=1;
(function(){var rs=[];for(var k=0;k<K;k++){for(var i=0;i<N;i++){var x=F[k][3*i],y=F[k][3*i+1];rs.push(Math.hypot(x,y))}}
 rs.sort(function(a,b){return a-b});R=rs[Math.floor(rs.length*0.97)]||1;if(!(R>0))R=1;R*=1.15})();
function resize(){var r=window.devicePixelRatio||1;var b=cv.getBoundingClientRect();W=Math.max(10,b.width);H2=Math.max(10,b.height);cv.width=W*r;cv.height=H2*r;cx.setTransform(r,0,0,r,0,0);draw()}
function map(x,y){var s=Math.min(W,H2)/2*0.94;if(sq){var r=Math.hypot(x,y);if(r>0){var k=Math.sqrt(r/R)*R/r;x*=k;y*=k}}return [W/2+x/R*s,H2/2-y/R*s]}
var maxm=Math.max.apply(null,D.mass);
function draw(){
 cx.clearRect(0,0,W,H2);
 cx.strokeStyle=css('--grid');cx.lineWidth=1;cx.beginPath();cx.moveTo(W/2,0);cx.lineTo(W/2,H2);cx.moveTo(0,H2/2);cx.lineTo(W,H2/2);cx.stroke();
 var showTr=trails&&N<=40;
 if(showTr){for(var i=0;i<N;i++){cx.strokeStyle=css(pal[i%7]);cx.globalAlpha=.45;cx.lineWidth=1.2;cx.beginPath();
  var from=Math.max(0,frame-120);for(var k=from;k<=frame;k++){var p=map(F[k][3*i],F[k][3*i+1]);if(k===from)cx.moveTo(p[0],p[1]);else cx.lineTo(p[0],p[1])}cx.stroke()}}
 cx.globalAlpha=1;
 for(var i=0;i<N;i++){var p=map(F[frame][3*i],F[frame][3*i+1]);
  var rad=N>40?1.8:Math.max(3,Math.min(11,3+7*Math.cbrt(D.mass[i]/maxm)));
  cx.fillStyle=css(pal[i%7]);cx.beginPath();cx.arc(p[0],p[1],rad,0,6.2832);cx.fill();
  if(N<=12){cx.fillStyle=css('--mute');cx.font='12px ui-sans-serif,system-ui';cx.fillText(D.names[i],p[0]+rad+4,p[1]+4)}}
 document.getElementById('tlabel').textContent='t = '+D.times[frame].toPrecision(5);
 scrub.value=frame;
}
var last=0;function tick(ts){if(playing&&ts-last>33){last=ts;frame=(frame+1)%K;draw()}requestAnimationFrame(tick)}
document.getElementById('play').onclick=function(){playing=!playing;this.textContent=playing?'❚❚ pause':'▶ play'};
scrub.oninput=function(){frame=+this.value;draw()};
document.getElementById('scale').onclick=function(){sq=!sq;this.setAttribute('aria-pressed',sq);draw()};
document.getElementById('trails').onclick=function(){trails=!trails;this.setAttribute('aria-pressed',trails);draw()};
// ---- chart
var ch=document.getElementById('chart'),cc=ch.getContext('2d'),CW=0,CH=0,hoverX=null;
var LO=-16,HI=1;
function cres(){var r=window.devicePixelRatio||1;var b=ch.getBoundingClientRect();CW=b.width;CH=b.height;ch.width=CW*r;ch.height=CH*r;cc.setTransform(r,0,0,r,0,0);drawChart()}
function drawChart(){
 var L=44,Rr=10,T=10,B=24,w=CW-L-Rr,hh=CH-T-B;cc.clearRect(0,0,CW,CH);
 var tmax=0;D.series.forEach(function(s){if(s.t.length)tmax=Math.max(tmax,s.t[s.t.length-1])});if(!(tmax>0))tmax=1;
 cc.font='11px ui-monospace,Menlo,monospace';cc.textBaseline='middle';
 for(var e=LO;e<=HI;e+=3){var y=T+hh*(1-(e-LO)/(HI-LO));cc.strokeStyle=css('--grid');cc.beginPath();cc.moveTo(L,y);cc.lineTo(L+w,y);cc.stroke();cc.fillStyle=css('--mute');cc.textAlign='right';cc.fillText('1e'+e,L-6,y)}
 cc.textAlign='center';cc.textBaseline='top';for(var k=0;k<=4;k++){var x=L+w*k/4;cc.fillText((tmax*k/4).toPrecision(3),x,T+hh+6)}
 D.series.forEach(function(s,i){cc.strokeStyle=css(pal[i%7]);cc.lineWidth=1.8;cc.beginPath();var started=false;
  for(var k=0;k<s.t.length;k++){var v=Math.log10(Math.max(s.e[k],1e-300));v=Math.max(LO,Math.min(HI,v));var x=L+w*s.t[k]/tmax,y=T+hh*(1-(v-LO)/(HI-LO));if(!started){cc.moveTo(x,y);started=true}else cc.lineTo(x,y)}cc.stroke()});
 if(hoverX!==null){cc.strokeStyle=css('--mute');cc.setLineDash([3,3]);cc.beginPath();cc.moveTo(hoverX,T);cc.lineTo(hoverX,T+hh);cc.stroke();cc.setLineDash([])}
 ch._geo={L:L,w:w,tmax:tmax};
}
ch.addEventListener('mousemove',function(ev){var b=ch.getBoundingClientRect();hoverX=ev.clientX-b.left;drawChart();var g=ch._geo;var t=(hoverX-g.L)/g.w*g.tmax;if(t<0||t>g.tmax){document.getElementById('hover').textContent='';return}
 var txt='t = '+t.toPrecision(4)+'   ';D.series.forEach(function(s){if(!s.t.length)return;var j=0;while(j<s.t.length-1&&s.t[j]<t)j++;txt+=s.method+': '+(s.e[j]>=1e29?'∞':s.e[j].toExponential(1))+'   '});
 document.getElementById('hover').textContent=txt});
ch.addEventListener('mouseleave',function(){hoverX=null;drawChart();document.getElementById('hover').textContent='Symplectic schemes wobble but stay bounded; non-symplectic ones drift away secularly.'});
window.addEventListener('resize',function(){resize();cres()});
resize();cres();requestAnimationFrame(tick);
})();
</script></body></html>
`
