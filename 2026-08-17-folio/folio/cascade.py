"""The CSS cascade: selector matching, specificity, inheritance, and
computed-style resolution -- turning (DOM + stylesheets) into one resolved
style dict per element, the way a real browser's style engine does.
"""

from .css_parser import parse_stylesheet, parse_declarations
from .values import parse_length, parse_color, Length

# ---------------------------------------------------------------------------
# Default user-agent stylesheet. This mirrors (a deliberately small, real)
# subset of what actual browsers ship as their built-in html.css, which is
# *why* unstyled HTML still lays out sensibly, and why fixtures that only
# rely on UA defaults (e.g. `<body><h1>...`) are meaningfully comparable to
# real Chromium.
# ---------------------------------------------------------------------------
UA_STYLESHEET_TEXT = """
html, address, blockquote, body, dd, div, dl, dt, fieldset, form,
h1, h2, h3, h4, h5, h6, noframes, ol, p, ul, center, dir, hr, menu,
pre, section, article, header, footer, nav, aside, figure, figcaption,
main, table, li { display: block; }
li { display: list-item; }
head, script, style, title, meta, link { display: none; }
body { margin: 8px; }
p, blockquote, figure, dl, pre, form { margin-top: 1em; margin-bottom: 1em; }
ol, ul { margin-top: 1em; margin-bottom: 1em; padding-left: 40px; }
h1 { font-size: 2em; font-weight: bold; margin-top: 0.67em; margin-bottom: 0.67em; }
h2 { font-size: 1.5em; font-weight: bold; margin-top: 0.83em; margin-bottom: 0.83em; }
h3 { font-size: 1.17em; font-weight: bold; margin-top: 1em; margin-bottom: 1em; }
h4 { font-weight: bold; margin-top: 1.33em; margin-bottom: 1.33em; }
h5 { font-size: 0.83em; font-weight: bold; margin-top: 1.67em; margin-bottom: 1.67em; }
h6 { font-size: 0.67em; font-weight: bold; margin-top: 2.33em; margin-bottom: 2.33em; }
b, strong { font-weight: bold; }
i, em { font-style: italic; }
a { color: #0000EE; }
hr { border-top-width: 1px; border-top-style: solid; border-color: #808080;
     margin-top: 0.5em; margin-bottom: 0.5em; height: 0px; }
pre { font-family: monospace; white-space: pre; }
"""

_ua_stylesheet_cache = None


def ua_stylesheet():
    global _ua_stylesheet_cache
    if _ua_stylesheet_cache is None:
        _ua_stylesheet_cache = parse_stylesheet(UA_STYLESHEET_TEXT)
    return _ua_stylesheet_cache


INHERITED_PROPERTIES = frozenset(
    [
        "color", "font-size", "font-family", "font-weight", "font-style",
        "line-height", "text-align", "white-space", "list-style-type",
        "visibility",
    ]
)

INITIAL_VALUES = {
    "display": "inline",
    "position": "static",
    "float": "none",
    "clear": "none",
    "color": "#000000",
    "background-color": "transparent",
    "font-size": "16px",
    "font-weight": "normal",
    "font-style": "normal",
    "font-family": "sans-serif",
    "line-height": "normal",
    "text-align": "left",
    "white-space": "normal",
    "visibility": "visible",
    "width": "auto",
    "height": "auto",
    "margin-top": "0px", "margin-right": "0px", "margin-bottom": "0px", "margin-left": "0px",
    "padding-top": "0px", "padding-right": "0px", "padding-bottom": "0px", "padding-left": "0px",
    "border-top-width": "0px", "border-right-width": "0px",
    "border-bottom-width": "0px", "border-left-width": "0px",
    "border-top-style": "none", "border-right-style": "none",
    "border-bottom-style": "none", "border-left-style": "none",
    "border-top-color": "currentColor", "border-right-color": "currentColor",
    "border-bottom-color": "currentColor", "border-left-color": "currentColor",
    "list-style-type": "disc",
}

