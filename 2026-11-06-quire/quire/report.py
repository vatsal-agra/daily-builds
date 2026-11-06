"""Self-contained HTML inspector: page thumbnails, text, fonts, a file-layout map and an object browser."""
import base64
import html
import json
import re

from .objects import Stream, Ref, Name, PdfString
from .render import render_page
from .text import extract_page
from .fonts import Font


def _fmt(o, depth=0):
    if isinstance(o, Stream):
        return "stream " + _fmt(o.dict, depth)
    if isinstance(o, dict):
        return "<< " + "  ".join(f"/{k} {_fmt(v, depth + 1)}" for k, v in o.items()) + " >>"
    if isinstance(o, list):
        return "[" + " ".join(_fmt(v, depth + 1) for v in o[:60]) + (" …" if len(o) > 60 else "") + "]"
    if isinstance(o, PdfString):
        b = bytes(o)
        s = b[2:].decode("utf-16-be", "replace") if b[:2] == b"\xfe\xff" else b.decode("latin-1")
        return "(" + "".join(c if c.isprintable() else "·" for c in s[:120]) + ("…" if len(s) > 120 else "") + ")"
    if isinstance(o, Name):
        return "/" + str(o)
    if isinstance(o, Ref):
        return f"{o.num} {o.gen} R"
    return repr(o) if not isinstance(o, str) else o


def _kind(doc, num, o):
    if isinstance(o, Stream):
        t, st = o.dict.get("Type"), o.dict.get("Subtype")
        if t == "ObjStm":
            return "objstm"
        if t == "XRef":
            return "xref"
        if st == "Image":
            return "image"
        if st == "Form":
            return "form"
        if "Length1" in o.dict or st in ("Type1C", "CIDFontType0C", "OpenType") or t == "Metadata" and False:
            return "fontfile"
        if t == "Metadata":
            return "meta"
        return "content"
    if isinstance(o, dict):
        t = o.get("Type")
        if t in ("Catalog", "Pages", "Page"):
            return "page"
        if t in ("Font", "FontDescriptor") or "FontFile" in o or "FontFile2" in o or "FontFile3" in o:
            return "font"
        if t == "Annot" or "Subtype" in o and "Rect" in o:
            return "annot"
    return "other"


