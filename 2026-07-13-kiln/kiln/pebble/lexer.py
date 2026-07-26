"""Tokenizer for Pebble, the tiny language Kiln compiles to real WASM."""

KEYWORDS = {"fn", "let", "if", "else", "while", "return", "print"}

_SYMBOLS = [
    "==", "!=", "<=", ">=", "&&", "||", "->",
    "(", ")", "{", "}", ",", ";", "=", "+", "-", "*", "/", "%", "<", ">",
]


class Token:
    __slots__ = ("kind", "text", "line")

    def __init__(self, kind, text, line):
        self.kind = kind  # 'int' | 'ident' | 'kw' | 'sym' | 'eof'
        self.text = text
        self.line = line

    def __repr__(self):
        return f"Token({self.kind}, {self.text!r}, line={self.line})"


class PebbleSyntaxError(Exception):
    pass


def tokenize(src):
    tokens = []
    i, n, line = 0, len(src), 1
    while i < n:
        c = src[i]
        if c == "\n":
            line += 1
            i += 1
            continue
        if c.isspace():
            i += 1
            continue
        if src.startswith("//", i):
            while i < n and src[i] != "\n":
                i += 1
            continue
        if c.isdigit():
            j = i
            while j < n and src[j].isdigit():
                j += 1
            tokens.append(Token("int", src[i:j], line))
            i = j
            continue
        if c.isalpha() or c == "_":
            j = i
            while j < n and (src[j].isalnum() or src[j] == "_"):
                j += 1
            word = src[i:j]
            tokens.append(Token("kw" if word in KEYWORDS else "ident", word, line))
            i = j
            continue
        matched = None
        for sym in _SYMBOLS:
            if src.startswith(sym, i):
                matched = sym
                break
        if matched is None:
            raise PebbleSyntaxError(f"line {line}: unexpected character {c!r}")
        tokens.append(Token("sym", matched, line))
        i += len(matched)
    tokens.append(Token("eof", "", line))
    return tokens
