"""Self-contained HTML/SVG visualizers for all four required features (plus
variant calling) — no build step, no CDN, no JS framework: a handful of
inline `<svg>` fragments generated directly from real run data, wrapped in
one small tabbed HTML shell with ~40 lines of vanilla JS.

Pure Python 3 stdlib only.
"""
from __future__ import annotations

import html
from collections import Counter

from helix.align import align_affine, _gotoh_matrices, _score_fn, NEG_INF
from helix.assembly import DeBruijnGraph, weakly_connected_components
from helix.phylo import TreeNode

# ---------------------------------------------------------------------------
# shared palette / svg helpers
# ---------------------------------------------------------------------------

COLORS = {
    "bg": "#0f1117", "panel": "#171b26", "border": "#2b3245",
    "text": "#e7ebf3", "muted": "#8890a3",
    "match": "#38b6a6", "mismatch": "#ef5f6b", "gap": "#f0a34d",
    "path": "#7aa2ff", "variant": "#f2c14e", "read": "#3d4a68",
    "read_alt": "#4a5a82",
}


def _esc(s) -> str:
    return html.escape(str(s), quote=True)


def _svg(width: int, height: int, body: str) -> str:
    return (
        f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'xmlns="http://www.w3.org/2000/svg" font-family="ui-monospace,SFMono-Regular,'
        f'Consolas,monospace">{body}</svg>'
    )


def _text(x, y, s, *, size=12, fill=None, anchor="start", weight="normal") -> str:
    fill = fill or COLORS["text"]
    return (f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" '
            f'text-anchor="{anchor}" font-weight="{weight}">{_esc(s)}</text>')


# ---------------------------------------------------------------------------
# 1. Alignment traceback matrix
# ---------------------------------------------------------------------------

