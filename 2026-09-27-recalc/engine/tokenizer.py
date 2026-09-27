"""Formula tokenizer: turns a formula string (without its leading '=') into
a flat list of Tokens for the parser."""

import re

from . import refs


class Token:
    __slots__ = ("kind", "text", "pos")

    def __init__(self, kind, text, pos):
        self.kind = kind
        self.text = text
        self.pos = pos

    def __repr__(self):
        return f"Token({self.kind!r}, {self.text!r})"


class TokenizeError(Exception):
    def __init__(self, message, pos):
        super().__init__(message)
        self.pos = pos


_NUMBER_RE = re.compile(r"\d+(\.\d+)?([eE][+-]?\d+)?|\.\d+([eE][+-]?\d+)?")
_CELLREF_RE = re.compile(r"\$?[A-Za-z]{1,3}\$?[0-9]+(?![A-Za-z0-9_])")
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")
# Error values are legal literals in a formula (real spreadsheets accept
# typing e.g. `=#REF!+1`), and this is also the text a broken reference
# serializes to after a copy/paste/fill shifts it off the grid — so it
# must reparse back into the same error, not blow up the tokenizer.
_ERROR_RE = re.compile(r"#(DIV/0!|VALUE!|REF!|NAME\?|N/A|NUM!|CYCLE!|ERROR!)")

_TWO_CHAR_OPS = ("<=", ">=", "<>")
_ONE_CHAR_OPS = "+-*/^&=<>(),:"


def tokenize(text):
    tokens = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in " \t\r\n":
            i += 1
            continue
        if ch == '"':
            j = i + 1
            buf = []
            while True:
                if j >= n:
                    raise TokenizeError("unterminated string literal", i)
                if text[j] == '"':
                    if j + 1 < n and text[j + 1] == '"':
                        buf.append('"')
                        j += 2
                        continue
                    j += 1
                    break
                buf.append(text[j])
                j += 1
            tokens.append(Token("STRING", "".join(buf), i))
            i = j
            continue
        if ch == "#":
            m = _ERROR_RE.match(text, i)
            if not m:
                raise TokenizeError(f"unrecognized error literal at {ch!r}", i)
            tokens.append(Token("ERRLIT", m.group(0), i))
            i = m.end()
            continue
        m = _CELLREF_RE.match(text, i)
        if m:
            tokens.append(Token("CELLREF", m.group(0), i))
            i = m.end()
            continue
        m = _NUMBER_RE.match(text, i)
        if m:
            tokens.append(Token("NUMBER", m.group(0), i))
            i = m.end()
            continue
        m = _IDENT_RE.match(text, i)
        if m:
            word = m.group(0)
            upper = word.upper()
            if upper in ("TRUE", "FALSE"):
                tokens.append(Token("BOOL", upper, i))
            else:
                tokens.append(Token("IDENT", word, i))
            i = m.end()
            continue
        two = text[i:i + 2]
        if two in _TWO_CHAR_OPS:
            tokens.append(Token("OP", two, i))
            i += 2
            continue
        if ch in _ONE_CHAR_OPS:
            kind = {
                "(": "LPAREN", ")": "RPAREN", ",": "COMMA", ":": "COLON",
            }.get(ch, "OP")
            tokens.append(Token(kind, ch, i))
            i += 1
            continue
        raise TokenizeError(f"unexpected character {ch!r}", i)
    tokens.append(Token("EOF", "", n))
    return tokens