_LENGTH_PROPS = frozenset(
    [
        "width", "height", "margin-top", "margin-right", "margin-bottom", "margin-left",
        "padding-top", "padding-right", "padding-bottom", "padding-left",
        "border-top-width", "border-right-width", "border-bottom-width", "border-left-width",
    ]
)
_PERCENT_OK = frozenset(
    [
        "width", "margin-top", "margin-right", "margin-bottom", "margin-left",
        "padding-top", "padding-right", "padding-bottom", "padding-left",
    ]
)
_AUTO_OK = frozenset(["width", "height", "margin-top", "margin-right", "margin-bottom", "margin-left"])
_COLOR_PROPS = frozenset(
    ["color", "background-color", "border-top-color", "border-right-color",
     "border-bottom-color", "border-left-color"]
)

_SIDES = ("top", "right", "bottom", "left")


def expand_shorthand(prop, value):
    """Expand a shorthand declaration into {longhand: value}. Unknown
    shorthands/props pass through unchanged (handled generically later)."""
    parts = value.split()
    if prop in ("margin", "padding"):
        vals = _four_side_values(parts)
        return {"%s-%s" % (prop, side): v for side, v in zip(_SIDES, vals)}
    if prop == "border-width":
        vals = _four_side_values(parts)
        return {"border-%s-width" % side: v for side, v in zip(_SIDES, vals)}
    if prop == "border-style":
        vals = _four_side_values(parts)
        return {"border-%s-style" % side: v for side, v in zip(_SIDES, vals)}
    if prop == "border-color":
        vals = _four_side_values(parts)
        return {"border-%s-color" % side: v for side, v in zip(_SIDES, vals)}
    if prop == "border" or prop in ("border-top", "border-right", "border-bottom", "border-left"):
        sides = _SIDES if prop == "border" else (prop.split("-", 1)[1],)
        out = {}
        for tok in parts:
            if tok.replace(".", "", 1).replace("-", "", 1).isdigit() or _looks_like_length(tok):
                for s in sides:
                    out["border-%s-width" % s] = tok
            elif tok.lower() in ("none", "solid", "dashed", "dotted", "double", "groove", "ridge", "inset", "outset"):
                for s in sides:
                    out["border-%s-style" % s] = tok
            else:
                for s in sides:
                    out["border-%s-color" % s] = tok
        return out
    if prop == "background":
        # Only the color half of `background` shorthand is modeled.
        for tok in parts:
            c = parse_color(tok)
            if c is not None:
                return {"background-color": tok}
        return {}
    return {prop: value}


def _looks_like_length(tok):
    return bool(tok) and (tok[0].isdigit() or tok[0] == "-") and any(
        tok.endswith(u) for u in ("px", "em", "%", "rem")
    ) or tok.replace(".", "", 1).lstrip("-").isdigit()


def _four_side_values(parts):
    if len(parts) == 1:
        return [parts[0]] * 4
    if len(parts) == 2:
        return [parts[0], parts[1], parts[0], parts[1]]
    if len(parts) == 3:
        return [parts[0], parts[1], parts[2], parts[1]]
    if len(parts) >= 4:
        return parts[:4]
    return ["0"] * 4


# ---------------------------------------------------------------------------
# Selector matching
# ---------------------------------------------------------------------------

def _compound_matches(comp, element):
    if comp.tag and comp.tag != element.tag:
        return False
    if comp.id and comp.id != element.id:
        return False
    if comp.classes:
        ecls = set(element.class_list)
        if not all(c in ecls for c in comp.classes):
            return False
    for name, op, val in comp.attrs:
        actual = element.attrs.get(name)
        if actual is None:
            return False
        if op == "=" and actual != val:
            return False
        if op == "~=" and val not in actual.split():
            return False
    for pseudo in comp.pseudo:
        if pseudo == "first-child" and not _is_nth_element_child(element, 0):
            return False
        elif pseudo == "last-child" and not _is_last_element_child(element):
            return False
    return True


