"""Explain mode: render a pattern's AST as an indented English breakdown."""

from . import parser as P
from .nfa import format_ranges

_ANCHORS = {
    "^": "the start of the string",
    "$": "the end of the string",
    "b": "a word boundary",
    "B": "a position that is not a word boundary",
}

_KNOWN_CLASSES = {
    "\\d": "a digit (0-9)",
    "\\D": "any character that is not a digit",
    "\\w": "a word character (letters, digits, _)",
    "\\W": "any non-word character",
    "\\s": "a whitespace character",
    "\\S": "any non-whitespace character",
}


def _times(lo, hi, lazy):
    how = " (lazy: as few as possible)" if lazy else ""
    if lo == 0 and hi is None:
        return f"zero or more{how} of"
    if lo == 1 and hi is None:
        return f"one or more{how} of"
    if lo == 0 and hi == 1:
        return f"optionally{how}"
    if hi is None:
        return f"{lo} or more{how} of"
    if lo == hi:
        return f"exactly {lo} of"
    return f"between {lo} and {hi}{how} of"


def _leaf(node):
    if isinstance(node, P.Lit):
        ch = node.ch
        if ch.isprintable() and ch != " ":
            return f"the character '{ch}'"
        return f"the character {ch!r}"
    if isinstance(node, P.Dot):
        return "any character except a newline"
    if isinstance(node, P.CharClass):
        if node.label in _KNOWN_CLASSES:
            return _KNOWN_CLASSES[node.label]
        kind = "any character NOT in" if node.negated else "one character of"
        return f"{kind} {format_ranges(node.ranges())}  (from {node.label})"
    if isinstance(node, P.Anchor):
        return "at " + _ANCHORS[node.kind]
    return None


def _lines(node, indent):
    pad = "  " * indent
    leaf = _leaf(node)
    if leaf is not None:
        return [pad + leaf]
    if isinstance(node, P.Concat):
        if not node.parts:
            return [pad + "the empty string"]
        # collapse runs of literal characters into one "the text …" line
        merged = []
        for part in node.parts:
            if isinstance(part, P.Lit) and merged and \
                    isinstance(merged[-1], list):
                merged[-1].append(part.ch)
            elif isinstance(part, P.Lit):
                merged.append([part.ch])
            else:
                merged.append(part)
        if len(merged) == 1 and isinstance(merged[0], list):
            return [pad + f"the text {''.join(merged[0])!r}"]
        out = [pad + "the sequence:"]
        for part in merged:
            if isinstance(part, list):
                text = "".join(part)
                out.append("  " * (indent + 1) + (
                    f"the text {text!r}" if len(part) > 1
                    else _leaf(P.Lit(text))))
            else:
                out += _lines(part, indent + 1)
        return out
    if isinstance(node, P.Alt):
        out = [pad + "any one of:"]
        for i, br in enumerate(node.branches):
            out.append(pad + f"  — branch {i + 1}:")
            out += _lines(br, indent + 2)
        return out
    if isinstance(node, P.Repeat):
        return [pad + _times(node.lo, node.hi, node.lazy) + ":"] + \
            _lines(node.child, indent + 1)
    if isinstance(node, P.Group):
        head = (f"capture group {node.index}, containing:"
                if node.index else "a (non-capturing) group containing:")
        return [pad + head] + _lines(node.child, indent + 1)
    return [pad + repr(node)]


def explain(pattern):
    """Return a plain-English, indented description of `pattern`."""
    ast, ngroups = P.parse(pattern)
    head = f"/{pattern}/ matches:"
    body = _lines(ast, 1)
    tail = []
    if ngroups:
        tail.append(f"(captures {ngroups} group"
                    f"{'s' if ngroups != 1 else ''})")
    return "\n".join([head] + body + tail)
