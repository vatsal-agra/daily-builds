"""The CSS cascade: given a DOM tree and a stylesheet, compute one
ComputedStyle per element — source order -> specificity -> !important,
then inheritance, exactly the algorithm real browsers run.
"""

import re
from .css_parser import parse_stylesheet, Declaration
from .dom import Element

INHERITED_PROPS = {
    "color", "font-family", "font-size", "font-weight", "font-style",
    "line-height", "text-align", "visibility", "white-space",
    "list-style-type", "letter-spacing",
}

INITIAL_VALUES = {
    "display": "inline",
    "width": "auto",
    "height": "auto",
    "margin-top": "0", "margin-right": "0", "margin-bottom": "0", "margin-left": "0",
    "padding-top": "0", "padding-right": "0", "padding-bottom": "0", "padding-left": "0",
    "border-top-width": "0", "border-right-width": "0",
    "border-bottom-width": "0", "border-left-width": "0",
    "border-top-style": "none", "border-right-style": "none",
    "border-bottom-style": "none", "border-left-style": "none",
    "border-top-color": "currentcolor", "border-right-color": "currentcolor",
    "border-bottom-color": "currentcolor", "border-left-color": "currentcolor",
    "box-sizing": "content-box",
    "color": "black",
    "background-color": "transparent",
    "font-size": "16px",
    "font-weight": "normal",
    "font-style": "normal",
    "font-family": "sans-serif",
    "line-height": "normal",
    "text-align": "left",
    "text-decoration": "none",
    "white-space": "normal",
    "float": "none",
    "clear": "none",
    "visibility": "visible",
    "letter-spacing": "normal",
}

# ------------------------------------------------------------- UA defaults

UA_STYLESHEET_TEXT = """
html, body, div, p, h1, h2, h3, h4, h5, h6, ul, ol, li, section, article,
header, footer, nav, main, aside, figure, figcaption, blockquote, form,
table, hr, pre, dl, dt, dd { display: block; }
span, a, b, strong, i, em, code, small, label, sub, sup, u, s { display: inline; }
br { display: inline; }
head, title, style, script { display: none; }
body { margin: 8px; }
p, blockquote, pre, dl, ol, ul, h1, h2, h3, h4, h5, h6, figure { margin-top: 16px; margin-bottom: 16px; }
h1 { font-size: 32px; font-weight: bold; margin-top: 21px; margin-bottom: 21px; }
h2 { font-size: 24px; font-weight: bold; margin-top: 20px; margin-bottom: 20px; }
h3 { font-size: 19px; font-weight: bold; margin-top: 19px; margin-bottom: 19px; }
h4 { font-size: 16px; font-weight: bold; margin-top: 21px; margin-bottom: 21px; }
h5 { font-size: 13px; font-weight: bold; }
h6 { font-size: 11px; font-weight: bold; }
b, strong { font-weight: bold; }
i, em { font-style: italic; }
u { text-decoration: underline; }
a { color: #0000EE; text-decoration: underline; }
pre, code { font-family: monospace; }
pre { white-space: pre; }
ul, ol { margin-left: 0; padding-left: 40px; }
li { display: list-item; }
hr { border-top-width: 1px; border-top-style: solid; border-top-color: #888888;
     margin-top: 8px; margin-bottom: 8px; }
"""

_UA_SHEET = None


def ua_stylesheet():
    global _UA_SHEET
    if _UA_SHEET is None:
        _UA_SHEET = parse_stylesheet(UA_STYLESHEET_TEXT)
    return _UA_SHEET


# ------------------------------------------------------------ shorthands

_SIDES = ("top", "right", "bottom", "left")


def _expand_four_sides(value):
    """The CSS 1/2/3/4-value shorthand pattern: '<v>' applies to all sides,
    '<v> <v>' is vert/horiz, '<v> <v> <v>' is top/horiz/bottom, and
    '<v> <v> <v> <v>' is top/right/bottom/left. Returns None if `value` is
    empty (nothing to expand)."""
    parts = value.split()
    if not parts:
        return None
    if len(parts) == 1:
        return list(parts) * 4
    if len(parts) == 2:
        return [parts[0], parts[1], parts[0], parts[1]]
    if len(parts) == 3:
        return [parts[0], parts[1], parts[2], parts[1]]
    return parts[:4]


