"""The CSS cascade: matches selectors, sorts by specificity/origin/order,
expands shorthands, applies inheritance, and produces one ComputedStyle
dict per DOM element.
"""

import re

from .css_parser import parse_css, parse_inline_style
from .dom import Element

# --- default user-agent stylesheet -----------------------------------

UA_STYLESHEET_TEXT = """
html, body, div, p, ul, ol, li, h1, h2, h3, h4, h5, h6,
header, footer, section, article, nav, aside, main, figure, figcaption,
blockquote, form, table, pre, hr, dl, dt, dd {
  display: block;
}
span, a, b, i, em, strong, small, code, label, img, br {
  display: inline;
}
head, title, script, style, meta, link {
  display: none;
}
body { margin: 8px; }
p { margin-top: 12px; margin-bottom: 12px; }
h1 { font-size: 32px; font-weight: bold; margin-top: 20px; margin-bottom: 20px; }
h2 { font-size: 26px; font-weight: bold; margin-top: 18px; margin-bottom: 18px; }
h3 { font-size: 22px; font-weight: bold; margin-top: 16px; margin-bottom: 16px; }
h4 { font-size: 19px; font-weight: bold; margin-top: 14px; margin-bottom: 14px; }
h5 { font-size: 17px; font-weight: bold; margin-top: 12px; margin-bottom: 12px; }
h6 { font-size: 16px; font-weight: bold; margin-top: 12px; margin-bottom: 12px; }
ul, ol { margin-top: 12px; margin-bottom: 12px; padding-left: 32px; }
b, strong { font-weight: bold; }
i, em { font-style: italic; }
a { color: blue; text-decoration: underline; }
hr { border-top-width: 1px; border-top-style: solid; border-top-color: black;
     margin-top: 8px; margin-bottom: 8px; }
"""

INHERITED_PROPERTIES = frozenset({
    "color", "font-size", "font-weight", "font-style", "font-family",
    "text-align", "line-height",
})

INITIAL_VALUES = {
    "display": "inline",
    "color": "black",
    "background-color": "transparent",
    "font-size": "16px",
    "font-weight": "normal",
    "font-style": "normal",
    "font-family": "monospace",
    "text-align": "left",
    "text-decoration": "none",
    "line-height": "normal",
    "width": "auto",
    "height": "auto",
    "margin-top": "0", "margin-right": "0", "margin-bottom": "0", "margin-left": "0",
    "padding-top": "0", "padding-right": "0", "padding-bottom": "0", "padding-left": "0",
    "border-top-width": "0", "border-right-width": "0",
    "border-bottom-width": "0", "border-left-width": "0",
    "border-top-style": "none", "border-right-style": "none",
    "border-bottom-style": "none", "border-left-style": "none",
    "border-top-color": "currentColor", "border-right-color": "currentColor",
    "border-bottom-color": "currentColor", "border-left-color": "currentColor",
    "box-sizing": "content-box",
    "float": "none",
    "clear": "none",
}

_SIDES = ("top", "right", "bottom", "left")


def _expand_edge_shorthand(base, value):
    """`margin: a [b [c [d]]]` -> {margin-top: a, margin-right: b, ...}."""
    parts = value.split()
    if not parts:
        return {}
    if len(parts) == 1:
        vals = [parts[0]] * 4
    elif len(parts) == 2:
        vals = [parts[0], parts[1], parts[0], parts[1]]
    elif len(parts) == 3:
        vals = [parts[0], parts[1], parts[2], parts[1]]
    else:
        vals = parts[:4]
    return {f"{base}-{side}": v for side, v in zip(_SIDES, vals)}


_COLOR_KEYWORDS = frozenset({
    "currentcolor", "transparent",
})


def _expand_border_edge(side, value):
    """`border-top: 1px solid red` (order-independent) -> width/style/color."""
    out = {}
    for tok in value.split():
        low = tok.lower()
        if re.match(r"^-?\d", tok) or low in ("thin", "medium", "thick"):
            out[f"border-{side}-width"] = tok
        elif low in ("none", "solid", "dashed", "dotted", "double"):
            out[f"border-{side}-style"] = tok
        else:
            out[f"border-{side}-color"] = tok
    return out


