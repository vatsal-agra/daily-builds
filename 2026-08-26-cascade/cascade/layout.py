"""The box-model layout engine: block formatting context (vertical stacking
+ margin collapsing), inline formatting context (whitespace collapsing +
greedy line breaking + text-align), and float placement.

Coordinates are absolute (document/page space), not parent-relative — this
is what lets floats registered by one box narrow the line boxes of an
unrelated descendant several levels down without any coordinate
translation, and it's directly comparable to a real browser's
`getBoundingClientRect()`, which is exactly what the Chromium oracle
(oracle/diff.cjs) diffs against.

Deliberate, documented scope cuts (see PLAN.md / REVIEW.md):
  - Only sibling-sibling margin collapsing is implemented, not
    parent/first-child collapsing through a border/padding-less parent.
  - `float` is supported for direct block-level children only, not floats
    embedded mid-paragraph inside inline content.
  - `inline-block`/floats with `width: auto` fall back to filling the
    remaining containing-block width rather than true shrink-to-fit.
"""

import re
from .dom import Element, Text, Comment
from .cascade import INHERITED_PROPS
from .fonts import text_width, char_advance, is_monospace, SPACE_ADVANCE

BLOCK_LEVEL_DISPLAYS = {"block", "list-item"}
SIDES = ("top", "right", "bottom", "left")


# --------------------------------------------------------------- geometry

class Rect:
    __slots__ = ("x", "y", "width", "height")

    def __init__(self, x, y, width, height):
        self.x, self.y, self.width, self.height = x, y, width, height

    def __repr__(self):
        return f"Rect({self.x:.1f},{self.y:.1f},{self.width:.1f},{self.height:.1f})"


class Edges:
    __slots__ = ("top", "right", "bottom", "left")

    def __init__(self, top=0.0, right=0.0, bottom=0.0, left=0.0):
        self.top, self.right, self.bottom, self.left = top, right, bottom, left


class Dimensions:
    __slots__ = ("content", "padding", "border", "margin")

    def __init__(self):
        self.content = Rect(0, 0, 0, 0)
        self.padding = Edges()
        self.border = Edges()
        self.margin = Edges()

    def padding_box(self):
        c, p = self.content, self.padding
        return Rect(c.x - p.left, c.y - p.top, c.width + p.left + p.right, c.height + p.top + p.bottom)

    def border_box(self):
        pb, b = self.padding_box(), self.border
        return Rect(pb.x - b.left, pb.y - b.top, pb.width + b.left + b.right, pb.height + b.top + b.bottom)

    def margin_box(self):
        bb, m = self.border_box(), self.margin
        return Rect(bb.x - m.left, bb.y - m.top, bb.width + m.left + m.right, bb.height + m.top + m.bottom)


class LayoutBox:
    def __init__(self, node, style, box_type):
        self.node = node          # Element, or None for an anonymous box
        self.style = style        # ComputedStyle (own, or nearest ancestor's for anon boxes)
        self.box_type = box_type  # 'block' | 'inline-block' | 'anon-inline'
        self.dims = Dimensions()
        self.children = []
        self.lines = []           # list[LineBox], only for box_type == 'anon-inline'
        self.is_float = False
        self.float_side = None

    def __repr__(self):
        tag = self.node.tag if isinstance(self.node, Element) else "anon"
        c = self.dims.content
        return f"<{tag} {self.box_type} {c.x:.0f},{c.y:.0f} {c.width:.0f}x{c.height:.0f}>"

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()


class LineBox:
    __slots__ = ("top", "height", "words", "baseline")

    def __init__(self, top, height, baseline):
        self.top = top
        self.height = height
        self.baseline = baseline
        self.words = []  # list of PlacedWord


