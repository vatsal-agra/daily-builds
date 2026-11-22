"""SVG renderer for braid-closure diagrams (over/under gaps, one colour per component)."""
from html import escape
from .link import Link, LinkError

PALETTES = {
    "light": {"bg": "#fbf7ef", "ink": "#2a2623", "muted": "#8a7f72",
              "comp": ["#c8452c", "#1f6f8b", "#6a8f3a", "#8b5fbf", "#d19a1a", "#2f2f2f"]},
    "dark": {"bg": "#16181d", "ink": "#ece7dd", "muted": "#8d93a0",
             "comp": ["#ff7a59", "#5cc8e8", "#a7d65e", "#c59cff", "#ffd166", "#e9e9e9"]},
}


def _component_ids(n, word):
    """Component index of each braid position at every level (levels 0..len(word))."""
    pos = list(range(n))               # pos[p] = starting position of the strand now at p
    levels = [pos[:]]
    for g in word:
        i = abs(g) - 1
        pos[i], pos[i + 1] = pos[i + 1], pos[i]
        levels.append(pos[:])
    final = levels[-1]                 # final[p] = start position of strand ending at p
    nxt = {final[p]: p for p in range(n)}      # start s ends at position p; closure returns to start p
    comp, cid = {}, 0
    for s in range(n):
        if s in comp:
            continue
        x = s
        while x not in comp:
            comp[x] = cid
            x = nxt[x]
        cid += 1
    return [[comp[s] for s in lv] for lv in levels], cid


def render_svg(link, title=None, caption=None, theme="light"):
    if not link.braid:
        raise LinkError("drawing needs a braid representation (use --braid, --name or --torus, not --pd)")
    n, word = link.braid
    pal = PALETTES[theme]
    dx, dy, margin = 64, 58, 64
    lanes = n
    top = 78 + n * 18
    bottom = top + dy * max(len(word), 1)
    width = margin * 2 + dx * (n - 1) + 60 + lanes * 22
    cap_lines = caption or []
    height = bottom + 60 + n * 18 + 22 * len(cap_lines)
    xs = [margin + dx * p for p in range(n)]
    ids, ncomp = _component_ids(n, word)
    col = lambda c: pal["comp"][c % len(pal["comp"])]
    W = 7
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" '
           f'height="{height}" font-family="Georgia, \'Times New Roman\', serif">',
           f'<rect width="100%" height="100%" fill="{pal["bg"]}"/>']
    if title:
        out.append(f'<text x="{width/2}" y="40" text-anchor="middle" font-size="26" fill="{pal["ink"]}" '
                   f'letter-spacing="1">{escape(title)}</text>')

    def seg(xa, ya, xb, yb):
        ym = (ya + yb) / 2
        return f"M{xa},{ya} C{xa},{ym} {xb},{ym} {xb},{yb}"

    def stroke(d, c):
        return (f'<path d="{d}" fill="none" stroke="{pal["bg"]}" stroke-width="{W + 7}" stroke-linecap="butt"/>'
                f'<path d="{d}" fill="none" stroke="{col(c)}" stroke-width="{W}" stroke-linecap="round"/>')

    levels_y = [top + dy * k for k in range(len(word) + 1)]
    under_over = []                    # drawn last, in order
    plain = []
    for k, g in enumerate(word):
        i = abs(g) - 1
        ya, yb = levels_y[k], levels_y[k + 1]
        # positions that do not take part in the crossing
        for p in range(n):
            if p not in (i, i + 1):
                plain.append(f'<path d="M{xs[p]},{ya} L{xs[p]},{yb}" stroke="{col(ids[k][p])}" '
                             f'stroke-width="{W}" stroke-linecap="round" fill="none"/>')
        tl, tr = i, i + 1
        s_tl = seg(xs[tl], ya, xs[tr], yb)      # TL -> BR
        s_tr = seg(xs[tr], ya, xs[tl], yb)      # TR -> BL
        c_tl, c_tr = ids[k][tl], ids[k][tr]
        if g > 0:                                # TL strand passes under
            under_over += [stroke(s_tl, c_tl), stroke(s_tr, c_tr)]
        else:
            under_over += [stroke(s_tr, c_tr), stroke(s_tl, c_tl)]
    # closure arcs, outermost = position 0
    arcs = []
    r = 14
    for p in range(n):
        c = ids[-1][p]
        depth = n - 1 - p
        lane_x = xs[-1] + 46 + depth * 22
        y_low = bottom + 26 + depth * 18
        y_hi = top - 26 - depth * 18
        d = (f"M{xs[p]},{bottom} L{xs[p]},{y_low - r} Q{xs[p]},{y_low} {xs[p] + r},{y_low} "
             f"L{lane_x - r},{y_low} Q{lane_x},{y_low} {lane_x},{y_low - r} "
             f"L{lane_x},{y_hi + r} Q{lane_x},{y_hi} {lane_x - r},{y_hi} "
             f"L{xs[p] + r},{y_hi} Q{xs[p]},{y_hi} {xs[p]},{y_hi + r} L{xs[p]},{top}")
        arcs.append(f'<path d="{d}" fill="none" stroke="{col(c)}" '
                    f'stroke-width="{W}" stroke-linecap="round" stroke-linejoin="round"/>')
    out += arcs + plain + under_over
    y = bottom + 56 + n * 18
    for line in cap_lines:
        out.append(f'<text x="{width/2}" y="{y}" text-anchor="middle" font-size="15" '
                   f'fill="{pal["muted"]}">{escape(line)}</text>')
        y += 22
    out.append("</svg>")
    return "\n".join(out)