def build_report(doc, filename, dpi=60.0, max_pages=24, max_objects=1500):
    pages = doc.pages()
    page_data = []
    font_rows = {}
    for i, p in enumerate(pages[:max_pages]):
        try:
            cv = render_page(doc, p, dpi)
            png = base64.b64encode(cv.to_png()).decode()
        except Exception as e:  # noqa: BLE001
            png = ""
            doc.warnings.append(f"page {i + 1} thumbnail failed: {e}")
        try:
            pt = extract_page(doc, p)
            txt = pt.text()
        except Exception as e:  # noqa: BLE001
            txt = f"(text extraction failed: {e})"
        box = doc.page_box(p)
        res = doc.resolve(p.get("Resources")) or {}
        fonts = doc.resolve(res.get("Font")) if isinstance(res, dict) else None
        names = []
        if isinstance(fonts, dict):
            for k, ref in fonts.items():
                fd = doc.resolve(ref)
                if isinstance(fd, dict):
                    bf = str(doc.resolve(fd.get("BaseFont")) or k)
                    names.append(bf)
                    key = (ref.num if isinstance(ref, Ref) else id(fd))
                    font_rows.setdefault(key, {"fd": fd, "pages": []})["pages"].append(i + 1)
        page_data.append({"n": i + 1, "w": round(box[2] - box[0], 1), "h": round(box[3] - box[1], 1), "rot": doc.page_rotate(p),
                          "png": png, "text": txt, "fonts": names, "annots": len(doc.resolve(p.get("Annots")) or [])})
    fonts_out = []
    for key, v in font_rows.items():
        fd = v["fd"]
        try:
            f = Font(doc, fd)
            prog = f.program
            kind = {"tt": "TrueType/OpenType", "cff": "CFF", "t1": "Type 1"}.get(prog.kind, "?") if prog else ("Type 3 (glyph procedures)" if f.type3 else "not embedded")
            if prog and prog.kind == "tt" and prog.is_cff_sfnt:
                kind = "OpenType/CFF"
            fonts_out.append({"name": f.basefont or "(unnamed)", "subtype": f.subtype, "program": kind, "subst": bool(f.substituted),
                              "toUnicode": f.tounicode is not None, "pages": sorted(set(v["pages"]))})
        except Exception as e:  # noqa: BLE001
            fonts_out.append({"name": str(fd.get("BaseFont")), "subtype": str(fd.get("Subtype")), "program": f"unreadable ({e})", "subst": False, "toUnicode": False, "pages": v["pages"]})
    # objects + layout
    nums = sorted(n for n, e in doc.xref.items() if e[0] != "f")
    offs = sorted((e[1], n) for n, e in doc.xref.items() if e[0] == "n")
    size_of = {}
    for k, (off, n) in enumerate(offs):
        nxt = offs[k + 1][0] if k + 1 < len(offs) else len(doc.data)
        size_of[n] = nxt - off
    objects = []
    layout = []
    for n in nums:
        o = doc.get_object(n)
        kind = _kind(doc, n, o)
        ent = doc.xref[n]
        row = {"n": n, "kind": kind, "where": "objstm %d" % ent[1] if ent[0] == "c" else f"@{ent[1]}",
               "size": size_of.get(n, 0), "desc": _fmt(o)[:900]}
        if isinstance(o, Stream):
            row["stream"] = len(o.raw)
            try:
                dec = doc.decode_stream(o)
                if o.dict.get("Subtype") != "Image" and o.dict.get("Type") not in ("XRef",) and "Length1" not in o.dict:
                    row["preview"] = dec[:1500].decode("latin-1")
                else:
                    row["preview"] = " ".join("%02x" % b for b in dec[:96])
            except Exception as e:  # noqa: BLE001
                row["preview"] = f"(cannot decode: {e})"
        if ent[0] == "n":
            layout.append({"n": n, "off": ent[1], "size": size_of.get(n, 0), "kind": kind})
        objects.append(row)
    info = {k: _fmt(doc.resolve(v)) for k, v in doc.info.items()}
    meta = {
        "file": filename, "version": doc.version, "pages": len(pages), "bytes": len(doc.data),
        "objects": len(nums), "compressed": sum(1 for e in doc.xref.values() if e[0] == "c"),
        "encryption": doc.dec.describe() if doc.dec else None,
        "perms": doc.dec.permissions() if doc.dec else None,
        "repaired": doc.repair_reason if doc.repaired else None, "info": info,
        "warnings": sorted(set(doc.warnings))[:40], "truncated": len(nums) > max_objects, "shownPages": len(page_data),
    }
    data = {"meta": meta, "pages": page_data, "fonts": fonts_out, "objects": objects[:max_objects], "layout": layout}
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return TEMPLATE.replace("/*DATA*/", payload).replace("__TITLE__", html.escape(filename))


TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Quire — __TITLE__</title>
<style>
:root{--bg:#f6f5f1;--card:#fff;--ink:#1d2330;--mute:#677086;--line:#e3e0d8;--accent:#c2410c;--accent2:#0f766e;
--c-page:#6366f1;--c-font:#0f766e;--c-image:#db2777;--c-content:#2563eb;--c-form:#7c3aed;--c-fontfile:#0891b2;--c-annot:#ca8a04;--c-objstm:#64748b;--c-xref:#94a3b8;--c-meta:#a16207;--c-other:#cbd5e1;
--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
@media (prefers-color-scheme:dark){:root{--bg:#14161c;--card:#1c1f27;--ink:#e8eaf0;--mute:#8b93a7;--line:#2c3040;--accent:#fb923c;--accent2:#2dd4bf;--c-other:#475569}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Inter,sans-serif}
header{padding:28px max(16px,4vw) 8px}h1{margin:0;font-size:26px;letter-spacing:-.02em}h1 span{color:var(--accent)}
.sub{color:var(--mute);font-family:var(--mono);font-size:13px;word-break:break-all}
main{padding:8px max(16px,4vw) 60px;max-width:1280px;margin:auto}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin:14px 0}
.stat{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 14px}.stat b{display:block;font-size:22px}.stat small{color:var(--mute);text-transform:uppercase;letter-spacing:.06em;font-size:11px}
.banner{border-radius:10px;padding:10px 14px;margin:8px 0;font-size:14px;border:1px solid var(--line);background:var(--card)}
.banner.warn{border-color:#d97706;background:color-mix(in srgb,#d97706 10%,var(--card))}.banner.lock{border-color:var(--accent2)}
nav{display:flex;gap:4px;flex-wrap:wrap;margin:18px 0 12px;border-bottom:1px solid var(--line)}
nav button{background:none;border:0;padding:9px 14px;font:inherit;color:var(--mute);cursor:pointer;border-bottom:2px solid transparent;margin-bottom:-1px}
nav button[aria-selected=true]{color:var(--ink);border-color:var(--accent);font-weight:600}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px}
.pages{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:14px}
.thumb{cursor:pointer;text-align:center}.thumb img{max-width:100%;border:1px solid var(--line);border-radius:6px;box-shadow:0 2px 10px #0002;background:#fff}
.thumb small{display:block;color:var(--mute);margin-top:6px;font-size:12px}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--mute);font-size:11px;text-transform:uppercase;letter-spacing:.06em}
.tag{display:inline-block;padding:1px 8px;border-radius:99px;font-size:12px;border:1px solid var(--line);margin-right:4px;white-space:nowrap}
.dot{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:6px;vertical-align:middle}
input[type=search]{width:100%;padding:10px 14px;border-radius:10px;border:1px solid var(--line);background:var(--card);color:var(--ink);font:inherit;margin-bottom:12px}
pre{margin:0;white-space:pre-wrap;word-break:break-word;font:12.5px/1.5 var(--mono)}
.objs{display:grid;grid-template-columns:minmax(220px,340px) 1fr;gap:14px;align-items:start}
.objlist{max-height:70vh;overflow:auto;border:1px solid var(--line);border-radius:12px;background:var(--card)}
.objlist div{padding:6px 12px;cursor:pointer;display:flex;gap:8px;align-items:center;border-bottom:1px solid var(--line);font-size:13px}
.objlist div:hover,.objlist div.sel{background:color-mix(in srgb,var(--accent) 10%,var(--card))}
.objlist .n{font-family:var(--mono);min-width:44px;color:var(--mute)}
.legend{display:flex;flex-wrap:wrap;gap:6px 14px;font-size:12.5px;color:var(--mute);margin:10px 0 0}
svg.map{width:100%;height:84px;border-radius:8px;background:var(--line)}
mark{background:#facc15;color:#000;border-radius:3px}
dialog{border:0;border-radius:14px;padding:0;max-width:min(94vw,900px);background:var(--card);color:var(--ink)}dialog::backdrop{background:#000a}
dialog .body{padding:16px;display:grid;gap:14px;max-height:92vh;overflow:auto}dialog img{max-width:100%;border:1px solid var(--line)}
@media(max-width:760px){.objs{grid-template-columns:1fr}}
</style></head><body>
<header><h1><span>Quire</span> inspector</h1><div class="sub" id="file"></div></header>
<main>
<div class="stats" id="stats"></div><div id="banners"></div>
<nav role="tablist" id="tabs"></nav>
<section id="v-pages"><div class="pages" id="pages"></div></section>
<section id="v-text" hidden><input type="search" id="q" placeholder="Search the extracted text…"><div class="card" id="textout"></div></section>
<section id="v-fonts" hidden><div class="card"><table id="fonts"></table></div></section>
<section id="v-layout" hidden><div class="card"><div style="color:var(--mute);font-size:13px;margin-bottom:6px">Every indirect object placed where it sits in the file (width ∝ bytes). Hover for details, click to open in the object browser.</div>
<svg class="map" id="map" viewBox="0 0 1000 84" preserveAspectRatio="none"></svg><div class="legend" id="legend"></div></div></section>
<section id="v-objs" hidden><div class="objs"><div class="objlist" id="objlist"></div><div class="card"><div id="objhead" style="margin-bottom:8px;font-weight:600"></div><pre id="objdesc"></pre><div id="objprev"></div></div></div></section>
</main>
<dialog id="dlg"><div class="body" id="dlgbody"></div></dialog>
<script>
const D=/*DATA*/;
const KC={page:'Structure',font:'Fonts',fontfile:'Font programs',image:'Images',content:'Content streams',form:'Form XObjects',annot:'Annotations',objstm:'Object streams',xref:'Xref stream',meta:'Metadata',other:'Other'};
const $=s=>document.querySelector(s),esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const kb=n=>n<1024?n+' B':n<1048576?(n/1024).toFixed(1)+' KiB':(n/1048576).toFixed(2)+' MiB';
const m=D.meta;$('#file').textContent=m.file+' · PDF '+m.version;
$('#stats').innerHTML=[[m.pages,'pages'],[kb(m.bytes),'file size'],[m.objects,'objects'],[m.compressed,'in object streams'],[D.fonts.length,'fonts']].map(([a,b])=>`<div class="stat"><b>${a}</b><small>${b}</small></div>`).join('');
let ban='';
if(m.encryption)ban+=`<div class="banner lock">🔒 <b>${esc(m.encryption)}</b> — permissions: ${Object.entries(m.perms).map(([k,v])=>`${v?'✓':'✗'} ${k}`).join(', ')}</div>`;
if(m.repaired)ban+=`<div class="banner warn">⚠ Cross-reference table was damaged and rebuilt by scanning the file (${esc(m.repaired)}).</div>`;
m.warnings.forEach(w=>ban+=`<div class="banner warn">⚠ ${esc(w)}</div>`);
const info=Object.entries(m.info);if(info.length)ban+=`<div class="banner">${info.map(([k,v])=>`<b>${esc(k)}</b> ${esc(v)}`).join(' &nbsp;·&nbsp; ')}</div>`;
$('#banners').innerHTML=ban;
const TABS=[['pages','Pages'],['text','Text'],['fonts','Fonts'],['layout','File layout'],['objs','Objects']];
$('#tabs').innerHTML=TABS.map(([k,l],i)=>`<button role="tab" data-k="${k}" aria-selected="${i==0}">${l}</button>`).join('');
function show(k){TABS.forEach(([t])=>{$('#v-'+t).hidden=t!==k});document.querySelectorAll('#tabs button').forEach(b=>b.setAttribute('aria-selected',b.dataset.k===k))}
$('#tabs').onclick=e=>{if(e.target.dataset.k)show(e.target.dataset.k)};
$('#pages').innerHTML=D.pages.map(p=>`<div class="thumb" data-n="${p.n}">${p.png?`<img loading="lazy" alt="page ${p.n}" src="data:image/png;base64,${p.png}">`:'<div class="card">no preview</div>'}<small>page ${p.n} · ${p.w}×${p.h} pt${p.rot?' · rot '+p.rot:''}${p.annots?' · '+p.annots+' annots':''}</small></div>`).join('')+(m.pages>m.shownPages?`<div class="card">…and ${m.pages-m.shownPages} more pages not shown</div>`:'');
$('#pages').onclick=e=>{const t=e.target.closest('.thumb');if(!t)return;const p=D.pages[t.dataset.n-1];$('#dlgbody').innerHTML=`<img src="data:image/png;base64,${p.png}"><div><b>Fonts:</b> ${esc(p.fonts.join(', ')||'none')}</div><pre>${esc(p.text.slice(0,1500))}</pre>`;$('#dlg').showModal()};
$('#dlg').onclick=e=>{if(e.target===$('#dlg'))$('#dlg').close()};
function renderText(q){const re=q?new RegExp(q.replace(/[.*+?^${}()|[\]\\]/g,'\\$&'),'gi'):null;let hits=0;
 $('#textout').innerHTML=D.pages.map(p=>{let t=esc(p.text)||'<i style="color:var(--mute)">(no extractable text)</i>';if(re)t=t.replace(re,x=>{hits++;return '<mark>'+x+'</mark>'});return `<div style="margin-bottom:18px"><div class="tag">page ${p.n}</div><pre>${t}</pre></div>`}).join('')+(q?`<div class="tag">${hits} match${hits==1?'':'es'}</div>`:'')}
renderText('');$('#q').oninput=e=>renderText(e.target.value);
$('#fonts').innerHTML='<tr><th>Font</th><th>Type</th><th>Program</th><th>Unicode map</th><th>Pages</th></tr>'+(D.fonts.map(f=>`<tr><td><b>${esc(f.name)}</b></td><td>${esc(f.subtype)}</td><td>${esc(f.program)}${f.subst?' <span class="tag">substituted</span>':''}</td><td>${f.toUnicode?'ToUnicode ✓':'—'}</td><td>${f.pages.join(', ')}</td></tr>`).join('')||'<tr><td colspan=5>No fonts on the shown pages.</td></tr>');
const total=D.layout.reduce((a,l)=>Math.max(a,l.off+l.size),1);
$('#map').innerHTML=D.layout.map(l=>`<rect data-n="${l.n}" x="${l.off/total*1000}" y="6" width="${Math.max(l.size/total*1000,.6)}" height="72" fill="var(--c-${l.kind})"><title>obj ${l.n} · ${KC[l.kind]} · ${kb(l.size)}</title></rect>`).join('');
$('#map').onclick=e=>{if(e.target.dataset.n){show('objs');pick(+e.target.dataset.n)}};
const kinds=[...new Set(D.layout.map(l=>l.kind))];
$('#legend').innerHTML=kinds.map(k=>`<span><i class="dot" style="background:var(--c-${k})"></i>${KC[k]} (${kb(D.layout.filter(l=>l.kind===k).reduce((a,l)=>a+l.size,0))})</span>`).join('');
$('#objlist').innerHTML=D.objects.map(o=>`<div data-n="${o.n}"><span class="n">${o.n}</span><i class="dot" style="background:var(--c-${o.kind})"></i>${KC[o.kind]}${o.stream!=null?' · '+kb(o.stream):''}</div>`).join('')+(m.truncated?'<div>… list truncated</div>':'');
function pick(n){const o=D.objects.find(x=>x.n===n);if(!o)return;document.querySelectorAll('#objlist div').forEach(d=>d.classList.toggle('sel',+d.dataset.n===n));
 $('#objhead').textContent=`Object ${n} · ${KC[o.kind]} · ${o.where}`;$('#objdesc').textContent=o.desc;$('#objprev').innerHTML=o.preview!=null?`<div style="margin:12px 0 4px;color:var(--mute);font-size:12px">decoded stream preview</div><pre class="card" style="max-height:44vh;overflow:auto">${esc(o.preview)}</pre>`:''}
$('#objlist').onclick=e=>{const d=e.target.closest('div[data-n]');if(d)pick(+d.dataset.n)};if(D.objects.length)pick(D.objects[0].n);
</script></body></html>"""
