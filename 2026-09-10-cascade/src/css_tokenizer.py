"""A CSS tokenizer covering the subset of CSS syntax this engine supports:
idents, hashes (#id / hex colors), strings, numbers/dimensions/percentages,
the structural punctuation, and combinators, with comments stripped."""

import re

_TOKEN_SPEC = [
    ("WS", r"[ \t\r\n\f]+"),
    ("COMMENT", r"/\*.*?\*/"),
    ("STRING", r'"(?:[^"\\]|\\.)*"' + r"|'(?:[^'\\]|\\.)*'"),
    ("HASH", r"#[A-Za-z0-9_-]+"),
    ("DIMENSION", r"[+-]?(?:\d*\.\d+|\d+)(?:[A-Za-z%]+)"),
    ("NUMBER", r"[+-]?(?:\d*\.\d+|\d+)"),
    ("IDENT", r"-?[A-Za-z_][A-Za-z0-9_-]*"),
    ("ATKEYWORD", r"@[A-Za-z-]+"),
    ("PUNCT", r"[{}();:,>+~\[\].*=~^$|!]"),
    ("OTHER", r"."),
]
_MASTER_RE = re.compile("|".join(f"(?P<{n}>{p})" for n, p in _TOKEN_SPEC), re.S)


class CSSToken:
    __slots__ = ("kind", "value")

    def __init__(self, kind, value):
        self.kind = kind
        self.value = value

    def __repr__(self):
        return f"{self.kind}({self.value!r})"


def tokenize_css(text):
    tokens = []
    for m in _MASTER_RE.finditer(text):
        kind = m.lastgroup
        val = m.group()
        if kind in ("WS", "COMMENT"):
            continue
        if kind == "DIMENSION":
            num_m = re.match(r"[+-]?(?:\d*\.\d+|\d+)", val)
            tokens.append(CSSToken("DIMENSION", (float(num_m.group()), val[num_m.end():])))
            continue
        if kind == "NUMBER":
            tokens.append(CSSToken("NUMBER", float(val)))
            continue
        if kind == "STRING":
            tokens.append(CSSToken("STRING", val[1:-1]))
            continue
        tokens.append(CSSToken(kind, val))
    return tokens
