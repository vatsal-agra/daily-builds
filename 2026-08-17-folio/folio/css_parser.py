"""A CSS parser, built from scratch.

Scoped to CSS2.1's rule grammar (selector-list { declaration-list }) plus
the handful of selector forms and value types Folio's layout engine
consumes. Rather than a full CSS Syntax Module tokenizer, this is a careful
depth-aware scanner: it never splits inside a quoted string or inside
parens/brackets/braces, which is exactly the part a naive `.split(",")`
gets wrong (`font-family: "Helvetica, Neue"` or `color: rgb(1,2,3)`).
"""

import re


class Declaration:
    __slots__ = ("prop", "value", "important")

    def __init__(self, prop, value, important):
        self.prop = prop
        self.value = value
        self.important = important


class SimpleSelector:
    """One compound selector: `div.foo#bar[data-x=y]:first-child`."""

    __slots__ = ("tag", "id", "classes", "attrs", "pseudo")

    def __init__(self):
        self.tag = None  # None means "*" (any tag)
        self.id = None
        self.classes = []
        self.attrs = []  # list of (name, op, value) op in ('', '=', '~=')
        self.pseudo = []  # list of pseudo-class names, e.g. 'first-child'

    def specificity(self):
        b = 1 if self.id else 0
        c = len(self.classes) + len(self.attrs) + len(self.pseudo)
        d = 1 if self.tag else 0
        return (b, c, d)


class Selector:
    """A full selector: a chain of SimpleSelectors joined by combinators.
    `compounds` is ordered left-to-right as written; `combinators[i]` is the
    combinator BETWEEN compounds[i] and compounds[i+1] (' ' or '>')."""

    __slots__ = ("compounds", "combinators", "source_text")

    def __init__(self, compounds, combinators, source_text=""):
        self.compounds = compounds
        self.combinators = combinators
        self.source_text = source_text

    def specificity(self):
        b = c = d = 0
        for comp in self.compounds:
            sb, sc, sd = comp.specificity()
            b += sb
            c += sc
            d += sd
        return (b, c, d)


class Rule:
    __slots__ = ("selectors", "declarations", "source_order")

    def __init__(self, selectors, declarations, source_order):
        self.selectors = selectors
        self.declarations = declarations
        self.source_order = source_order


class Stylesheet:
    __slots__ = ("rules",)

    def __init__(self, rules):
        self.rules = rules


def _strip_comments(text):
    out = []
    i = 0
    n = len(text)
    while i < n:
        if text[i : i + 2] == "/*":
            end = text.find("*/", i + 2)
            i = (end + 2) if end != -1 else n
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def _split_top_level(text, seps):
    """Split `text` on any char in `seps` at nesting-depth 0 (not inside
    (), [], {}, or quotes). Returns the parts, seps excluded."""
    parts = []
    depth = 0
    buf = []
    quote = None
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if quote:
            buf.append(ch)
            if ch == quote and (i == 0 or text[i - 1] != "\\"):
                quote = None
            i += 1
            continue
        if ch in "\"'":
            quote = ch
            buf.append(ch)
        elif ch in "([{":
            depth += 1
            buf.append(ch)
        elif ch in ")]}":
            depth = max(0, depth - 1)
            buf.append(ch)
        elif depth == 0 and ch in seps:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    parts.append("".join(buf))
    return parts


_ATTR_RE = re.compile(
    r"""\[\s*([-\w]+)\s*(?:([~^$*|]?=)\s*(?:"([^"]*)"|'([^']*)'|([-\w]+)))?\s*\]"""
)


