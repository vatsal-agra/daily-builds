"""Self-contained interactive HTML report: property verdicts + step-through counterexample viewers."""
import html
import json

from .model import fmt_slot
from .trace import STUTTER

TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Argus report — __TITLE__</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#16181d;--mute:#667085;--line:#e3e6eb;--ok:#0f8a4f;--bad:#c62828;--warn:#b26a00;
--accent:#3b5bdb;--hi:#fff4c2;--loop:#e8efff;--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#0f1115;--card:#171a21;--ink:#e8eaee;--mute:#98a1b3;--line:#272c36;
--ok:#4cd08a;--bad:#ff7b72;--warn:#e3b341;--accent:#8ea2ff;--hi:#4a3f12;--loop:#1d2740}}
:root[data-theme=dark]{--bg:#0f1115;--card:#171a21;--ink:#e8eaee;--mute:#98a1b3;--line:#272c36;--ok:#4cd08a;--bad:#ff7b72;--warn:#e3b341;--accent:#8ea2ff;--hi:#4a3f12;--loop:#1d2740}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:1180px;margin:0 auto;padding:28px 16px 64px}
h1{font-size:26px;margin:0 0 2px;letter-spacing:-.01em}h1 small{font-weight:500;color:var(--mute);font-size:15px;margin-left:8px}
.sub{color:var(--mute);margin:0 0 22px}
.cards{display:grid;gap:10px;margin-bottom:28px}
.prop{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 16px;display:grid;grid-template-columns:28px 1fr auto;gap:4px 12px;align-items:center}
.prop .mark{font-size:20px;font-weight:700}.prop.ok .mark{color:var(--ok)}.prop.bad .mark{color:var(--bad)}.prop.lim .mark{color:var(--warn)}
.prop b{font-size:15px}.prop .meta{color:var(--mute);font-size:13px;grid-column:2}.prop .tag{font:600 12px var(--mono);padding:2px 8px;border-radius:99px;border:1px solid var(--line);color:var(--mute)}
.viol{background:var(--card);border:1px solid var(--line);border-radius:14px;margin:0 0 26px;overflow:hidden}
.viol>header{padding:14px 18px;border-bottom:1px solid var(--line);display:flex;flex-wrap:wrap;gap:6px 14px;align-items:baseline}
.viol h2{margin:0;font-size:18px;color:var(--bad)}.viol .msg{color:var(--mute);font-size:14px}
.facts{padding:8px 18px 10px;border-bottom:1px solid var(--line);font-size:13px;color:var(--mute)}.facts span{color:var(--ok);font-weight:700}
.lanes{padding:14px 18px 6px;overflow-x:auto}
.lane{display:flex;align-items:center;height:26px}.lane .nm{width:120px;flex:none;font:12px var(--mono);color:var(--mute);overflow:hidden;text-overflow:ellipsis}
.lane .track{position:relative;flex:1;height:100%;min-width:calc(var(--n)*14px)}
.dot{position:absolute;top:50%;width:10px;height:10px;margin:-5px 0 0 -5px;border-radius:50%;background:var(--accent);opacity:.45;cursor:pointer;transition:transform .1s}
.dot:hover{transform:scale(1.5)}.dot.cur{opacity:1;box-shadow:0 0 0 3px color-mix(in srgb,var(--accent) 30%,transparent)}
.dot.fail{background:var(--bad);opacity:1}.loopband{position:absolute;top:0;bottom:0;background:var(--loop);border-radius:6px;z-index:0}
.body{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(0,1fr);min-height:300px}
@media(max-width:820px){.body{grid-template-columns:1fr}}
.steps{border-right:1px solid var(--line);max-height:460px;overflow:auto}
.step{display:grid;grid-template-columns:34px 92px 1fr;gap:8px;padding:6px 14px;cursor:pointer;border-bottom:1px solid var(--line);font-size:13.5px}
.step:hover{background:color-mix(in srgb,var(--accent) 7%,transparent)}.step.cur{background:color-mix(in srgb,var(--accent) 16%,transparent)}
.step.inloop{box-shadow:inset 3px 0 0 var(--accent)}.step .n{color:var(--mute);font-family:var(--mono)}.step .p{font:600 12.5px var(--mono)}
.step .t{font-family:var(--mono);font-size:12.5px;word-break:break-word}.step .t i{color:var(--mute);font-style:normal}
.step.failstep .t{color:var(--bad)}.loopmark{padding:4px 14px;font-size:12px;color:var(--accent);background:var(--loop);border-bottom:1px solid var(--line)}
.state{padding:12px 18px}.state h3{margin:6px 0 6px;font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--mute)}
table{border-collapse:collapse;width:100%;font:13px var(--mono)}td{padding:3px 8px;border-bottom:1px dashed var(--line)}td:first-child{color:var(--mute);width:45%}
tr.chg td{background:var(--hi)}tr.chg td:last-child{font-weight:700}
.ctl{display:flex;gap:8px;padding:10px 18px;border-top:1px solid var(--line);align-items:center;flex-wrap:wrap}
button{background:var(--card);color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:5px 12px;font:inherit;cursor:pointer}
button:hover{border-color:var(--accent)}.ctl .pos{margin-left:auto;color:var(--mute);font:13px var(--mono)}
.legend{color:var(--mute);font-size:12px;padding:0 18px 10px}.themebtn{position:fixed;top:12px;right:14px}
</style></head><body><main>
<button class="themebtn" id="theme" title="toggle light/dark theme">Theme</button>
<h1>Argus <small>__TITLE__</small></h1>
<p class="sub" id="sub"></p>
<div class="cards" id="props"></div>
<div id="viols"></div>
<script id="data" type="application/json">__DATA__</script>
<script>
const D=JSON.parse(document.getElementById('data').textContent);
const $=(t,c,h)=>{const e=document.createElement(t);if(c)e.className=c;if(h!=null)e.innerHTML=h;return e};
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
document.getElementById('sub').textContent=D.summary;
const pr=document.getElementById('props');
D.properties.forEach(p=>{const c=$('div','prop '+(p.status));
 c.innerHTML='<span class="mark">'+({ok:'✓',bad:'✗',lim:'?'}[p.status])+'</span><b>'+esc(p.name)+'</b><span class="tag">'+esc(p.kind)+'</span><span class="meta">'+esc(p.detail)+'</span>';pr.appendChild(c)});
