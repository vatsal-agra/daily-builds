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
collapsing across a block that establishes a new block formatting context:
floats correctly wall off collapsing by never being considered a
first/last *in-flow* block child (`first_in_flow_block_child` etc. filter
by `float_type`), even though they're still ordinary members of
`block_children` -- source order matters for float placement, so they stay
in that one shared list rather than being split out.
"""

from . import fontmetrics
from .values import Length, AUTO_LENGTH, ZERO

BLOCK_DISPLAYS = ("block", "list-item")


class LayoutBox:
    __slots__ = (
        "element", "style", "is_anonymous",
        "mode",  # 'block' | 'inline' | 'none' (empty)
        "block_children", "inline_items", "lines",
        "float_type", "position", "clear",
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
        self.clear = "none"
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


def _effective_display(style):
    """CSS2.1 9.7: a floated (or absolutely-positioned) element's `display`
    is "blockified" -- an inline element with `float: left` lays out as a
    block box, not inline content. Without this, `<img style="float:left">`
    (img defaults to inline) would be flattened into the surrounding text
    run instead of becoming a real floated box."""
    display = style.get("display", "inline")
    if display == "none":
        return display
    if style.get("float", "none") in ("left", "right") and display not in BLOCK_DISPLAYS:
        return "block"
    return display


def _build_block_box(element, style, styles):
    box = LayoutBox(element, style)
    box.float_type = style.get("float", "none")
    box.position = style.get("position", "static")
    box.clear = style.get("clear", "none")

    def _is_displayed(node):
        return not (node.is_element and _effective_display(styles[node]) == "none")

    kids = [c for c in element.children if _is_displayed(c)]
    has_block_child = any(
        c.is_element and _effective_display(styles[c]) in BLOCK_DISPLAYS for c in kids
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
                cdisplay = _effective_display(styles[child])
                if cdisplay == "none":
                    continue
                if cdisplay in BLOCK_DISPLAYS:
                    flush_run()
                    child_box = _build_block_box(child, styles[child], styles)
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
    # Note: `position: absolute/fixed` is parsed (ComputedStyle exposes it)
    # but Folio does not implement out-of-flow positioned layout -- such an
    # element is deliberately kept "in flow" here rather than silently
    # dropped from the tree, which would be worse than not implementing the
    # feature at all (a vanishing element vs. a mispositioned one).
    for c in box.block_children:
        if c.float_type == "none":
            return c
    return None


def last_in_flow_block_child(box):
    for c in reversed(box.block_children):
        if c.float_type == "none":
            return c
    return None


def in_flow_block_children(box):
    return [c for c in box.block_children if c.float_type == "none"]


# ---------------------------------------------------------------------------
# Floats (CSS2.1 9.5) -- STRETCH feature.
#
# Scope: one FloatContext per distinct content-width scope -- a fresh one
# is created every time `_layout_block_children` starts laying out a box's
# own children, including across top-margin collapse-through delegation
# (a zero-border/padding wrapper can still have its own explicit width
# different from its parent's, so its floats must be scoped to *its*
# content box, not reused from the outer one -- an earlier draft shared
# the outer float_ctx across delegation and got exactly this wrong: a
# `width:400px` wrapper's float ended up placed against an 800px outer
# width. See REVIEW.md). Floats affect direct sibling content within that
# same container -- in-flow text wraps around them and `clear` respects
# them -- but Folio does not propagate float avoidance into a *nested*
# descendant container (e.g. a wrapper `<div>` around a paragraph two
# levels below an ancestor's float). Real browsers do propagate arbitrarily
# deep; the single-container scope here still covers the overwhelmingly
# common real-world float pattern (an image or pull-quote floated beside
# the paragraph(s) that follow it in the same container) and is disclosed
# explicitly rather than silently approximated -- see REVIEW.md.
# ---------------------------------------------------------------------------

class FloatContext:
    def __init__(self, content_x, content_width):
        self.content_x = content_x
        self.content_width = content_width
        self.left_floats = []  # list of [x1, x2, y1, y2] in absolute page coords
        self.right_floats = []

    def place(self, side, width, height, y_min):
        """Place a new float of `side` ('left'|'right'), sized width x
        height, no higher than `y_min`. Returns its absolute (x, y)."""
        same = self.left_floats if side == "left" else self.right_floats
        other = self.right_floats if side == "left" else self.left_floats
        y = y_min
        for _ in range(10000):  # bounded: each iteration consumes a real float
            active_same = [f for f in same if f[2] < y + max(height, 1e-6) and f[3] > y]
            active_other = [f for f in other if f[2] < y + max(height, 1e-6) and f[3] > y]
            left_taken = max([f[1] for f in active_same], default=self.content_x)
            right_taken = min([f[0] for f in active_other], default=self.content_x + self.content_width)
            available = right_taken - left_taken
            if available >= width - 1e-6 or (not active_same and not active_other):
                x = left_taken if side == "left" else right_taken - width
                same.append([x, x + width, y, y + height])
                return x, y
            blockers = active_same + active_other
            y = min(f[3] for f in blockers)
        return left_taken, y  # pragma: no cover -- defensive only

    def clear_y(self, clear_value, y_min):
        ys = [y_min]
        if clear_value in ("left", "both"):
            ys += [f[3] for f in self.left_floats]
        if clear_value in ("right", "both"):
            ys += [f[3] for f in self.right_floats]
        return max(ys)

    def available_range(self, y, height):
        """The [x_start, x_end) still free at vertical band [y, y+height)."""
        active_left = [f for f in self.left_floats if f[2] < y + max(height, 1e-6) and f[3] > y]
        active_right = [f for f in self.right_floats if f[2] < y + max(height, 1e-6) and f[3] > y]
        left_taken = max([f[1] for f in active_left], default=self.content_x)
        right_taken = min([f[0] for f in active_right], default=self.content_x + self.content_width)
        return left_taken, max(left_taken, right_taken)

    def has_any(self):
        return bool(self.left_floats or self.right_floats)


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


def resolve_float_width(box, cb_width):
    """Floats follow a *different* width algorithm than normal in-flow
    blocks (CSS2.1 10.3.5, not 10.3.3): critically, they never get the
    "adjust margin-right to make an over-specified box exactly fill the
    containing block" treatment `resolve_box_width` applies -- reusing that
    function for a float with an explicit width and default (0, not auto)
    margins was a real bug caught in testing: a `width:150px` float ended
    up with a 450px margin-right silently added to make 150+450=600 (the
    container width), turning a 150px-wide float into one whose *margin
    box* spanned the entire container and blocked all text from wrapping
    beside it at all. Auto margins on a float always compute to 0 (never
    centering); width:auto uses a shrink-to-fit approximation."""
    bl = _border_width(box, "left")
    br = _border_width(box, "right")
    pl, _ = _len(box, "padding-left", cb_width, False)
    pr, _ = _len(box, "padding-right", cb_width, False)
    w, w_auto = _len(box, "width", cb_width, True)
    ml, ml_auto = _len(box, "margin-left", cb_width, True)
    mr, mr_auto = _len(box, "margin-right", cb_width, True)
    if ml_auto:
        ml = 0.0
    if mr_auto:
        mr = 0.0
    if w_auto:
        insets = bl + pl + pr + br + ml + mr
        w = max(0.0, min(_shrink_to_fit_width(box), max(0.0, cb_width - insets)))
    box.border_left, box.border_right = bl, br
    box.padding_left, box.padding_right = pl, pr
    box.margin_left, box.margin_right = ml, mr
    box.content_width = w


def _shrink_to_fit_width(box):
    """A deliberately simple shrink-to-fit approximation for auto-width
    floats: the widest naturally-occurring (unwrapped) run of inline
    content, ignoring descendant block structure entirely. A fully general
    CSS shrink-to-fit (recursive min/max-content-width over arbitrary
    nested block content) is a substantially larger undertaking than this
    stretch feature calls for -- real-world floats overwhelmingly specify
    an explicit width for exactly this reason (image floats, sidebars),
    which take the exact branch above instead of this one."""
    if box.mode != "inline":
        return float("inf")  # no shrink-to-fit data available -> behave like a normal block (fills available width)
    widest = 0.0
    total = 0.0
    needs_space = False
    for kind, text, item_style in box.inline_items:
        if kind == "br":
            widest = max(widest, total)
            total = 0.0
            needs_space = False
            continue
        font_size = item_style.get("font-size", 16.0)
        bold = item_style.get("font-weight", "normal") == "bold"
        words, lead, trail = _tokenize_words(text or "")
        for w in words:
            if total > 0.0 or needs_space:
                total += fontmetrics.char_width(font_size, bold=bold)
            total += fontmetrics.measure_text(w, font_size, bold=bold)
            needs_space = False
        needs_space = trail
    widest = max(widest, total)
    return widest


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
    float_ctx = FloatContext(0.0, viewport_width)
    y_cursor, group, pending = _layout_block_children(
        [root_box], 0.0, [], [], viewport_width, 0.0, viewport_width, float_ctx
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


def _shift_box_tree(box, dx, dy):
    """Translate an already-fully-laid-out box (and everything inside it,
    including inline line fragments) by (dx, dy). Used to move a float's
    subtree from the provisional position it was measured at into its real
    position once that's known -- see `_place_float`."""
    box.x += dx
    box.border_box_top += dy
    box.content_box_top += dy
    box.content_box_bottom += dy
    for line in box.lines:
        line.y += dy
        for frag in line.fragments:
            frag[0] += dx
    for c in box.block_children:
        _shift_box_tree(c, dx, dy)


