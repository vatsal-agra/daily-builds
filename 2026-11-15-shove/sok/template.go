package sok

const htmlTemplate = `<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{TITLE}}</title>
<style>
:root{--bg:#14161c;--panel:#1d2029;--ink:#e9e6df;--dim:#8d93a3;--accent:#f2b35e;--good:#6fd39a;--bad:#ef6a5e;--line:#2b2f3b}
*{box-sizing:border-box}
body{margin:0;background:radial-gradient(1200px 700px at 50% -10%,#22283a,var(--bg));color:var(--ink);font:15px/1.4 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;min-height:100vh}
header{display:flex;align-items:center;gap:16px;padding:14px 20px;border-bottom:1px solid var(--line);flex-wrap:wrap}
h1{margin:0;font-size:20px;letter-spacing:.14em;text-transform:uppercase;color:var(--accent)}
h1 small{color:var(--dim);letter-spacing:.05em;font-weight:400;text-transform:none;margin-left:8px}
main{display:grid;grid-template-columns:230px 1fr 250px;gap:18px;padding:18px 20px;max-width:1200px;margin:0 auto}
@media(max-width:860px){main{grid-template-columns:1fr;padding:12px}#stage{order:-1}#levels{flex-direction:row;max-height:none;overflow-x:auto;padding-bottom:4px}#levels button{white-space:nowrap}}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px}
#levels{max-height:70vh;overflow:auto;display:flex;flex-direction:column;gap:6px}
#levels button{all:unset;cursor:pointer;padding:8px 10px;border-radius:8px;border:1px solid transparent;display:flex;justify-content:space-between;gap:8px}
#levels button:hover{background:#262a37}
#levels button.cur{border-color:var(--accent);background:#2a2d3a}
#levels .tick{color:var(--good)}
#levels .r{color:var(--dim);font-size:12px}
#stage{display:flex;flex-direction:column;align-items:center;gap:10px}
canvas{max-width:100%;border-radius:10px;background:#0f1117;box-shadow:0 10px 40px #0008;touch-action:none}
.stats{display:flex;gap:10px;flex-wrap:wrap;justify-content:center}
.stat{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:6px 14px;text-align:center;min-width:84px}
.stat b{display:block;font-size:20px;font-variant-numeric:tabular-nums}
.stat span{color:var(--dim);font-size:11px;text-transform:uppercase;letter-spacing:.1em}
.btns{display:flex;gap:8px;flex-wrap:wrap;justify-content:center}
button.b{background:#2a2e3c;color:var(--ink);border:1px solid #3a4052;border-radius:8px;padding:7px 14px;cursor:pointer;font:inherit}
button.b:hover{border-color:var(--accent)}
button.b:disabled{opacity:.4;cursor:default}
#warn{height:22px;color:var(--bad);font-weight:600;transition:opacity .2s}
#msg{height:22px;color:var(--good);font-weight:600}
h3{margin:0 0 8px;font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:var(--dim)}
.kv{display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px dashed var(--line)}
.kv:last-child{border:none}
kbd{background:#2a2e3c;border:1px solid #3a4052;border-radius:4px;padding:0 5px;font-size:12px}
input[type=range]{width:100%}
</style></head><body>
<header><h1>Shove<small id="ttl">Sokoban &middot; solver-verified levels</small></h1></header>
<main>
<section class="card"><h3>Levels</h3><div id="levels"></div></section>
<section id="stage">
 <div class="stats"><div class="stat"><b id="sMoves">0</b><span>moves</span></div><div class="stat"><b id="sPush">0</b><span>pushes</span></div><div class="stat"><b id="sBest">–</b><span>your best</span></div><div class="stat"><b id="sOpt">–</b><span>optimal</span></div></div>
 <canvas id="cv" width="640" height="480"></canvas>
 <div id="warn"></div><div id="msg"></div>
 <div class="btns"><button class="b" id="bUndo">Undo <kbd>Z</kbd></button><button class="b" id="bReset">Restart <kbd>R</kbd></button><button class="b" id="bPrev">&larr; Prev</button><button class="b" id="bNext">Next &rarr;</button><button class="b" id="bHint" title="Solve from the current position in your browser and play the next push">Hint</button><button class="b" id="bSolve">Show solution</button></div>
</section>
<aside class="card"><h3>This level</h3>
 <div class="kv"><span>Rating</span><b id="iRate"></b></div>
 <div class="kv"><span>Boxes</span><b id="iBoxes"></b></div>
 <div class="kv"><span>Optimal pushes</span><b id="iOpt"></b></div>
 <div class="kv"><span>Solution length</span><b id="iLen"></b></div>
 <h3 style="margin-top:16px">Playback speed</h3><input id="spd" type="range" min="1" max="30" value="8">
 <h3 style="margin-top:16px">Controls</h3>
 <div class="kv"><span>Move</span><span><kbd>&uarr;</kbd><kbd>&darr;</kbd><kbd>&larr;</kbd><kbd>&rarr;</kbd> / WASD</span></div>
 <div class="kv"><span>Undo</span><span><kbd>Z</kbd> / <kbd>Backspace</kbd></span></div>
 <div class="kv"><span>Restart</span><kbd>R</kbd></div>
 <div class="kv"><span>Touch</span><span>swipe</span></div>
 <p style="color:var(--dim);font-size:12px">The red warning appears the moment you create a position that provably cannot be solved (a frozen crate or a crate on a dead square). Solutions are machine-verified push-optimal.</p>
</aside>
</main>
<script>
"use strict";
var LEVELS=/*LEVELS*/[];
var DIRS={u:[0,-1],d:[0,1],l:[-1,0],r:[1,0]};
var cv=document.getElementById("cv"),ctx=cv.getContext("2d");
var $=function(i){return document.getElementById(i)};
var cur=0,L=null,st=null,hist=[],playing=null,peeked=false,solvedSet={},best={};
try{best=JSON.parse(localStorage.getItem("shove-best-"+document.title)||"{}")}catch(e){best={}}
function saveBest(){try{localStorage.setItem("shove-best-"+document.title,JSON.stringify(best))}catch(e){}}

function load(i){
  stopPlay();peeked=false;cur=i;var d=LEVELS[i];var w=0;d.rows.forEach(function(r){w=Math.max(w,r.length)});
  L={w:w,h:d.rows.length,wall:[],goal:[],boxes:{},player:-1,d:d};
  for(var y=0;y<L.h;y++)for(var x=0;x<w;x++){var c=d.rows[y][x]||" ",k=y*w+x;
    L.wall[k]=c==="#";L.goal[k]=(c==="."||c==="*"||c==="+");
    if(c==="$"||c==="*")L.boxes[k]=1;if(c==="@"||c==="+")L.player=k;}
  computeDead();
  st={boxes:Object.assign({},L.boxes),p:L.player,moves:0,pushes:0};hist=[];
  size();render();updateUI();
}
function computeDead(){
  var n=L.w*L.h;L.dead=[];var reach=[];
  var q=[];for(var i=0;i<n;i++)if(L.goal[i]){reach[i]=1;q.push(i)}
  var off=[1,-1,L.w,-L.w];
  for(var h=0;h<q.length;h++){var c=q[h];
    for(var j=0;j<4;j++){var o=off[j],p=c-o,pl=p-o;
      if(p<0||pl<0||p>=n||pl>=n||L.wall[p]||L.wall[pl]||reach[p])continue;
      reach[p]=1;q.push(p)}}
  for(var k=0;k<n;k++)L.dead[k]=!L.wall[k]&&!reach[k];
}
function freezeDead(boxes,p){
  var state={},list=[];
  function blocked(c,step){var a=c-step,b=c+step;
    if(L.wall[a]||L.wall[b])return true;
    if(L.dead[a]&&L.dead[b])return true;
    var o=[a,b];for(var i=0;i<2;i++){var x=o[i];if(boxes[x]){var s=state[x];if(s===1||s===2)return true;if(s===3)continue;if(frozen(x))return true}}
    return false}
  function frozen(c){state[c]=1;var r=blocked(c,1)&&blocked(c,L.w);if(r){state[c]=2;list.push(c)}else state[c]=3;return r}
  if(!frozen(p))return false;
  for(var i=0;i<list.length;i++)if(!L.goal[list[i]])return true;
  return false}
function deadlocked(){
  for(var b in st.boxes){b=+b;if(L.dead[b]&&!L.goal[b])return true}
  for(var b2 in st.boxes){if(freezeDead(st.boxes,+b2))return true}
  return false}
function solved(){for(var b in st.boxes)if(!L.goal[b])return false;return true}

function move(dir,quiet){
  var d=DIRS[dir];if(!d)return false;
  var x=st.p%L.w+d[0],y=Math.floor(st.p/L.w)+d[1];
  if(x<0||y<0||x>=L.w||y>=L.h)return false;
  var n=y*L.w+x;if(L.wall[n])return false;
  var push=false,snap={p:st.p,moves:st.moves,pushes:st.pushes,from:-1,to:-1};
  if(st.boxes[n]){var nx=x+d[0],ny=y+d[1];if(nx<0||ny<0||nx>=L.w||ny>=L.h)return false;
    var nn=ny*L.w+nx;if(L.wall[nn]||st.boxes[nn])return false;
    delete st.boxes[n];st.boxes[nn]=1;push=true;snap.from=n;snap.to=nn;st.pushes++}
  st.p=n;st.moves++;hist.push(snap);
  if(!quiet){render();updateUI()}
  return true}
function undo(){var s=hist.pop();if(!s)return;
  if(s.to>=0){delete st.boxes[s.to];st.boxes[s.from]=1}
  st.p=s.p;st.moves=s.moves;st.pushes=s.pushes;render();updateUI()}
function updateUI(){
  $("sMoves").textContent=st.moves;$("sPush").textContent=st.pushes;
  var d=L.d;$("sOpt").textContent=d.pushes;$("iOpt").textContent=d.pushes;$("iRate").textContent=d.rating;
  $("iBoxes").textContent=Object.keys(L.boxes).length;$("iLen").textContent=d.solution.length+" moves";
  var b=best[cur];$("sBest").textContent=b?b.pushes+"p/"+b.moves+"m":"–";
  var dl=!playing&&deadlocked();$("warn").textContent=dl&&!solved()?"⚠ Deadlock: this position can no longer be solved. Undo or restart.":"";
  if(solved()&&!playing&&peeked){$("msg").textContent="Solution shown \u2014 press R to try it yourself.";}
  else if(solved()&&!playing){
    var verdict=st.pushes===d.pushes?"Perfect — push-optimal!":"Solved in "+st.pushes+" pushes (optimal is "+d.pushes+").";
    $("msg").textContent=verdict;solvedSet[cur]=1;
    if(!best[cur]||st.pushes<best[cur].pushes||(st.pushes===best[cur].pushes&&st.moves<best[cur].moves)){best[cur]={pushes:st.pushes,moves:st.moves};saveBest()}
    $("sBest").textContent=best[cur].pushes+"p/"+best[cur].moves+"m";
  }else $("msg").textContent=playing?"Playing verified solution…":"";
  renderList();$("bUndo").disabled=!hist.length||!!playing;$("bPrev").disabled=cur===0;$("bNext").disabled=cur>=LEVELS.length-1;
  $("bSolve").textContent=playing?"Stop":"Show solution"}
function renderList(){var el=$("levels");el.innerHTML="";
  LEVELS.forEach(function(d,i){var b=document.createElement("button");if(i===cur)b.className="cur";
    var s=document.createElement("span");s.textContent=d.name;var r=document.createElement("span");r.className="r";
    r.innerHTML=(solvedSet[i]||best[i]?'<span class="tick">✓</span> ':"")+d.rating;b.appendChild(s);b.appendChild(r);
    b.onclick=function(){load(i)};el.appendChild(b)})}

var T=40;
function size(){var maxW=Math.min(660,window.innerWidth-40);T=Math.max(16,Math.min(56,Math.floor(maxW/L.w),Math.floor(520/L.h)));
  cv.width=L.w*T;cv.height=L.h*T}
function rr(x,y,w,h,r){ctx.beginPath();ctx.moveTo(x+r,y);ctx.arcTo(x+w,y,x+w,y+h,r);ctx.arcTo(x+w,y+h,x,y+h,r);ctx.arcTo(x,y+h,x,y,r);ctx.arcTo(x,y,x+w,y,r);ctx.closePath()}
function render(){
  ctx.clearRect(0,0,cv.width,cv.height);
  // reachable floor = interior (flood from player ignoring boxes)
  if(!L.floor){L.floor={};var q=[L.player];L.floor[L.player]=1;
    for(var h=0;h<q.length;h++){[1,-1,L.w,-L.w].forEach(function(o){var n=q[h]+o;if(!L.wall[n]&&!L.floor[n]){L.floor[n]=1;q.push(n)}})}}
  var bad=!playing&&deadlocked()&&!solved();
  for(var y=0;y<L.h;y++)for(var x=0;x<L.w;x++){var k=y*L.w+x,px=x*T,py=y*T;
    if(L.wall[k]){
      // draw walls only if they touch the floor (hides the void)
      var touch=false;for(var dy=-1;dy<=1;dy++)for(var dx=-1;dx<=1;dx++){var xx=x+dx,yy=y+dy;if(xx>=0&&yy>=0&&xx<L.w&&yy<L.h&&L.floor[yy*L.w+xx])touch=true}
      if(!touch)continue;
      var g=ctx.createLinearGradient(px,py,px,py+T);g.addColorStop(0,"#4b5167");g.addColorStop(1,"#343848");
      ctx.fillStyle=g;ctx.fillRect(px,py,T,T);ctx.strokeStyle="#2a2e3c";ctx.strokeRect(px+.5,py+.5,T-1,T-1);
      ctx.fillStyle="#ffffff10";ctx.fillRect(px+2,py+2,T-4,4);continue}
    if(!L.floor[k])continue;
    ctx.fillStyle=((x+y)&1)?"#1b1f2a":"#1e2230";ctx.fillRect(px,py,T,T);
    if(L.goal[k]){ctx.fillStyle="#f2b35e";ctx.globalAlpha=.22;ctx.beginPath();ctx.arc(px+T/2,py+T/2,T*.34,0,7);ctx.fill();ctx.globalAlpha=1;
      ctx.strokeStyle="#f2b35e";ctx.lineWidth=2;ctx.beginPath();ctx.arc(px+T/2,py+T/2,T*.2,0,7);ctx.stroke();ctx.lineWidth=1}
    if(L.dead[k]&&!L.goal[k]&&showDead){ctx.fillStyle="#ef6a5e22";ctx.fillRect(px,py,T,T)}}
  Object.keys(st.boxes).forEach(function(k){k=+k;var x=k%L.w,y=Math.floor(k/L.w),px=x*T+3,py=y*T+3,s=T-6,on=L.goal[k];
    var g=ctx.createLinearGradient(px,py,px,py+s);
    if(on){g.addColorStop(0,"#7fe0a8");g.addColorStop(1,"#3e9d68")}else if(bad&&(L.dead[k]||freezeDead(st.boxes,k))){g.addColorStop(0,"#ff8c80");g.addColorStop(1,"#b3382d")}else{g.addColorStop(0,"#d9a05b");g.addColorStop(1,"#a06a2f")}
    ctx.fillStyle=g;rr(px,py,s,s,5);ctx.fill();ctx.strokeStyle="#00000055";ctx.stroke();
    ctx.strokeStyle="#00000040";ctx.beginPath();ctx.moveTo(px+4,py+4);ctx.lineTo(px+s-4,py+s-4);ctx.moveTo(px+s-4,py+4);ctx.lineTo(px+4,py+s-4);ctx.stroke();
    ctx.fillStyle="#ffffff25";ctx.fillRect(px+3,py+3,s-6,3)});
  var pxx=(st.p%L.w)*T+T/2,pyy=Math.floor(st.p/L.w)*T+T/2;
  ctx.fillStyle="#0006";ctx.beginPath();ctx.ellipse(pxx,pyy+T*.28,T*.26,T*.1,0,0,7);ctx.fill();
  ctx.fillStyle="#6aa9ff";ctx.beginPath();ctx.arc(pxx,pyy,T*.28,0,7);ctx.fill();
  ctx.fillStyle="#fff";ctx.beginPath();ctx.arc(pxx-T*.09,pyy-T*.05,T*.06,0,7);ctx.arc(pxx+T*.09,pyy-T*.05,T*.06,0,7);ctx.fill();
  ctx.fillStyle="#102";ctx.beginPath();ctx.arc(pxx-T*.09,pyy-T*.05,T*.03,0,7);ctx.arc(pxx+T*.09,pyy-T*.05,T*.03,0,7);ctx.fill();
}
var showDead=false;

function stopPlay(){if(playing){clearTimeout(playing);playing=null}}
function startPlay(){
  if(playing){stopPlay();updateUI();return}
  load(cur);peeked=true;var sol=L.d.solution.toLowerCase(),i=0;playing=true;
  (function step(){if(i>=sol.length){playing=null;updateUI();return}
    move(sol[i++]);playing=setTimeout(step,1000/(+$("spd").value))})();
  $("bSolve").textContent="Stop";}

document.addEventListener("keydown",function(e){
  if(e.ctrlKey||e.metaKey||e.altKey)return;
  var m={ArrowUp:"u",ArrowDown:"d",ArrowLeft:"l",ArrowRight:"r",w:"u",s:"d",a:"l",d:"r",W:"u",S:"d",A:"l",D:"r"}[e.key];
  if(m){e.preventDefault();if(!playing)move(m);return}
  if(e.key==="z"||e.key==="Z"||e.key==="Backspace"){e.preventDefault();if(!playing)undo()}
  else if(e.key==="r"||e.key==="R"){load(cur)}
  else if(e.key==="n"&&cur<LEVELS.length-1)load(cur+1);
  else if(e.key==="p"&&cur>0)load(cur-1);
  else if(e.key==="x")showDead=!showDead,render()});
$("bUndo").onclick=function(){if(!playing)undo()};$("bReset").onclick=function(){load(cur)};
$("bPrev").onclick=function(){if(cur>0)load(cur-1)};$("bNext").onclick=function(){if(cur<LEVELS.length-1)load(cur+1)};
$("bSolve").onclick=startPlay;
// ---- in-browser A* (admissible sum-of-nearest-goal bound) used by the Hint button ----
function pushTables(){
  if(L.pd)return;var n=L.w*L.h,off=[1,-1,L.w,-L.w];L.pd=[];
  for(var g=0;g<n;g++){if(!L.goal[g])continue;var d=new Int32Array(n).fill(-1);d[g]=0;var q=[g];
    for(var h=0;h<q.length;h++){var c=q[h];for(var j=0;j<4;j++){var o=off[j],p=c-o,pl=p-o;
      if(p<0||pl<0||L.wall[p]||L.wall[pl]||d[p]>=0)continue;d[p]=d[c]+1;q.push(p)}}
    L.pd.push(d)}}
var G=null;
function scratch(){var n=L.w*L.h;if(G&&G.n===n&&G.L===L)return G;G={L:L,n:n,occ:new Uint8Array(n),seen:new Int32Array(n),stamp:0,q:new Int32Array(n),reach:new Uint8Array(n)};return G}
// min-cost box->goal matching (Hungarian, O(n^3)) over single-box push distances: admissible and much tighter than sum-of-nearest
function hOf(bx){var n=bx.length,BIG=1<<20,C=[];
  for(var i=0;i<=n;i++)C.push(new Array(n+1).fill(0));
  for(var i2=0;i2<n;i2++)for(var j=0;j<n;j++){var v=L.pd[j][bx[i2]];C[i2+1][j+1]=v<0?BIG:v}
  var u=new Array(n+1).fill(0),v2=new Array(n+1).fill(0),p=new Array(n+1).fill(0),way=new Array(n+1).fill(0);
  for(var r=1;r<=n;r++){p[0]=r;var j0=0,minv=new Array(n+1).fill(1e9),used=new Array(n+1).fill(false);
    do{used[j0]=true;var i0=p[j0],dl=1e9,j1=0;
      for(var j3=1;j3<=n;j3++)if(!used[j3]){var cur=C[i0][j3]-u[i0]-v2[j3];if(cur<minv[j3]){minv[j3]=cur;way[j3]=j0}if(minv[j3]<dl){dl=minv[j3];j1=j3}}
      for(var j4=0;j4<=n;j4++){if(used[j4]){u[p[j4]]+=dl;v2[j4]-=dl}else minv[j4]-=dl}
      j0=j1}while(p[j0]!==0);
    do{var j5=way[j0];p[j0]=p[j5];j0=j5}while(j0)}
  var tot=0;for(var jj=1;jj<=n;jj++)tot+=C[p[jj]][jj];return tot>=BIG?-1:tot}
// BFS from p with boxes as walls. Returns min reachable cell; if out is given, marks reachable cells in it.
function region(bx,p,out){var g=scratch(),off=[-L.w,L.w,-1,1];
  for(var i=0;i<bx.length;i++)g.occ[bx[i]]=1;
  var st2=++g.stamp,qh=0,qt=0,mn=p;g.q[qt++]=p;g.seen[p]=st2;if(out)out.fill(0);
  while(qh<qt){var c=g.q[qh++];if(c<mn)mn=c;if(out)out[c]=1;
    for(var j=0;j<4;j++){var m=c+off[j];if(g.seen[m]!==st2&&!L.wall[m]&&!g.occ[m]){g.seen[m]=st2;g.q[qt++]=m}}}
  for(var k=0;k<bx.length;k++)g.occ[bx[k]]=0;return mn}
function aStar(startBoxes,startP,cap,deadline){
  pushTables();var g=scratch(),off=[-L.w,L.w,-1,1];
  var bx0=startBoxes.slice().sort(function(a,b){return a-b}),h0=hOf(bx0);if(h0<0)return null;
  var nodes=[{b:bx0,p:startP,par:-1,from:-1,dir:-1,g:0}],open=[[h0,h0,0]],best={};
  function hpush(e){open.push(e);var i=open.length-1;while(i>0){var pa=(i-1)>>1;if(open[pa][0]<=e[0])break;open[i]=open[pa];i=pa}open[i]=e}
  function hpop(){var top=open[0],last=open.pop();if(open.length){var i=0;for(;;){var l=2*i+1;if(l>=open.length)break;var r=l+1,c=(r<open.length&&open[r][0]<open[l][0])?r:l;if(open[c][0]>=last[0])break;open[i]=open[c];i=c}open[i]=last}return top}
  best[bx0.join(",")+"|"+region(bx0,startP,null)]=0;var exp=0;
  while(open.length){var e=hpop(),nd=nodes[e[2]];
    if(e[1]===0){var path=[];for(var id=e[2];nodes[id].par>=0;id=nodes[id].par)path.push(id);return {nodes:nodes,path:path.reverse(),expanded:exp}}
    if(++exp>cap||((exp&255)===0&&deadline&&performance.now()>deadline))return null;
    region(nd.b,nd.p,g.reach);var occ={};nd.b.forEach(function(x){occ[x]=1});
    for(var i=0;i<nd.b.length;i++){var b=nd.b[i];for(var d=0;d<4;d++){var pl=b-off[d],tg=b+off[d];
      if(!g.reach[pl]||L.wall[tg]||occ[tg])continue;
      var nb=nd.b.slice();nb[i]=tg;nb.sort(function(a,c){return a-c});
      var bo={};nb.forEach(function(x){bo[x]=1});if(freezeDead(bo,tg))continue;
      var h=hOf(nb);if(h<0)continue;var key=nb.join(",")+"|"+region(nb,b,null),gg=nd.g+1;
      if(best[key]!==undefined&&best[key]<=gg)continue;best[key]=gg;nodes.push({b:nb,p:b,par:e[2],from:b,dir:d,g:gg});
      hpush([gg+h,h,nodes.length-1])}}}
  return null}
function walkTo(from,to,occ){var n=L.w*L.h,prev=new Int32Array(n).fill(-2),mv=new Array(n),off=[-L.w,L.w,-1,1],DN=["u","d","l","r"];prev[from]=-1;var q=[from];
  for(var h=0;h<q.length&&prev[to]===-2;h++)for(var j=0;j<4;j++){var m=q[h]+off[j];if(prev[m]===-2&&!L.wall[m]&&!occ[m]){prev[m]=q[h];mv[m]=DN[j];q.push(m)}}
  var out=[];for(var c=to;c!==from;c=prev[c])out.push(mv[c]);return out.reverse()}
function hint(){
  if(playing||solved())return;
  var bxs=Object.keys(st.boxes).map(Number);
  $("msg").textContent="Thinking…";
  setTimeout(function(){
    var res=aStar(bxs,st.p,1e9,performance.now()+8000);
    if(!res){$("msg").textContent="No hint within 8 s: this position is either unsolvable or too deep to search here. Try Undo.";return}
    var e=res.nodes[res.path[0]],steps=walkTo(st.p,e.from-[-L.w,L.w,-1,1][e.dir],st.boxes);
    steps.push(["u","d","l","r"][e.dir]);peeked=true;var i=0;playing=true;
    (function step(){if(i>=steps.length){playing=null;updateUI();$("msg").textContent="Hint: "+res.path.length+" push(es) left from here.";return}
      move(steps[i++]);playing=setTimeout(step,1000/(+$("spd").value))})()},20)}
$("bHint").onclick=hint;

var tx=0,ty=0;
cv.addEventListener("touchstart",function(e){tx=e.touches[0].clientX;ty=e.touches[0].clientY},{passive:true});
cv.addEventListener("touchend",function(e){var t=e.changedTouches[0],dx=t.clientX-tx,dy=t.clientY-ty;
  if(Math.max(Math.abs(dx),Math.abs(dy))<20||playing)return;
  move(Math.abs(dx)>Math.abs(dy)?(dx>0?"r":"l"):(dy>0?"d":"u"))});
window.addEventListener("resize",function(){size();render()});
if(LEVELS.length)load(0);else{$("msg").textContent="No levels."}
window.__shove={hint:hint,aStar:aStar,load:load,move:move,undo:undo,state:function(){return st},solved:solved,deadlocked:deadlocked,levels:LEVELS,play:startPlay};
</script></body></html>`
