"""A from-scratch CSS parser: real selector grammar (type/class/id,
descendant ` ` and child `>` combinators, comma-separated groups) and
declaration parsing into a CSSOM of `Rule` objects, each carrying its own
source order (needed later for cascade tie-breaking).

Unsupported top-level constructs (`@media`, `@font-face`, ...) are skipped
by brace-balance rather than crashing the parser, since a real stylesheet
may contain them even though this engine's cascade doesn't act on them.
"""

import re


class Compound:
    __slots__ = ('type_name', 'id', 'classes')

    def __init__(self, type_name=None, id=None, classes=None):
        self.type_name = type_name
        self.id = id
        self.classes = classes or set()

    def __repr__(self):
        return f'Compound(type={self.type_name!r}, id={self.id!r}, classes={self.classes!r})'


class Rule:
    __slots__ = ('selectors', 'declarations', 'order')

    def __init__(self, selectors, declarations, order):
        self.selectors = selectors  # list of "steps": [(combinator, Compound), ...]
        self.declarations = declarations  # dict prop -> (value, important)
        self.order = order


class Stylesheet:
    def __init__(self, rules=None):
        self.rules = rules or []

    def extend(self, other):
        base = len(self.rules)
        for rule in other.rules:
            rule.order += base
            self.rules.append(rule)


def _strip_comments(text):
    out = []
    i = 0
    n = len(text)
    while i < n:
        if text.startswith('/*', i):
            end = text.find('*/', i + 2)
            i = n if end == -1 else end + 2
        else:
            out.append(text[i])
            i += 1
    return ''.join(out)


def _parse_compound(token):
    comp = Compound()
    i = 0
    n = len(token)
    if i < n and (token[i].isalpha() or token[i] == '*'):
        start = i
        while i < n and token[i] not in '.#':
            i += 1
        name = token[start:i]
        comp.type_name = None if name == '*' else name.lower()
    while i < n:
        if token[i] == '.':
            i += 1
            start = i
            while i < n and token[i] not in '.#':
                i += 1
            comp.classes.add(token[start:i])
        elif token[i] == '#':
            i += 1
            start = i
            while i < n and token[i] not in '.#':
                i += 1
            comp.id = token[start:i]
        else:
            i += 1
    return comp


def _parse_selector(sel_str):
    sel_str = sel_str.replace('>', ' > ')
    parts = [p for p in sel_str.split() if p]
    steps = []
    combinator = None
    for part in parts:
        if part == '>':
            combinator = '>'
            continue
        steps.append((combinator, _parse_compound(part)))
        combinator = ' '
    return steps


def _parse_selector_group(text):
    return [_parse_selector(s.strip()) for s in text.split(',') if s.strip()]


def _parse_declarations(text):
    decls = {}
    for chunk in text.split(';'):
        chunk = chunk.strip()
        if not chunk or ':' not in chunk:
            continue
        prop, _, value = chunk.partition(':')
        prop = prop.strip().lower()
        value = value.strip()
        important = False
        stripped = re.sub(r'!\s*important\s*$', '', value, flags=re.IGNORECASE)
        if stripped != value:
            important = True
            value = stripped.strip()
        if prop:
            decls[prop] = (value, important)
    return decls


def specificity(steps):
    """(id-count, class-count, type-count) per the CSS spec's tie-break order."""
    a = b = c = 0
    for _combinator, compound in steps:
        if compound.id:
            a += 1
        b += len(compound.classes)
        if compound.type_name:
            c += 1
    return (a, b, c)


def parse_stylesheet(css_text):
    text = _strip_comments(css_text)
    rules = []
    i = 0
    n = len(text)
    order = 0
    while i < n:
        while i < n and text[i].isspace():
            i += 1
        if i >= n:
            break
        if text[i] == '@':
            brace = text.find('{', i)
            semi = text.find(';', i)
            if brace != -1 and (semi == -1 or brace < semi):
                depth = 0
                j = brace
                while j < n:
                    if text[j] == '{':
                        depth += 1
                    elif text[j] == '}':
                        depth -= 1
                        if depth == 0:
                            j += 1
                            break
                    j += 1
                i = j
            else:
                i = (semi + 1) if semi != -1 else n
            continue
        brace = text.find('{', i)
        if brace == -1:
            break
        selector_text = text[i:brace]
        close = text.find('}', brace)
        if close == -1:
            decl_text = text[brace + 1:]
            i = n
        else:
            decl_text = text[brace + 1:close]
            i = close + 1
        selectors = _parse_selector_group(selector_text)
        if not selectors:
            continue
        declarations = _parse_declarations(decl_text)
        rules.append(Rule(selectors, declarations, order))
        order += 1
    return Stylesheet(rules)