def parse_selector(text):
    text = text.strip()
    combinators = []
    compound_texts = []
    # tokenize combinators: '>' becomes its own combinator; runs of
    # whitespace between compounds become the descendant combinator.
    buf = ""
    i = 0
    n = len(text)
    pending_ws = False
    bracket_depth = 0
    quote = None
    while i < n:
        ch = text[i]
        if quote:
            buf += ch
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "\"'":
            quote = ch
            buf += ch
            i += 1
            continue
        if ch == "[":
            bracket_depth += 1
            buf += ch
            i += 1
            continue
        if ch == "]":
            bracket_depth = max(0, bracket_depth - 1)
            buf += ch
            i += 1
            continue
        if bracket_depth > 0:
            buf += ch
            i += 1
            continue
        if ch == ">":
            compound_texts.append(buf.strip())
            combinators.append(">")
            buf = ""
            pending_ws = False
            i += 1
        elif ch in " \t\n":
            if buf.strip():
                pending_ws = True
            i += 1
        else:
            if pending_ws:
                compound_texts.append(buf.strip())
                combinators.append(" ")
                buf = ""
                pending_ws = False
            buf += ch
            i += 1
    if buf.strip():
        compound_texts.append(buf.strip())

    compounds = []
    for ctext in compound_texts:
        comp = SimpleSelector()
        rest = ctext
        # tag name / universal, must come first if present
        m = re.match(r"^[A-Za-z][-\w]*", rest)
        if m:
            comp.tag = m.group(0).lower()
            rest = rest[m.end() :]
        elif rest.startswith("*"):
            rest = rest[1:]

        while rest:
            if rest.startswith("."):
                m = re.match(r"\.([-\w]+)", rest)
                if not m:
                    break
                comp.classes.append(m.group(1))
                rest = rest[m.end() :]
            elif rest.startswith("#"):
                m = re.match(r"#([-\w]+)", rest)
                if not m:
                    break
                comp.id = m.group(1)
                rest = rest[m.end() :]
            elif rest.startswith("["):
                m = _ATTR_RE.match(rest)
                if not m:
                    break
                name = m.group(1).lower()
                op = m.group(2) or ""
                val = m.group(3)
                if val is None:
                    val = m.group(4)
                if val is None:
                    val = m.group(5)
                comp.attrs.append((name, op, val))
                rest = rest[m.end() :]
            elif rest.startswith(":"):
                m = re.match(r":([-\w]+)", rest)
                if not m:
                    break
                comp.pseudo.append(m.group(1))
                rest = rest[m.end() :]
            else:
                break
        compounds.append(comp)
    return Selector(compounds, combinators, source_text=text)


def parse_declarations(text):
    decls = []
    for chunk in _split_top_level(text, ";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        if ":" not in chunk:
            continue
        prop, _, value = chunk.partition(":")
        prop = prop.strip().lower()
        value = value.strip()
        important = False
        m = re.search(r"!\s*important\s*$", value, re.IGNORECASE)
        if m:
            important = True
            value = value[: m.start()].strip()
        if prop and value:
            decls.append(Declaration(prop, value, important))
    return decls


def parse_stylesheet(text):
    text = _strip_comments(text)
    # Drop @-rules we don't support (e.g. @media, @import, @font-face) by
    # skipping a leading '@word' up to its matching top-level '{...}' or ';'.
    text = _strip_at_rules(text)
    rules = []
    order = 0
    i = 0
    n = len(text)
    while i < n:
        brace = _find_top_level(text, "{", i)
        if brace == -1:
            break
        selector_text = text[i:brace]
        end = _find_top_level(text, "}", brace + 1)
        if end == -1:
            end = n
        body = text[brace + 1 : end]
        selectors = [
            parse_selector(s) for s in _split_top_level(selector_text, ",") if s.strip()
        ]
        declarations = parse_declarations(body)
        if selectors and declarations:
            rules.append(Rule(selectors, declarations, order))
            order += 1
        i = end + 1
    return Stylesheet(rules)


def _find_top_level(text, ch, start):
    depth = 0
    quote = None
    i = start
    n = len(text)
    while i < n:
        c = text[i]
        if quote:
            if c == quote and text[i - 1] != "\\":
                quote = None
            i += 1
            continue
        if c in "\"'":
            quote = c
        elif c in "([":
            depth += 1
        elif c in ")]":
            depth = max(0, depth - 1)
        elif depth == 0 and c == ch:
            return i
        i += 1
    return -1


def _find_matching_brace(text, open_pos):
    """`text[open_pos]` must be '{'. Returns the index of its matching '}',
    tracking brace nesting (and quotes) so a nested rule block's own braces
    don't get mistaken for the outer one -- exactly what @media's
    `{ selector { decls } }` shape needs and a depth-0-only scan gets wrong."""
    depth = 0
    quote = None
    i = open_pos
    n = len(text)
    while i < n:
        c = text[i]
        if quote:
            if c == quote:
                quote = None
        elif c in "\"'":
            quote = c
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _strip_at_rules(text):
    out = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] == "@":
            brace = _find_top_level(text, "{", i)
            semi = text.find(";", i)
            if brace != -1 and (semi == -1 or brace < semi):
                end = _find_matching_brace(text, brace)
                i = (end + 1) if end != -1 else n
            elif semi != -1:
                i = semi + 1
            else:
                i = n
        else:
            out.append(text[i])
            i += 1
    return "".join(out)
