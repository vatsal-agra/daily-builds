"""Parse trees and their renderings."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import List, Union

from .lexer import Token


@dataclass
class Node:
    name: str
    children: List[Union["Node", Token]] = field(default_factory=list)

    def __repr__(self):
        return f"Node({self.name!r}, <{len(self.children)} children>)"

    def __eq__(self, other):
        if not isinstance(other, Node):
            return NotImplemented
        stack = [(self, other)]
        while stack:
            a, b = stack.pop()
            if isinstance(a, Token) or isinstance(b, Token):
                if not (isinstance(a, Token) and isinstance(b, Token)) or (a.type, a.text) != (b.type, b.text):
                    return False
            elif a.name != b.name or len(a.children) != len(b.children):
                return False
            else:
                stack.extend(zip(a.children, b.children))
        return True

    __hash__ = None

    def leaves(self):
        stack = [self]
        while stack:
            n = stack.pop()
            if isinstance(n, Token):
                yield n
            else:
                stack.extend(reversed(n.children))

    def text(self) -> str:
        return " ".join(t.text for t in self.leaves())

    # -- renderings -------------------------------------------------------
    def sexp(self) -> str:
        out, stack = [], [self]
        while stack:
            n = stack.pop()
            if isinstance(n, str):
                out.append(")")
            elif isinstance(n, Token):
                out.append(_atom(n))
            elif not n.children:
                out.append(f"({n.name})")
            else:
                out.append(f"({n.name}")
                stack.append(")")
                stack.extend(reversed(n.children))
        return " ".join(out).replace(" )", ")")

    def pretty(self) -> str:
        lines: List[str] = []
        stack = [(self, "", "", True)]
        while stack:
            n, prefix, lead, last = stack.pop()
            label = _leaf_label(n) if isinstance(n, Token) else n.name + ("  ε" if not n.children else "")
            lines.append(prefix + lead + label)
            if isinstance(n, Node):
                cp = prefix + ("" if lead == "" else ("    " if last else "│   "))
                kids = n.children
                for i in range(len(kids) - 1, -1, -1):
                    is_last = i == len(kids) - 1
                    stack.append((kids[i], cp, "└── " if is_last else "├── ", is_last))
        return "\n".join(lines)

    def to_json(self):
        root = {}
        stack = [(self, root)]
        while stack:
            n, slot = stack.pop()
            if isinstance(n, Token):
                slot.update(token=n.type, text=n.text, line=n.line, col=n.col)
            else:
                slot["rule"] = n.name
                slot["children"] = [{} for _ in n.children]
                stack.extend(zip(n.children, slot["children"]))
        return root

    def json(self, indent=2) -> str:
        from .util import run_deep
        if indent and self.count() > 2000:   # indentation of deep left-nested trees is quadratic
            indent = None
        return run_deep(lambda: json.dumps(self.to_json(), indent=indent))

    def compact(self) -> "Node":
        """Collapse chains of single-child nonterminals (unit productions)."""
        def collapse(n):
            while isinstance(n, Node) and len(n.children) == 1 and isinstance(n.children[0], Node):
                n = n.children[0]
            return n
        root = collapse(self)
        out = Node(root.name, [])
        stack = [(root, out)]
        while stack:
            src, dst = stack.pop()
            for c in src.children:
                if isinstance(c, Token):
                    dst.children.append(c)
                else:
                    c = collapse(c)
                    nn = Node(c.name, [])
                    dst.children.append(nn); stack.append((c, nn))
        return out

    def count(self) -> int:
        return sum(1 for _ in self._walk())

    def _walk(self):
        stack = [self]
        while stack:
            n = stack.pop()
            yield n
            if isinstance(n, Node):
                stack.extend(n.children)


def _atom(t: Token) -> str:
    return t.text if t.type.startswith("'") else f"{t.type}:{t.text}"


def _leaf_label(t: Token) -> str:
    return t.type if t.type.startswith("'") else f'{t.type} "{t.text}"'


def flatten_children(kids: list, hidden: set) -> list:
    """Splice the children of hidden (EBNF helper) nodes into the parent, iteratively."""
    if not any(isinstance(k, Node) and k.name in hidden for k in kids):
        return kids
    out, stack = [], list(reversed(kids))
    while stack:
        k = stack.pop()
        if isinstance(k, Node) and k.name in hidden:
            stack.extend(reversed(k.children))
        else:
            out.append(k)
    return out