class PlacedWord:
    __slots__ = ("x", "width", "text", "style", "owners", "underline", "box")

    def __init__(self, x, width, text, style, owners, underline, box=None):
        self.x = x
        self.width = width
        self.text = text          # word text, or None when `box` is set
        self.style = style
        self.owners = owners      # tuple of Elements (outermost..innermost) owning this word
        self.underline = underline
        self.box = box            # set for an inline-block: a pre-laid-out LayoutBox instead of text


# ----------------------------------------------------------- value helpers

_LEN_RE = re.compile(r"^(-?[\d.]+)(px|%)?$")


def px(value, base):
    """Parse a length/percentage string against `base` px. Returns a float,
    or None for 'auto' / an unresolvable percentage (base is None)."""
    if value is None:
        return None
    v = value.strip()
    if v in ("auto", ""):
        return None
    m = _LEN_RE.match(v)
    if not m:
        return None
    num = float(m.group(1))
    unit = m.group(2)
    if unit == "%":
        if base is None:
            return None
        return num / 100.0 * base
    return num


def px0(value, base):
    r = px(value, base)
    return 0.0 if r is None else r


def border_width(style, side):
    if style.get(f"border-{side}-style") == "none":
        return 0.0
    return px0(style.get(f"border-{side}-width"), 0)


def resolve_line_height(style):
    lh = style.get("line-height").strip()
    fs = px0(style.get("font-size"), 16)
    if lh == "normal" or lh == "":
        return fs * 1.2
    try:
        return float(lh) * fs
    except ValueError:
        pass
    v = px(lh, fs)
    return v if v is not None else fs * 1.2


def adjoin_margins(a, b):
    """The real CSS adjoining-margins formula: max of the positives plus
    min of the negatives (handles mixed-sign margins correctly)."""
    pos = max(a, 0, b, 0) if (a >= 0 or b >= 0) else 0
    positives = [x for x in (a, b) if x >= 0]
    negatives = [x for x in (a, b) if x < 0]
    return (max(positives) if positives else 0) + (min(negatives) if negatives else 0)


# -------------------------------------------------------------- float ctx

class FloatContext:
    """Tracks placed floats in absolute document coordinates, shared across
    the whole document (a simplified single global block-formatting
    context — see module docstring)."""

    def __init__(self):
        self.lefts = []   # [top, bottom, right_edge_x]
        self.rights = []  # [top, bottom, left_edge_x]

    def add(self, side, top, bottom, edge_x):
        (self.lefts if side == "left" else self.rights).append([top, bottom, edge_x])

    def line_bounds(self, y, y2, left, right):
        l, r = left, right
        for top, bottom, edge in self.lefts:
            if top < y2 and bottom > y:
                l = max(l, edge)
        for top, bottom, edge in self.rights:
            if top < y2 and bottom > y:
                r = min(r, edge)
        return l, r

    def next_relevant_bottom(self, y, left, right):
        """The nearest bottom edge (> y) of a float currently narrowing
        [left, right] — used to skip a line down when nothing fits."""
        bottoms = []
        for top, bottom, edge in self.lefts + self.rights:
            if bottom > y and top <= y:
                bottoms.append(bottom)
        return min(bottoms) if bottoms else None

    def clear_y(self, clear, y):
        candidates = [y]
        if clear in ("left", "both"):
            candidates += [b for _, b, _ in self.lefts]
        if clear in ("right", "both"):
            candidates += [b for _, b, _ in self.rights]
        return max(candidates)


# -------------------------------------------------------------- classify

def classify(child, styles):
    if isinstance(child, Comment):
        return "skip"
    if isinstance(child, Text):
        return "inline"
    if isinstance(child, Element):
        st = styles.get(child)
        if st is None:
            return "skip"
        if st.get("display") == "none":
            return "skip"
        if st.get("float") in ("left", "right"):
            return "block"  # floats are always block-level, own box
        if st.get("display") in BLOCK_LEVEL_DISPLAYS:
            return "block"
        return "inline"
    return "skip"