def _place_float(box, y_cursor, cb_width, content_x, viewport_width, float_ctx):
    """Lay out a floated box: measure its (margin-box) size with a trial
    layout at a provisional position, ask `float_ctx` where a box of that
    size actually fits, then translate the whole already-laid-out subtree
    there. Floats establish their own BFC (CSS2.1 9.5), so their own
    content gets a fresh, empty FloatContext -- Folio does not support a
    float dodging an *outer* float's exclusion zone from inside a float's
    own content (a rare, doubly-nested case)."""
    resolve_float_width(box, cb_width)
    _vertical_box_props(box, cb_width)
    box.x = content_x + box.margin_left
    box.border_box_top = y_cursor
    box.content_box_top = box.border_box_top + box.border_top + box.padding_top
    inner_float_ctx = FloatContext(box.x + box.border_left + box.padding_left, box.content_width)
    if box.mode == "block" and box.block_children:
        y_end, trailing_group, inner_pending = _layout_block_children(
            box.block_children, box.content_box_top, [], [], box.content_width,
            box.x + box.border_left + box.padding_left, viewport_width, inner_float_ctx,
        )
        # A float is its own BFC root: nothing left to bleed *out* of it,
        # so any still-pending trailing margin is consumed here, not left
        # dangling for a caller that will never ask for it again.
        extra = collapse(trailing_group)
        _flush_pending(inner_pending, y_end + extra)
        box.content_box_bottom = y_end + extra
    elif box.mode == "inline":
        cx = box.x + box.border_left + box.padding_left
        box.content_box_bottom = layout_inline_content(box, cx, box.content_box_top, box.content_width, inner_float_ctx)
    else:
        box.content_box_bottom = box.content_box_top
    explicit_h = _explicit_height(box)
    if explicit_h is not None:
        box.content_box_bottom = box.content_box_top + explicit_h

    margin_box_w = box.margin_left + box.border_box_width + box.margin_right
    margin_box_h = box.margin_top + box.border_box_height + box.margin_bottom
    y_min = float_ctx.clear_y(box.clear, y_cursor) if box.clear != "none" else y_cursor
    mx, my = float_ctx.place(box.float_type, margin_box_w, margin_box_h, y_min)
    dx = (mx + box.margin_left) - box.x
    dy = (my + box.margin_top) - box.border_box_top
    if dx or dy:
        _shift_box_tree(box, dx, dy)


