"""A from-scratch CSS tokenizer + parser producing a plain list of Rule
objects: (selector, declarations, specificity placeholder, source order).

Grammar supported (deliberately a real, useful subset — see PLAN.md's
"Honest scope boundaries"):
  - selectors: `*`, `tag`, `.class`, `#id`, any chain of those (e.g.
    `div.card#main`), combined with descendant (space), child (`>`), and
    adjacent-sibling (`+`) combinators, and comma-separated selector lists.
  - declarations: `property: value;` pairs, with an optional `!important`.
  - comments `/* ... */` anywhere.
"""

import re

_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)


class SimpleSelector:
    """One compound selector step, e.g. `div.card#main` or `*`."""

    __slots__ = ("tag", "id", "classes")

    def __init__(self, tag=None, id=None, classes=None):
        self.tag = tag
        self.id = id
        self.classes = classes or []

    def matches(self, element):
        if self.tag and self.tag != "*" and element.tag != self.tag:
            return False
        if self.id and element.id != self.id:
            return False
        if self.classes:
            el_classes = set(element.classes)
            if not all(c in el_classes for c in self.classes):
                return False
        return True

    def specificity(self):
        a = 1 if self.id else 0
        b = len(self.classes)
        c = 1 if (self.tag and self.tag != "*") else 0
        return (a, b, c)

    def __repr__(self):
        bits = [self.tag or ""]
        if self.id:
            bits.append(f"#{self.id}")
        bits.extend(f".{c}" for c in self.classes)
        return "".join(bits) or "*"


class Selector:
    """A chain of SimpleSelectors joined by combinators.

    Stored rightmost-first: `steps[0]` is the *key* simple selector (the one
    that must match the candidate element itself), and each subsequent step
    is (combinator, simple_selector) describing an ancestor/sibling
    constraint, read left-to-right as you'd write the selector.
    """

    __slots__ = ("steps",)

    def __init__(self, steps):
        # steps: [(combinator_or_None, SimpleSelector), ...] in source order,
        # first entry's combinator is always None.
        self.steps = steps

    def specificity(self):
        a = b = c = 0
        for _, simple in self.steps:
            sa, sb, sc = simple.specificity()
            a += sa
            b += sb
            c += sc
        return (a, b, c)

    def matches(self, element):
        # Walk the chain from the rightmost (last) selector backwards.
        idx = len(self.steps) - 1
        combinator, simple = self.steps[idx]
        if not simple.matches(element):
            return False
        return self._match_ancestors(element, idx - 1)

    def _match_ancestors(self, element, idx):
        if idx < 0:
            return True
        combinator, simple = self.steps[idx + 1]
        _, prev_simple = self.steps[idx]
        if combinator == ">":
            parent = element.parent
            from .dom import Element
            if not isinstance(parent, Element):
                return False
            if not prev_simple.matches(parent):
                return False
            return self._match_ancestors(parent, idx - 1)
        if combinator == "+":
            sibling = _previous_element_sibling(element)
            if sibling is None:
                return False
            if not prev_simple.matches(sibling):
                return False
            return self._match_ancestors(sibling, idx - 1)
        # Descendant combinator (space): search all ancestors.
        from .dom import Element
        node = element.parent
        while isinstance(node, Element):
            if prev_simple.matches(node) and self._match_ancestors(node, idx - 1):
                return True
            node = node.parent
        return False

    def __repr__(self):
        parts = []
        for combinator, simple in self.steps:
            if combinator:
                parts.append(combinator)
            parts.append(repr(simple))
        return " ".join(parts)


def _previous_element_sibling(element):
    from .dom import Element
    parent = element.parent
    if parent is None:
        return None
    siblings = parent.children
    idx = siblings.index(element)
    for i in range(idx - 1, -1, -1):
        if isinstance(siblings[i], Element):
            return siblings[i]
    return None


class Declaration:
    __slots__ = ("prop", "value", "important")

    def __init__(self, prop, value, important=False):
        self.prop = prop
        self.value = value
        self.important = important


class Rule:
    __slots__ = ("selectors", "declarations", "order")

    def __init__(self, selectors, declarations, order):
        self.selectors = selectors  # list[Selector] (comma-separated group)
        self.declarations = declarations
        self.order = order


class Stylesheet:
    def __init__(self, rules=None):
        self.rules = rules or []


_IDENT = r"[a-zA-Z_-][a-zA-Z0-9_-]*"
_SIMPLE_RE = re.compile(
    rf"(?P<star>\*)|(?P<tag>{_IDENT})|\.(?P<class>{_IDENT})|#(?P<id>{_IDENT})"
)


def _parse_simple_selector(text):
    tag = None
    id_ = None
    classes = []
    pos = 0
    while pos < len(text):
        m = _SIMPLE_RE.match(text, pos)
        if not m:
            break
        if m.group("star"):
            tag = "*"
        elif m.group("tag"):
            tag = m.group("tag")
        elif m.group("class"):
            classes.append(m.group("class"))
        elif m.group("id"):
            id_ = m.group("id")
        pos = m.end()
    return SimpleSelector(tag, id_, classes)


def _parse_selector(text):
    text = text.strip()
    # Tokenize on combinators, keeping them.
    tokens = re.split(r"\s*(>|\+)\s*|\s+", text)
    tokens = [t for t in tokens if t]
    steps = []
    pending_combinator = None
    for tok in tokens:
        if tok in (">", "+"):
            pending_combinator = tok
            continue
        simple = _parse_simple_selector(tok)
        steps.append((pending_combinator if steps else None, simple))
        pending_combinator = None
    return Selector(steps)


def parse_css(css_text):
    """Parse a CSS stylesheet string into a Stylesheet of Rules."""
    css_text = _COMMENT_RE.sub("", css_text)
    rules = []
    pos = 0
    n = len(css_text)
    order = 0
    while pos < n:
        brace = css_text.find("{", pos)
        if brace == -1:
            break
        selector_text = css_text[pos:brace]
        close = css_text.find("}", brace)
        if close == -1:
            body = css_text[brace + 1:]
            pos = n
        else:
            body = css_text[brace + 1:close]
            pos = close + 1

        selector_groups = [s.strip() for s in selector_text.split(",")]
        selectors = [_parse_selector(s) for s in selector_groups if s.strip()]
        if not selectors:
            continue

        declarations = _parse_declarations(body)
        if declarations:
            rules.append(Rule(selectors, declarations, order))
            order += 1
    return Stylesheet(rules)


def _parse_declarations(body):
    declarations = []
    for chunk in body.split(";"):
        chunk = chunk.strip()
        if not chunk or ":" not in chunk:
            continue
        prop, _, value = chunk.partition(":")
        prop = prop.strip().lower()
        value = value.strip()
        important = False
        if re.search(r"!\s*important\s*$", value):
            value = re.sub(r"!\s*important\s*$", "", value).strip()
            important = True
        if prop and value:
            declarations.append(Declaration(prop, value, important))
    return declarations


def parse_inline_style(style_attr):
    """Parse the contents of a `style="..."` attribute into Declarations."""
    return _parse_declarations(style_attr or "")