def render_alignment_svg(
    seq_a: str, seq_b: str, *,
    match: int = 2, mismatch: int = -1, gap_open: int = 4, gap_extend: int = 1,
    mode: str = "global",
) -> str:
    """DP traceback matrix for a Gotoh affine-gap alignment of two SHORT
    sequences (meant for teaching-scale inputs, not genome-scale — the grid
    is O(n*m) cells)."""
    trace: list = []
    result = align_affine(
        seq_a, seq_b, mode=mode, match=match, mismatch=mismatch,
        gap_open=gap_open, gap_extend=gap_extend, trace=trace,
    )
    score_fn = _score_fn(match, mismatch, None)
    M, D, I, _ = _gotoh_matrices(seq_a, seq_b, score_fn, gap_open, gap_extend, local=(mode == "local"))
    n, m = len(seq_a), len(seq_b)
    trace_set = set(trace)

    cell = 34
    gutter = 26
    ox, oy = gutter + cell, gutter + cell
    width = ox + (m + 1) * cell + 20
    height = oy + (n + 1) * cell + 60

    parts = [f'<rect width="{width}" height="{height}" fill="{COLORS["panel"]}" rx="10"/>']
    # column headers (seq_b)
    parts.append(_text(ox + cell // 2, oy - 10, "-", size=13, fill=COLORS["muted"], anchor="middle"))
    for j, ch in enumerate(seq_b):
        parts.append(_text(ox + (j + 1) * cell + cell // 2, oy - 10, ch, size=13, anchor="middle"))
    # row headers (seq_a)
    parts.append(_text(ox - 10, oy + cell // 2 + 4, "-", size=13, fill=COLORS["muted"], anchor="end"))
    for i, ch in enumerate(seq_a):
        parts.append(_text(ox - 10, oy + (i + 1) * cell + cell // 2 + 4, ch, size=13, anchor="end"))

    def cell_score(i, j):
        v = max(M[i][j], D[i][j], I[i][j])
        return None if v == NEG_INF else v

    for i in range(n + 1):
        for j in range(m + 1):
            x, y = ox + j * cell, oy + i * cell
            on_path = (i, j) in trace_set
            fill = COLORS["path"] if on_path else "#1d2233"
            opacity = "0.85" if on_path else "1"
            parts.append(f'<rect x="{x}" y="{y}" width="{cell - 2}" height="{cell - 2}" '
                          f'rx="4" fill="{fill}" opacity="{opacity}" stroke="{COLORS["border"]}"/>')
            v = cell_score(i, j)
            if v is not None:
                txt_color = "#0c0e14" if on_path else COLORS["muted"]
                parts.append(_text(x + cell // 2 - 1, y + cell // 2 + 4, v, size=11,
                                    fill=txt_color, anchor="middle"))

    # path polyline connecting cell centers, drawn under the score text
    if len(trace) > 1:
        pts = " ".join(f"{ox + j*cell + cell//2 - 1},{oy + i*cell + cell//2 - 1}" for i, j in trace)
        parts.insert(1, f'<polyline points="{pts}" fill="none" stroke="{COLORS["path"]}" '
                        f'stroke-width="3" opacity="0.55" stroke-linecap="round"/>')

    # aligned strings beneath the grid
    ay = oy + (n + 1) * cell + 30
    ax = ox
    for x, y in zip(result.aligned_a, result.aligned_b):
        color = COLORS["match"] if x == y and x != "-" else (COLORS["gap"] if "-" in (x, y) else COLORS["mismatch"])
        parts.append(_text(ax, ay, x, size=14, fill=color, anchor="middle"))
        parts.append(_text(ax, ay + 18, y, size=14, fill=color, anchor="middle"))
        ax += 16

    svg = _svg(width, height, "".join(parts))
    caption = (f"score={result.score} &middot; cigar={_esc(result.cigar)} &middot; "
               f"mode={mode} &middot; blue path = real traceback through the DP matrix")
    return f'<div class="viz-caption">{caption}</div>{svg}'


# ---------------------------------------------------------------------------
# 2. Phylogenetic dendrogram (rectangular cladogram)
# ---------------------------------------------------------------------------

def render_dendrogram_svg(tree: TreeNode, *, method_label: str = "") -> str:
    leaves = tree.leaves()
    n_leaves = len(leaves)
    row_h = 34
    longest_name = max((len(leaf.name) for leaf in leaves), default=1)
    left_pad, top_pad = 140, 30
    right_pad = 24 + longest_name * 8  # ~8px/char at font-size 13 monospace
    max_depth = _max_root_depth(tree)
    plot_w = 480

    def x_of(depth: float) -> float:
        if max_depth == 0:
            return left_pad
        return left_pad + (depth / max_depth) * plot_w

    width = left_pad + plot_w + right_pad
    height = top_pad * 2 + n_leaves * row_h

    y_of_leaf = {}
    for idx, leaf in enumerate(leaves):
        y_of_leaf[id(leaf)] = top_pad + idx * row_h + row_h / 2

    parts = [f'<rect width="{width}" height="{height}" fill="{COLORS["panel"]}" rx="10"/>']

    def walk(node: TreeNode, depth: float) -> float:
        """Returns this node's y-coordinate; draws its subtree."""
        x = x_of(depth)
        if node.is_leaf():
            y = y_of_leaf[id(node)]
            parts.append(_text(x + 8, y + 4, node.name, size=13))
            return y
        child_ys = []
        for c in node.children:
            cy = walk(c, depth + c.branch_length)
            cx = x_of(depth + c.branch_length)
            parts.append(f'<line x1="{x}" y1="{cy}" x2="{cx}" y2="{cy}" '
                         f'stroke="{COLORS["path"]}" stroke-width="2"/>')
            child_ys.append(cy)
        y = sum(child_ys) / len(child_ys)
        parts.append(f'<line x1="{x}" y1="{min(child_ys)}" x2="{x}" y2="{max(child_ys)}" '
                     f'stroke="{COLORS["path"]}" stroke-width="2"/>')
        return y

    walk(tree, 0.0)
    svg = _svg(width, height, "".join(parts))
    caption = f"{_esc(method_label)} &middot; x-position = cumulative branch length from the root"
    return f'<div class="viz-caption">{caption if method_label else ""}</div>{svg}'


def _max_root_depth(tree: TreeNode) -> float:
    best = [0.0]

    def walk(node, depth):
        best[0] = max(best[0], depth)
        for c in node.children:
            walk(c, depth + c.branch_length)

    walk(tree, 0.0)
    return best[0] or 1.0


# ---------------------------------------------------------------------------
# 3. De Bruijn assembly graph — compressed to unitig-level segments
# ---------------------------------------------------------------------------

def _compress_to_segments(graph: DeBruijnGraph):
    """Collapse every maximal run of degree-(1,1) nodes into one visual
    'segment' edge — the same simplification real assembly-graph viewers
    (e.g. Bandage) use, since drawing one box per k-mer is illegible at any
    real scale. Returns (junctions, segments) where a junction is any node
    that is NOT a simple pass-through (a branch point, a tip, or an
    isolated endpoint), and each segment is (from, to, length_in_edges)."""
    def out_deg(n):
        return sum(graph.edges.get(n, {}).values())

    rev: dict[str, Counter] = {}
    for u, nbrs in graph.edges.items():
        for v, c in nbrs.items():
            rev.setdefault(v, Counter())[u] += c

    def in_deg(n):
        return sum(rev.get(n, {}).values())

    def is_junction(n):
        return not (out_deg(n) == 1 and in_deg(n) == 1)

    junctions = [n for n in graph.nodes() if is_junction(n)]
    visited_start_of_segment = set()
    segments = []
    for j in junctions:
        for v0 in list(graph.edges.get(j, {}).keys()):
            key = (j, v0)
            if key in visited_start_of_segment:
                continue
            length = 1
            cur = v0
            while not is_junction(cur):
                visited_start_of_segment.add((cur, next(iter(graph.edges[cur]))))
                cur = next(iter(graph.edges[cur]))
                length += 1
            segments.append((j, cur, length))
    return junctions, segments


def render_assembly_graph_svg(graph: DeBruijnGraph, *, highlight_note: str = "") -> str:
    comps = weakly_connected_components(graph)
    junctions, segments = _compress_to_segments(graph)

    # Layered left-to-right layout: depth = distance (in segments) from a
    # component's start; row = a vertical "lane" assigned depth-first so a
    # single unbranching chain stays on one horizontal line (its first/only
    # child inherits the parent's lane) and only an actual branch point
    # opens new lanes for its extra children.
    adj: dict[str, list[str]] = {}
    for a, b, _ in segments:
        adj.setdefault(a, []).append(b)
    incoming = Counter(b for _, b, _ in segments)
    depth: dict[str, int] = {}
    row: dict[str, int] = {}
    next_row = [0]

    def assign(start: str, start_row: int, visited: set) -> None:
        # Iterative DFS (a junction-compressed graph could still, in
        # principle, chain long enough to blow Python's recursion limit).
        stack = [(start, 0, start_row)]
        while stack:
            node, d, r = stack.pop()
            if node in visited:
                continue
            visited.add(node)
            depth[node] = d
            row[node] = r
            children = adj.get(node, [])
            # push in reverse so the first child pops (and is visited)
            # first, keeping a simple chain's node order intuitive
            for k in range(len(children) - 1, -1, -1):
                child = children[k]
                if k == 0:
                    stack.append((child, d + 1, r))
                else:
                    stack.append((child, d + 1, next_row[0]))
                    next_row[0] += 1

    visited: set = set()
    for comp in comps:
        comp_junctions = [j for j in junctions if j in comp]
        if not comp_junctions:
            continue
        starts = [j for j in comp_junctions if incoming[j] == 0] or comp_junctions[:1]
        for s in starts:
            if s in visited:
                continue
            # Reserve this row BEFORE descending: assign() may itself
            # allocate further new rows for extra branches while it runs,
            # and if the reservation happened only after it returns, a
            # branch discovered mid-DFS could grab this same still-unused
            # row number out from under the node it was meant for.
            start_row = next_row[0]
            next_row[0] += 1
            assign(s, start_row, visited)
        for j in comp_junctions:  # any junction a cycle kept DFS from reaching
            if j not in visited:
                start_row = next_row[0]
                next_row[0] += 1
                assign(j, start_row, visited)

    col_w, row_h = 150, 60
    pad = 40
    max_depth = max(depth.values(), default=0)
    n_rows = next_row[0] or 1
    width = pad * 2 + (max_depth + 1) * col_w
    height = pad * 2 + n_rows * row_h

    def pos(n):
        return pad + depth.get(n, 0) * col_w + 60, pad + row.get(n, 0) * row_h + 25

    parts = [f'<rect width="{width}" height="{height}" fill="{COLORS["panel"]}" rx="10"/>']
    for a, b, length in segments:
        ax, ay = pos(a)
        bx, by = pos(b)
        mx = (ax + bx) / 2
        parts.append(f'<line x1="{ax}" y1="{ay}" x2="{bx}" y2="{by}" '
                     f'stroke="{COLORS["match"]}" stroke-width="3" opacity="0.8"/>')
        parts.append(_text(mx, (ay + by) / 2 - 8, f"{length}bp", size=10, fill=COLORS["muted"], anchor="middle"))
    for j in junctions:
        x, y = pos(j)
        deg_out = sum(graph.edges.get(j, {}).values())
        deg_in = sum(1 for a, b, _ in segments if b == j)
        kind = "tip" if deg_out == 0 or deg_in == 0 else "branch"
        color = COLORS["mismatch"] if kind == "tip" else COLORS["variant"]
        parts.append(f'<circle cx="{x}" cy="{y}" r="7" fill="{color}"/>')

    svg = _svg(width, height, "".join(parts))
    legend = (
        f'<span style="color:{COLORS["match"]}">&#9644;</span> unitig segment &nbsp; '
        f'<span style="color:{COLORS["variant"]}">&#9679;</span> branch point &nbsp; '
        f'<span style="color:{COLORS["mismatch"]}">&#9679;</span> tip/dead-end'
    )
    caption = f'{legend} &middot; {len(junctions)} junction(s), {len(segments)} segment(s), {len(comps)} component(s)'
    if highlight_note:
        caption += f" &middot; {_esc(highlight_note)}"
    return f'<div class="viz-caption">{caption}</div>{svg}'


# ---------------------------------------------------------------------------
# 4. Genome browser / pileup view
# ---------------------------------------------------------------------------

def render_pileup_svg(
    reference: str, placed_reads: list[tuple[int, str]], variants: list,
    *, window: tuple[int, int] | None = None, max_rows: int = 40,
) -> str:
    start, end = window or (0, len(reference))
    span = end - start
    px_per_base = max(2, min(10, 900 // max(span, 1)))
    left_pad, top_pad = 50, 40
    width = left_pad + span * px_per_base + 20
    row_h = 10

    # greedy interval packing so overlapping reads stack into new rows
    rows_end: list[int] = []
    placements = []
    for s, seq in sorted(placed_reads, key=lambda t: t[0]):
        e = s + len(seq)
        if e <= start or s >= end:
            continue
        row = None
        for ridx, row_end in enumerate(rows_end):
            if s >= row_end:
                row = ridx
                break
        if row is None:
            if len(rows_end) >= max_rows:
                continue
            row = len(rows_end)
            rows_end.append(0)
        rows_end[row] = e + 1
        placements.append((row, s, seq))

    n_rows = len(rows_end)
    height = top_pad + n_rows * row_h + 70

    def x_of(pos):
        return left_pad + (pos - start) * px_per_base

    parts = [f'<rect width="{width}" height="{height}" fill="{COLORS["panel"]}" rx="10"/>']
    # ruler
    tick_every = max(1, span // 10 // 10 * 10) or 10
    p = (start // tick_every) * tick_every
    while p <= end:
        if p >= start:
            x = x_of(p)
            parts.append(f'<line x1="{x}" y1="{top_pad-6}" x2="{x}" y2="{top_pad}" stroke="{COLORS["muted"]}"/>')
            parts.append(_text(x, top_pad - 10, p, size=9, fill=COLORS["muted"], anchor="middle"))
        p += tick_every
    parts.append(f'<line x1="{left_pad}" y1="{top_pad}" x2="{width-20}" y2="{top_pad}" stroke="{COLORS["muted"]}"/>')

    for row, s, seq in placements:
        y = top_pad + 6 + row * row_h
        x = x_of(max(s, start))
        vis_start = max(s, start)
        vis_end = min(s + len(seq), end)
        w = max(1, (vis_end - vis_start) * px_per_base)
        parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{row_h-2}" rx="2" fill="{COLORS["read"]}"/>')
        for i, base in enumerate(seq):
            pos = s + i
            if start <= pos < end and 0 <= pos < len(reference) and base != reference[pos]:
                mx = x_of(pos)
                parts.append(f'<rect x="{mx}" y="{y}" width="{max(1,px_per_base)}" '
                             f'height="{row_h-2}" fill="{COLORS["mismatch"]}"/>')

    # variant markers below the reads
    vy = top_pad + n_rows * row_h + 20
    for v in variants:
        if not (start <= v.position < end):
            continue
        x = x_of(v.position)
        title = f"{v.position}: {v.ref_base}>{v.alt_base} AF={v.allele_frequency:.2f} DP={v.depth}"
        parts.append(
            f'<g><title>{_esc(title)}</title>'
            f'<circle cx="{x}" cy="{vy}" r="5" fill="{COLORS["variant"]}"/>'
            f'<line x1="{x}" y1="{top_pad}" x2="{x}" y2="{vy}" '
            f'stroke="{COLORS["variant"]}" stroke-dasharray="2,2" opacity="0.6"/></g>'
        )
    parts.append(_text(left_pad, vy + 18, f"{len(variants)} variant(s) called in this window "
                                          f"(hover a marker for details)", size=10, fill=COLORS["muted"]))

    svg = _svg(width, height, "".join(parts))
    caption = (f"reference [{start}:{end}] &middot; {len(placements)} reads shown "
               f"(of {len(placed_reads)} placed) &middot; red = mismatch vs. reference")
    return f'<div class="viz-caption">{caption}</div>{svg}'


# ---------------------------------------------------------------------------
# HTML report shell
# ---------------------------------------------------------------------------

_CSS = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body { margin:0; background:%(bg)s; color:%(text)s; font-family:-apple-system,
  BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif; }
header { padding:28px 32px 12px; border-bottom:1px solid %(border)s; }
header h1 { margin:0 0 4px; font-size:22px; letter-spacing:.2px; }
header p { margin:0; color:%(muted)s; font-size:13px; }
nav { display:flex; gap:4px; padding:14px 32px 0; border-bottom:1px solid %(border)s; }
nav button { background:none; border:none; color:%(muted)s; font-size:14px; padding:10px 16px;
  cursor:pointer; border-radius:8px 8px 0 0; }
nav button.active { color:%(text)s; background:%(panel)s; }
nav button:hover { color:%(text)s; }
main { padding:28px 32px 60px; }
section { display:none; }
section.active { display:block; }
section h2 { font-size:16px; margin:0 0 4px; }
section .sub { color:%(muted)s; font-size:12.5px; margin:0 0 18px; }
.viz-block { margin-bottom:34px; background:%(panel)s; border:1px solid %(border)s;
  border-radius:12px; padding:18px; overflow-x:auto; }
.viz-caption { color:%(muted)s; font-size:12px; margin-bottom:10px; }
svg { display:block; }
footer { padding:20px 32px 40px; color:%(muted)s; font-size:12px; border-top:1px solid %(border)s; }
"""

_JS = """
function showTab(name){
  document.querySelectorAll('section').forEach(s=>s.classList.toggle('active', s.id==='tab-'+name));
  document.querySelectorAll('nav button').forEach(b=>b.classList.toggle('active', b.dataset.tab===name));
}
showTab(document.querySelector('nav button').dataset.tab);
"""


def build_report_html(sections: list[tuple[str, str, str]], *, title: str = "Helix Report") -> str:
    """sections: list of (tab_id, tab_label, inner_html)."""
    nav = "".join(
        f'<button data-tab="{_esc(tid)}" onclick="showTab(\'{_esc(tid)}\')">{_esc(label)}</button>'
        for tid, label, _ in sections
    )
    body = "".join(f'<section id="tab-{_esc(tid)}">{inner}</section>' for tid, _, inner in sections)
    css = _CSS % COLORS
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{_esc(title)}</title>
<style>{css}</style></head>
<body>
<header><h1>{_esc(title)}</h1>
<p>A from-scratch computational biology toolkit — pairwise alignment, phylogenetics,
de novo assembly, and variant calling, visualized from a real run of this session.</p></header>
<nav>{nav}</nav>
<main>{body}</main>
<footer>Generated by <code>helix viz</code> &middot; pure Python 3 stdlib, no dependencies, no CDN.</footer>
<script>{_JS}</script>
</body></html>"""
