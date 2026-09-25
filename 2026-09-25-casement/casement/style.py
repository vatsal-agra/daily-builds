"""Cascade + computed-style resolution.

Turns a DOM tree + a Stylesheet into a `ComputedStyle` per element: the
cascade (specificity + source order + `!important` + inline `style="..."`),
inheritance of the inheritable properties, and fallback to CSS initial
values for everything else. Values that need layout context to resolve
(percentages, `auto`) are kept as parsed-but-unresolved `Value` objects and
resolved during layout, not here.
"""

import re

from .css_parser import parse_declarations, parse_stylesheet
from .dom import Element

INHERITED = frozenset(
    {
        "color", "font-size", "font-weight", "line-height", "text-align",
        "font-family", "visibility",
    }
)

DEFAULTS = {
    "display": "inline",
    "position": "static",
    "top": "auto", "right": "auto", "bottom": "auto", "left": "auto",
    "z-index": "auto",
    "width": "auto", "height": "auto",
    "min-width": "0", "min-height": "0",
    "max-width": "none", "max-height": "none",
    "margin-top": "0", "margin-right": "0", "margin-bottom": "0", "margin-left": "0",
    "padding-top": "0", "padding-right": "0", "padding-bottom": "0", "padding-left": "0",
    "border-top-width": "0", "border-right-width": "0",
    "border-bottom-width": "0", "border-left-width": "0",
    "border-top-style": "none", "border-right-style": "none",
    "border-bottom-style": "none", "border-left-style": "none",
    "border-top-color": "black", "border-right-color": "black",
    "border-bottom-color": "black", "border-left-color": "black",
    "background-color": "transparent",
    "color": "black",
    "font-size": "16px",
    "font-weight": "normal",
    "font-family": "monospace",
    "line-height": "normal",
    "text-align": "left",
    "box-sizing": "content-box",
    "flex-direction": "row",
    "justify-content": "flex-start",
    "align-items": "stretch",
    "flex-wrap": "nowrap",
    "flex-grow": "0",
    "flex-shrink": "1",
    "flex-basis": "auto",
    "overflow": "visible",
    "visibility": "visible",
}

UA_STYLESHEET_TEXT = """
html, body, div, section, article, header, footer, nav, main, aside,
p, h1, h2, h3, h4, h5, h6, ul, ol, li, blockquote, form, fieldset, hr,
figure, figcaption, address, pre { display: block; }
span, a, strong, b, em, i, small, code, label, sub, sup { display: inline; }
br { display: inline; }
img { display: inline-block; width: 60px; height: 40px; }
body { margin: 8px; }
h1 { font-size: 32px; font-weight: bold; margin: 21px 0; }
h2 { font-size: 24px; font-weight: bold; margin: 20px 0; }
h3 { font-size: 19px; font-weight: bold; margin: 18px 0; }
h4 { font-size: 16px; font-weight: bold; margin: 21px 0; }
h5 { font-size: 14px; font-weight: bold; margin: 22px 0; }
h6 { font-size: 12px; font-weight: bold; margin: 25px 0; }
p, pre { margin: 16px 0; }
ul, ol { margin: 16px 0; padding-left: 32px; }
strong, b { font-weight: bold; }
a { color: #0000ee; }
hr { border-top-width: 1px; border-top-style: solid; margin: 8px 0; height: 0; }
blockquote { margin: 16px 40px; }
"""


class Value:
    """A parsed-but-not-yet-resolved property value."""

    __slots__ = ("kind", "data")

    def __init__(self, kind, data=None):
        self.kind = kind
        self.data = data

    def __repr__(self):
        return f"Value({self.kind}, {self.data!r})"

    def is_auto(self):
        return self.kind == "auto"


_LENGTH_RE = re.compile(r"^(-?[\d.]+)(px)?$")
_PCT_RE = re.compile(r"^(-?[\d.]+)%$")


def parse_length(raw):
    """Parse a <length>|<percentage>|auto value into a Value."""
    raw = (raw or "").strip().lower()
    if raw == "auto":
        return Value("auto")
    if raw in ("none",):
        return Value("none")
    if raw in ("normal",):
        return Value("normal")
    m = _PCT_RE.match(raw)
    if m:
        return Value("pct", float(m.group(1)))
    m = _LENGTH_RE.match(raw)
    if m:
        return Value("px", float(m.group(1)))
    return Value("auto")


