"""The layout engine: DOM + computed styles -> a tree of positioned boxes.

Implements the CSS2.1 box model (section 8), block formatting contexts with
correct margin collapsing (section 8.3.1), the block-level width/height
resolution algorithm (sections 10.3.3 / 10.6.3), a greedy inline
formatting context with text-align (section 9.4.2 / 16.2), and float
layout (section 9.5).

Scope note on margin collapsing: Folio implements unlimited-depth
sibling-to-sibling collapsing and self-collapsing empty boxes exactly, and
parent<->first/last-child collapse-through recursively (so it *does*
compose through arbitrarily many zero-border/padding wrapper levels, not
just one) -- see `_layout_block_children` below. What it does not attempt:
collapsing across a block that establishes a new block formatting context
(floats, absolutely-positioned boxes, and anything with `overflow` other
than `visible` all correctly wall off collapsing by never being considered
a first/last in-flow block child in the first place, since floats aren't
in `block_children` at all).
"""

from . import fontmetrics
from .values import Length, AUTO_LENGTH, ZERO

BLOCK_DISPLAYS = ("block", "list-item")


class LayoutBox:
    __slots__ = (
        "element", "style", "is_anonymous",
        "mode",  # 'block' | 'inline' | 'none' (empty)
        "block_children", "inline_items", "lines",
        "float_type", "position",
        "x", "border_box_top", "content_width",
        "content_box_top", "content_box_bottom",
        "margin_top", "margin_right", "margin_bottom", "margin_left",
        "border_top", "border_right", "border_bottom", "border_left",
        "padding_top", "padding_right", "padding_bottom", "padding_left",
    )

    def __init__(self, element, style, is_anonymous=False):
        self.element = element
        self.style = style
        self.is_anonymous = is_anonymous
        self.mode = "none"
        self.block_children = []
        self.inline_items = []
        self.lines = []
        self.float_type = "none"
        self.position = "static"
        self.x = 0.0
        self.border_box_top = 0.0
        self.content_width = 0.0
        self.content_box_top = 0.0
        self.content_box_bottom = 0.0
        self.margin_top = self.margin_right = self.margin_bottom = self.margin_left = 0.0
        self.border_top = self.border_right = self.border_bottom = self.border_left = 0.0
        self.padding_top = self.padding_right = self.padding_bottom = self.padding_left = 0.0

    @property
    def content_height(self):
        return max(0.0, self.content_box_bottom - self.content_box_top)

    @property
    def border_box_bottom(self):
        return self.content_box_bottom + self.padding_bottom + self.border_bottom

    @property
    def border_box_x(self):
        return self.x

    @property
    def border_box_width(self):
        return self.padding_left + self.border_left + self.content_width + self.border_right + self.padding_right

    @property
    def border_box_height(self):
        return self.border_box_bottom - self.border_box_top

    def rect(self):
        """(x, y, width, height) of the border box -- what a browser's
        getBoundingClientRect() reports."""
        return (self.border_box_x, self.border_box_top, self.border_box_width, self.border_box_height)

    def __repr__(self):
        tag = "anon" if self.is_anonymous else (self.element.tag if self.element else "?")
        return "Box<%s mode=%s>" % (tag, self.mode)


# ---------------------------------------------------------------------------
# Tree construction: DOM + computed styles -> LayoutBox tree, with anonymous
# block-box generation for mixed block/inline content (CSS2.1 9.2.1.1).
# ---------------------------------------------------------------------------

def build_layout_tree(element, styles):
    style = styles[element]
    if style["display"] == "none":
        return None
    return _build_block_box(element, style, styles)


