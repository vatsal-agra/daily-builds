"""Text extraction: glyph runs -> words -> lines -> blocks (recursive XY-cut) -> reading order,
plus text search returning page-space bounding boxes."""
import math
import statistics
import unicodedata
from collections import namedtuple

from .content import Device, Interpreter, hidden_ocgs, mmul, IDENT

TChar = namedtuple("TChar", "text x0 y0 x1 y1 size base_x base_y")  # display-space bbox (y up) + origin
_LIGS = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st"}


class _Collector(Device):
    def __init__(self, rot, box):
        self.rot = rot
        self.box = box
        self.chars = []  # (angle_bucket, TChar-in-display-space)

    def _disp(self, x, y):
        x0, y0, x1, y1 = self.box
        rot = self.rot
        if rot == 0:
            return x - x0, y - y0
        if rot == 90:
            return y - y0, x1 - x
        if rot == 180:
            return x1 - x, y1 - y
        return y1 - y, x - x0

    def text(self, font, glyph, trm, adv_user, size, visible):
        if not glyph.text and not glyph.is_space:
            return
        a, b, c, d, e, f = trm
        ex, ey = self._disp(e, f)
        # baseline direction in display space
        bx, by = self._disp(e + a, f + b)
        dx, dy = bx - ex, by - ey
        ang = math.degrees(math.atan2(dy, dx))
        bucket = int(round(ang / 90.0)) % 4 * 90
        vsize = math.hypot(c, d) or abs(size)
        hsize = math.hypot(a, b)
        # advance along baseline in display units
        n = math.hypot(dx, dy) or 1.0
        ux, uy = dx / n, dy / n
        adv = adv_user
        # glyph box: along baseline [0, adv], perpendicular [-0.22, 0.78] * vsize
        px, py = -uy, ux
        corners = []
        for t, h in ((0, -0.22), (adv, -0.22), (adv, 0.78), (0, 0.78)):
            corners.append((ex + ux * t + px * h * vsize, ey + uy * t + py * h * vsize))
        xs = [p[0] for p in corners]
        ys = [p[1] for p in corners]
        txt = glyph.text
        self.chars.append((bucket, TChar(txt, min(xs), min(ys), max(xs), max(ys), vsize, ex, ey), visible))


Line = namedtuple("Line", "text x0 y0 x1 y1 size chars")


def _rot_char(ch, bucket, W, H):
    """Rotate a display-space char into its own upright frame."""
    def rp(x, y):
        if bucket == 0:
            return x, y
        if bucket == 90:      # text runs upward -> rotate clockwise to horizontal
            return y, -x
        if bucket == 180:
            return -x, -y
        return -y, x
    p0 = rp(ch.x0, ch.y0)
    p1 = rp(ch.x1, ch.y1)
    bx, by = rp(ch.base_x, ch.base_y)
    return TChar(ch.text, min(p0[0], p1[0]), min(p0[1], p1[1]), max(p0[0], p1[0]), max(p0[1], p1[1]), ch.size, bx, by)


def build_lines(chars):
    """chars in content order (single orientation) -> list of Line."""
    lines = []
    cur = []
    for ch in chars:
        if cur:
            last = cur[-1]
            tol = 0.35 * max(last.size, ch.size, 1e-6)
            same_base = abs(ch.base_y - last.base_y) <= tol
            gap = ch.x0 - last.x1
            if same_base and -0.6 * ch.size <= gap <= 8 * ch.size:
                cur.append(ch)
                continue
            # content order jumped: try to attach to an existing line (e.g. text drawn out of order)
        placed = False
        if cur:
            lines.append(cur)
        cur = [ch]
    if cur:
        lines.append(cur)
    # merge runs that share a baseline and are horizontally interleaved (kerned across Tj pieces)
    merged = []
    for run in lines:
        merged.append(run)
    return merged


def _line_from_run(run):
    parts = []
    last = None
    for ch in run:
        if last is not None:
            gap = ch.x0 - last.x1
            thresh = 0.18 * max(ch.size, last.size)
            if gap > thresh and not (parts and parts[-1].endswith(" ")) and ch.text != " " and not ch.text.startswith(" "):
                parts.append(" ")
        parts.append(ch.text)
        last = ch
    text = "".join(parts)
    return Line(text, min(c.x0 for c in run), min(c.y0 for c in run), max(c.x1 for c in run), max(c.y1 for c in run),
                statistics.median(c.size for c in run), run)


def _join_same_baseline(runs):
    """Runs on the same baseline that touch/abut (separate show-ops) become one line;
    runs far apart stay separate (table cells / columns)."""
    runs = sorted(runs, key=lambda r: (-round(r[0].base_y, 0), r[0].x0))
    out = []
    for r in runs:
        for o in out:
            tol = 0.3 * max(o[-1].size, r[0].size)
            if abs(o[0].base_y - r[0].base_y) <= tol:
                gap = r[0].x0 - o[-1].x1
                if -0.6 * r[0].size <= gap <= 1.5 * max(r[0].size, 1):
                    o.extend(r)
                    break
        else:
            out.append(list(r))
    return out