def group_runs(el, styles):
    """Partition el's children into ('block', Element) items and
    ('inline', [nodes]) runs of consecutive inline-level content."""
    runs = []
    cur_inline = []
    for child in el.children:
        kind = classify(child, styles)
        if kind == "skip":
            continue
        if kind == "block":
            if cur_inline:
                runs.append(("inline", cur_inline))
                cur_inline = []
            runs.append(("block", child))
        else:
            cur_inline.append(child)
    if cur_inline:
        runs.append(("inline", cur_inline))
    return runs


# -------------------------------------------------------------- block box

def layout_block(el, style, containing, bfc, styles, border_box_top_y):
    """containing: Rect with .x/.width defining the containing block (its
    .y/.height are unused here). border_box_top_y: absolute y where this
    box's border-box begins (the caller has already resolved margin
    collapsing). Returns the fully laid-out LayoutBox."""
    box = LayoutBox(el, style, "block")
    cw = containing.width
    is_float = style.get("float") in ("left", "right")
    is_inline_block = style.get("display") == "inline-block"

    box_sizing = style.get("box-sizing")
    ml_raw = style.get("margin-left")
    mr_raw = style.get("margin-right")
    ml = px(ml_raw, cw)
    mr = px(mr_raw, cw)
    mt = px0(style.get("margin-top"), cw)
    mb = px0(style.get("margin-bottom"), cw)
    pl = px0(style.get("padding-left"), cw)
    pr = px0(style.get("padding-right"), cw)
    pt = px0(style.get("padding-top"), cw)
    pb = px0(style.get("padding-bottom"), cw)
    bl = border_width(style, "left")
    br_ = border_width(style, "right")
    bt = border_width(style, "top")
    bb = border_width(style, "bottom")

    w = px(style.get("width"), cw)
    if w is None:
        ml_r = ml if ml is not None else 0.0
        mr_r = mr if mr is not None else 0.0
        avail = max(0.0, cw - ml_r - mr_r - bl - br_ - pl - pr)
        if is_float or is_inline_block:
            # Shrink-to-fit: measure the box's own inline content at
            # unconstrained width and use that (capped by what's actually
            # available), rather than stretching to fill the remaining
            # containing-block width like a normal block does. Only
            # approximates text content (see docstring); a float/
            # inline-block with block-level children and no explicit
            # width still falls back to filling `avail`.
            natural = _measure_natural_inline_width(el, styles)
            content_width = min(natural, avail) if natural > 0 else avail
        else:
            content_width = avail
        if ml is None:
            ml = 0.0
        if mr is None:
            mr = 0.0
    else:
        content_width = max(0.0, w - pl - pr - bl - br_) if box_sizing == "border-box" else w
        if ml is None and mr is None:
            leftover = max(0.0, cw - (content_width + pl + pr + bl + br_))
            ml = mr = leftover / 2.0
        elif ml is None:
            mr = mr if mr is not None else 0.0
            ml = max(0.0, cw - (content_width + pl + pr + bl + br_) - mr)
        elif mr is None:
            mr = max(0.0, cw - (content_width + pl + pr + bl + br_) - ml)

    content_x = containing.x + ml + bl + pl
    content_y = border_box_top_y + bt + pt
    box.dims.content.x = content_x
    box.dims.content.y = content_y
    box.dims.content.width = content_width

    child_bounds = Rect(content_x, content_y, content_width, None)
    content_height = _layout_children(box, el, styles, child_bounds, bfc)

    h = px(style.get("height"), None)
    if h is not None and box_sizing == "border-box":
        h = max(0.0, h - pt - pb - bt - bb)
    box.dims.content.height = h if h is not None else content_height

    box.dims.margin = Edges(mt, mr, mb, ml)
    box.dims.border = Edges(bt, br_, bb, bl)
    box.dims.padding = Edges(pt, pr, pb, pl)
    box.is_float = is_float
    box.float_side = style.get("float") if is_float else None
    return box