const vs=document.getElementById('viols');
D.violations.forEach((v,vi)=>{
 const root=$('section','viol');root.id='v'+vi;
 root.appendChild($('header','',"<h2>"+esc(v.title)+"</h2><span class='msg'>"+esc(v.message)+"</span>"));
 if(v.facts.length)root.appendChild($('div','facts',v.facts.map(f=>'<span>✓</span> '+esc(f)).join('<br>')));
 const N=v.states.length; // states[0]=init
 const lanes=$('div','lanes');lanes.style.setProperty('--n',N);
 v.procs.forEach((pn,pi)=>{const l=$('div','lane');l.appendChild($('div','nm',esc(pn)));const tr=$('div','track');
  if(pi===0&&v.loop_to!=null){const b=$('div','loopband');b.style.left=((v.loop_to+.5)/N*100)+'%';b.style.right='0';tr.appendChild(b)}
  v.steps.forEach((s,si)=>{if(s.proc===pi){const d=$('div','dot'+(s.fail?' fail':''));d.style.left=((si+1)/N*100)+'%';d.title=(si+1)+': '+s.text;d.onclick=()=>go(si+1);d.dataset.i=si+1;tr.appendChild(d)}});
  l.appendChild(tr);lanes.appendChild(l)});
 root.appendChild(lanes);
 if(v.loop_to!=null)root.appendChild($('div','legend','shaded band = the cycle that repeats forever (steps '+(v.loop_to+1)+'–'+v.steps.length+')'));
 const body=$('div','body');const steps=$('div','steps');const st=$('div','state');body.append(steps,st);root.appendChild(body);
 const rows=[];
 const mk=(i,html,cls)=>{const r=$('div','step '+cls,html);r.onclick=()=>go(i);steps.appendChild(r);rows[i]=r;return r};
 mk(0,'<span class="n">0</span><span class="p">init</span><span class="t">initial state</span>','');
 v.steps.forEach((s,si)=>{
  if(v.loop_to!=null&&si===v.loop_to){steps.appendChild($('div','loopmark','↻ loop starts — everything below repeats forever'))}
  mk(si+1,'<span class="n">'+(si+1)+'</span><span class="p">'+esc(s.procname)+'</span><span class="t">'+esc(s.text)+(s.line?' <i>:'+s.line+'</i>':'')+(s.fail?'<br>✗ '+esc(s.fail):'')+'</span>',
   (s.fail?'failstep ':'')+((v.loop_to!=null&&si>=v.loop_to)?'inloop':''))});
 const pos=$('span','pos');
 let cur=0;
 function render(){
  const s=v.states[cur],pv=cur?v.states[cur-1]:null;
  let h='<h3>shared state</h3><table>'+s.vars.map((kv,i)=>'<tr class="'+(pv&&pv.vars[i][1]!==kv[1]?'chg':'')+'"><td>'+esc(kv[0])+'</td><td>'+esc(kv[1])+'</td></tr>').join('')+'</table>';
  h+='<h3>processes</h3><table>'+s.procs.map((p,i)=>{const q=pv&&pv.procs[i];const ch=q&&(q[1]!==p[1]||q[2]!==p[2]);
   return '<tr class="'+(ch?'chg':'')+'"><td>'+esc(p[0])+'</td><td>@'+esc(p[1])+(p[2]?' <span style="color:var(--mute)">'+esc(p[2])+'</span>':'')+'</td></tr>'}).join('')+'</table>';
  st.innerHTML=h;
  rows.forEach((r,i)=>r&&r.classList.toggle('cur',i===cur));
  root.querySelectorAll('.dot').forEach(d=>d.classList.toggle('cur',+d.dataset.i===cur));
  pos.textContent='step '+cur+' / '+v.steps.length;
  if(rows[cur])rows[cur].scrollIntoView({block:'nearest'});
 }
 function go(i){cur=Math.max(0,Math.min(v.steps.length,i));render()}
 const ctl=$('div','ctl');
 [['⏮',()=>go(0)],['◀',()=>go(cur-1)],['▶',()=>go(cur+1)],['⏭',()=>go(v.steps.length)]].forEach(([t,f])=>{const b=$('button','',t);b.onclick=f;ctl.appendChild(b)});
 let timer=null;const play=$('button','','Play');play.onclick=()=>{if(timer){clearInterval(timer);timer=null;play.textContent='Play'}else{play.textContent='Pause';if(cur>=v.steps.length)cur=0;timer=setInterval(()=>{if(cur>=v.steps.length){if(v.loop_to!=null)cur=v.loop_to;else{clearInterval(timer);timer=null;play.textContent='Play';return}}go(cur+1)},650)}};
 ctl.append(play,pos);root.appendChild(ctl);
 root.tabIndex=0;root.addEventListener('keydown',e=>{if(e.key==='ArrowRight'){go(cur+1);e.preventDefault()}if(e.key==='ArrowLeft'){go(cur-1);e.preventDefault()}});
 vs.appendChild(root);go(0);
});
const th=document.getElementById('theme');th.onclick=()=>{const r=document.documentElement;const dark=getComputedStyle(r).getPropertyValue('--bg').trim()==='#0f1115';r.dataset.theme=dark?'light':'dark'};
</script></main></body></html>
"""


def describe_state(m, s):
    vars_ = []
    for name, v in m.vars.items():
        vars_.append([name, str(s[v.base]) if v.size is None else "[" + ", ".join(map(str, s[v.base:v.base + v.size])) + "]"])
    for name, c in m.chans.items():
        vars_.append([name, fmt_slot(m, c.slot, s[c.slot])])
    procs = []
    for p in m.procs:
        procs.append([p.name, p.node_name[s[p.pc_slot]], " ".join(f"{k}={s[sl]}" for k, sl in p.locals.items())])
    return {"vars": vars_, "procs": procs}


def violation_data(m, v, facts):
    tr = v.trace
    steps = []
    for pid, edge, st in tr.steps:
        steps.append({"proc": pid if edge is not STUTTER else -1,
                      "procname": m.procs[pid].name if edge is not STUTTER else "—",
                      "text": edge.text if edge is not STUTTER else "(system idle — repeats forever)",
                      "line": edge.line if edge is not STUTTER else None, "fail": None})
    states = [describe_state(m, s) for s in tr.states()]
    if tr.fail:
        pid, edge, msg = tr.fail
        steps.append({"proc": pid, "procname": m.procs[pid].name, "text": edge.text, "line": edge.line, "fail": msg})
        states.append(states[-1])
    msg = v.message
    if v.kind == "invariant" and v.prop is not None:
        msg = f"condition: {v.prop.text}"
    return {"title": v.title(), "message": msg, "facts": facts, "procs": [p.name for p in m.procs],
            "steps": steps, "states": states, "loop_to": tr.loop_to}


def build_report(m, filename, props, violations, summary):
    data = {"summary": summary, "properties": props, "violations": violations}
    blob = json.dumps(data).replace("</", "<\\/")
    return (TEMPLATE.replace("__TITLE__", html.escape(filename)).replace("__DATA__", blob))
