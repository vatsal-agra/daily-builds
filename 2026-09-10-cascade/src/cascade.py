"""The CSS cascade: match rules against the DOM, resolve specificity/order/
!important, expand shorthands, apply inheritance, and produce one computed
style dict (raw string values, resolved for cascade+inheritance) per
element."""

import re

from css_parser import parse_stylesheet
from css_values import INHERITED_PROPERTIES, INITIAL_VALUES
from dom import Element

UA_STYLESHEET = """
html, body, div, section, article, header, footer, nav, main, ul, ol, li,
p, h1, h2, h3, h4, h5, h6, form, figure, figcaption, blockquote, dl, dt, dd,
table, thead, tbody, tfoot, tr { display: block; }
head, script, style, title, link, meta { display: none; }
span, a, b, strong, i, em, small, code, label, img, input, button,
select, textarea { display: inline; }
img { display: inline-block; }

body { margin: 8px; font-family: sans-serif; font-size: 16px; color: #000000; }
p { margin-top: 1em; margin-bottom: 1em; }
h1 { font-size: 2em; font-weight: bold; margin-top: 0.67em; margin-bottom: 0.67em; }
h2 { font-size: 1.5em; font-weight: bold; margin-top: 0.83em; margin-bottom: 0.83em; }
h3 { font-size: 1.17em; font-weight: bold; margin-top: 1em; margin-bottom: 1em; }
h4 { font-size: 1em; font-weight: bold; margin-top: 1.33em; margin-bottom: 1.33em; }
h5 { font-size: 0.83em; font-weight: bold; margin-top: 1.67em; margin-bottom: 1.67em; }
h6 { font-size: 0.67em; font-weight: bold; margin-top: 2.33em; margin-bottom: 2.33em; }
b, strong { font-weight: bold; }
i, em { font-style: italic; }
a { color: #0000ee; text-decoration: underline; }
ul, ol { margin-top: 1em; margin-bottom: 1em; padding-left: 40px; }
li { display: list-item; }
hr { display: block; margin-top: 0.5em; margin-bottom: 0.5em; border-top-width: 1px; border-top-style: solid; border-top-color: #888888; }
blockquote { margin-top: 1em; margin-bottom: 1em; margin-left: 40px; margin-right: 40px; }
table { display: table; }
button, input { padding: 2px 6px; border-top-width: 1px; border-right-width: 1px;
  border-bottom-width: 1px; border-left-width: 1px; border-top-style: solid;
  border-right-style: solid; border-bottom-style: solid; border-left-style: solid;
  border-top-color: #767676; border-right-color: #767676; border-bottom-color: #767676;
  border-left-color: #767676; }
"""

_TOKEN_KEEP_FN = re.compile(r"[^\s,]+\([^)]*\)|\S+")


def _split_values(value):
    return _TOKEN_KEEP_FN.findall(value)


def expand_shorthand(prop, value):
    """Return {longhand: value} for a shorthand property, or None if prop
    is already a longhand (caller should store it as-is)."""
    parts = _split_values(value)

    if prop in ("margin", "padding"):
        prefix = prop
        if len(parts) == 1:
            t = r = b = l = parts[0]
        elif len(parts) == 2:
            t = b = parts[0]
            r = l = parts[1]
        elif len(parts) == 3:
            t = parts[0]
            r = l = parts[1]
            b = parts[2]
        elif len(parts) >= 4:
            t, r, b, l = parts[:4]
        else:
            return None
        return {f"{prefix}-top": t, f"{prefix}-right": r,
                f"{prefix}-bottom": b, f"{prefix}-left": l}

    if prop == "border-width" or prop == "border-style" or prop == "border-color":
        kind = prop.split("-")[1]
        if len(parts) == 1:
            t = r = b = l = parts[0]
        elif len(parts) == 2:
            t = b = parts[0]
            r = l = parts[1]
        elif len(parts) == 3:
            t = parts[0]
            r = l = parts[1]
            b = parts[2]
        elif len(parts) >= 4:
            t, r, b, l = parts[:4]
        else:
            return None
        return {f"border-top-{kind}": t, f"border-right-{kind}": r,
                f"border-bottom-{kind}": b, f"border-left-{kind}": l}

    if prop == "border":
        w, s, c = _parse_border_shorthand(parts)
        out = {}
        for side in ("top", "right", "bottom", "left"):
            if w is not None:
                out[f"border-{side}-width"] = w
            if s is not None:
                out[f"border-{side}-style"] = s
            if c is not None:
                out[f"border-{side}-color"] = c
        return out

    if prop in ("border-top", "border-right", "border-bottom", "border-left"):
        side = prop.split("-")[1]
        w, s, c = _parse_border_shorthand(parts)
        out = {}
        if w is not None:
            out[f"border-{side}-width"] = w
        if s is not None:
            out[f"border-{side}-style"] = s
        if c is not None:
            out[f"border-{side}-color"] = c
        return out

    if prop == "background":
        for p in parts:
            if p.lower() != "none":
                return {"background-color": p}
        return {"background-color": "transparent"}

    if prop == "list-style":
        for p in parts:
            if p.lower() in ("disc", "circle", "square", "decimal", "none"):
                return {"list-style-type": p.lower()}
        return None

    if prop == "flex":
        if len(parts) == 1 and parts[0] == "none":
            return {"flex-grow": "0", "flex-shrink": "0", "flex-basis": "auto"}
        if len(parts) == 1:
            return {"flex-grow": parts[0], "flex-shrink": "1", "flex-basis": "0%"}
        if len(parts) == 2:
            return {"flex-grow": parts[0], "flex-shrink": parts[1], "flex-basis": "0%"}
        if len(parts) >= 3:
            return {"flex-grow": parts[0], "flex-shrink": parts[1], "flex-basis": parts[2]}
        return None

    if prop == "font":
        weight = "normal"
        style = "normal"
        size = None
        family_start = None
        for i, p in enumerate(parts):
            low = p.lower()
            if low in ("bold", "bolder"):
                weight = "bold"
            elif low == "italic":
                style = "italic"
            elif re.match(r"^[\d.]+(px|em|pt|%)", low):
                size = p.split("/")[0]
                family_start = i + 1
                break
        out = {"font-weight": weight, "font-style": style}
        if size:
            out["font-size"] = size
        if family_start is not None and family_start < len(parts):
            out["font-family"] = " ".join(parts[family_start:])
        return out

    return None