def _layout_children(parent_box, el, styles, cb, bfc):
    """cb: Rect(x, y, width, height=None) content box of `el` in absolute
    coords. Lays out el's children into parent_box.children and returns the
    total used content height."""
    runs = group_runs(el, styles)
    cursor_y = cb.y
    prev_margin_bottom = 0.0
    have_prev = False
    max_y = cursor_y

    for kind, payload in runs:
        if kind == "block":
            child_el = payload
            cstyle = styles[child_el]
            if cstyle.get("float") in ("left", "right"):
                # Floats don't participate in normal-flow margin collapsing,
                # and — matching real (no-clearfix) CSS — an auto-height
                # container does NOT grow to contain a floated child's
                # extent; only `clear` on a later box reaches down for it.
                child_box = layout_block(child_el, cstyle, Rect(cb.x, cursor_y, cb.width, None),
                                          bfc, styles, cursor_y)
                _place_float(bfc, child_box, cstyle.get("float"), cb, cursor_y)
                parent_box.children.append(child_box)
                continue

            child_margin_top = px0(cstyle.get("margin-top"), cb.width)
            collapsed = adjoin_margins(prev_margin_bottom, child_margin_top) if have_prev else child_margin_top
            child_top = cursor_y + collapsed
            clear = cstyle.get("clear")
            if clear in ("left", "right", "both"):
                child_top = bfc.clear_y(clear, child_top)

            child_box = layout_block(child_el, cstyle, Rect(cb.x, child_top, cb.width, None),
                                      bfc, styles, child_top)
            parent_box.children.append(child_box)
            mbox = child_box.dims.margin_box()
            cursor_y = mbox.y + mbox.height - child_box.dims.margin.bottom
            prev_margin_bottom = child_box.dims.margin.bottom
            have_prev = True
            max_y = max(max_y, mbox.y + mbox.height)
        else:  # inline run -> anonymous block establishing an IFC
            nodes = payload
            cursor_y += prev_margin_bottom
            have_prev = True
            prev_margin_bottom = 0.0
            anon = LayoutBox(None, parent_box.style, "anon-inline")
            used_h = layout_inline_run(nodes, parent_box.style, styles,
                                        Rect(cb.x, cursor_y, cb.width, None), bfc, anon)
            anon.dims.content = Rect(cb.x, cursor_y, cb.width, used_h)
            parent_box.children.append(anon)
            cursor_y += used_h
            max_y = max(max_y, cursor_y)

    return max(0.0, max_y - cb.y)


def _place_float(bfc, box, side, cb, min_y):
    mbox = box.dims.margin_box()
    w = mbox.width
    y = min_y
    for _ in range(len(bfc.lefts) + len(bfc.rights) + 2):
        left, right = bfc.line_bounds(y, y + max(mbox.height, 1), cb.x, cb.x + cb.width)
        if right - left >= w or (left == cb.x and right == cb.x + cb.width):
            break
        nxt = bfc.next_relevant_bottom(y, cb.x, cb.x + cb.width)
        if nxt is None or nxt <= y:
            break
        y = nxt
    left, right = bfc.line_bounds(y, y + max(mbox.height, 1), cb.x, cb.x + cb.width)
    edge_x = left if side == "left" else right - w
    edge_x = max(edge_x, cb.x)
    dx = edge_x - mbox.x
    dy = y - mbox.y
    _translate_box(box, dx, dy)
    nb = box.dims.margin_box()
    bfc.add(side, nb.y, nb.y + nb.height, nb.x + nb.width if side == "left" else nb.x)


def _translate_box(box, dx, dy):
    for b in box.walk():
        b.dims.content.x += dx
        b.dims.content.y += dy
        for line in b.lines:
            line.top += dy
            for w in line.words:
                w.x += dx


# ------------------------------------------------------------ inline/text

