"""CSS parsing: raw stylesheet text -> a list of Rule(selectors, declarations).

Supports the subset of CSS this engine implements: type/class/id/universal/
attribute selectors, descendant/child/adjacent-sibling combinators,
:first-child/:last-child/:nth-child()/:only-child pseudo-classes,
comma-separated selector lists, `!important`, and treats @-rules with a
block body (like @media) by flattening their contents in unconditionally
(no responsive condition evaluation -- documented simplification) while
skipping statement-only @-rules (@import, @charset, ...).
"""

import re

from selector import Combinator, Selector, SimpleSelector


class Declaration:
    __slots__ = ("prop", "value", "important")

    def __init__(self, prop, value, important=False):
        self.prop = prop
        self.value = value
        self.important = important


class Rule:
    __slots__ = ("selectors", "declarations", "order")

    def __init__(self, selectors, declarations, order):
        self.selectors = selectors  # list[Selector]
        self.declarations = declarations  # list[Declaration]
        self.order = order  # source-order index, for cascade tie-breaking


def _strip_comments(text):
    return re.sub(r"/\*.*?\*/", " ", text, flags=re.S)


def _find_matching_brace(text, open_idx):
    depth = 0
    i = open_idx
    n = len(text)
    while i < n:
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return n - 1


def parse_stylesheet(text, _order_start=0):
    text = _strip_comments(text)
    rules = []
    order = [_order_start]
    _parse_block(text, rules, order)
    return rules


def _parse_block(text, rules, order):
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        if ch == "@":
            # at-rule: find end (either ';' or the matching '}' of a block)
            brace = text.find("{", i)
            semi = text.find(";", i)
            if brace != -1 and (semi == -1 or brace < semi):
                end = _find_matching_brace(text, brace)
                inner = text[brace + 1:end]
                _parse_block(inner, rules, order)
                i = end + 1
            else:
                i = (semi + 1) if semi != -1 else n
            continue
        brace = text.find("{", i)
        if brace == -1:
            break
        selector_text = text[i:brace]
        end = _find_matching_brace(text, brace)
        body = text[brace + 1:end]
        selectors = parse_selector_list(selector_text)
        decls = parse_declarations(body)
        if selectors and decls:
            rules.append(Rule(selectors, decls, order[0]))
        order[0] += 1
        i = end + 1


def parse_declarations(body):
    decls = []
    for chunk in _split_top_level(body, ";"):
        chunk = chunk.strip()
        if not chunk or ":" not in chunk:
            continue
        prop, _, value = chunk.partition(":")
        prop = prop.strip().lower()
        value = value.strip()
        important = False
        m = re.search(r"!\s*important\s*$", value, re.I)
        if m:
            important = True
            value = value[: m.start()].strip()
        if prop and value:
            decls.append(Declaration(prop, value, important))
    return decls


def _split_top_level(text, sep):
    out = []
    depth = 0
    cur = []
    for ch in text:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == sep and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return out


def parse_selector_list(text):
    out = []
    for piece in _split_top_level(text, ","):
        piece = piece.strip()
        if not piece:
            continue
        sel = parse_selector(piece)
        if sel:
            out.append(sel)
    return out


_COMBINATOR_CHARS = {">": Combinator.CHILD, "+": Combinator.ADJACENT, "~": Combinator.SIBLING}
_IDENT = r"-?[A-Za-z_][A-Za-z0-9_-]*"


def _split_selector_parts(text):
    """Splits selector text into tokens (compound selectors and bare
    combinator symbols), tracking ()/[] depth so a `+`/`~` inside
    `:nth-child(2n+1)` or `[attr~=val]` is never mistaken for a sibling
    combinator."""
    parts = []
    buf = []
    depth = 0

    def flush():
        if buf:
            parts.append("".join(buf))
            buf.clear()

    for ch in text:
        if ch in "([":
            depth += 1
            buf.append(ch)
        elif ch in ")]":
            depth -= 1
            buf.append(ch)
        elif depth == 0 and ch in _COMBINATOR_CHARS:
            flush()
            parts.append(ch)
        elif depth == 0 and ch.isspace():
            flush()
        else:
            buf.append(ch)
    flush()
    return parts


def parse_selector(text):
    parts = _split_selector_parts(text)
    compounds = []
    combinators = []  # combinator BEFORE each compound after the first
    pending_combinator = Combinator.DESCENDANT
    for part in parts:
        if part in _COMBINATOR_CHARS:
            pending_combinator = _COMBINATOR_CHARS[part]
            continue
        simple = _parse_compound(part)
        if simple is None:
            continue
        if compounds:
            combinators.append(pending_combinator)
        compounds.append(simple)
        pending_combinator = Combinator.DESCENDANT
    if not compounds:
        return None
    return Selector(compounds, combinators)


_COMPOUND_RE = re.compile(
    r"(?P<type>\*|" + _IDENT + r")?"
    r"(?P<rest>(?:#" + _IDENT + r"|\." + _IDENT +
    r"|\[[^\]]*\]|:{1,2}" + _IDENT + r"(?:\([^)]*\))?)*)$"
)
_REST_TOKEN_RE = re.compile(
    r"#(?P<id>" + _IDENT + r")"
    r"|\.(?P<cls>" + _IDENT + r")"
    r"|\[(?P<attr>[^\]]*)\]"
    r"|:{1,2}(?P<pseudo>" + _IDENT + r")(?:\((?P<arg>[^)]*)\))?"
)


def _parse_compound(part):
    m = _COMPOUND_RE.match(part)
    if not m:
        return None
    type_ = m.group("type")
    simple = SimpleSelector(type_ if type_ and type_ != "*" else None)
    for tm in _REST_TOKEN_RE.finditer(m.group("rest")):
        if tm.group("id"):
            simple.id = tm.group("id")
        elif tm.group("cls"):
            simple.classes.append(tm.group("cls"))
        elif tm.group("attr") is not None:
            simple.attrs.append(_parse_attr_selector(tm.group("attr")))
        elif tm.group("pseudo"):
            simple.pseudos.append((tm.group("pseudo").lower(), tm.group("arg")))
    return simple


def _parse_attr_selector(raw):
    m = re.match(r'([A-Za-z_-][A-Za-z0-9_-]*)\s*(?:([~^$*|]?=)\s*(.+))?$', raw.strip())
    if not m:
        return (raw.strip(), None, None)
    name, op, value = m.group(1), m.group(2), m.group(3)
    if value is not None:
        value = value.strip().strip("'\"")
    return (name.lower(), op, value)
