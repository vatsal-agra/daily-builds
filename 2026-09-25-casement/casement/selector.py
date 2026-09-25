"""Selector matching + specificity, per the CSS2.1 specificity rules."""

from .dom import Element


class SimpleSelector:
    __slots__ = ("type", "id", "classes", "pseudo")

    def __init__(self):
        self.type = None  # None or "*" both mean "any type"
        self.id = None
        self.classes = []
        self.pseudo = []

    def matches(self, el):
        if not isinstance(el, Element):
            return False
        if self.type and self.type != "*" and el.tag != self.type:
            return False
        if self.id and el.id != self.id:
            return False
        el_classes = set(el.classes)
        for c in self.classes:
            if c not in el_classes:
                return False
        for p in self.pseudo:
            if not _matches_pseudo(el, p):
                return False
        return True

    def specificity(self):
        a = 1 if self.id else 0
        b = len(self.classes) + len(self.pseudo)
        c = 1 if (self.type and self.type != "*") else 0
        return (a, b, c)


def _matches_pseudo(el, pseudo):
    if el.parent is None:
        return False
    siblings = el.parent.element_children()
    if pseudo == "first-child":
        return bool(siblings) and siblings[0] is el
    if pseudo == "last-child":
        return bool(siblings) and siblings[-1] is el
    return False


class Selector:
    """A compound selector chain: [(combinator, SimpleSelector), ...],
    where the first entry's combinator is always None and the last entry
    is the "subject" (the element the whole selector matches)."""

    def __init__(self, steps):
        self.steps = steps

    def specificity(self):
        a = b = c = 0
        for _, simple in self.steps:
            sa, sb, sc = simple.specificity()
            a += sa
            b += sb
            c += sc
        return (a, b, c)

    def matches(self, el):
        if not self.steps:
            return False
        if not self.steps[-1][1].matches(el):
            return False
        current = el
        for i in range(len(self.steps) - 2, -1, -1):
            combinator = self.steps[i + 1][0]
            simple = self.steps[i][1]
            if combinator == "child":
                parent = current.parent
                if not isinstance(parent, Element) or not simple.matches(parent):
                    return False
                current = parent
            else:  # "descendant"
                node = current.parent
                found = None
                while isinstance(node, Element):
                    if simple.matches(node):
                        found = node
                        break
                    node = node.parent
                if found is None:
                    return False
                current = found
        return True