def _expand_box_shorthand(prefix, value):
    vals = _expand_four_sides(value)
    if vals is None:
        return {}
    return {f"{prefix}-{side}": v for side, v in zip(_SIDES, vals)}


def _expand_border_component(component, value):
    """`border-width` / `border-style` / `border-color` shorthand ->
    {'border-top-width': v, 'border-right-width': v, ...}."""
    vals = _expand_four_sides(value)
    if vals is None:
        return {}
    return {f"border-{side}-{component}": v for side, v in zip(_SIDES, vals)}


_BORDER_STYLES = {"none", "solid", "dashed", "dotted", "double"}


def _looks_like_color(tok):
    return (tok.startswith("#") or tok.startswith("rgb")
            or tok.lower() in _NAMED_COLORS or tok.lower() == "transparent"
            or tok.lower() == "currentcolor")


def _expand_border_triplet(value):
    """Parses `<width> <style> <color>` in any order (each optional) as the
    `border` / `border-<side>` shorthand does."""
    width = style = color = None
    for tok in value.split():
        low = tok.lower()
        if low in _BORDER_STYLES:
            style = low
        elif _looks_like_color(tok):
            color = tok
        else:
            width = tok
    out = {}
    if width is not None:
        out["width"] = width
    if style is not None:
        out["style"] = style
    if color is not None:
        out["color"] = color
    return out


def expand_declarations(decls):
    """decls: list[Declaration] (already in winning cascade order) ->
    dict[prop] = (value, important). Expands shorthands to longhands."""
    out = {}

    def set_prop(prop, value, important):
        out[prop] = (value, important)

    for d in decls:
        p, v, imp = d.prop, d.value.strip(), d.important
        if p == "margin":
            for k2, v2 in _expand_box_shorthand("margin", v).items():
                set_prop(k2, v2, imp)
        elif p == "padding":
            for k2, v2 in _expand_box_shorthand("padding", v).items():
                set_prop(k2, v2, imp)
        elif p in ("border-width", "border-style", "border-color"):
            component = p.split("-")[1]
            for k2, v2 in _expand_border_component(component, v).items():
                set_prop(k2, v2, imp)
        elif p == "border":
            triplet = _expand_border_triplet(v)
            for side in _SIDES:
                if "width" in triplet:
                    set_prop(f"border-{side}-width", triplet["width"], imp)
                if "style" in triplet:
                    set_prop(f"border-{side}-style", triplet["style"], imp)
                if "color" in triplet:
                    set_prop(f"border-{side}-color", triplet["color"], imp)
        elif p in ("border-top", "border-right", "border-bottom", "border-left"):
            side = p.split("-")[1]
            triplet = _expand_border_triplet(v)
            if "width" in triplet:
                set_prop(f"border-{side}-width", triplet["width"], imp)
            if "style" in triplet:
                set_prop(f"border-{side}-style", triplet["style"], imp)
            if "color" in triplet:
                set_prop(f"border-{side}-color", triplet["color"], imp)
        elif p == "background":
            # We only support solid-color backgrounds; treat the shorthand
            # as background-color if its value plausibly is one.
            first = v.split()[0] if v.split() else ""
            if _looks_like_color(first):
                set_prop("background-color", first, imp)
        else:
            set_prop(p, v, imp)
    return out


# ------------------------------------------------------------- computation

class ComputedStyle:
    __slots__ = ("_values",)

    def __init__(self, values):
        self._values = values

    def get(self, prop):
        return self._values.get(prop, INITIAL_VALUES.get(prop, ""))

    def __repr__(self):
        return f"ComputedStyle({self._values!r})"


def _matching_declarations(el, sheets):
    """Returns list of (sort_key, Declaration) across all stylesheets for
    element `el`. sort_key sorts ascending; last-wins order = winner."""
    out = []
    for origin, sheet in sheets:
        for rule in sheet.rules:
            if rule.selector.matches(el):
                spec = rule.selector.specificity()
                for decl in rule.declarations:
                    key = (1 if decl.important else 0, origin, spec, rule.order)
                    out.append((key, decl))
    out.sort(key=lambda pair: pair[0])
    return [d for _, d in out]


