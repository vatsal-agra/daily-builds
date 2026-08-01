"""Selector matching + the CSS cascade: for every DOM element, find every
rule whose selector matches it, resolve conflicting declarations by
specificity -> source order -> !important, then apply property
inheritance to produce one `ComputedStyle` per node.
"""

import re

from .css_parser import specificity

INHERITED_PROPERTIES = {
    'color', 'font-size', 'font-weight', 'font-style', 'text-align',
    'line-height',
}

INITIAL_VALUES = {
    'color': 'black',
    'background-color': 'transparent',
    'font-size': '16px',
    'font-weight': 'normal',
    'font-style': 'normal',
    'text-align': 'left',
    'line-height': 'normal',
    'width': 'auto',
    'height': 'auto',
    'margin-top': '0px', 'margin-right': '0px', 'margin-bottom': '0px', 'margin-left': '0px',
    'padding-top': '0px', 'padding-right': '0px', 'padding-bottom': '0px', 'padding-left': '0px',
    'border-top-width': '0px', 'border-right-width': '0px',
    'border-bottom-width': '0px', 'border-left-width': '0px',
    'border-top-style': 'none', 'border-right-style': 'none',
    'border-bottom-style': 'none', 'border-left-style': 'none',
    'border-top-color': 'black', 'border-right-color': 'black',
    'border-bottom-color': 'black', 'border-left-color': 'black',
    'flex-direction': 'row',
    'justify-content': 'flex-start',
    'align-items': 'stretch',
    'gap': '0px',
    'flex-grow': '0',
}

# A minimal user-agent stylesheet: real browsers ship one, and without it
# every element looks like unstyled body text (headings the same size as
# paragraphs, links not blue, lists with no indent). These are ordinary
# rules fed through the same cascade as author CSS -- lowest source order,
# so any author rule of equal specificity overrides them -- rather than a
# separate "default" code path, which is what lets an author's own
# `h1 { font-size: ... }` correctly win without special-casing.
UA_STYLESHEET = """
h1 { font-size: 2em; font-weight: bold; margin-top: 0.67em; margin-bottom: 0.67em; }
h2 { font-size: 1.5em; font-weight: bold; margin-top: 0.75em; margin-bottom: 0.75em; }
h3 { font-size: 1.17em; font-weight: bold; margin-top: 0.83em; margin-bottom: 0.83em; }
h4 { font-size: 1em; font-weight: bold; margin-top: 1.12em; margin-bottom: 1.12em; }
h5 { font-size: 0.83em; font-weight: bold; margin-top: 1.5em; margin-bottom: 1.5em; }
h6 { font-size: 0.75em; font-weight: bold; margin-top: 1.67em; margin-bottom: 1.67em; }
b, strong { font-weight: bold; }
i, em { font-style: italic; }
p { margin-top: 1em; margin-bottom: 1em; }
ul, ol { margin-top: 1em; margin-bottom: 1em; padding-left: 40px; }
a { color: blue; }
"""

DEFAULT_DISPLAY = {
    'html': 'block', 'body': 'block', 'div': 'block', 'p': 'block',
    'ul': 'block', 'ol': 'block', 'li': 'block',
    'h1': 'block', 'h2': 'block', 'h3': 'block', 'h4': 'block', 'h5': 'block', 'h6': 'block',
    'section': 'block', 'article': 'block', 'header': 'block', 'footer': 'block',
    'nav': 'block', 'main': 'block', 'table': 'block', 'blockquote': 'block',
    'pre': 'block', 'form': 'block', 'hr': 'block', 'figure': 'block',
    'span': 'inline', 'a': 'inline', 'b': 'inline', 'i': 'inline',
    'strong': 'inline', 'em': 'inline', 'small': 'inline', 'code': 'inline',
    'label': 'inline', 'img': 'inline',
    'head': 'none', 'title': 'none', 'script': 'none', 'style': 'none',
    'meta': 'none', 'link': 'none',
}


def _expand_box(value, prefix):
    parts = value.split()
    if not parts:
        return {}
    if len(parts) == 1:
        t = r = b = l = parts[0]
    elif len(parts) == 2:
        t = b = parts[0]
        r = l = parts[1]
    elif len(parts) == 3:
        t = parts[0]
        r = l = parts[1]
        b = parts[2]
    else:
        t, r, b, l = parts[0], parts[1], parts[2], parts[3]
    return {
        f'{prefix}-top': t, f'{prefix}-right': r,
        f'{prefix}-bottom': b, f'{prefix}-left': l,
    }


