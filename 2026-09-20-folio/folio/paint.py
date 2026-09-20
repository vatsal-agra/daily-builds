"""Turns a positioned layout tree into an ordered list of paint commands
(rect fills, rect strokes for borders, text runs) in painter's-algorithm
(document) order -- the single source of truth both the PNG rasterizer and
the interactive HTML/SVG inspector draw from.
"""

from .layout import Box, InlineBox, TextRun

NAMED_COLORS = {
    "black": (0, 0, 0), "white": (255, 255, 255), "red": (255, 0, 0),
    "green": (0, 128, 0), "blue": (0, 0, 255), "yellow": (255, 255, 0),
    "orange": (255, 165, 0), "purple": (128, 0, 128), "gray": (128, 128, 128),
    "grey": (128, 128, 128), "silver": (192, 192, 192), "maroon": (128, 0, 0),
    "navy": (0, 0, 128), "teal": (0, 128, 128), "olive": (128, 128, 0),
    "lime": (0, 255, 0), "aqua": (0, 255, 255), "cyan": (0, 255, 255),
    "magenta": (255, 0, 255), "fuchsia": (255, 0, 255), "pink": (255, 192, 203),
    "brown": (165, 42, 42), "gold": (255, 215, 0), "indigo": (75, 0, 130),
    "coral": (255, 127, 80), "salmon": (250, 128, 114), "khaki": (240, 230, 140),
    "crimson": (220, 20, 60), "chocolate": (210, 105, 30), "tan": (210, 180, 140),
    "lightgray": (211, 211, 211), "lightgrey": (211, 211, 211),
    "darkgray": (169, 169, 169), "darkgrey": (169, 169, 169),
    "lightblue": (173, 216, 230), "lightgreen": (144, 238, 144),
    "darkgreen": (0, 100, 0), "darkblue": (0, 0, 139), "darkred": (139, 0, 0),
    "beige": (245, 245, 220), "ivory": (255, 255, 240), "transparent": None,
}


def parse_color(value, fallback=(0, 0, 0)):
    if value is None:
        return fallback
    value = value.strip()
    low = value.lower()
    if low == "transparent":
        return None
    if low in NAMED_COLORS:
        return NAMED_COLORS[low]
    if value.startswith("#"):
        hexpart = value[1:]
        try:
            if len(hexpart) == 3:
                r, g, b = (int(c * 2, 16) for c in hexpart)
                return (r, g, b)
            if len(hexpart) == 6:
                r = int(hexpart[0:2], 16)
                g = int(hexpart[2:4], 16)
                b = int(hexpart[4:6], 16)
                return (r, g, b)
        except ValueError:
            return fallback
    if low.startswith("rgb(") or low.startswith("rgba("):
        inner = value[value.find("(") + 1:value.rfind(")")]
        parts = [p.strip() for p in inner.split(",")]
        try:
            r, g, b = (max(0, min(255, int(float(p)))) for p in parts[:3])
            return (r, g, b)
        except ValueError:
            return fallback
    return fallback


class PaintCommand:
    __slots__ = ("kind", "box", "x", "y", "width", "height", "color", "extra")

    def __init__(self, kind, box, x, y, width, height, color, extra=None):
        self.kind = kind  # 'rect' | 'border' | 'text'
        self.box = box
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.color = color
        self.extra = extra or {}

    def to_dict(self):
        d = {
            "kind": self.kind,
            "x": self.x, "y": self.y,
            "width": self.width, "height": self.height,
            "color": list(self.color) if self.color else None,
        }
        d.update(self.extra)
        return d


def build_paint_commands(root_box):
    commands = []
    _paint_box(root_box, commands)
    return commands


def _paint_box(box, commands):
    if isinstance(box, Box):
        if box.node is not None and box.style is not None:
            _paint_background_and_border(box, commands)
        for child in box.children:
            _paint_box(child, commands)
    elif isinstance(box, TextRun):
        _paint_text_run(box, commands)
    elif isinstance(box, InlineBox):
        _paint_inline_box(box, commands)


def _paint_background_and_border(box, commands):
    style = box.style
    bg = parse_color(style.get("background-color"))
    if bg is not None and box.width > 0 and box.height > 0:
        commands.append(PaintCommand(
            "rect", box, box.x, box.y, box.width, box.height, bg,
            extra={"dom": _dom_label(box)},
        ))

    for side, (bx, by, bw, bh) in _border_edges(box).items():
        width = box.border[side]
        if width <= 0:
            continue
        style_kw = style.get(f"border-{side}-style")
        if style_kw == "none":
            continue
        color = parse_color(style.resolved_color(f"border-{side}-color"))
        if color is None or bw <= 0 or bh <= 0:
            continue
        commands.append(PaintCommand(
            "rect", box, bx, by, bw, bh, color,
            extra={"border_side": side},
        ))


def _border_edges(box):
    x, y, w, h = box.x, box.y, box.width, box.height
    t, r, b, l = (box.border["top"], box.border["right"],
                  box.border["bottom"], box.border["left"])
    return {
        "top": (x, y, w, t),
        "bottom": (x, y + h - b, w, b),
        "left": (x, y, l, h),
        "right": (x + w - r, y, r, h),
    }


def _paint_text_run(run, commands):
    color = parse_color(run.style.resolved_color("color"), fallback=(0, 0, 0))
    weight = run.style.get("font-weight")
    style_kw = run.style.get("font-style")
    decoration = run.style.get("text-decoration")
    commands.append(PaintCommand(
        "text", run, run.x, run.y, run.width, run.height, color,
        extra={
            "text": run.text,
            "bold": weight == "bold",
            "italic": style_kw == "italic",
            "underline": "underline" in (decoration or ""),
            "dom": _dom_label(run),
        },
    ))


def _paint_inline_box(inline_box, commands):
    color = parse_color(inline_box.style.get("background-color")) or (200, 200, 200)
    commands.append(PaintCommand(
        "rect", inline_box, inline_box.x, inline_box.y,
        inline_box.width, inline_box.height, color,
        extra={"placeholder_img": True, "dom": _dom_label(inline_box)},
    ))


def _dom_label(box):
    node = getattr(box, "node", None)
    from .dom import Element
    if isinstance(node, Element):
        return repr(node)
    if node is not None and hasattr(node, "parent"):
        parent = node.parent
        if isinstance(parent, Element):
            return repr(parent)
    return None