_BORDER_STYLE_KEYWORDS = {"none", "solid", "dashed", "dotted", "double", "groove", "ridge"}


def _parse_border_shorthand(parts):
    w = s = c = None
    for p in parts:
        low = p.lower()
        if low in _BORDER_STYLE_KEYWORDS:
            s = low
        elif re.match(r"^[\d.]+(px|em|pt)?$", low) or low in ("thin", "medium", "thick"):
            w = {"thin": "1px", "medium": "3px", "thick": "5px"}.get(low, p)
        else:
            c = p
    return w, s, c


SHORTHANDS = {
    "margin", "padding", "border", "border-width", "border-style", "border-color",
    "border-top", "border-right", "border-bottom", "border-left",
    "background", "list-style", "flex", "font",
}


class Cascade:
    def __init__(self, author_css=""):
        self.ua_rules = parse_stylesheet(UA_STYLESHEET, _order_start=0)
        ua_max_order = max((r.order for r in self.ua_rules), default=0) + 1
        self.author_rules = parse_stylesheet(author_css, _order_start=ua_max_order)
        self.all_rules = self.ua_rules + self.author_rules

    def compute_styles(self, root):
        self._compute_recursive(root, {})

    def _compute_recursive(self, node, parent_style):
        if isinstance(node, Element):
            style = self._compute_for(node, parent_style)
            node.computed_style = style
            for child in node.children:
                self._compute_recursive(child, style)
        else:
            for child in getattr(node, "children", []):
                self._compute_recursive(child, parent_style)

    def _compute_for(self, el, parent_style):
        # 1. start from initial values, then inherit from parent where applicable
        style = dict(INITIAL_VALUES)
        for prop in INHERITED_PROPERTIES:
            if prop in parent_style:
                style[prop] = parent_style[prop]

        # 2. gather every declaration whose selector matches this element
        #    as (prop, value, important, specificity, order)
        candidates = {}
        for rule in self.all_rules:
            best_spec = None
            for sel in rule.selectors:
                if sel.matches(el):
                    spec = sel.specificity()
                    if best_spec is None or spec > best_spec:
                        best_spec = spec
            if best_spec is None:
                continue
            for decl in rule.declarations:
                # key = (important, is_inline, specificity, source-order):
                # importance dominates; within a tier, inline (not part of
                # the selector specificity system) outranks any selector;
                # ties within a tier break on specificity then source order.
                key = (1 if decl.important else 0, 0, best_spec, rule.order)
                props = expand_shorthand(decl.prop, decl.value)
                if props is None:
                    props = {decl.prop: decl.value}
                for p, v in props.items():
                    cur = candidates.get(p)
                    if cur is None or key >= cur[0]:
                        candidates[p] = (key, v)

        # 3. inline style="" attribute -- outranks any selector-based rule
        #    of the same importance tier.
        inline = el.attrs.get("style")
        if inline:
            for order, decl in enumerate(_parse_inline(inline)):
                key = (1 if decl.important else 0, 1, (0, 0, 0), order)
                props = expand_shorthand(decl.prop, decl.value)
                if props is None:
                    props = {decl.prop: decl.value}
                for p, v in props.items():
                    cur = candidates.get(p)
                    if cur is None or key >= cur[0]:
                        candidates[p] = (key, v)

        for p, (_, v) in candidates.items():
            style[p] = v

        return style


def _parse_inline(inline):
    from css_parser import parse_declarations
    return parse_declarations(inline)
