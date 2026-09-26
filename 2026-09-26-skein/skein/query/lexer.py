"""Tokenizer for SkeinQL, a small Cypher-inspired query language."""
import re
from dataclasses import dataclass
from typing import Any


class LexError(Exception):
    pass


@dataclass
class Token:
    kind: str
    value: Any
    pos: int


KEYWORDS = {
    "MATCH", "WHERE", "RETURN", "CREATE", "SET", "DELETE", "DETACH",
    "ORDER", "BY", "LIMIT", "AND", "OR", "NOT", "AS", "TRUE", "FALSE",
    "NULL", "ASC", "DESC",
}

_TOKEN_SPEC = [
    ("WS", r"[ \t\r\n]+"),
    ("NUMBER", r"\d+\.\d+|\d+"),
    ("STRING", r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\""),
    ("ARROW_R", r"->"),
    ("ARROW_L", r"<-"),
    ("NEQ", r"<>"),
    ("LTE", r"<="),
    ("GTE", r">="),
    ("IDENT", r"[A-Za-z_][A-Za-z0-9_]*"),
    ("PUNCT", r"[(){}\[\]:,.=<>+\-*/|]"),
]

_MASTER_RE = re.compile("|".join(f"(?P<{name}>{pattern})" for name, pattern in _TOKEN_SPEC))

_ESCAPES = {"\\'": "'", '\\"': '"', "\\\\": "\\", "\\n": "\n", "\\t": "\t"}


def _unescape(raw: str) -> str:
    return re.sub(r"\\.", lambda m: _ESCAPES.get(m.group(), m.group()[1:]), raw)


def tokenize(text: str):
    tokens = []
    pos = 0
    n = len(text)
    while pos < n:
        m = _MASTER_RE.match(text, pos)
        if not m:
            raise LexError(f"unexpected character {text[pos]!r} at position {pos}")
        kind = m.lastgroup
        raw = m.group()
        start = m.start()
        pos = m.end()
        if kind == "WS":
            continue
        if kind == "IDENT" and raw.upper() in KEYWORDS:
            tokens.append(Token(raw.upper(), raw, start))
        elif kind == "NUMBER":
            value = float(raw) if "." in raw else int(raw)
            tokens.append(Token("NUMBER", value, start))
        elif kind == "STRING":
            tokens.append(Token("STRING", _unescape(raw[1:-1]), start))
        elif kind == "PUNCT":
            tokens.append(Token(raw, raw, start))
        else:
            tokens.append(Token(kind, raw, start))
    tokens.append(Token("EOF", None, n))
    return tokens