def _build_block_box(element, style, styles):
    box = LayoutBox(element, style)
    box.float_type = style.get("float", "none")
    box.position = style.get("position", "static")

    kids = [c for c in element.children if not (c.is_element and styles.get(c, {}).get("display") == "none" if c.is_element else False)]
    has_block_child = any(
        c.is_element and styles[c]["display"] in BLOCK_DISPLAYS for c in kids
    )

    if has_block_child:
        box.mode = "block"
        run = []

        def flush_run():
            if run:
                items = []
                for node in run:
                    items.extend(_flatten_inline(node, styles, style))
                # A run of purely collapsible whitespace directly between
                # block-level siblings (typically the source formatting
                # indentation) generates no line box in a real browser --
                # skip it rather than emitting a phantom empty anonymous
                # block that would otherwise still claim one empty line's
                # worth of height.
                if _has_visible_inline_content(items):
                    anon = LayoutBox(None, style, is_anonymous=True)
                    anon.mode = "inline"
                    anon.inline_items = items
                    box.block_children.append(anon)
                run.clear()

        for child in element.children:
            if child.is_element:
                if styles[child]["display"] == "none":
                    continue
                if styles[child]["display"] in BLOCK_DISPLAYS:
                    flush_run()
                    child_box = _build_block_box(child, styles[child], styles)
                    if child_box.float_type in ("left", "right"):
                        box.block_children.append(child_box)  # floats still recorded; layout skips them in flow
                    else:
                        box.block_children.append(child_box)
                else:
                    run.append(child)
            elif child.is_text:
                run.append(child)
        flush_run()
    elif kids:
        items = []
        for child in element.children:
            if child.is_element and styles.get(child, {}).get("display") == "none":
                continue
            items.extend(_flatten_inline(child, styles, style))
        if _has_visible_inline_content(items):
            box.mode = "inline"
            box.inline_items = items
        else:
            box.mode = "none"
    else:
        box.mode = "none"

    return box


def _has_visible_inline_content(items):
    for kind, text, _style in items:
        if kind == "br":
            return True
        if text and text.strip(" \t\n\r\f"):
            return True
    return False


def _flatten_inline(node, styles, context_style):
    """Flatten a DOM node (Element or Text) that lives in inline content
    into a list of ('text', text, style) / ('br', None, style) tuples."""
    if node.is_text:
        return [("text", node.data, context_style)]
    if not node.is_element:
        return []
    style = styles.get(node, context_style)
    if style.get("display") == "none":
        return []
    if node.tag == "br":
        return [("br", None, style)]
    out = []
    for child in node.children:
        out.extend(_flatten_inline(child, styles, style))
    return out


def first_in_flow_block_child(box):
    for c in box.block_children:
        if c.float_type == "none" and c.position != "absolute":
            return c
    return None


def last_in_flow_block_child(box):
    for c in reversed(box.block_children):
        if c.float_type == "none" and c.position != "absolute":
            return c
    return None


def in_flow_block_children(box):
    return [c for c in box.block_children if c.float_type == "none" and c.position != "absolute"]


def float_children(box):
    return [c for c in box.block_children if c.float_type in ("left", "right")]


# ---------------------------------------------------------------------------
# Width resolution (CSS2.1 10.3.3)
# ---------------------------------------------------------------------------

def _len(box, prop, cb_width, auto_ok):
    if box.is_anonymous:
        if prop.startswith("margin") or prop.startswith("padding") or "border" in prop:
            return 0.0, False
        if prop == "width":
            return 0.0, True  # auto
        return 0.0, False
    style = box.style
    val = style[prop]
    if not isinstance(val, Length):
        return 0.0, False
    if val.is_auto and auto_ok:
        return 0.0, True
    return val.resolve(cb_width), False


def _border_width(box, side):
    if box.is_anonymous:
        return 0.0
    style = box.style
    if style.get("border-%s-style" % side, "none") == "none":
        return 0.0
    val = style["border-%s-width" % side]
    return val.resolve(0.0) if isinstance(val, Length) else 0.0


def resolve_box_width(box, cb_width):
    bl = _border_width(box, "left")
    br = _border_width(box, "right")
    pl, _ = _len(box, "padding-left", cb_width, False)
    pr, _ = _len(box, "padding-right", cb_width, False)
    w, w_auto = _len(box, "width", cb_width, True)
    ml, ml_auto = _len(box, "margin-left", cb_width, True)
    mr, mr_auto = _len(box, "margin-right", cb_width, True)

    if not w_auto and not ml_auto and not mr_auto:
        total = ml + bl + pl + w + pr + br + mr
        if total != cb_width:
            mr += cb_width - total
    elif w_auto:
        ml = 0.0 if ml_auto else ml
        mr = 0.0 if mr_auto else mr
        w = max(0.0, cb_width - (ml + bl + pl + pr + br + mr))
    elif ml_auto and mr_auto:
        remaining = max(0.0, cb_width - (bl + pl + w + pr + br))
        ml = mr = remaining / 2.0
    elif ml_auto:
        ml = cb_width - (bl + pl + w + pr + br + mr)
    elif mr_auto:
        mr = cb_width - (ml + bl + pl + w + pr + br)

    box.border_left, box.border_right = bl, br
    box.padding_left, box.padding_right = pl, pr
    box.margin_left, box.margin_right = ml, mr
    box.content_width = w