def _element_siblings(element):
    if element.parent is None:
        return [element]
    return [c for c in element.parent.children if c.is_element]


def _is_nth_element_child(element, index):
    sibs = _element_siblings(element)
    return bool(sibs) and sibs[index] is element


def _is_last_element_child(element):
    sibs = _element_siblings(element)
    return bool(sibs) and sibs[-1] is element


def selector_matches(selector, element):
    if not selector.compounds:
        return False
    if not _compound_matches(selector.compounds[-1], element):
        return False
    node = element
    for i in range(len(selector.compounds) - 2, -1, -1):
        comb = selector.combinators[i]
        comp = selector.compounds[i]
        if comb == ">":
            node = node.parent
            if node is None or not node.is_element or not _compound_matches(comp, node):
                return False
        else:
            node = node.parent
            found = False
            while node is not None and node.is_element:
                if _compound_matches(comp, node):
                    found = True
                    break
                node = node.parent
            if not found:
                return False
    return True


# ---------------------------------------------------------------------------
# Cascade
# ---------------------------------------------------------------------------

_UA_WEIGHT = 0
_AUTHOR_WEIGHT = 10
_AUTHOR_IMPORTANT_WEIGHT = 20


class ComputedStyle:
    """Resolved values for one element. Length-valued properties hold a
    `values.Length`; colors hold an (r,g,b,a) tuple; everything else is a
    plain lower-cased keyword string."""

    def __init__(self, raw):
        self.raw = raw  # prop -> resolved value

    def __getitem__(self, prop):
        return self.raw[prop]

    def get(self, prop, default=None):
        return self.raw.get(prop, default)

    def __contains__(self, prop):
        return prop in self.raw

    def __repr__(self):
        return "ComputedStyle(%r)" % (self.raw,)


def _collect_declarations(element, stylesheets_with_origin, inline_decls):
    """Returns list of (weight, specificity_tuple, source_order, prop, value)."""
    out = []
    counter = 0
    for stylesheet, is_ua in stylesheets_with_origin:
        for rule in stylesheet.rules:
            for selector in rule.selectors:
                if selector_matches(selector, element):
                    spec = (0,) + selector.specificity()
                    for decl in rule.declarations:
                        weight = _UA_WEIGHT if is_ua else (
                            _AUTHOR_IMPORTANT_WEIGHT if decl.important else _AUTHOR_WEIGHT
                        )
                        for lp, lv in expand_shorthand(decl.prop, decl.value).items():
                            out.append((weight, spec, rule.source_order * 1000 + counter, lp, lv))
                    counter += 1
    for decl in inline_decls:
        weight = _AUTHOR_IMPORTANT_WEIGHT if decl.important else _AUTHOR_WEIGHT
        spec = (1, 0, 0, 0)
        for lp, lv in expand_shorthand(decl.prop, decl.value).items():
            out.append((weight, spec, 10**9, lp, lv))
    return out


def _resolve_value(prop, raw_value, font_size_px, current_color):
    raw_value = raw_value.strip()
    if prop in _LENGTH_PROPS:
        length = parse_length(
            raw_value,
            font_size_px=font_size_px,
            allow_auto=prop in _AUTO_OK,
            allow_percent=prop in _PERCENT_OK,
        )
        return length
    if prop in _COLOR_PROPS:
        color = parse_color(raw_value, current_color=current_color)
        return color
    if prop == "font-size":
        length = parse_length(raw_value, font_size_px=font_size_px, allow_auto=False, allow_percent=False)
        if length is None or length.kind != "px":
            return None
        return length.value
    if prop == "line-height":
        if raw_value == "normal":
            return "normal"
        try:
            return ("multiple", float(raw_value))  # bare number: a multiplier of font-size
        except ValueError:
            pass
        length = parse_length(raw_value, font_size_px=font_size_px, allow_auto=False, allow_percent=False)
        if length is not None and length.kind == "px":
            return length.value
        return None
    return raw_value.lower() if prop not in ("font-family",) else raw_value