NAMED_COLORS = {
    "black": (0, 0, 0), "white": (255, 255, 255), "red": (255, 0, 0),
    "green": (0, 128, 0), "blue": (0, 0, 255), "yellow": (255, 255, 0),
    "gray": (128, 128, 128), "grey": (128, 128, 128),
    "orange": (255, 165, 0), "purple": (128, 0, 128), "pink": (255, 192, 203),
    "brown": (165, 42, 42), "cyan": (0, 255, 255), "magenta": (255, 0, 255),
    "navy": (0, 0, 128), "teal": (0, 128, 128), "lime": (0, 255, 0),
    "maroon": (128, 0, 0), "silver": (192, 192, 192), "gold": (255, 215, 0),
    "indigo": (75, 0, 130), "violet": (238, 130, 238), "coral": (255, 127, 80),
    "salmon": (250, 128, 114), "khaki": (240, 230, 140), "beige": (245, 245, 220),
    "ivory": (255, 255, 240), "crimson": (220, 20, 60),
    "darkred": (139, 0, 0), "darkgreen": (0, 100, 0), "darkblue": (0, 0, 139),
    "lightgray": (211, 211, 211), "lightgrey": (211, 211, 211),
    "lightblue": (173, 216, 230), "lightgreen": (144, 238, 144),
    "dimgray": (105, 105, 105), "dimgrey": (105, 105, 105),
    "steelblue": (70, 130, 180), "tomato": (255, 99, 71),
    "slategray": (112, 128, 144), "whitesmoke": (245, 245, 245),
    "aliceblue": (240, 248, 255), "seagreen": (46, 139, 87),
    "firebrick": (178, 34, 34), "chocolate": (210, 105, 30),
}


def parse_color(raw, default=(0, 0, 0, 255)):
    raw = (raw or "").strip().lower()
    if raw in ("transparent", ""):
        return (0, 0, 0, 0)
    if raw == "currentcolor":
        return None  # caller must substitute `color`
    if raw.startswith("#"):
        hexpart = raw[1:]
        if len(hexpart) == 3:
            r, g, b = (int(c * 2, 16) for c in hexpart)
            return (r, g, b, 255)
        if len(hexpart) == 6:
            r = int(hexpart[0:2], 16)
            g = int(hexpart[2:4], 16)
            b = int(hexpart[4:6], 16)
            return (r, g, b, 255)
        if len(hexpart) == 8:
            r = int(hexpart[0:2], 16)
            g = int(hexpart[2:4], 16)
            b = int(hexpart[4:6], 16)
            a = int(hexpart[6:8], 16)
            return (r, g, b, a)
        return default
    m = re.match(r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)", raw)
    if m:
        r, g, b = (int(float(m.group(i))) for i in (1, 2, 3))
        a = int(float(m.group(4)) * 255) if m.group(4) else 255
        return (r, g, b, a)
    if raw in NAMED_COLORS:
        r, g, b = NAMED_COLORS[raw]
        return (r, g, b, 255)
    return default


SHORTHAND_SIDES = ("top", "right", "bottom", "left")


def _expand_box_shorthand(prefix, value, out):
    parts = value.split()
    if len(parts) == 1:
        vals = parts * 4
    elif len(parts) == 2:
        vals = [parts[0], parts[1], parts[0], parts[1]]
    elif len(parts) == 3:
        vals = [parts[0], parts[1], parts[2], parts[1]]
    elif len(parts) >= 4:
        vals = parts[:4]
    else:
        return
    for side, v in zip(SHORTHAND_SIDES, vals):
        out[f"{prefix}-{side}"] = v


def _expand_border_side(side, value, out):
    parts = value.split()
    width = "1px"
    style = "solid"
    color = None
    for p in parts:
        pl = p.lower()
        if pl in ("none", "solid", "dashed", "dotted", "double"):
            style = pl
        elif re.match(r"^-?[\d.]+(px)?$", pl):
            width = p
        else:
            color = p
    out[f"border-{side}-width"] = width
    out[f"border-{side}-style"] = style
    if color:
        out[f"border-{side}-color"] = color


def expand_shorthands(prop, value):
    """Return a dict of longhand-property -> value for a shorthand, or None
    if `prop` isn't a shorthand this engine expands."""
    out = {}
    if prop == "background":
        # Only the plain-color case is supported (no background-image,
        # position, repeat, etc.) -- the first token that parses as a
        # color becomes background-color; anything else in the shorthand
        # is silently dropped rather than crashing the cascade.
        for token in value.split():
            if token.lower() == "transparent" or token.startswith("#") or token.lower().startswith("rgb") or token.lower() in NAMED_COLORS:
                out["background-color"] = token
                break
        return out
    if prop == "margin":
        _expand_box_shorthand("margin", value, out)
        return out
    if prop == "padding":
        _expand_box_shorthand("padding", value, out)
        return out
    if prop == "border":
        for side in SHORTHAND_SIDES:
            _expand_border_side(side, value, out)
        return out
    if prop in ("border-top", "border-right", "border-bottom", "border-left"):
        side = prop.split("-")[1]
        _expand_border_side(side, value, out)
        return out
    if prop == "border-width":
        parts = value.split()
        vals = parts * 4 if len(parts) == 1 else parts
        for side, v in zip(SHORTHAND_SIDES, vals + vals):
            out[f"border-{side}-width"] = v
        return out
    if prop == "font":
        m = re.search(r"(bold|normal)?\s*([\d.]+px)", value)
        if m:
            if m.group(1):
                out["font-weight"] = m.group(1)
            out["font-size"] = m.group(2)
        return out
    if prop == "flex":
        parts = value.split()
        if len(parts) == 1 and parts[0] not in ("none",):
            out["flex-grow"] = parts[0]
            out["flex-shrink"] = "1"
            out["flex-basis"] = "0%"
        elif len(parts) >= 2:
            out["flex-grow"] = parts[0]
            out["flex-shrink"] = parts[1]
            if len(parts) >= 3:
                out["flex-basis"] = parts[2]
        return out
    return None