def expand_declaration(prop, value):
    """Expand a shorthand declaration into concrete longhand (prop, value)
    pairs. Non-shorthand properties pass through unchanged."""
    if prop in ("margin", "padding"):
        return list(_expand_edge_shorthand(prop, value).items())
    if prop == "border":
        out = {}
        for side in _SIDES:
            out.update(_expand_border_edge(side, value))
        return list(out.items())
    if prop in (f"border-{s}" for s in _SIDES):
        side = prop.split("-")[1]
        return list(_expand_border_edge(side, value).items())
    if prop == "border-width":
        return list(_expand_edge_shorthand("border-width", value).items())
    if prop == "border-style":
        return list(_expand_edge_shorthand("border-style", value).items())
    if prop == "border-color":
        return list(_expand_edge_shorthand("border-color", value).items())
    if prop == "background":
        # Simplified: only handle a plain color token, which is the common
        # case; anything fancier (gradients, images) is out of scope.
        return [("background-color", value)]
    return [(prop, value)]


class ComputedStyle:
    """A resolved (specified-value) style for one element, keyed by the
    longhand CSS property names in INITIAL_VALUES. Percentage/auto values
    for box-model properties are still symbolic strings here; layout.py
    resolves them into used pixel values against a containing block.
    """

    __slots__ = ("props",)

    def __init__(self, props):
        self.props = props

    def get(self, prop):
        return self.props.get(prop, INITIAL_VALUES.get(prop))

    def __getitem__(self, prop):
        return self.get(prop)

    def resolved_color(self, prop):
        value = self.get(prop)
        if value == "currentColor" or value == "currentcolor":
            return self.get("color")
        return value

    def __repr__(self):
        return f"ComputedStyle({self.props!r})"


def _default_ua_stylesheet():
    return parse_css(UA_STYLESHEET_TEXT)


_UA_SHEET = _default_ua_stylesheet()


def _matching_declarations(element, author_sheet):
    """Return [(specificity, order, origin_rank, Declaration), ...] for
    every declaration whose selector matches `element`, across the UA sheet
    and the author sheet, ready to be sorted for the cascade."""
    matched = []
    order = 0
    for origin_rank, sheet in ((0, _UA_SHEET), (1, author_sheet)):
        if sheet is None:
            continue
        for rule in sheet.rules:
            best = None
            for selector in rule.selectors:
                if selector.matches(element):
                    spec = selector.specificity()
                    if best is None or spec > best:
                        best = spec
            if best is not None:
                for decl in rule.declarations:
                    matched.append((best, rule.order, origin_rank, decl))
                order += 1
    return matched


def compute_style(element, parent_style, author_sheet):
    """Compute the final style dict for `element`, given its already-computed
    parent style (or None for the root) and the author stylesheet."""
    matched = _matching_declarations(element, author_sheet)

    inline_style = element.get("style")
    if inline_style:
        for decl in parse_inline_style(inline_style):
            # Inline declarations win over any selector regardless of
            # specificity (spec: inline style has specificity above all
            # normal author rules), modeled with a synthetic max specificity.
            matched.append(((999, 999, 999), 10 ** 9, 2, decl))

    # Cascade sort key: !important first, then specificity, then origin,
    # then source order -- all ascending, so the winner is sorted last.
    def sort_key(item):
        spec, order, origin_rank, decl = item
        return (int(decl.important), origin_rank, spec, order)

    matched.sort(key=sort_key)

    specified = {}
    for _, _, _, decl in matched:
        for longhand, value in expand_declaration(decl.prop, decl.value):
            specified[longhand] = value

    props = {}
    for prop, initial in INITIAL_VALUES.items():
        if prop in specified and specified[prop] != "inherit":
            props[prop] = specified[prop]
        elif prop in specified and specified[prop] == "inherit":
            props[prop] = (
                parent_style.get(prop) if parent_style else initial
            )
        elif prop in INHERITED_PROPERTIES and parent_style is not None:
            props[prop] = parent_style.get(prop)
        else:
            props[prop] = initial

    return ComputedStyle(props)


def compute_styles(document, author_css_text=""):
    """Walk the whole document, returning {Element: ComputedStyle}."""
    author_sheet = parse_css(author_css_text) if author_css_text else None
    styles = {}

    def visit(node, parent_style):
        for child in node.children:
            if isinstance(child, Element):
                style = compute_style(child, parent_style, author_sheet)
                styles[child] = style
                visit(child, style)

    visit(document, None)
    return styles


def collect_author_css(document):
    """Concatenate every <style> element's text content, document order."""
    from .dom import iter_descendants, Text
    chunks = []
    for el in iter_descendants(document):
        if el.tag == "style":
            text = "".join(
                c.data for c in el.children if isinstance(c, Text)
            )
            chunks.append(text)
    return "\n".join(chunks)