_WS_RUN_RE = re.compile(r"\S+|\s+")


def _tokenize_inline(nodes, container_style, styles):
    """Flattens a run of sibling nodes (text + inline elements) into a flat
    token stream, collapsing whitespace per CSS's normal `white-space`
    rules (runs of whitespace -> single space, leading whitespace at the
    very start of the run dropped)."""
    tokens = []
    state = {"last_was_space": True}

    def walk(node, owners):
        for child in node.children:
            if isinstance(child, Comment):
                continue
            if isinstance(child, Text):
                for m in _WS_RUN_RE.finditer(child.data):
                    seg = m.group()
                    if seg.isspace():
                        if not state["last_was_space"]:
                            tokens.append(("space", None, owners))
                            state["last_was_space"] = True
                    else:
                        tokens.append(("word", seg, owners))
                        state["last_was_space"] = False
            elif isinstance(child, Element):
                st = styles.get(child)
                if st is None or st.get("display") == "none":
                    continue
                if child.tag == "br":
                    tokens.append(("break", None, owners))
                    state["last_was_space"] = True
                    continue
                if st.get("display") == "inline-block":
                    # Atomic inline-level box: don't recurse into its text,
                    # it lays out as its own independent block formatting
                    # context (handled in layout_inline_run).
                    tokens.append(("box", child, owners))
                    state["last_was_space"] = False
                    continue
                walk(child, owners + (child,))

    class _Wrapper:
        """A stand-in with just enough shape (`.children`) for `walk()` to
        treat the top-level run of sibling nodes uniformly, whether they're
        loose Text nodes or inline Elements."""
        children = nodes

    walk(_Wrapper, ())
    while tokens and tokens[-1][0] == "space":
        tokens.pop()
    return tokens


def _measure_natural_inline_width(el, styles):
    """Shrink-to-fit approximation for a float/inline-block with `width:
    auto`: the width its own inline content would take laid out on one
    unwrapped line (the CSS 'max-content' width), so short content (a
    badge, a button label) sizes to itself instead of stretching to fill
    its container. An explicit `<br>` still starts a fresh natural line."""
    style = styles[el]
    tokens = _tokenize_inline(el.children, style, styles)
    widest = 0.0
    cur = 0.0
    for kind, payload, owners in tokens:
        owner_style = styles.get(owners[-1]) if owners else style
        if kind == "break":
            widest = max(widest, cur)
            cur = 0.0
        elif kind == "space":
            cur += SPACE_ADVANCE * px0(owner_style.get("font-size"), 16)
        elif kind == "word":
            mono = is_monospace(owner_style.get("font-family"))
            cur += text_width(payload, px0(owner_style.get("font-size"), 16), mono)
        elif kind == "box":
            nested_w = px(styles[payload].get("width"), None)
            cur += nested_w if nested_w is not None else 0.0
    widest = max(widest, cur)
    return widest