def compute_styles(dom, author_css_text):
    """Returns dict[Element -> ComputedStyle] for every element in `dom`."""
    author_sheet = parse_stylesheet(author_css_text) if author_css_text else parse_stylesheet("")
    sheets = [(0, ua_stylesheet()), (1, author_sheet)]

    result = {}

    def visit(node, parent_style):
        for el in node.children:
            if not isinstance(el, Element):
                continue
            decls = _matching_declarations(el, sheets)
            specified = expand_declarations(decls)
            style_attr = el.attrs.get("style")
            if style_attr:
                # Inline `style="..."` beats any normal author/UA rule
                # (treated as maximum specificity) but not an !important
                # declaration from the cascade above.
                inline_sheet = parse_stylesheet("x{" + style_attr.replace("{", "").replace("}", "") + "}")
                inline_decls = expand_declarations(inline_sheet.rules[0].declarations) if inline_sheet.rules else {}
                for prop, (val, imp) in inline_decls.items():
                    cur = specified.get(prop)
                    if imp or cur is None or not cur[1]:
                        specified[prop] = (val, imp)

            values = {}
            for prop in set(list(specified.keys()) + list(INITIAL_VALUES.keys())):
                if prop in specified:
                    values[prop] = specified[prop][0]
                elif prop in INHERITED_PROPS and parent_style is not None:
                    values[prop] = parent_style.get(prop)
                else:
                    values[prop] = INITIAL_VALUES.get(prop, "")
            style = ComputedStyle(values)
            result[el] = style
            visit(el, style)

    visit(dom, None)
    return result


_NAMED_COLORS = {
    "black": (0, 0, 0), "white": (255, 255, 255), "red": (255, 0, 0),
    "green": (0, 128, 0), "blue": (0, 0, 255), "yellow": (255, 255, 0),
    "orange": (255, 165, 0), "purple": (128, 0, 128), "gray": (128, 128, 128),
    "grey": (128, 128, 128), "pink": (255, 192, 203), "brown": (165, 42, 42),
    "cyan": (0, 255, 255), "magenta": (255, 0, 255), "lime": (0, 255, 0),
    "navy": (0, 0, 128), "teal": (0, 128, 128), "maroon": (128, 0, 0),
    "olive": (128, 128, 0), "silver": (192, 192, 192), "gold": (255, 215, 0),
    "darkgray": (169, 169, 169), "darkgrey": (169, 169, 169),
    "lightgray": (211, 211, 211), "lightgrey": (211, 211, 211),
    "crimson": (220, 20, 60), "coral": (255, 127, 80), "salmon": (250, 128, 114),
    "khaki": (240, 230, 140), "indigo": (75, 0, 130), "violet": (238, 130, 238),
    "turquoise": (64, 224, 208), "beige": (245, 245, 220), "tan": (210, 180, 140),
    "chocolate": (210, 105, 30), "firebrick": (178, 34, 34), "forestgreen": (34, 139, 34),
    "royalblue": (65, 105, 225), "steelblue": (70, 130, 180), "slategray": (112, 128, 144),
}


def parse_color(value, current_color=(0, 0, 0)):
    """-> (r, g, b, a) with a in [0, 1]."""
    if not value:
        return (0, 0, 0, 0)
    v = value.strip().lower()
    if v in ("transparent",):
        return (0, 0, 0, 0)
    if v == "currentcolor":
        return (*current_color, 1.0)
    if v.startswith("#"):
        h = v[1:]
        if len(h) == 3:
            r, g, b = (int(c * 2, 16) for c in h)
            return (r, g, b, 1.0)
        if len(h) == 6:
            try:
                r = int(h[0:2], 16)
                g = int(h[2:4], 16)
                b = int(h[4:6], 16)
                return (r, g, b, 1.0)
            except ValueError:
                return (0, 0, 0, 1.0)
    m = re.match(r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)", v)
    if m:
        r, g, b = float(m.group(1)), float(m.group(2)), float(m.group(3))
        a = float(m.group(4)) if m.group(4) is not None else 1.0
        return (r, g, b, a)
    if v in _NAMED_COLORS:
        r, g, b = _NAMED_COLORS[v]
        return (r, g, b, 1.0)
    return (0, 0, 0, 1.0)


def color_to_svg(rgba):
    r, g, b, a = rgba
    return f"rgb({int(r)},{int(g)},{int(b)})", a