_BORDER_STYLES = {'solid', 'dashed', 'dotted', 'double', 'none', 'groove', 'ridge', 'inset', 'outset'}
_LENGTH_RE = re.compile(r'^-?[\d.]+(px|em|pt|%)?$')


def _split_respecting_parens(value):
    """Split on whitespace, but never inside `fn(...)` -- so a border
    shorthand like `1px solid rgb(0, 0, 0)` keeps the color as one token
    instead of shredding it into `rgb(0,` `0,` `0)`."""
    tokens = []
    current = ''
    depth = 0
    for ch in value:
        if ch == '(':
            depth += 1
            current += ch
        elif ch == ')':
            depth = max(0, depth - 1)
            current += ch
        elif ch.isspace() and depth == 0:
            if current:
                tokens.append(current)
                current = ''
        else:
            current += ch
    if current:
        tokens.append(current)
    return tokens


def _expand_border(value):
    width = style = color = None
    for tok in _split_respecting_parens(value):
        low = tok.lower()
        if low in _BORDER_STYLES:
            style = low
        elif _LENGTH_RE.match(low) or low in ('thin', 'medium', 'thick'):
            width = tok
        else:
            color = tok
    out = {}
    for side in ('top', 'right', 'bottom', 'left'):
        if width is not None:
            out[f'border-{side}-width'] = width
        if style is not None:
            out[f'border-{side}-style'] = style
        if color is not None:
            out[f'border-{side}-color'] = color
    return out


SHORTHANDS = {
    'margin': lambda v: _expand_box(v, 'margin'),
    'padding': lambda v: _expand_box(v, 'padding'),
    'border': _expand_border,
    'background': lambda v: {'background-color': v},
}


def _matches_compound(compound, node):
    if node.node_type != 'element':
        return False
    if compound.type_name and node.name != compound.type_name:
        return False
    if compound.id and node.attrs.get('id') != compound.id:
        return False
    if compound.classes:
        node_classes = set(node.attrs.get('class', '').split())
        if not compound.classes.issubset(node_classes):
            return False
    return True


def matches(steps, node):
    if not steps:
        return False
    if not _matches_compound(steps[-1][1], node):
        return False
    current = node
    for k in range(len(steps) - 1, 0, -1):
        combinator = steps[k][0]
        target = steps[k - 1][1]
        if combinator == '>':
            parent = current.parent
            if parent is None or not _matches_compound(target, parent):
                return False
            current = parent
        else:
            ancestor = current.parent
            found = None
            while ancestor is not None:
                if _matches_compound(target, ancestor):
                    found = ancestor
                    break
                ancestor = ancestor.parent
            if found is None:
                return False
            current = found
    return True


class ComputedStyle:
    def __init__(self, node, properties, matches_debug=None):
        self.node = node
        self.properties = properties
        self.matches_debug = matches_debug or []

    def get(self, prop, default=None):
        return self.properties.get(prop, default)


def _initial_value(prop, node):
    if prop == 'display':
        return DEFAULT_DISPLAY.get(node.name, 'inline')
    return INITIAL_VALUES.get(prop, '0px')


def _collect_candidates(node, stylesheet):
    """Every (rank, prop, value) a matching rule contributes, with
    shorthand properties already expanded to longhands."""
    candidates = []
    debug = []
    for rule in stylesheet.rules:
        for steps in rule.selectors:
            if matches(steps, node):
                spec = specificity(steps)
                debug.append((spec, rule.order, steps))
                for prop, (value, important) in rule.declarations.items():
                    expander = SHORTHANDS.get(prop)
                    if expander:
                        for longprop, longvalue in expander(value).items():
                            candidates.append((important, spec, rule.order, longprop, longvalue))
                    else:
                        candidates.append((important, spec, rule.order, prop, value))
                break  # a rule's selector group only needs to match once per node
    return candidates, debug


