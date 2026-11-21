"""Self-contained HTML proof report: every command, and for every tactic proof each step's goals."""
import html
from .audit import export_certificate, audit_certificate

CSS = """
:root{--bg:#f6f4ef;--panel:#fffdf8;--ink:#1d2330;--mute:#6b7280;--line:#e3ddd0;--ok:#1f7a4d;--okbg:#e4f3ea;
--bad:#b4281e;--badbg:#fbe9e7;--acc:#3b4ea8;--code:#f1ede3;--hyp:#4a5568;--goal:#1d2330}
:root[data-theme=dark]{--bg:#14171f;--panel:#1b1f2a;--ink:#e8e6df;--mute:#9aa3b2;--line:#2b3140;--ok:#59c68d;--okbg:#17302a;
--bad:#ff8a80;--badbg:#3a1f1f;--acc:#8fa2ff;--code:#222735;--hyp:#aab4c5;--goal:#f1efe8}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#14171f;--panel:#1b1f2a;--ink:#e8e6df;--mute:#9aa3b2;--line:#2b3140;--ok:#59c68d;--okbg:#17302a;
--bad:#ff8a80;--badbg:#3a1f1f;--acc:#8fa2ff;--code:#222735;--hyp:#aab4c5;--goal:#f1efe8}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.55 ui-serif,Georgia,'Iowan Old Style',serif}
.wrap{max-width:900px;margin:0 auto;padding:28px 16px 80px}
header h1{font-size:34px;letter-spacing:-.02em;margin:0 0 4px}
header h1 span{color:var(--acc)}
.sub{color:var(--mute);font-family:ui-monospace,Menlo,monospace;font-size:13px}
.stats{display:flex;flex-wrap:wrap;gap:10px;margin:18px 0 22px}
.stat{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 16px;min-width:120px}
.stat b{display:block;font-size:26px;font-variant-numeric:tabular-nums}
.stat small{color:var(--mute);font-family:ui-sans-serif,system-ui,sans-serif;font-size:12px;text-transform:uppercase;letter-spacing:.06em}
.stat.good b{color:var(--ok)} .stat.bad b{color:var(--bad)}
.tools{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px;font-family:ui-sans-serif,system-ui,sans-serif}
button{background:var(--panel);color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:6px 12px;font:inherit;font-size:13px;cursor:pointer}
button:hover{border-color:var(--acc)} button[aria-pressed=true]{background:var(--acc);color:#fff;border-color:var(--acc)}
.card{background:var(--panel);border:1px solid var(--line);border-left:5px solid var(--ok);border-radius:10px;margin:12px 0;overflow:hidden}
.card.fail{border-left-color:var(--bad)}
.card>summary,.card>.head{list-style:none;cursor:pointer;padding:12px 16px;display:flex;gap:10px;align-items:baseline;flex-wrap:wrap}
.card>summary::-webkit-details-marker{display:none}
.kind{font:600 11px ui-sans-serif,system-ui,sans-serif;text-transform:uppercase;letter-spacing:.08em;color:var(--mute);min-width:70px}
.name{font:600 16px ui-monospace,Menlo,monospace}
.badge{margin-left:auto;font:600 12px ui-sans-serif,system-ui,sans-serif;padding:2px 9px;border-radius:99px;background:var(--okbg);color:var(--ok)}
.fail .badge{background:var(--badbg);color:var(--bad)}
.stmt{font:14px ui-monospace,Menlo,monospace;background:var(--code);padding:8px 16px;white-space:pre-wrap;word-break:break-word;border-top:1px solid var(--line)}
.axiom{color:var(--bad);font:12px ui-sans-serif,system-ui,sans-serif;padding:4px 16px}
.steps{padding:6px 16px 14px;border-top:1px solid var(--line)}
.step{margin:10px 0;border-left:2px solid var(--line);padding-left:12px}
.tac{font:600 14px ui-monospace,Menlo,monospace;color:var(--acc)}
pre.goal{font:13px/1.45 ui-monospace,Menlo,monospace;margin:4px 0 0;padding:8px 10px;background:var(--code);border-radius:6px;white-space:pre-wrap;word-break:break-word;color:var(--goal)}
pre.before{opacity:.72}
.lab{font:11px ui-sans-serif,system-ui,sans-serif;color:var(--mute);text-transform:uppercase;letter-spacing:.07em;margin-top:6px}
.err{font:13px/1.45 ui-monospace,Menlo,monospace;white-space:pre-wrap;background:var(--badbg);color:var(--bad);padding:10px 16px}
.done{color:var(--ok);font:600 13px ui-sans-serif,system-ui,sans-serif;margin-top:8px}
footer{margin-top:30px;color:var(--mute);font:12px ui-sans-serif,system-ui,sans-serif}
@media(max-width:560px){header h1{font-size:28px}.kind{min-width:auto}}
"""