def _explicit_height(box):
    if box.is_anonymous:
        return None
    val = box.style["height"]
    if isinstance(val, Length) and not val.is_auto and val.kind == "px":
        return val.value
    return None


def _vertical_box_props(box, cb_width):
    box.margin_top, _ = _len(box, "margin-top", cb_width, True)
    box.margin_bottom, _ = _len(box, "margin-bottom", cb_width, True)
    box.border_top = _border_width(box, "top")
    box.border_bottom = _border_width(box, "bottom")
    box.padding_top, _ = _len(box, "padding-top", cb_width, False)
    box.padding_bottom, _ = _len(box, "padding-bottom", cb_width, False)


# ---------------------------------------------------------------------------
# Margin collapsing + vertical layout (CSS2.1 8.3.1)
# ---------------------------------------------------------------------------

def collapse(margins):
    pos = 0.0
    neg = 0.0
    seen = False
    for m in margins:
        seen = True
        if m >= 0:
            pos = max(pos, m)
        else:
            neg = min(neg, m)
    if not seen:
        return 0.0
    return pos + neg


def _is_self_collapsing(box):
    if box.mode != "none":
        return False
    return (
        box.border_top == 0 and box.padding_top == 0
        and box.border_bottom == 0 and box.padding_bottom == 0
        and _explicit_height(box) is None
    )


def layout_block_box(box, x, cb_width, viewport_width):
    """Lay out `box` as a block-level box in normal flow, given its
    containing block's content width. Does NOT set box.border_box_top /
    box.content_box_top -- the caller (a block-children walk) does that as
    part of margin collapsing. This function resolves width/margins and
    lays out `box`'s own content (children), producing box.content_width and
    (via `_finish_vertical`) box.content_box_bottom."""
    resolve_box_width(box, cb_width)
    _vertical_box_props(box, cb_width)
    box.x = x + box.margin_left


def layout_subtree(root_element, styles, viewport_width):
    """Full pipeline: build the layout tree for `root_element` and lay it
    out against a viewport of `viewport_width` px. Returns the root
    LayoutBox with all geometry resolved.

    The root is laid out by feeding it through the very same
    `_layout_block_children` sibling-collapsing walk used for every other
    block box, with an initial (y_cursor=0, group=[]) -- not a special
    case. That matters: it is what makes a body with no top border/padding
    correctly let its own top margin collapse *through* with its first
    child's margin-top (the classic "margin escapes the body" behavior),
    rather than always reserving real space for it."""
    root_box = build_layout_tree(root_element, styles)
    if root_box is None:
        root_box = LayoutBox(root_element, styles[root_element], is_anonymous=True)
        root_box.mode = "none"
    y_cursor, group, pending = _layout_block_children(
        [root_box], 0.0, [], [], viewport_width, 0.0, viewport_width, []
    )
    _flush_pending(pending, y_cursor)
    return root_box


def _flush_pending(pending, y):
    """Backfill the position of every still-unresolved self-collapsing box
    in `pending` to `y` -- the point where their (bled-through) margin group
    finally got consumed. Matches real browsers: a self-collapsing box
    reports its geometry at the *final* collapsed position, not wherever it
    happened to sit in source order (verified against Chromium -- see
    test_layout_block.py's `test_self_collapsing_empty_div_between_siblings`)."""
    for box in pending:
        box.border_box_top = box.content_box_top = box.content_box_bottom = y


def _establishes_new_bfc(box):
    # Folio's float-avoidance model only: floats themselves start a fresh BFC.
    return box.float_type in ("left", "right")