def _compute_for_element(node, stylesheet, parent_style):
    candidates, debug = _collect_candidates(node, stylesheet)

    # Inline `style="..."` attribute: treated as maximum specificity, beating
    # every selector-based rule but still losing to `!important` declarations.
    inline = node.attrs.get('style')
    if inline:
        from .css_parser import _parse_declarations
        for prop, (value, important) in _parse_declarations(inline).items():
            expander = SHORTHANDS.get(prop)
            rank_spec = (999, 999, 999)
            if expander:
                for longprop, longvalue in expander(value).items():
                    candidates.append((important, rank_spec, 10**9, longprop, longvalue))
            else:
                candidates.append((important, rank_spec, 10**9, prop, value))

    winners = {}
    for important, spec, order, prop, value in candidates:
        rank = (important, spec, order)
        current = winners.get(prop)
        if current is None or rank > current[0]:
            winners[prop] = (rank, value)
    explicit = {prop: value for prop, (_rank, value) in winners.items()}

    # font-size is resolved to an absolute px number *now*, not left as a
    # string, specifically so a chain of relative sizes (e.g. two nested
    # elements each at "font-size: 0.5em") compounds against each
    # ancestor's real resolved size instead of every element's "em"
    # resolving against the same fixed 16px constant.
    parent_font_px = parent_style.get('font-size') if parent_style is not None else None
    if not isinstance(parent_font_px, (int, float)):
        parent_font_px = to_px(parent_font_px, font_size=16.0) if parent_font_px else None
    if parent_font_px is None:
        parent_font_px = 16.0

    if 'font-size' in explicit:
        font_size_px = to_px(explicit['font-size'], font_size=parent_font_px, percent_base=parent_font_px)
        if font_size_px is None:
            font_size_px = parent_font_px
    elif parent_style is not None:
        font_size_px = parent_font_px
    else:
        font_size_px = to_px(_initial_value('font-size', node), font_size=16.0) or 16.0

    resolved = {'font-size': font_size_px}
    for prop in INHERITED_PROPERTIES:
        if prop == 'font-size':
            continue
        if prop in explicit:
            resolved[prop] = explicit[prop]
        elif parent_style is not None:
            resolved[prop] = parent_style.get(prop)
        else:
            resolved[prop] = _initial_value(prop, node)

    known_noninherited = set(INITIAL_VALUES) | {'display'} | set(explicit)
    for prop in known_noninherited:
        if prop in INHERITED_PROPERTIES:
            continue
        resolved[prop] = explicit.get(prop, _initial_value(prop, node))

    return ComputedStyle(node, resolved, debug)


def compute_styles(document, extra_css=''):
    """Return {node: ComputedStyle} for every element/text node reachable
    from `document`, after cascading `extra_css` (e.g. an externally
    supplied stylesheet) followed by every <style> tag found in the
    document -- in that source order, so same-specificity conflicts inside
    the document win, matching how a browser treats a page's own <style>
    relative to an earlier-loaded stylesheet. Inheritance is then applied.
    Text nodes reuse their parent element's computed style (needed so the
    painter knows what color/font-size to render them in)."""
    from .css_parser import parse_stylesheet

    stylesheet = parse_stylesheet(UA_STYLESHEET)
    stylesheet.extend(parse_stylesheet(extra_css or ''))
    for style_node in document.find_all('style'):
        stylesheet.extend(parse_stylesheet(style_node.text_content()))

    styles = {}

    def walk(node, parent_style):
        if node.node_type == 'element':
            computed = _compute_for_element(node, stylesheet, parent_style)
            styles[node] = computed
            for child in node.children:
                walk(child, computed)
        else:
            if parent_style is not None:
                styles[node] = parent_style
            for child in node.children:
                walk(child, parent_style)

    walk(document, None)
    return styles, stylesheet


_UNIT_RE = re.compile(r'^(-?[\d.]+)(px|em|pt|%)?$')


def to_px(value, font_size=16.0, percent_base=None):
    """Resolve a CSS length string to a float pixel value. Returns None
    for keywords the caller must special-case ('auto', 'normal', 'none')."""
    if value is None:
        return None
    value = str(value).strip().lower()
    if value in ('auto', 'normal', 'none', ''):
        return None
    match = _UNIT_RE.match(value)
    if not match:
        return None
    number = float(match.group(1))
    unit = match.group(2) or 'px'
    if unit == 'px':
        return number
    if unit == 'pt':
        return number * (96.0 / 72.0)
    if unit == 'em':
        return number * font_size
    if unit == '%':
        if percent_base is None:
            return None
        return number / 100.0 * percent_base
    return number
