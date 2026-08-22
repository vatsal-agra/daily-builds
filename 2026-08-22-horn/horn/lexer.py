"""Tokenizer for the Horn (Prolog-subset) syntax.

Character classes follow ISO Prolog's rough shape: solo chars ( ) [ ] | , !
are their own tokens; a run of "symbol" chars (+-*/\\^<>=~:.?@#&) glues
together into one operator token (so ':-' , '=<', '\\+', '=:=' are each a
single token, not two); alphanumeric identifiers starting lowercase are
plain names (which may themselves be operators, e.g. 'is', 'mod'); those
starting uppercase or '_' are variables. A lone '.' followed by whitespace,
a comment, or end-of-input ends a clause; a '.' with no following layout
(as in '3.14' or, in principle, a compound operator run) is not.
"""

import re

from .errors import HornError

_SYMBOL_CHARS = "+-*/\\^<>=~:.?@#&$"

_TOKEN_SPEC = [
    ("BLOCK_COMMENT", re.compile(r"/\*.*?\*/", re.DOTALL)),
    ("LINE_COMMENT", re.compile(r"%[^\n]*")),
    ("WS", re.compile(r"[ \t\r\n]+")),
    ("FLOAT", re.compile(r"\d+\.\d+(?:[eE][+-]?\d+)?")),
    ("INT", re.compile(r"\d+")),
    ("VAR", re.compile(r"[A-Z_][A-Za-z0-9_]*")),
    ("NAME", re.compile(r"[a-z][A-Za-z0-9_]*")),
    ("QATOM", re.compile(r"'(?:[^'\\]|\\.)*'", re.DOTALL)),
    ("STRING", re.compile(r'"(?:[^"\\]|\\.)*"', re.DOTALL)),
    ("PUNCT", re.compile(r"[()\[\]|,!]")),
    ("SYMOP", re.compile(r"[" + re.escape(_SYMBOL_CHARS) + r"]+")),
]

_ESCAPES = {"n": "\n", "t": "\t", "\\": "\\", "'": "'", '"': '"', "a": "\a", "r": "\r"}


def _unescape(s):
    out = []
    i = 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            out.append(_ESCAPES.get(nxt, nxt))
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


class Token:
    __slots__ = ("type", "value", "pos")

    def __init__(self, type_, value, pos):
        self.type = type_
        self.value = value
        self.pos = pos

    def __repr__(self):
        return f"Token({self.type!r}, {self.value!r})"


def tokenize(text):
    tokens = []
    i = 0
    n = len(text)
    while i < n:
        for kind, pattern in _TOKEN_SPEC:
            m = pattern.match(text, i)
            if not m:
                continue
            raw = m.group(0)
            end = m.end()
            if kind in ("WS", "LINE_COMMENT", "BLOCK_COMMENT"):
                i = end
                break
            if kind == "FLOAT":
                tokens.append(Token("NUMBER", float(raw), i))
            elif kind == "INT":
                tokens.append(Token("NUMBER", int(raw), i))
            elif kind == "VAR":
                tokens.append(Token("VAR", raw, i))
            elif kind == "NAME":
                tokens.append(Token("NAME", raw, i))
            elif kind == "QATOM":
                tokens.append(Token("NAME", _unescape(raw[1:-1]), i))
            elif kind == "STRING":
                tokens.append(Token("STRING", _unescape(raw[1:-1]), i))
            elif kind == "PUNCT":
                tokens.append(Token(raw, raw, i))
            elif kind == "SYMOP":
                if raw == ".":
                    followed_by_layout = end >= n or text[end] in " \t\r\n%" or (
                        end + 1 < n and text[end : end + 2] == "/*"
                    )
                    tokens.append(Token("END" if followed_by_layout else "SYMOP", raw, i))
                else:
                    tokens.append(Token("SYMOP", raw, i))
            i = end
            break
        else:
            raise HornError(f"syntax_error: unexpected character {text[i]!r} at position {i}")
    tokens.append(Token("EOF", None, n))
    return tokens
