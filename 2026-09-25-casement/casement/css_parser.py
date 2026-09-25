"""A from-scratch CSS tokenizer, selector parser, and cascade engine.

Supported selector grammar: type selectors, `*`, `.class`, `#id`,
`:first-child` / `:last-child`, compound selectors combining several of
those on one element (e.g. `div.card#hero`), and combinators ` ` (descendant)
and `>` (direct child), with comma-separated selector groups.

Unsupported at-rules (e.g. `@media`) are skipped as opaque blocks rather
than crashing the parser, so a stylesheet using them still applies its
other rules.
"""

import re

from .selector import Selector, SimpleSelector


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
        self.order = order


class Stylesheet:
    def __init__(self, rules):
        self.rules = rules


def _strip_comments(text):
    return re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)


def parse_stylesheet(text):
    text = _strip_comments(text)
    rules = []
    i = 0
    n = len(text)
    order = 0
    while i < n:
        if text[i].isspace():
            i += 1
            continue
        if text[i] == "@":
            # skip an at-rule: either "...;" or "...{ ... }" (one nesting level
            # of braces is enough for @media/@font-face/@keyframes bodies).
            depth = 0
            j = i
            while j < n:
                if text[j] == "{":
                    depth += 1
                elif text[j] == "}":
                    depth -= 1
                    if depth == 0:
                        j += 1
                        break
                elif text[j] == ";" and depth == 0:
                    j += 1
                    break
                j += 1
            i = j
            continue
        brace = text.find("{", i)
        if brace == -1:
            break
        selector_text = text[i:brace].strip()
        close = _find_matching_brace(text, brace)
        body = text[brace + 1:close]
        selectors = [parse_selector(s.strip()) for s in _split_top(selector_text, ",") if s.strip()]
        decls = parse_declarations(body)
        if selectors and decls:
            rules.append(Rule(selectors, decls, order))
            order += 1
        i = close + 1
    return Stylesheet(rules)


def _find_matching_brace(text, open_pos):
    depth = 0
    for j in range(open_pos, len(text)):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return j
    return len(text)


def _split_top(text, sep):
    """Split text on `sep` at depth 0 (ignoring parens)."""
    parts = []
    depth = 0
    start = 0
    for i, c in enumerate(text):
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif c == sep and depth == 0:
            parts.append(text[start:i])
            start = i + 1
    parts.append(text[start:])
    return parts


def parse_declarations(body):
    decls = []
    for chunk in _split_top(body, ";"):
        chunk = chunk.strip()
        if not chunk or ":" not in chunk:
            continue
        prop, _, value = chunk.partition(":")
        prop = prop.strip().lower()
        value = value.strip()
        important = False
        if re.search(r"!\s*important\s*$", value, flags=re.IGNORECASE):
            important = True
            value = re.sub(r"!\s*important\s*$", "", value, flags=re.IGNORECASE).strip()
        if prop and value:
            decls.append(Declaration(prop, value, important))
    return decls


_TOKEN_RE = re.compile(r"\s*(>|\*|#[\w-]+|\.[\w-]+|:[\w-]+|[A-Za-z][\w-]*|\s+)")


def parse_selector(text):
    """Parse one selector (no commas) into a Selector: a list of
    (combinator, SimpleSelector) steps, rightmost (subject) last."""
    text = text.strip()
    # tokenize into compound-selector chunks separated by combinators
    steps = []
    combinator = None
    i = 0
    n = len(text)
    cur = SimpleSelector()
    have_cur = False
    while i < n:
        c = text[i]
        if c.isspace():
            j = i
            while j < n and text[j].isspace():
                j += 1
            if j < n and text[j] == ">":
                i = j
                continue
            if have_cur:
                steps.append((combinator, cur))
                combinator = "descendant"
                cur = SimpleSelector()
                have_cur = False
            i = j
            continue
        if c == ">":
            if have_cur:
                steps.append((combinator, cur))
                cur = SimpleSelector()
                have_cur = False
            combinator = "child"
            i += 1
            continue
        if c == "*":
            cur.type = "*"
            have_cur = True
            i += 1
            continue
        if c == "#":
            m = re.match(r"#([\w-]+)", text[i:])
            cur.id = m.group(1)
            have_cur = True
            i += m.end()
            continue
        if c == ".":
            m = re.match(r"\.([\w-]+)", text[i:])
            cur.classes.append(m.group(1))
            have_cur = True
            i += m.end()
            continue
        if c == ":":
            m = re.match(r":([\w-]+)", text[i:])
            cur.pseudo.append(m.group(1))
            have_cur = True
            i += m.end()
            continue
        m = re.match(r"[A-Za-z][\w-]*", text[i:])
        if m:
            cur.type = m.group(0).lower()
            have_cur = True
            i += m.end()
            continue
        i += 1
    if have_cur:
        steps.append((combinator, cur))
    return Selector(steps)