def order_lines(lines):
    """Recursive XY-cut over Line objects (display space, y up). Returns list of blocks (list of lines)."""
    if len(lines) <= 1:
        return [lines] if lines else []
    med = statistics.median(l.size for l in lines) or 10.0
    # --- vertical gutter?
    xs = sorted(lines, key=lambda l: l.x0)
    reach = xs[0].x1
    best = None
    for l in xs[1:]:
        if l.x0 - reach >= 2.0 * med and (best is None or l.x0 - reach > best[0]):
            best = (l.x0 - reach, reach, l.x0)
        reach = max(reach, l.x1)
    if best is not None:
        cut = (best[1] + best[2]) / 2
        left = [l for l in lines if (l.x0 + l.x1) / 2 < cut]
        right = [l for l in lines if (l.x0 + l.x1) / 2 >= cut]
        if left and right and len(left) < len(lines):
            return order_lines(left) + order_lines(right)
    # --- horizontal cut at the biggest empty band
    ys = sorted(lines, key=lambda l: -l.y1)
    reach = ys[0].y0
    best = None
    for l in ys[1:]:
        gap = reach - l.y1
        if gap > 0 and (best is None or gap > best[0]):
            best = (gap, (reach + l.y1) / 2)
        reach = min(reach, l.y0)
    if best is not None:
        cut = best[1]
        top = [l for l in lines if (l.y0 + l.y1) / 2 >= cut]
        bot = [l for l in lines if (l.y0 + l.y1) / 2 < cut]
        if top and bot:
            return order_lines(top) + order_lines(bot)
    return [sorted(lines, key=lambda l: (-round((l.y0 + l.y1) / 2 / max(med * 0.5, 1)), l.x0))]


class PageText:
    def __init__(self, blocks, chars, box, rot):
        self.blocks = blocks
        self.box = box
        self.rot = rot
        self.chars = chars

    @property
    def lines(self):
        return [l for b in self.blocks for l in b]

    def text(self, expand_ligatures=True, paragraphs=True):
        out = []
        prev = None
        for l in self.lines:
            if prev is not None:
                new_para = (l.y1 > prev.y0 + 0.2 * l.size) or (prev.y0 - l.y1 > 0.7 * max(l.size, prev.size))
                out.append("\n\n" if (new_para and paragraphs) else "\n")
            out.append(l.text)
            prev = l
        s = "".join(out)
        s = unicodedata.normalize("NFC", s)
        if expand_ligatures:
            for k, v in _LIGS.items():
                s = s.replace(k, v)
        return s


def extract_page(doc, page, include_invisible=True):
    box = doc.page_box(page)
    rot = doc.page_rotate(page)
    col = _Collector(rot, box)
    res = doc.resolve(page.get("Resources"))
    data = doc.page_content(page)
    base = IDENT
    Interpreter(doc, col, res, base, hidden_ocgs=hidden_ocgs(doc)).run(data)
    by = {}
    for bucket, ch, visible in col.chars:
        if visible or include_invisible:
            by.setdefault(bucket, []).append(ch)
    W, H = box[2] - box[0], box[3] - box[1]
    all_blocks = []
    flat = []
    for bucket in sorted(by, key=lambda b: (b != 0, b)):
        rotated = [_rot_char(c, bucket, W, H) for c in by[bucket]]
        runs = build_lines(rotated)
        runs = _join_same_baseline(runs)
        lines = [_line_from_run(r) for r in runs if r]
        lines = [l for l in lines if l.text.strip()]
        all_blocks += order_lines(lines)
        flat += by[bucket]
    return PageText(all_blocks, flat, box, rot)


def extract_text(doc, pages=None, expand_ligatures=True):
    out = []
    pl = doc.pages()
    for i, p in enumerate(pl):
        if pages is not None and i not in pages:
            continue
        out.append(extract_page(doc, p).text(expand_ligatures))
    return "\f".join(out)


# --------------------------------------------------------------- search ----
Match = namedtuple("Match", "page text boxes")


def search_page(doc, page_index, page, query, ignore_case=True):
    """Find `query` in reading-order text; returns Match list with page-space (user space) rects."""
    pt = extract_page(doc, page)
    seq = []     # (char, bbox display space) in reading order
    for line in pt.lines:
        for i, ch in enumerate(line.chars):
            if i and ch.x0 - line.chars[i - 1].x1 > 0.18 * max(ch.size, line.chars[i - 1].size) and not ch.text.startswith(" ") and not line.chars[i - 1].text.endswith(" "):
                seq.append((" ", None))
            for t in ch.text:
                seq.append((t, ch))
        seq.append((" ", None))
    hay = "".join(c for c, _ in seq)
    if ignore_case:
        hay_cmp, q = hay.lower(), query.lower()
    else:
        hay_cmp, q = hay, query
    q = " ".join(q.split())
    out = []
    i = 0
    while q:
        j = hay_cmp.find(q, i)
        if j < 0:
            break
        boxes = []
        cur = None
        for c, ch in seq[j:j + len(q)]:
            if ch is None:
                continue
            # merge consecutive chars on the same line into one box
            if cur and abs(ch.base_y - cur[4]) < 0.5 * ch.size and ch.x0 - cur[2] < ch.size:
                cur[0], cur[1] = min(cur[0], ch.x0), min(cur[1], ch.y0)
                cur[2], cur[3] = max(cur[2], ch.x1), max(cur[3], ch.y1)
            else:
                if cur:
                    boxes.append(tuple(cur[:4]))
                cur = [ch.x0, ch.y0, ch.x1, ch.y1, ch.base_y]
        if cur:
            boxes.append(tuple(cur[:4]))
        out.append(Match(page_index, hay[j:j + len(q)], [display_to_user(b, pt.box, pt.rot) for b in boxes]))
        i = j + max(1, len(q))
    return out


def display_to_user(b, box, rot):
    """display-space rect (origin bottom-left of rotated page) -> user-space rect."""
    x0, y0, x1, y1 = b
    bx0, by0, bx1, by1 = box
    def inv(x, y):
        if rot == 0:
            return x + bx0, y + by0
        if rot == 90:
            return bx1 - y, x + by0
        if rot == 180:
            return bx1 - x, by1 - y
        return y + bx0, by1 - x
    p, q = inv(x0, y0), inv(x1, y1)
    return (min(p[0], q[0]), min(p[1], q[1]), max(p[0], q[0]), max(p[1], q[1]))