def _layout_block_children(children, y_cursor, group, pending, cb_width, content_x, viewport_width, floats):
    """Lay out `children` (in-flow block boxes, already known to belong to
    one block formatting context) top-to-bottom starting at `y_cursor` with
    `group` = pending (unflushed) adjoining margins and `pending` = the
    self-collapsing boxes already absorbed into `group` whose on-screen
    position is still undetermined (see `_flush_pending`). Returns
    (y_cursor_final, group_final, pending_final): `group_final`/
    `pending_final` are what's left unresolved, for the caller to either
    bleed further outward or finally consume (calling `_flush_pending`)."""
    for child in children:
        layout_block_box(child, content_x, cb_width, viewport_width)
        group = group + [child.margin_top]
        first_block = first_in_flow_block_child(child) if child.mode == "block" else None

        if _is_self_collapsing(child):
            # Transparent to the group: neither flushes a real gap nor walls
            # off collapsing on either side -- its own top+bottom margins
            # (and everything already pending) all merge into one group
            # that keeps bleeding until something non-self-collapsing (or
            # the end of this children list) finally consumes it. Its own
            # displayed position isn't known yet either -- defer it.
            group = group + [child.margin_bottom]
            pending = pending + [child]
            continue

        delegate_top = child.border_top == 0 and child.padding_top == 0 and first_block is not None

        if delegate_top:
            # child's own top margin (already pushed onto `group` above)
            # collapses straight through into its first child's subtree --
            # recurse in the SAME collapsing scope rather than starting a
            # fresh one, so child's border-box-top ends up exactly where
            # its (recursively-collapsed) first descendant's does.
            y_cursor, group, pending = _layout_block_children(
                child.block_children, y_cursor, group, pending, child.content_width,
                child.x + child.border_left + child.padding_left, viewport_width, floats,
            )
            child.border_box_top = first_block.border_box_top
            child.content_box_top = child.border_box_top
        else:
            gap = collapse(group)
            child.border_box_top = y_cursor + gap
            _flush_pending(pending, child.border_box_top)
            pending = []
            y_cursor = child.border_box_top
            group = []
            child.content_box_top = child.border_box_top + child.border_top + child.padding_top

            if child.mode == "block" and in_flow_block_children(child):
                y_cursor, group, pending = _layout_block_children(
                    in_flow_block_children(child), child.content_box_top, [], [], child.content_width,
                    child.x + child.border_left + child.padding_left, viewport_width, floats,
                )
            elif child.mode == "inline":
                cx = child.x + child.border_left + child.padding_left
                bottom = layout_inline_content(child, cx, child.content_box_top, child.content_width)
                child.content_box_bottom = bottom
                y_cursor = child.content_box_bottom
                group = []
            else:
                child.content_box_bottom = child.content_box_top
                y_cursor = child.content_box_bottom
                group = []

        # --- resolve child's own bottom edge from (y_cursor, group) ---
        explicit_h = _explicit_height(child)
        can_bleed = (
            explicit_h is None and child.border_bottom == 0 and child.padding_bottom == 0
            and child.mode != "inline"
        )
        if explicit_h is not None:
            child.content_box_bottom = child.content_box_top + explicit_h
            _flush_pending(pending, child.border_box_bottom)
            pending = []
            y_cursor = child.border_box_bottom
            group = [child.margin_bottom]
        elif can_bleed:
            child.content_box_bottom = y_cursor
            group = group + [child.margin_bottom]
        else:
            extra = collapse(group)
            child.content_box_bottom = y_cursor + extra
            _flush_pending(pending, child.border_box_bottom)
            pending = []
            y_cursor = child.border_box_bottom
            group = [child.margin_bottom]

    return y_cursor, group, pending


# ---------------------------------------------------------------------------
# Inline layout (line-box construction, CSS2.1 9.4.2 / 16.2)
# ---------------------------------------------------------------------------

class LineBox:
    __slots__ = ("y", "height", "fragments", "width_used")

    def __init__(self, y, height):
        self.y = y
        self.height = height
        self.fragments = []  # list of (x, text, style, width)
        self.width_used = 0.0


