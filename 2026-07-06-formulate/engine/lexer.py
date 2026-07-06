"""Tokenizer for the Formulate formula language."""

import re


class LexError(Exception):
    def __init__(self, message, pos):
        super().__init__(message)
        self.message = message
        self.pos = pos


# Token kinds
NUMBER = "NUMBER"
STRING = "STRING"
BOOL = "BOOL"
REF = "REF"          # A1, $A1, A$1, $A$1
NAME = "NAME"         # function name / bare identifier
LPAREN = "LPAREN"
RPAREN = "RPAREN"
COMMA = "COMMA"
COLON = "COLON"
BANG = "BANG"         # Sheet1!A1
PLUS = "PLUS"
MINUS = "MINUS"
STAR = "STAR"
SLASH = "SLASH"
CARET = "CARET"
PERCENT = "PERCENT"
AMP = "AMP"
EQ = "EQ"
NE = "NE"
LT = "LT"
LE = "LE"
GT = "GT"
GE = "GE"
EOF = "EOF"

_REF_RE = re.compile(r"\$?[A-Za-z]+\$?[0-9]+")
_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")
_NUMBER_RE = re.compile(r"(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?")

_SIMPLE_TOKENS = {
    "(": LPAREN,
    ")": RPAREN,
    ",": COMMA,
    ":": COLON,
    "!": BANG,
    "+": PLUS,
    "-": MINUS,
    "*": STAR,
    "/": SLASH,
    "^": CARET,
    "%": PERCENT,
    "&": AMP,
}


class Token:
    __slots__ = ("kind", "value", "pos")

    def __init__(self, kind, value, pos):
        self.kind = kind
        self.value = value
        self.pos = pos

    def __repr__(self):
        return f"Token({self.kind!r}, {self.value!r})"


def tokenize(text):
    """Tokenize a formula body (without the leading '=')."""
    tokens = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c in " \t\n\r":
            i += 1
            continue
        if c == '"':
            j = i + 1
            buf = []
            while True:
                if j >= n:
                    raise LexError("unterminated string literal", i)
                if text[j] == '"':
                    if j + 1 < n and text[j + 1] == '"':
                        buf.append('"')
                        j += 2
                        continue
                    j += 1
                    break
                buf.append(text[j])
                j += 1
            tokens.append(Token(STRING, "".join(buf), i))
            i = j
            continue
        if c == "<":
            if i + 1 < n and text[i + 1] == ">":
                tokens.append(Token(NE, "<>", i))
                i += 2
            elif i + 1 < n and text[i + 1] == "=":
                tokens.append(Token(LE, "<=", i))
                i += 2
            else:
                tokens.append(Token(LT, "<", i))
                i += 1
            continue
        if c == ">":
            if i + 1 < n and text[i + 1] == "=":
                tokens.append(Token(GE, ">=", i))
                i += 2
            else:
                tokens.append(Token(GT, ">", i))
                i += 1
            continue
        if c == "=":
            tokens.append(Token(EQ, "=", i))
            i += 1
            continue
        if c.isdigit() or (c == "." and i + 1 < n and text[i + 1].isdigit()):
            m = _NUMBER_RE.match(text, i)
            tokens.append(Token(NUMBER, float(m.group(0)), i))
            i = m.end()
            continue
        if c in _SIMPLE_TOKENS:
            tokens.append(Token(_SIMPLE_TOKENS[c], c, i))
            i += 1
            continue
        m = _REF_RE.match(text, i)
        if m:
            j = m.end()
            while j < n and text[j] in " \t":
                j += 1
            if j < n and text[j] in "(!":
                # looks like a ref (e.g. LOG10, or SHEET2 before '!') but is
                # actually a function name or a sheet name.
                m = _NAME_RE.match(text, i)
                tokens.append(Token(NAME, m.group(0), i))
                i = m.end()
                continue
            tokens.append(Token(REF, m.group(0).upper(), i))
            i = m.end()
            continue
        m = _NAME_RE.match(text, i)
        if m:
            word = m.group(0)
            upper = word.upper()
            if upper in ("TRUE", "FALSE"):
                tokens.append(Token(BOOL, upper == "TRUE", i))
            else:
                # Case is preserved (sheet names are case-sensitive); function
                # name lookups uppercase at dispatch time instead.
                tokens.append(Token(NAME, word, i))
            i = m.end()
            continue
        raise LexError(f"unexpected character {c!r}", i)
    tokens.append(Token(EOF, None, n))
    return tokens