def extract_inline_stylesheets(document):
    """Collect the text content of every <style> element in the document,
    in document order -- the CSS a real browser picks up automatically from
    `<style>` blocks, without the caller having to separately supply it."""
    texts = []
    for el in document.iter_element_descendants():
        if el.tag == "style":
            texts.append("".join(child.data for child in el.children if child.is_text))
    return texts


def compute_style_tree(document, author_css_texts, inline_attr="style"):
    """Compute a ComputedStyle for every Element in `document`. Returns a
    dict: Element -> ComputedStyle. `author_css_texts` are extra stylesheets
    (e.g. from linked .css files) layered after any `<style>` blocks found
    in `document` itself, which are always picked up automatically."""
    all_css_texts = extract_inline_stylesheets(document) + list(author_css_texts)
    author_sheets = [parse_stylesheet(text) for text in all_css_texts]
    stylesheets_with_origin = [(ua_stylesheet(), True)] + [(s, False) for s in author_sheets]

    styles = {}

    def visit(element, parent_style):
        inline_text = element.get_attr(inline_attr, "")
        inline_decls = parse_declarations(inline_text) if inline_text else []
        declarations = _collect_declarations(element, stylesheets_with_origin, inline_decls)

        winners = {}
        for weight, spec, order, prop, value in declarations:
            key = (weight, spec, order)
            if prop not in winners or key > winners[prop][0]:
                winners[prop] = (key, value)

        parent_font_size = parent_style.get("font-size", 16.0) if parent_style else 16.0
        raw_font_size_str = winners.get("font-size", (None, None))[1]
        if raw_font_size_str is not None:
            font_size_px = _resolve_value("font-size", raw_font_size_str, parent_font_size, (0, 0, 0))
            if font_size_px is None:
                font_size_px = parent_font_size
        else:
            font_size_px = parent_font_size

        parent_color = parent_style.get("color", (0, 0, 0, 255)) if parent_style else (0, 0, 0, 255)
        raw_color_str = winners.get("color", (None, None))[1]
        current_color = parent_color
        if raw_color_str is not None:
            c = _resolve_value("color", raw_color_str, font_size_px, parent_color)
            if c is not None:
                current_color = c

        resolved = {}
        all_props = set(INITIAL_VALUES) | set(winners)
        for prop in all_props:
            if prop in winners:
                raw_value = winners[prop][1]
                value = _resolve_value(prop, raw_value, font_size_px, current_color)
                if value is None:
                    value = None  # fall through to inherit/initial below
            else:
                value = None

            if value is None:
                if prop in INHERITED_PROPERTIES and parent_style is not None:
                    value = parent_style.get(prop, _initial(prop, font_size_px, current_color))
                else:
                    value = _initial(prop, font_size_px, current_color)
            resolved[prop] = value

        resolved["font-size"] = font_size_px
        resolved["color"] = current_color
        style = ComputedStyle(resolved)
        styles[element] = style
        for child in element.children:
            if child.is_element:
                visit(child, style)

    for child in document.children:
        if child.is_element:
            visit(child, None)

    return styles


def _initial(prop, font_size_px, current_color):
    if prop == "font-size":
        return font_size_px
    if prop == "color":
        return current_color
    if prop in _COLOR_PROPS:
        raw = INITIAL_VALUES[prop]
        return parse_color(raw, current_color=current_color)
    if prop in _LENGTH_PROPS:
        raw = INITIAL_VALUES.get(prop, "0px")
        return parse_length(raw, font_size_px=font_size_px, allow_auto=prop in _AUTO_OK, allow_percent=prop in _PERCENT_OK)
    if prop == "line-height":
        return "normal"
    return INITIAL_VALUES.get(prop, "")
