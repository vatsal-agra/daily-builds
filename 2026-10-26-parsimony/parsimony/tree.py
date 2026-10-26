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

    def __eq__(self, other):
        return isinstance(other, Node) and self.name == other.name and self.children == other.children

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
            if n == ")":
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
        def conv(n):
            if isinstance(n, Token):
                return {"token": n.type, "text": n.text, "line": n.line, "col": n.col}
            return {"rule": n.name, "children": [conv(c) for c in n.children]}
        return conv(self)

    def json(self, indent=2) -> str:
        return json.dumps(self.to_json(), indent=indent)

    def compact(self) -> "Node":
        """Collapse chains of single-child nonterminals (unit productions)."""
        def go(n):
            if isinstance(n, Token):
                return n
            kids = [go(c) for c in n.children]
            if len(kids) == 1 and isinstance(kids[0], Node):
                return kids[0]
            return Node(n.name, kids)
        return go(self)

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