class ComputedStyle:
    __slots__ = ("props",)

    def __init__(self, props):
        self.props = props

    def raw(self, prop):
        return self.props.get(prop, DEFAULTS.get(prop, ""))

    def length(self, prop):
        return parse_length(self.raw(prop))

    def color(self, prop):
        c = parse_color(self.raw(prop))
        if c is None:
            return parse_color(self.raw("color"))
        return c

    def keyword(self, prop):
        return self.raw(prop)

    def number(self, prop, default=0.0):
        try:
            return float(self.raw(prop))
        except ValueError:
            return default

    def font_size_px(self):
        v = self.length("font-size")
        return v.data if v.kind == "px" else 16.0

    def line_height_px(self):
        raw = self.raw("line-height")
        fs = self.font_size_px()
        if raw in ("normal", ""):
            return fs * 1.2
        v = parse_length(raw)
        if v.kind == "px":
            return v.data
        if v.kind == "pct":
            return fs * v.data / 100.0
        try:
            return fs * float(raw)
        except ValueError:
            return fs * 1.2

    def is_bold(self):
        w = self.raw("font-weight").lower()
        if w == "bold":
            return True
        try:
            return int(w) >= 600
        except ValueError:
            return False


def _flatten_declarations(decls):
    """Expand shorthands into longhands, later entries in the list win."""
    flat = {}
    important = {}
    for d in decls:
        expanded = expand_shorthands(d.prop, d.value)
        if expanded is not None:
            for k, v in expanded.items():
                flat[k] = v
                important[k] = d.important
        else:
            flat[d.prop] = d.value
            important[d.prop] = d.important
    return flat, important


def parse_inline_style(style_attr):
    return parse_declarations(style_attr or "")


def compute_styles(document, stylesheet):
    """Compute the cascade for every element in `document`, returning a
    dict {Element: ComputedStyle}."""
    ua_sheet = parse_stylesheet(UA_STYLESHEET_TEXT)
    all_rules = list(ua_sheet.rules)
    # Each stylesheet was parsed independently, so both start their own
    # `.order` numbering at 0 -- without this offset, an author rule could
    # carry a *lower* order than a same-specificity UA rule appearing later
    # in the UA sheet, letting the cascade's "later wins" tie-break pick the
    # UA default over the author's own rule (e.g. `body { margin: 0 }`
    # losing to the UA sheet's `body { margin: 8px }`).
    base_order = len(all_rules)
    for r in stylesheet.rules:
        r.order += base_order
        all_rules.append(r)

    result = {}

    def compute_for(el, parent_style):
        # Collect (important, specificity, order, prop, value) candidates.
        candidates = []
        for rule in all_rules:
            for sel in rule.selectors:
                if sel.matches(el):
                    spec = sel.specificity()
                    for d in rule.declarations:
                        candidates.append((d.important, spec, rule.order, d.prop, d.value))
        inline_raw = el.get("style")
        if inline_raw:
            inline_decls = parse_inline_style(inline_raw)
            flat, important = _flatten_declarations(inline_decls)
            for prop, value in flat.items():
                candidates.append((important[prop], (2, 0, 0), 1_000_000, prop, value))

        # Expand shorthands found in matched rules too.
        expanded_candidates = []
        for important, spec, order, prop, value in candidates:
            expanded = expand_shorthands(prop, value)
            if expanded is not None:
                for k, v in expanded.items():
                    expanded_candidates.append((important, spec, order, k, v))
            else:
                expanded_candidates.append((important, spec, order, prop, value))

        expanded_candidates.sort(key=lambda c: (c[0], c[1], c[2]))
        specified = {}
        for _, _, _, prop, value in expanded_candidates:
            specified[prop] = value

        props = {}
        for prop in DEFAULTS:
            if prop in specified:
                props[prop] = specified[prop]
            elif prop in INHERITED and parent_style is not None:
                props[prop] = parent_style.props.get(prop, DEFAULTS[prop])
            else:
                props[prop] = DEFAULTS[prop]
        style = ComputedStyle(props)
        result[el] = style
        for child in el.children:
            if isinstance(child, Element):
                compute_for(child, style)

    for child in document.children:
        if isinstance(child, Element):
            compute_for(child, None)
    return result