def _tokenize_words(text):
    """CSS white-space:normal collapsing: runs of whitespace collapse to a
    single space; split into words + explicit space markers."""
    words = []
    buf = []
    for ch in text:
        if ch in " \t\n\r\f":
            if buf:
                words.append("".join(buf))
                buf = []
        else:
            buf.append(ch)
    if buf:
        words.append("".join(buf))
    leading_ws = bool(text) and text[0] in " \t\n\r\f"
    trailing_ws = bool(text) and text[-1] in " \t\n\r\f"
    return words, leading_ws, trailing_ws


def layout_inline_content(box, content_x, content_top, content_width):
    """Greedy line-breaking over box.inline_items. Returns the y-coordinate
    of the bottom of the last line (== content bottom)."""
    style = box.style
    font_size = style.get("font-size", 16.0)
    bold = style.get("font-weight", "normal") == "bold"
    line_h = fontmetrics.resolve_line_height(style.get("line-height", "normal"), font_size)
    align = style.get("text-align", "left")
    white_space = style.get("white-space", "normal")

    # Build a flat word list: (word_text, style, starts_new_line_after)
    words = []
    pending_space_before_next = False
    for kind, text, item_style in box.inline_items:
        if kind == "br":
            words.append(("__BR__", item_style, False))
            continue
        if white_space == "pre":
            for line_text in text.split("\n"):
                if words and pending_space_before_next:
                    pass
                words.append((("__RAW__", line_text), item_style, False))
                words.append(("__BR__", item_style, False))
            words.pop()  # no trailing forced break after the final pre-formatted chunk
            continue
        ws, lead, trail = _tokenize_words(text)
        if not ws:
            if lead or trail:
                pending_space_before_next = True
            continue
        for i, w in enumerate(ws):
            need_space = pending_space_before_next if i == 0 else True
            words.append((w, item_style, need_space))
            pending_space_before_next = False
        if trail:
            pending_space_before_next = True

    lines = []
    cur = LineBox(content_top, line_h)
    cur_x = 0.0
    cur_font_size_max = font_size
    any_word_on_line = False

    def push_line():
        nonlocal cur, cur_x, any_word_on_line, cur_font_size_max
        lines.append(cur)
        cur = LineBox(cur.y + cur.height, line_h)
        cur_x = 0.0
        any_word_on_line = False
        cur_font_size_max = font_size

    for entry in words:
        w, item_style, need_space = entry
        if w == "__BR__":
            push_line()
            continue
        item_font_size = item_style.get("font-size", font_size)
        item_bold = item_style.get("font-weight", "normal") == "bold"
        if isinstance(w, tuple) and w[0] == "__RAW__":
            text = w[1]
            width = fontmetrics.measure_text(text, item_font_size, bold=item_bold)
            cur.fragments.append([cur_x, text, item_style, width])
            cur_x += width
            any_word_on_line = True
            continue

        space_w = fontmetrics.char_width(item_font_size, bold=item_bold) if need_space else 0.0
        word_w = fontmetrics.measure_text(w, item_font_size, bold=item_bold)
        projected = cur_x + space_w + word_w
        if any_word_on_line and projected > content_width + 1e-6:
            push_line()
            need_space = False
            space_w = 0.0
            projected = word_w

        x_start = cur_x + space_w
        cur.fragments.append([x_start, w, item_style, word_w])
        cur_x = x_start + word_w
        any_word_on_line = True

    if cur.fragments or not lines:
        lines.append(cur)

    box.lines = lines
    for i, line in enumerate(lines):
        line.width_used = max((f[0] + f[3] for f in line.fragments), default=0.0)
        _apply_text_align(line, content_width, align, is_last=(i == len(lines) - 1))
        for f in line.fragments:
            f[0] += content_x

    if not lines:
        return content_top
    return lines[-1].y + lines[-1].height


def _apply_text_align(line, content_width, align, is_last):
    if not line.fragments:
        return
    extra = content_width - line.width_used
    if extra <= 0:
        return
    if align == "right":
        for f in line.fragments:
            f[0] += extra
    elif align == "center":
        for f in line.fragments:
            f[0] += extra / 2.0
    elif align == "justify" and not is_last and len(line.fragments) > 1:
        gaps = len(line.fragments) - 1
        add_per_gap = extra / gaps
        shift = 0.0
        for i, f in enumerate(line.fragments):
            f[0] += shift
            shift += add_per_gap
