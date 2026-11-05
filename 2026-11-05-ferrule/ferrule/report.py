"""Self-contained HTML link-layout report (no external assets)."""
import html
import json

SEG_COLORS = {"R-X": "var(--c-text)", "R--": "var(--c-ro)", "RW-": "var(--c-data)"}
CLS_NAMES = {0: "code", 1: "read-only data", 2: "data", 3: "bss (zero-fill)"}


def _h(x):
    return html.escape(str(x), quote=True)


def _hex(v):
    return f"0x{v:x}"


def render_html(res, name="a.out"):
    total_mem = sum(s["memsz"] for s in res.segments) or 1
    secs = res.sections
    code = sum(s["size"] for s in secs if s["cls"] == 0)
    rodata = sum(s["size"] for s in secs if s["cls"] == 1)
    data = sum(s["size"] for s in secs if s["cls"] == 2)
    bss = sum(s["size"] for s in secs if s["cls"] == 3)
    saved = sum(d[2] for d in res.discarded)
    syms = sorted(((n, a) for n, a in res.symbols.items() if not n.startswith("\0")), key=lambda x: (x[1], x[0]))

    seg_html = "".join(
        f'<div class="seg" style="flex:{max(s["memsz"], 1)}" data-k="{_h(s["name"])}">'
        f'<b>{_h(s["name"])}</b><span>{_hex(s["vaddr"])}</span><span>{s["memsz"]:,} B</span></div>'
        for s in res.segments)

    sec_rows = []
    for s in secs:
        inputs = s["inputs"]
        inner = ""
        if inputs:
            rows = "".join(
                f'<tr><td class="mono">{_hex(a)}</td><td class="num">{sz:,}</td><td>{_h(o)}</td><td class="mono">{_h(sn)}</td>'
                f'<td><i style="width:{max(sz / max(s["size"], 1) * 100, 0.8):.2f}%"></i></td></tr>'
                for (o, sn, a, sz) in inputs)
            inner = (f'<div class="scroll"><table class="inner"><thead><tr><th>address</th><th>size</th><th>object</th><th>input section</th>'
                     f'<th>share</th></tr></thead><tbody>{rows}</tbody></table></div>')
        elif s["name"] == ".got":
            inner = "<p class=\"note\">Synthesised global offset table (one 8-byte slot per GOT-referenced symbol).</p>"
        else:
            inner = "<p class=\"note\">Zero-initialised common symbols only.</p>"
        sec_rows.append(
            f'<details class="sec cls{s["cls"]}"><summary><span class="dot"></span><b class="mono">{_h(s["name"])}</b>'
            f'<span class="meta">{CLS_NAMES[s["cls"]]}</span><span class="mono">{_hex(s["addr"])}</span>'
            f'<span class="num">{s["size"]:,} B</span><span class="meta">align {s["align"]}</span>'
            f'<span class="meta">{len(inputs)} input{"s" if len(inputs) != 1 else ""}</span></summary>{inner}</details>')

    disc = "".join(f'<tr><td>{_h(o)}</td><td class="mono">{_h(sn)}</td><td class="num">{sz:,}</td><td>{_h(why)}</td></tr>'
                   for o, sn, sz, why in res.discarded) or '<tr><td colspan="4" class="note">nothing discarded</td></tr>'
    pulled = "".join(f'<tr><td>{_h(a)}</td><td class="mono">{_h(m)}</td><td class="mono">{_h(why)}</td></tr>'
                     for a, m, why in res.pulled) or '<tr><td colspan="3" class="note">no archive members pulled in</td></tr>'
    sym_json = json.dumps([[n, a] for n, a in syms]).replace("</", "<\\/")

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ferrule link report — {_h(name)}</title>
<style>
:root{{--bg:#f6f4ee;--panel:#fffdf8;--ink:#1d1b16;--mute:#6b665a;--line:#e4dfd2;--accent:#b4531a;
--c-text:#c2410c;--c-ro:#4d7c0f;--c-data:#1d4ed8;--c-bss:#7c3aed;--shadow:0 1px 2px rgba(60,40,10,.08)}}
@media (prefers-color-scheme:dark){{:root{{--bg:#15130f;--panel:#1d1a14;--ink:#efeadd;--mute:#9a9380;--line:#332f25;
--accent:#f08a4b;--c-text:#fb923c;--c-ro:#a3e635;--c-data:#60a5fa;--c-bss:#c4b5fd;--shadow:none}}.seg{{color:#14110c!important}}}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}}
.mono{{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.92em}}
.num{{font-variant-numeric:tabular-nums;text-align:right}}
main{{max-width:1040px;margin:0 auto;padding:32px 16px 64px}}
h1{{font-size:28px;margin:0 0 4px;letter-spacing:-.02em}} h1 em{{color:var(--accent);font-style:normal}}
h2{{font-size:13px;text-transform:uppercase;letter-spacing:.09em;color:var(--mute);margin:36px 0 10px}}
.sub{{color:var(--mute);margin:0 0 24px}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}}
.card{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 16px;box-shadow:var(--shadow)}}
.card b{{display:block;font-size:22px;letter-spacing:-.01em}} .card span{{color:var(--mute);font-size:13px}}
.bar{{display:flex;gap:3px;height:74px}}
.seg{{border-radius:8px;padding:8px 10px;color:#fff;display:flex;flex-direction:column;justify-content:space-between;min-width:78px;overflow:hidden;font-size:12px}}
.seg b{{font-size:14px}} .seg[data-k="R-X"]{{background:var(--c-text)}} .seg[data-k="R--"]{{background:var(--c-ro)}} .seg[data-k="RW-"]{{background:var(--c-data)}}
.seg span{{opacity:.92;font-family:ui-monospace,Menlo,monospace}}
details.sec{{background:var(--panel);border:1px solid var(--line);border-radius:10px;margin:8px 0;box-shadow:var(--shadow)}}
details.sec summary{{display:grid;grid-template-columns:14px 1fr 120px 110px 90px 80px 80px;gap:10px;align-items:center;padding:10px 14px;cursor:pointer;list-style:none}}
details.sec summary::-webkit-details-marker{{display:none}}
.dot{{width:10px;height:10px;border-radius:50%;background:var(--c-text)}}
.cls1 .dot{{background:var(--c-ro)}} .cls2 .dot{{background:var(--c-data)}} .cls3 .dot{{background:var(--c-bss)}}
.meta{{color:var(--mute);font-size:13px}}
table{{width:100%;border-collapse:collapse}} th{{text-align:left;color:var(--mute);font-weight:600;font-size:12px;padding:6px 10px;border-bottom:1px solid var(--line)}}
td{{padding:5px 10px;border-bottom:1px solid var(--line);vertical-align:middle}} td i{{display:block;height:6px;border-radius:3px;background:var(--accent);opacity:.75}}
.inner{{margin:0 0 8px;min-width:480px}} .scroll{{overflow-x:auto}} td:last-child{{width:18%}}
.panel{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:6px 8px;box-shadow:var(--shadow);overflow-x:auto}}
.note{{color:var(--mute);padding:8px 14px;margin:0}}
input[type=search]{{width:100%;padding:10px 14px;border-radius:10px;border:1px solid var(--line);background:var(--panel);color:var(--ink);font:inherit;margin-bottom:8px}}
#symtbl td{{padding:4px 10px}} #cnt{{color:var(--mute);font-size:13px;margin:4px 2px 8px}}
@media (max-width:640px){{details.sec summary{{grid-template-columns:14px 1fr 90px}} details.sec summary>:nth-child(n+5){{display:none}}}}
</style></head><body><main>
<h1>Ferrule <em>link report</em></h1>
<p class="sub"><span class="mono">{_h(name)}</span> · entry <span class="mono">{_hex(res.entry)}</span> · {len(res.data):,} bytes on disk · {len(res.objects)} object(s)</p>
<div class="cards">
<div class="card"><b>{code:,}</b><span>code bytes</span></div>
<div class="card"><b>{rodata:,}</b><span>read-only data</span></div>
<div class="card"><b>{data:,}</b><span>initialised data</span></div>
<div class="card"><b>{bss:,}</b><span>bss (zero-fill)</span></div>
<div class="card"><b>{saved:,}</b><span>bytes discarded (gc / COMDAT)</span></div>
</div>
<h2>Address space ({total_mem:,} bytes mapped)</h2>
<div class="bar">{seg_html}</div>
<h2>Output sections — click to see which input sections landed where</h2>
{''.join(sec_rows)}
<h2>Archive members pulled in</h2>
<div class="panel"><table><thead><tr><th>archive</th><th>member</th><th>pulled by symbol</th></tr></thead><tbody>{pulled}</tbody></table></div>
<h2>Discarded input sections</h2>
<div class="panel"><table><thead><tr><th>object</th><th>section</th><th>bytes</th><th>reason</th></tr></thead><tbody>{disc}</tbody></table></div>
<h2>Global symbols ({len(syms):,})</h2>
<input type="search" id="q" placeholder="filter symbols by name or address…" aria-label="filter symbols">
<div id="cnt"></div>
<div class="panel"><table id="symtbl"><thead><tr><th>address</th><th>symbol</th></tr></thead><tbody></tbody></table></div>
</main>
<script>
const SYMS={sym_json};
const body=document.querySelector('#symtbl tbody'),q=document.getElementById('q'),cnt=document.getElementById('cnt');
function draw(){{const f=q.value.trim().toLowerCase();const rows=[];let n=0;
for(const [name,a] of SYMS){{const hex='0x'+a.toString(16);if(f&&!name.toLowerCase().includes(f)&&!hex.includes(f))continue;n++;
if(rows.length<400)rows.push('<tr><td class="mono">'+hex+'</td><td class="mono"></td></tr>');}}
body.innerHTML=rows.join('');let i=0;for(const [name,a] of SYMS){{const hex='0x'+a.toString(16);if(f&&!name.toLowerCase().includes(f)&&!hex.includes(f))continue;if(i>=400)break;body.rows[i++].cells[1].textContent=name;}}
cnt.textContent=n+' match'+(n===1?'':'es')+(n>400?' (showing first 400)':'');}}
q.addEventListener('input',draw);draw();
</script></body></html>
"""
