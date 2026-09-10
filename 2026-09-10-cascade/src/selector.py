"""Selector data model, matching against the DOM, and specificity."""

import re

from dom import Element


class Combinator:
    DESCENDANT = "descendant"  # 'A B'
    CHILD = "child"            # 'A > B'
    ADJACENT = "adjacent"      # 'A + B'
    SIBLING = "sibling"        # 'A ~ B'


class SimpleSelector:
    def __init__(self, type_=None):
        self.type = type_  # tag name, or None for universal
        self.id = None
        self.classes = []
        self.attrs = []     # list of (name, op, value)
        self.pseudos = []   # list of (name, arg)

    def __repr__(self):
        bits = [self.type or "*"]
        if self.id:
            bits.append(f"#{self.id}")
        bits += [f".{c}" for c in self.classes]
        for name, op, val in self.attrs:
            bits.append(f"[{name}{op or ''}{val or ''}]")
        for name, arg in self.pseudos:
            bits.append(f":{name}" + (f"({arg})" if arg else ""))
        return "".join(bits)


class Selector:
    def __init__(self, compounds, combinators):
        self.compounds = compounds          # list[SimpleSelector], left..right (subject last)
        self.combinators = combinators      # combinator BEFORE compounds[i], for i>=1

    def __repr__(self):
        out = [repr(self.compounds[0])]
        for comb, comp in zip(self.combinators, self.compounds[1:]):
            sym = {"descendant": " ", "child": " > ", "adjacent": " + ", "sibling": " ~ "}[comb]
            out.append(sym + repr(comp))
        return "".join(out)

    def specificity(self):
        a = b = c = 0
        for comp in self.compounds:
            if comp.id:
                a += 1
            b += len(comp.classes) + len(comp.attrs) + len(comp.pseudos)
            if comp.type:
                c += 1
        return (a, b, c)

    def matches(self, el):
        idx = len(self.compounds) - 1
        if not _simple_matches(self.compounds[idx], el):
            return False
        node = el
        idx -= 1
        while idx >= 0:
            comb = self.combinators[idx]
            comp = self.compounds[idx]
            if comb == Combinator.DESCENDANT:
                anc = node.parent
                found = None
                while isinstance(anc, Element):
                    if _simple_matches(comp, anc):
                        found = anc
                        break
                    anc = anc.parent
                if found is None:
                    return False
                node = found
            elif comb == Combinator.CHILD:
                anc = node.parent
                if not isinstance(anc, Element) or not _simple_matches(comp, anc):
                    return False
                node = anc
            elif comb == Combinator.ADJACENT:
                prev = node.prev_sibling_element
                if prev is None or not _simple_matches(comp, prev):
                    return False
                node = prev
            elif comb == Combinator.SIBLING:
                prev = node.prev_sibling_element
                found = None
                while prev is not None:
                    if _simple_matches(comp, prev):
                        found = prev
                        break
                    prev = prev.prev_sibling_element
                if found is None:
                    return False
                node = found
            idx -= 1
        return True


def _attr_op_matches(op, actual, expected):
    if op is None or op == "=":
        return op is None or actual == expected
    if op == "~=":
        return expected in actual.split()
    if op == "^=":
        return actual.startswith(expected)
    if op == "$=":
        return actual.endswith(expected)
    if op == "*=":
        return expected in actual
    if op == "|=":
        return actual == expected or actual.startswith(expected + "-")
    return False


def _simple_matches(simple, el):
    if not isinstance(el, Element):
        return False
    if simple.type and el.tag != simple.type:
        return False
    if simple.id and el.id != simple.id:
        return False
    el_classes = el.classes
    for c in simple.classes:
        if c not in el_classes:
            return False
    for name, op, value in simple.attrs:
        if name not in el.attrs:
            return False
        if not _attr_op_matches(op, el.attrs[name], value):
            return False
    for name, arg in simple.pseudos:
        if not _match_pseudo(name, arg, el):
            return False
    return True


_NTH_RE = re.compile(r"^\s*([+-]?\d*)n\s*([+-]\s*\d+)?\s*$|^\s*([+-]?\d+)\s*$")


def _match_nth(arg, index_1based):
    if arg is None:
        return False
    arg = arg.strip().lower()
    if arg == "odd":
        a, b = 2, 1
    elif arg == "even":
        a, b = 2, 0
    else:
        m = _NTH_RE.match(arg)
        if not m:
            return False
        if m.group(3) is not None:
            a, b = 0, int(m.group(3))
        else:
            coef = m.group(1)
            if coef in ("", "+"):
                a = 1
            elif coef == "-":
                a = -1
            else:
                a = int(coef)
            off = m.group(2)
            b = int(off.replace(" ", "")) if off else 0
    if a == 0:
        return index_1based == b
    k = (index_1based - b)
    return k % a == 0 and k // a >= 0


def _match_pseudo(name, arg, el):
    if name == "first-child":
        return el.prev_sibling_element is None
    if name == "last-child":
        return el.next_sibling_element is None
    if name == "only-child":
        return el.prev_sibling_element is None and el.next_sibling_element is None
    if name == "root":
        return el.tag == "html"
    if name == "empty":
        return len(el.children) == 0
    if name == "nth-child":
        siblings = el.parent.element_children() if el.parent else [el]
        index = siblings.index(el) + 1 if el in siblings else 1
        return _match_nth(arg, index)
    if name in ("hover", "focus", "active", "visited", "target", "checked"):
        return False
    if name == "link":
        return el.tag == "a" and "href" in el.attrs
    return False
