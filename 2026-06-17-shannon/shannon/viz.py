"""Self-contained interactive HTML report for a given input.

No external dependencies — everything (CSS + a little JS for tab switching) is
inlined, so the output is a single file you can open anywhere. It renders four
views straight from the real engine output:

* **Overview** — entropy numbers and a codec-size comparison bar chart.
* **Huffman** — the actual canonical Huffman tree (over the most frequent bytes).
* **BWT** — the sorted rotation matrix of a prefix, last column = transform.
* **LZ77** — the literal/back-reference token map of a prefix.
"""
from __future__ import annotations

import html
from typing import Dict, List, Tuple

from . import analyze, lz77
from . import transforms as T
from .huffman import HuffmanCode, code_lengths_from_freqs
from collections import Counter


# -- helpers ------------------------------------------------------------------

def _char_label(byte: int) -> str:
    if byte == ord(" "):
        return "␣"
    if 33 <= byte <= 126:
        return chr(byte)
    if byte == ord("\n"):
        return "\\n"
    if byte == ord("\t"):
        return "\\t"
    return f"·{byte:02x}"


# -- Huffman tree -------------------------------------------------------------

def _huffman_tree_svg(data: bytes, max_leaves: int = 28) -> str:
    counts = Counter(data)
    if not counts:
        return "<p class='muted'>empty input — no tree</p>"
    note = ""
    if len(counts) > max_leaves:
        top = dict(counts.most_common(max_leaves))
        note = (f"<p class='muted'>showing a Huffman tree built over the "
                f"{max_leaves} most frequent of {len(counts)} distinct bytes</p>")
        counts = Counter(top)
    code = HuffmanCode(code_lengths_from_freqs(counts))

    # Build a binary tree from canonical codewords.
    root: Dict = {}
    leaves: List[Tuple[Dict, int, int]] = []  # (node, symbol, length)
    for sym, (cw, length) in code.enc.items():
        node = root
        for b in range(length - 1, -1, -1):
            bit = (cw >> b) & 1
            key = "l" if bit == 0 else "r"
            child = node.get(key)
            if child is None:
                child = {}
                node[key] = child
            node = child
        node["sym"] = sym
        node["len"] = length

    # Assign x by in-order leaf index, y by depth.
    xcounter = [0]
    positions: Dict[int, Tuple[float, float]] = {}
    edges: List[Tuple[int, int]] = []
    node_info: Dict[int, Dict] = {}
    nid = [0]

    def visit(node: Dict, depth: int) -> int:
        my = nid[0]; nid[0] += 1
        is_leaf = "sym" in node
        if is_leaf:
            x = xcounter[0]; xcounter[0] += 1
            positions[my] = (x, depth)
            node_info[my] = {"leaf": True, "sym": node["sym"], "len": node["len"]}
        else:
            kids = []
            for key in ("l", "r"):
                if key in node:
                    kids.append(visit(node[key], depth + 1))
            xs = [positions[k][0] for k in kids]
            positions[my] = (sum(xs) / len(xs), depth)
            node_info[my] = {"leaf": False}
            for k in kids:
                edges.append((my, k))
        return my

    visit(root, 0)
    maxdepth = max(d for _, d in positions.values())
    maxx = max(x for x, _ in positions.values())
    PADX, PADY, SX, SY = 40, 36, max(46, 760 // (maxx + 1)), 78
    W = int(maxx * SX + 2 * PADX)
    H = int(maxdepth * SY + 2 * PADY)

    def px(n): return PADX + positions[n][0] * SX
    def py(n): return PADY + positions[n][1] * SY

    parts = [f"<svg viewBox='0 0 {W} {H}' class='tree' width='{W}' height='{H}'>"]
    for a, b in edges:
        # label the edge bit
        bit = "0" if positions[b][0] <= positions[a][0] else "1"
        # determine bit by which child key — recompute from x ordering is unreliable;
        # instead infer from edge order is complex, so use midpoint label generically
        parts.append(
            f"<line x1='{px(a):.1f}' y1='{py(a):.1f}' x2='{px(b):.1f}' "
            f"y2='{py(b):.1f}' class='edge'/>")
    # edge bit labels (0 = left child, 1 = right child) determined by x side
    for a, b in edges:
        mx, my = (px(a) + px(b)) / 2, (py(a) + py(b)) / 2
        bit = "0" if px(b) < px(a) else ("1" if px(b) > px(a) else "")
        if bit:
            parts.append(f"<text x='{mx:.1f}' y='{my:.1f}' class='bit'>{bit}</text>")
    for n, info in node_info.items():
        x, y = px(n), py(n)
        if info["leaf"]:
            lbl = html.escape(_char_label(info["sym"]))
            cw = code.enc[info["sym"]]
            bits = format(cw[0], f"0{cw[1]}b")
            parts.append(f"<g><rect x='{x-16:.1f}' y='{y-14:.1f}' width='32' "
                         f"height='28' rx='5' class='leaf'/>"
                         f"<text x='{x:.1f}' y='{y-1:.1f}' class='leaftxt'>{lbl}</text>"
                         f"<text x='{x:.1f}' y='{y+10:.1f}' class='codetxt'>{bits}</text></g>")
        else:
            parts.append(f"<circle cx='{x:.1f}' cy='{y:.1f}' r='6' class='internal'/>")
    parts.append("</svg>")
    return note + "<div class='scroll'>" + "".join(parts) + "</div>"


# -- BWT rotation matrix ------------------------------------------------------

def _bwt_matrix_html(data: bytes, max_len: int = 30) -> str:
    block = data[:max_len]
    if not block:
        return "<p class='muted'>empty input — no rotations</p>"
    s = list(block) + [T.SENTINEL]
    n = len(s)
    rotations = [tuple(s[i:] + s[:i]) for i in range(n)]
    order = sorted(range(n), key=lambda i: rotations[i])
    bw, sent_pos = T.bwt_encode(block)

    def cell(sym, last=False, sent_col=False):
        if sym == T.SENTINEL:
            txt = "$"
            cls = "sent"
        else:
            txt = html.escape(_char_label(sym))
            cls = ""
        cls += " last" if last else ""
        return f"<span class='cell {cls}'>{txt}</span>"

    rows = []
    for rank, i in enumerate(order):
        rot = rotations[i]
        cells = "".join(cell(rot[j], last=(j == n - 1)) for j in range(n))
        mark = " primary" if rank == sent_pos else ""
        tag = " ◀ output row ($ here)" if rank == sent_pos else ""
        rows.append(f"<div class='rotrow{mark}'>{cells}<span class='muted small'>{tag}</span></div>")
    note = (f"<p class='muted'>rotations of the first {len(block)} bytes + a sentinel "
            f"<span class='sent'>$</span>, sorted. The <b>last column</b> (highlighted) "
            f"is the BWT output; row {sent_pos} is the primary index.</p>")
    out_str = "".join(_char_label(b) for b in bw)
    return note + "<div class='matrix'>" + "".join(rows) + "</div>" + \
        f"<p class='mono'>BWT = <b>{html.escape(out_str)}</b> &nbsp; primary index = {sent_pos}</p>"


# -- LZ77 token map -----------------------------------------------------------

def _lz_map_html(data: bytes, max_len: int = 600) -> str:
    block = data[:max_len]
    if not block:
        return "<p class='muted'>empty input — no tokens</p>"
    tokens = lz77.tokenize(block)
    spans = []
    palette = 8
    color = 0
    nlit = nmatch = saved = 0
    for t in tokens:
        if t[0] == "l":
            nlit += 1
            spans.append(f"<span class='lit'>{html.escape(_char_label(t[1]))}</span>")
        else:
            nmatch += 1
            length, dist = t[1], t[2]
            saved += length
            color = (color + 1) % palette
            spans.append(
                f"<span class='match c{color}' title='length {length}, distance {dist}'>"
                f"[{length}&larr;{dist}]</span>")
    note = (f"<p class='muted'>LZSS parse of the first {len(block)} bytes: "
            f"{nlit} literals, {nmatch} back-references covering {saved} bytes. "
            f"Hover a <span class='match c1'>[len&larr;dist]</span> box for details.</p>")
    return note + "<div class='lzmap'>" + "".join(spans) + "</div>"


# -- assembly -----------------------------------------------------------------

_CSS = """
:root{--bg:#0f1117;--panel:#171a23;--ink:#e6e9ef;--muted:#8b93a7;--accent:#5eead4;
--accent2:#7c9cff;}
*{box-sizing:border-box}
body{margin:0;background:#0f1117;color:#e6e9ef;font:15px/1.5 ui-sans-serif,system-ui,Segoe UI,Roboto,Helvetica,Arial}
header{padding:28px 32px 12px;border-bottom:1px solid #232838}
h1{margin:0;font-size:24px;letter-spacing:.3px}
h1 .sub{color:#8b93a7;font-weight:400;font-size:15px}
.tabs{display:flex;gap:6px;padding:14px 32px 0;border-bottom:1px solid #232838;background:#0f1117;position:sticky;top:0;z-index:5}
.tab{padding:9px 16px;border:1px solid #232838;border-bottom:none;border-radius:9px 9px 0 0;
background:#141824;color:#8b93a7;cursor:pointer;font-size:14px}
.tab.active{background:#171a23;color:#5eead4;border-color:#2c3346}
.view{display:none;padding:26px 32px 64px}
.view.active{display:block}
.muted{color:#8b93a7}.small{font-size:12px}
.mono,.codetxt{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.cards{display:flex;flex-wrap:wrap;gap:14px;margin-bottom:22px}
.card{background:#171a23;border:1px solid #232838;border-radius:12px;padding:16px 18px;min-width:150px}
.card .n{font-size:26px;font-weight:600;color:#5eead4}
.card .l{color:#8b93a7;font-size:13px;margin-top:2px}
.bars{display:flex;flex-direction:column;gap:10px;max-width:720px}
.barrow{display:grid;grid-template-columns:90px 1fr 120px;align-items:center;gap:12px}
.barrow .name{color:#cdd3e0}
.track{background:#10131c;border-radius:7px;height:26px;overflow:hidden;border:1px solid #232838}
.fill{height:100%;background:linear-gradient(90deg,#7c9cff,#5eead4);display:flex;align-items:center;
justify-content:flex-end;padding-right:8px;color:#0f1117;font-weight:600;font-size:12px}
.barrow.best .fill{background:linear-gradient(90deg,#34d399,#a7f3d0)}
.barrow .sz{color:#8b93a7;text-align:right}
.scroll{overflow:auto;border:1px solid #232838;border-radius:12px;background:#11141d;padding:10px}
svg.tree{display:block}
.edge{stroke:#39415a;stroke-width:1.5}
.bit{fill:#5b6480;font-size:11px;text-anchor:middle;font-family:ui-monospace,monospace}
.leaf{fill:#1d2740;stroke:#7c9cff;stroke-width:1.5}
.leaftxt{fill:#e6e9ef;font-size:13px;text-anchor:middle;font-weight:600}
.codetxt{fill:#5eead4;font-size:9px;text-anchor:middle}
.internal{fill:#5eead4;stroke:#0f1117;stroke-width:1.5}
.matrix{font-family:ui-monospace,monospace;font-size:13px;background:#11141d;border:1px solid #232838;
border-radius:12px;padding:12px;overflow:auto}
.rotrow{white-space:nowrap;padding:1px 4px;border-radius:5px}
.rotrow.primary{background:#1d2740}
.cell{display:inline-block;width:1.5em;text-align:center;color:#aeb6c9}
.cell.last{color:#5eead4;font-weight:700}
.cell.sent,.sent{color:#f0abfc;font-weight:700}
.lzmap{font-family:ui-monospace,monospace;font-size:14px;line-height:2.1;background:#11141d;
border:1px solid #232838;border-radius:12px;padding:14px;word-break:break-all}
.lit{color:#aeb6c9}
.match{color:#0f1117;border-radius:5px;padding:1px 5px;margin:0 1px;font-weight:600;cursor:help}
.c0{background:#7c9cff}.c1{background:#5eead4}.c2{background:#fca5a5}.c3{background:#fcd34d}
.c4{background:#a7f3d0}.c5{background:#f0abfc}.c6{background:#93c5fd}.c7{background:#fdba74}
"""


def render(data: bytes, label: str = "input") -> str:
    m = analyze.measure(data)
    n = m["length"]
    # cards
    cards = [
        ("length", f"{n}", "bytes"),
        ("distinct", f"{m['distinct']}", "symbols"),
        ("H₀", f"{m['h0']:.2f}", "bits/byte"),
        ("H₁", f"{m['h1']:.2f}", "bits/byte (order-1)"),
    ]
    card_html = "".join(
        f"<div class='card'><div class='n'>{v}</div><div class='l'>{name} — {unit}</div></div>"
        for name, v, unit in cards)

    results = sorted(m["codecs"], key=lambda r: r[1])
    maxsize = max((sz for _, sz, _ in results), default=1) or 1
    best = results[0][0]
    bars = []
    for name, sz, ok in results:
        frac = sz / maxsize
        cls = "barrow best" if name == best else "barrow"
        ratio = (sz / n) if n else 0
        bars.append(
            f"<div class='{cls}'><div class='name'>{name}</div>"
            f"<div class='track'><div class='fill' style='width:{frac*100:.1f}%'>"
            f"{ratio:.3f}x</div></div><div class='sz'>{sz} B</div></div>")
    overview = (f"<div class='cards'>{card_html}</div>"
                f"<h3>codec comparison <span class='muted small'>(shorter is better; "
                f"green = winner)</span></h3><div class='bars'>{''.join(bars)}</div>")

    tree = _huffman_tree_svg(data)
    matrix = _bwt_matrix_html(data)
    lzmap = _lz_map_html(data)

    tabs = [("overview", "Overview"), ("huffman", "Huffman tree"),
            ("bwt", "BWT matrix"), ("lz77", "LZ77 tokens")]
    tab_html = "".join(
        f"<div class='tab{' active' if i == 0 else ''}' data-t='{tid}'>{tlabel}</div>"
        for i, (tid, tlabel) in enumerate(tabs))
    views = {
        "overview": overview, "huffman": tree, "bwt": matrix, "lz77": lzmap,
    }
    view_html = "".join(
        f"<section class='view{' active' if i == 0 else ''}' id='v-{tid}'>{views[tid]}</section>"
        for i, (tid, _) in enumerate(tabs))

    js = """
    document.querySelectorAll('.tab').forEach(function(t){
      t.addEventListener('click',function(){
        document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));
        document.querySelectorAll('.view').forEach(x=>x.classList.remove('active'));
        t.classList.add('active');
        document.getElementById('v-'+t.dataset.t).classList.add('active');
      });
    });
    """
    return f"""<!doctype html>
<html lang='en'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Shannon — {html.escape(label)}</title>
<style>{_CSS}</style></head>
<body>
<header><h1>Shannon <span class='sub'>— compression report for {html.escape(label)}</span></h1></header>
<div class='tabs'>{tab_html}</div>
{view_html}
<script>{js}</script>
</body></html>"""