def layout_inline_run(nodes, container_style, styles, cb, bfc, out_box):
    """Greedy line-breaking of an inline-level token stream into LineBoxes
    on out_box.lines. cb: Rect(x, y, width, height=None). Returns the total
    height consumed."""
    tokens = _tokenize_inline(nodes, container_style, styles)
    text_align = container_style.get("text-align")
    y = cb.y
    i = 0
    n = len(tokens)
    lines = []

    def word_metrics(text, style):
        mono = is_monospace(style.get("font-family"))
        fs = px0(style.get("font-size"), 16)
        return text_width(text, fs, mono)

    def style_for(owners):
        return styles.get(owners[-1]) if owners else container_style

    while i < n:
        left, right = bfc.line_bounds(y, y + 1, cb.x, cb.x + cb.width)
        max_line_height = 0.0
        placed = []
        x = left
        line_start_i = i
        first_on_line = True
        def place_box(el, owners, at_x):
            st = styles[el]
            ibox = layout_block(el, st, Rect(cb.x, y, cb.width, None), bfc, styles, y)
            mbox = ibox.dims.margin_box()
            _translate_box(ibox, at_x - mbox.x, 0)
            out_box.children.append(ibox)
            return PlacedWord(at_x, mbox.width, None, st, owners, False, box=ibox), mbox.height

        while i < n:
            kind, payload, owners = tokens[i]
            if kind == "break":
                i += 1
                break
            if kind == "space":
                if first_on_line:
                    i += 1
                    continue
                style = style_for(owners) if owners else container_style
                space_w = SPACE_ADVANCE * px0(style.get("font-size"), 16)
                if x + space_w > right and placed:
                    break
                x += space_w
                i += 1
                continue
            if kind == "box":
                pw, box_h = place_box(payload, owners, x)
                if not first_on_line and x + pw.width > right:
                    break
                placed.append(pw)
                max_line_height = max(max_line_height, box_h)
                x += pw.width
                first_on_line = False
                i += 1
                continue
            # word
            text = payload
            style = style_for(owners) if owners else container_style
            w = word_metrics(text, style)
            if not first_on_line and x + w > right:
                break
            underline = style.get("text-decoration") == "underline"
            placed.append(PlacedWord(x, w, text, style, owners, underline))
            max_line_height = max(max_line_height, resolve_line_height(style))
            x += w
            first_on_line = False
            i += 1
        if not placed and i < n and line_start_i == i:
            # A single item wider than the line and nothing else fit yet:
            # force-place it to guarantee forward progress.
            kind, payload, owners = tokens[i]
            if kind == "word":
                style = style_for(owners) if owners else container_style
                w = word_metrics(payload, style)
                underline = style.get("text-decoration") == "underline"
                placed.append(PlacedWord(left, w, payload, style, owners, underline))
                max_line_height = max(max_line_height, resolve_line_height(style))
                i += 1
            elif kind == "box":
                pw, box_h = place_box(payload, owners, left)
                placed.append(pw)
                max_line_height = max(max_line_height, box_h)
                i += 1
            else:
                i += 1
                continue
        if not placed:
            if max_line_height == 0:
                max_line_height = resolve_line_height(container_style)
            y += max_line_height
            continue
        line_width = (placed[-1].x + placed[-1].width) - left
        avail = right - left
        _apply_align(placed, text_align, left, avail, line_width, i >= n or tokens[i - 1][0] == "break")
        lb = LineBox(y, max_line_height, max_line_height * 0.8)
        lb.words = placed
        lines.append(lb)
        y += max_line_height

    out_box.lines = lines
    return y - cb.y


def _shift_word(w, dx):
    w.x += dx
    if w.box is not None:
        _translate_box(w.box, dx, 0)


def _apply_align(words, align, left, avail, used, is_last_line):
    if not words:
        return
    if align == "right":
        shift = avail - used
        if shift > 0:
            for w in words:
                _shift_word(w, shift)
    elif align == "center":
        shift = (avail - used) / 2.0
        if shift > 0:
            for w in words:
                _shift_word(w, shift)
    elif align == "justify" and not is_last_line and len(words) > 1:
        extra = max(0.0, avail - used)
        gap = extra / (len(words) - 1)
        offset = 0.0
        for idx, w in enumerate(words):
            _shift_word(w, offset)
            offset += gap
    # left / default: no adjustment needed


# --------------------------------------------------------------- entry

def layout_document(dom, styles, viewport_width):
    body = dom.find("body")
    root_el = body if body is not None else dom.find("html")
    if root_el is None:
        elements = list(dom.walk_elements())
        root_el = elements[0] if elements else None
    if root_el is None or root_el not in styles:
        return None, FloatContext()
    style = styles[root_el]
    bfc = FloatContext()
    containing = Rect(0, 0, viewport_width, None)
    box = layout_block(root_el, style, containing, bfc, styles, 0)
    return box, bfc
