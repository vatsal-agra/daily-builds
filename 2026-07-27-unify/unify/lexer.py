"""Lexer for the Unify language: source text -> a flat list of Tokens."""

from dataclasses import dataclass

KEYWORDS = {
    "let", "rec", "in", "fun", "if", "then", "else",
    "match", "with", "true", "false", "Some", "None",
}

# Longest-match-first matters: "<=" before "<", "->" before "-", etc.
SYMBOLS = [
    "->", "::", "<=", ">=", "&&", "||", "<>",
    "(", ")", "[", "]", ",", "=", "<", ">", "+", "-", "*", "/", "|", "_",
]


class LexError(Exception):
    def __init__(self, message, line, col):
        super().__init__(message)
        self.message = message
        self.line = line
        self.col = col


@dataclass
class Token:
    kind: str   # INT, STRING, IDENT, KEYWORD, SYMBOL, EOF
    text: str
    value: object  # parsed literal value for INT/STRING, else None
    pos: int    # absolute char offset of first char
    line: int
    col: int


def _line_col(source, pos):
    line = source.count("\n", 0, pos) + 1
    last_nl = source.rfind("\n", 0, pos)
    col = pos - last_nl
    return line, col


def tokenize(source):
    tokens = []
    i = 0
    n = len(source)
    while i < n:
        c = source[i]

        if c in " \t\r\n":
            i += 1
            continue

        if c == "#":  # line comment
            while i < n and source[i] != "\n":
                i += 1
            continue

        line, col = _line_col(source, i)

        if c.isdigit():
            j = i
            while j < n and source[j].isdigit():
                j += 1
            text = source[i:j]
            tokens.append(Token("INT", text, int(text), i, line, col))
            i = j
            continue

        if c == '"':
            j = i + 1
            buf = []
            while j < n and source[j] != '"':
                if source[j] == "\\" and j + 1 < n:
                    esc = source[j + 1]
                    buf.append({"n": "\n", "t": "\t", "\\": "\\", '"': '"'}.get(esc, esc))
                    j += 2
                else:
                    buf.append(source[j])
                    j += 1
            if j >= n:
                raise LexError("unterminated string literal", line, col)
            text = source[i:j + 1]
            tokens.append(Token("STRING", text, "".join(buf), i, line, col))
            i = j + 1
            continue

        if c.isalpha() or c == "_":
            j = i
            while j < n and (source[j].isalnum() or source[j] == "_" or source[j] == "'"):
                j += 1
            text = source[i:j]
            if text == "_":
                tokens.append(Token("SYMBOL", "_", None, i, line, col))
            elif text in KEYWORDS:
                tokens.append(Token("KEYWORD", text, None, i, line, col))
            else:
                tokens.append(Token("IDENT", text, None, i, line, col))
            i = j
            continue

        matched = None
        for sym in SYMBOLS:
            if source.startswith(sym, i):
                matched = sym
                break
        if matched is not None:
            tokens.append(Token("SYMBOL", matched, None, i, line, col))
            i += len(matched)
            continue

        raise LexError(f"unexpected character {c!r}", line, col)

    line, col = _line_col(source, n)
    tokens.append(Token("EOF", "", None, n, line, col))
    return tokens
