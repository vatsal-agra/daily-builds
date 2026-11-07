package sable

const reportCSS = `
:root{--bg:#f6f5f1;--panel:#fffefb;--ink:#1d2328;--muted:#5d6872;--line:#d9d6cc;--accent:#2f6f6a;--accent2:#b5532f;
--code:#f0eee6;--hdr:#2f6f6a;--edge:#6b7680;--back:#b5532f;--phi:#8a3ea0;--ls:#2f6f6a;--gc:#c9783a;
--r0:#3b7ea1;--r1:#c9783a;--r2:#5f9e6e;--r3:#a65e9a;--r4:#c9a227;--r5:#d1495b;--r6:#4a6fa5;--r7:#7a9a2e;--r8:#8c6d4f;--r9:#2a9d8f;--r10:#9a6fb0;--r11:#6b7a89}
@media (prefers-color-scheme:dark){:root{--bg:#14181b;--panel:#1b2125;--ink:#e6e9ea;--muted:#9aa5ad;--line:#2f383e;--accent:#6fc2b9;--accent2:#e08a62;
--code:#222a2f;--hdr:#6fc2b9;--edge:#8795a0;--back:#e08a62;--phi:#c58ae0;--ls:#6fc2b9;--gc:#e0a15f;
--r0:#6aaed0;--r1:#e0a15f;--r2:#85c294;--r3:#cc8fc2;--r4:#e0c458;--r5:#ec7b8a;--r6:#7f9fd0;--r7:#a5c45a;--r8:#b89b7c;--r9:#52c4b6;--r10:#bd98d0;--r11:#93a2b0}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 -apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
header{padding:28px 16px 8px;max-width:1100px;margin:0 auto}
h1{margin:0;font-size:28px;letter-spacing:-.02em}h1 span{color:var(--accent);font-weight:500}
.sub{margin:4px 0 0;color:var(--muted)}
main{max-width:1100px;margin:0 auto;padding:8px 16px 40px}
section{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px 20px;margin:18px 0}
h2{margin:0 0 10px;font-size:19px;letter-spacing:-.01em}
.note{color:var(--muted);font-size:13.5px;margin:4px 0 12px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px;background:none;border:none;padding:0}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.cl{font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
.cv{font-size:19px;font-weight:650;margin:3px 0;word-break:break-word}.cn{font-size:12.5px;color:var(--muted)}
table{border-collapse:collapse;width:100%;font-size:14px}
th,td{padding:6px 10px;border-bottom:1px solid var(--line);text-align:left}
th{font-weight:600;color:var(--muted);font-size:12.5px;text-transform:uppercase;letter-spacing:.04em}
td.num{text-align:right;font-variant-numeric:tabular-nums}
code,pre{font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace}
code{background:var(--code);padding:1px 6px;border-radius:5px;font-size:13px}
pre{background:var(--code);border-radius:8px;padding:12px 14px;overflow:auto;font-size:12.5px;line-height:1.5;margin:8px 0}
.ln{color:var(--muted);user-select:none}
details{margin:8px 0;border:1px solid var(--line);border-radius:10px;padding:2px 12px}
summary{cursor:pointer;padding:8px 0;font-weight:550}
.scroll{overflow:auto;padding:6px 0 12px;max-width:100%}
svg{display:block}
.cfg .blk rect{fill:var(--panel);stroke:var(--line);stroke-width:1.4}
.cfg .blk.hdr rect{stroke:var(--hdr);stroke-width:2.2}
.cfg text{font:12px ui-monospace,Menlo,Consolas,monospace;fill:var(--ink)}
.cfg .bname{font-weight:700;fill:var(--accent)}.cfg .term{fill:var(--accent2)}.cfg .phi{fill:var(--phi)}
.cfg .edge{fill:none;stroke:var(--edge);stroke-width:1.4}.cfg .edge.back{stroke:var(--back);stroke-dasharray:5 4}
.cfg .arrowhead{fill:var(--edge)}.cfg .elabel{font-size:11px;fill:var(--muted)}
.ivl .r{stroke:none}.ivl text,.chart text{font:11px ui-monospace,Menlo,Consolas,monospace;fill:var(--muted)}
.ivl .r0{fill:var(--r0)}.ivl .r1{fill:var(--r1)}.ivl .r2{fill:var(--r2)}.ivl .r3{fill:var(--r3)}.ivl .r4{fill:var(--r4)}.ivl .r5{fill:var(--r5)}
.ivl .r6{fill:var(--r6)}.ivl .r7{fill:var(--r7)}.ivl .r8{fill:var(--r8)}.ivl .r9{fill:var(--r9)}.ivl .r10{fill:var(--r10)}.ivl .r11{fill:var(--r11)}
.ivl .spill{stroke:var(--muted);stroke-width:1}.hatchbg{fill:var(--panel)}.hatchln{stroke:var(--muted);stroke-width:2}
.ivl .callline{stroke:var(--accent2);stroke-width:1;stroke-dasharray:2 3;opacity:.7}.ivl .xmark{fill:var(--accent2)}
.chart{width:100%;max-width:760px;margin:6px 0 14px}.chart .grid{stroke:var(--line)}
.chart .bar.ls{fill:var(--ls)}.chart .bar.gc{fill:var(--gc)}
.asm{max-height:480px}
footer{max-width:1100px;margin:0 auto;padding:0 16px 40px;color:var(--muted);font-size:13px}
@media (max-width:640px){body{font-size:14px}section{padding:14px}h1{font-size:23px}th,td{padding:5px 6px}}
`