JS = """
const cards=[...document.querySelectorAll('.card')];
function setFilter(f,btn){document.querySelectorAll('[data-f]').forEach(b=>b.setAttribute('aria-pressed',b===btn));
cards.forEach(c=>{c.style.display=(f==='all'||(f==='fail'&&c.classList.contains('fail'))||(f==='proof'&&c.dataset.kind==='theorem'))?'':'none'})}
function toggleAll(open){cards.forEach(c=>{if(c.tagName==='DETAILS')c.open=open})}
function theme(){const r=document.documentElement;const d=r.dataset.theme==='dark'||(!r.dataset.theme&&matchMedia('(prefers-color-scheme:dark)').matches);r.dataset.theme=d?'light':'dark'}
"""


def esc(s):
    return html.escape(s or "")


def build_report(sess, filename, src):
    results = [r for r in sess.results[sess.n_prelude:]]
    cert = export_certificate(sess, None)
    audit = audit_certificate(cert)
    thms = [r for r in results if r.get("kind") == "theorem" and r.get("ok")]
    defs = [r for r in results if r.get("kind") == "def" and r.get("ok")]
    inds = [r for r in results if r.get("kind") == "inductive" and r.get("ok")]
    fails = [r for r in results if not r.get("ok")]
    cards = []
    for r in results:
        ok = r.get("ok")
        kind = r.get("kind", "")
        name = r.get("name", "")
        pos = r.get("pos")
        where = f" · line {pos[0]}" if pos else ""
        parts = []
        steps = r.get("steps") or []
        head = (f'<span class="kind">{esc(kind)}</span><span class="name">{esc(name)}</span>'
                f'<span class="sub">{esc(where.strip(" ·"))}</span>'
                f'<span class="badge">{"✓ kernel-checked" if ok else "✗ rejected"}</span>')
        body = []
        if r.get("stmt"):
            body.append(f'<div class="stmt">{esc(r["stmt"])}</div>')
        if r.get("axioms"):
            body.append(f'<div class="axiom">⚠ depends on axiom(s): {esc(", ".join(r["axioms"]))}</div>')
        if r.get("equations"):
            body.append(f'<div class="sub" style="padding:4px 16px">+{r["equations"]} generated equation lemma(s)</div>')
        if steps:
            sb = ['<div class="steps">']
            for i, st in enumerate(steps, 1):
                sb.append(f'<div class="step"><div class="tac">{i}. {esc(st["tac"])}</div>'
                          f'<div class="lab">goals before</div><pre class="goal before">{esc(st["before"])}</pre>'
                          f'<div class="lab">goals after</div><pre class="goal">{esc(st["after"])}</pre></div>')
            if ok:
                sb.append('<div class="done">∎ no goals — proof term built and accepted by the kernel</div>')
            sb.append("</div>")
            body.append("".join(sb))
        if not ok:
            body.append(f'<div class="err">{esc(r.get("msg", ""))}</div>')
        cls = "card" + ("" if ok else " fail")
        if steps or not ok:
            cards.append(f'<details class="{cls}" data-kind="{esc(kind)}"{"" if ok else " open"}><summary>{head}</summary>{"".join(body)}</details>')
        else:
            cards.append(f'<div class="{cls}" data-kind="{esc(kind)}"><div class="head">{head}</div>{"".join(body)}</div>')
    audit_cls = "good" if audit.ok else "bad"
    audit_txt = "verified" if audit.ok else "REJECTED"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Lemma report</title><style>{CSS}</style></head><body><div class="wrap">
<header><h1>Lem<span>ma</span> report</h1><div class="sub">{esc(filename)}</div></header>
<div class="stats">
<div class="stat good"><b>{len(thms)}</b><small>theorems proved</small></div>
<div class="stat"><b>{len(defs)}</b><small>definitions</small></div>
<div class="stat"><b>{len(inds)}</b><small>inductive types</small></div>
<div class="stat {'bad' if fails else 'good'}"><b>{len(fails)}</b><small>errors</small></div>
<div class="stat {audit_cls}"><b>{audit_txt}</b><small>independent audit · {audit.checked} decls</small></div>
</div>
<div class="tools"><button data-f="all" aria-pressed="true" onclick="setFilter('all',this)">all</button>
<button data-f="proof" aria-pressed="false" onclick="setFilter('proof',this)">theorems</button>
<button data-f="fail" aria-pressed="false" onclick="setFilter('fail',this)">errors</button>
<button onclick="toggleAll(true)">expand proofs</button><button onclick="toggleAll(false)">collapse</button>
<button onclick="theme()">light / dark</button></div>
{''.join(cards)}
<footer>Generated by Lemma. Each ✓ means the trusted kernel type-checked the final proof term; the audit badge means a second,
independently written checker re-verified the exported certificate (including re-deriving every recursor).</footer>
</div><script>{JS}</script></body></html>"""