def _layout_block_children(children, y_cursor, group, pending, cb_width, content_x, viewport_width, float_ctx):
    """Lay out `children` (block-level boxes -- in-flow AND floated, still
    in source order) top-to-bottom starting at `y_cursor` with `group` =
    pending (unflushed) adjoining margins and `pending` = the
    self-collapsing boxes already absorbed into `group` whose on-screen
    position is still undetermined (see `_flush_pending`). `float_ctx` is
    the FloatContext for this container (floats are placed into it; in-flow
    inline content queries it to wrap around them). Returns
    (y_cursor_final, group_final, pending_final): `group_final`/
    `pending_final` are what's left unresolved, for the caller to either
    bleed further outward or finally consume (calling `_flush_pending`)."""
    # `group`/`pending` are mutated in place (.append) rather than rebuilt
    # with `+ [x]` on every margin: this loop is the hot path for wide
    # sibling lists (thousands of paragraphs/rows), and `list + [x]` is an
    # O(n) copy -- rebuilding it on every child makes the whole walk
    # O(n^2). Nothing aliases an old snapshot of either list across
    # iterations (each reassignment either mutates the current list or
    # replaces it outright at a flush point), so in-place mutation is safe.
    for child in children:
        if child.float_type in ("left", "right"):
            # A float never itself flushes the pending margin `group` (it's
            # transparent to collapsing, same as spec), but it still needs
            # to be placed *below* whatever space that group represents --
            # using the raw, unflushed `y_cursor` here was a real bug: a
            # float that was the first thing inside a delegating (zero
            # border/padding) box landed 8px too high, ignoring the still-
            # pending body margin above it. `group`/`pending` themselves are
            # left completely untouched for the next in-flow sibling.
            float_y_min = y_cursor + collapse(group)
            _place_float(child, float_y_min, cb_width, content_x, viewport_width, float_ctx)
            continue  # floats are out-of-flow: never touch y_cursor/group/pending

        layout_block_box(child, content_x, cb_width, viewport_width)
        if child.clear != "none" and float_ctx.has_any():
            # Simplified (documented) clearance model: `clear` floors the
            # box's final top at the relevant floats' bottom edge, applied
            # on top of normal margin collapsing, rather than the full
            # CSS2.1 rule that clearance *suppresses* collapsing outright.
            # See REVIEW.md.
            y_cursor = max(y_cursor, float_ctx.clear_y(child.clear, y_cursor) - collapse(group + [child.margin_top]))
        group.append(child.margin_top)
        first_block = first_in_flow_block_child(child) if child.mode == "block" else None

        if _is_self_collapsing(child):
            # Transparent to the group: neither flushes a real gap nor walls
            # off collapsing on either side -- its own top+bottom margins
            # (and everything already pending) all merge into one group
            # that keeps bleeding until something non-self-collapsing (or
            # the end of this children list) finally consumes it. Its own
            # displayed position isn't known yet either -- defer it.
            group.append(child.margin_bottom)
            pending.append(child)
            continue

        delegate_top = child.border_top == 0 and child.padding_top == 0 and first_block is not None

        if delegate_top:
            # child's own top margin (already pushed onto `group` above)
            # collapses straight through into its first child's subtree --
            # recurse in the SAME *collapsing* scope rather than starting a
            # fresh one, so child's border-box-top ends up exactly where
            # its (recursively-collapsed) first descendant's does. This is
            # NOT the same as sharing the same *float* scope, though: child
            # may have its own explicit width different from the outer
            # float_ctx's (a zero-border/padding wrapper can still narrow
            # the containing block) -- always give it a fresh FloatContext
            # sized to its own content box, matching the "one FloatContext
            # per distinct content-width scope" rule used everywhere else.
            delegate_cx = child.x + child.border_left + child.padding_left
            delegate_float_ctx = FloatContext(delegate_cx, child.content_width)
            y_cursor, group, pending = _layout_block_children(
                child.block_children, y_cursor, group, pending, child.content_width,
                delegate_cx, viewport_width, delegate_float_ctx,
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

            if child.mode == "block" and child.block_children:
                child_cx = child.x + child.border_left + child.padding_left
                child_float_ctx = FloatContext(child_cx, child.content_width)
                y_cursor, group, pending = _layout_block_children(
                    child.block_children, child.content_box_top, [], [], child.content_width,
                    child_cx, viewport_width, child_float_ctx,
                )
            elif child.mode == "inline":
                cx = child.x + child.border_left + child.padding_left
                bottom = layout_inline_content(child, cx, child.content_box_top, child.content_width, float_ctx)
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
            group.append(child.margin_bottom)
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
    __slots__ = ("y", "height", "fragments", "width_used", "ends_with_forced_break", "left_edge", "avail_width")

    def __init__(self, y, height, left_edge=0.0, avail_width=0.0):
        self.y = y
        self.height = height
        self.fragments = []  # list of (x, text, style, width) -- x is line-relative until the final pass
        self.width_used = 0.0
        self.ends_with_forced_break = False
        self.left_edge = left_edge
        self.avail_width = avail_width


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


def layout_inline_content(box, content_x, content_top, content_width, float_ctx=None):
    """Greedy line-breaking over box.inline_items. Returns the y-coordinate
    of the bottom of the last line (== content bottom). If `float_ctx` has
    any floats registered, each line's available width/x-offset is
    (re-)queried per line so text wraps around them (CSS2.1 9.5) instead of
    using one fixed width for the whole block -- with no floats active
    `float_ctx.available_range` (or its absence) degenerates to exactly
    (content_x, content_x + content_width), so non-float layout is
    unaffected."""
    style = box.style
    font_size = style.get("font-size", 16.0)
    bold = style.get("font-weight", "normal") == "bold"
    line_h = fontmetrics.resolve_line_height(style.get("line-height", "normal"), font_size)
    align = style.get("text-align", "left")
    white_space = style.get("white-space", "normal")

    def line_geometry(y):
        if float_ctx is None:
            return content_x, content_width
        raw_left, raw_right = float_ctx.available_range(y, line_h)
        left = max(raw_left, content_x)
        right = min(raw_right, content_x + content_width)
        return left, max(0.0, right - left)

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
    first_left, first_avail = line_geometry(content_top)
    cur = LineBox(content_top, line_h, first_left, first_avail)
    cur_x = 0.0
    cur_font_size_max = font_size
    any_word_on_line = False

    def push_line(forced_break=False):
        nonlocal cur, cur_x, any_word_on_line, cur_font_size_max
        cur.ends_with_forced_break = forced_break
        lines.append(cur)
        new_y = cur.y + cur.height
        left, avail = line_geometry(new_y)
        cur = LineBox(new_y, line_h, left, avail)
        cur_x = 0.0
        any_word_on_line = False
        cur_font_size_max = font_size

    for entry in words:
        w, item_style, need_space = entry
        if w == "__BR__":
            push_line(forced_break=True)
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
        if any_word_on_line and projected > cur.avail_width + 1e-6:
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
        # CSS2.1 16.2: the last line of a block, AND any line ending in a
        # forced break (<br>), are never justified -- only lines that wrap
        # naturally get the extra inter-word space.
        is_last = i == len(lines) - 1
        _apply_text_align(line, line.avail_width, align, is_last=is_last or line.ends_with_forced_break)
        for f in line.fragments:
            f[0] += line.left_edge

    if not lines:
        return content_top
    return lines[-1].y + lines[-1].height


def _apply_text_align(line, avail_width, align, is_last):
    if not line.fragments:
        return
    extra = avail_width - line.width_used
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
