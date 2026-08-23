"""Hand-written lexer for the Runic language."""

KEYWORDS = {"fn", "let", "if", "else", "while", "return", "array"}

SYMBOLS3 = []
SYMBOLS2 = ["==", "!=", "<=", ">=", "&&", "||"]
SYMBOLS1 = "+-*/%()<>{}=;,[]!"


class Token:
    __slots__ = ("kind", "value", "line", "col")

    def __init__(self, kind, value, line, col):
        self.kind = kind
        self.value = value
        self.line = line
        self.col = col

    def __repr__(self):
        return f"Token({self.kind!r}, {self.value!r}, {self.line}:{self.col})"


class LexError(Exception):
    def __init__(self, msg, line, col):
        super().__init__(f"lex error at {line}:{col}: {msg}")
        self.line = line
        self.col = col


def tokenize(src):
    tokens = []
    i = 0
    n = len(src)
    line = 1
    col = 1

    def advance(k=1):
        nonlocal i, line, col
        for _ in range(k):
            if i < n and src[i] == "\n":
                line += 1
                col = 1
            else:
                col += 1
            i += 1

    while i < n:
        c = src[i]

        if c in " \t\r\n":
            advance()
            continue

        if c == "/" and i + 1 < n and src[i + 1] == "/":
            while i < n and src[i] != "\n":
                advance()
            continue

        if c == "/" and i + 1 < n and src[i + 1] == "*":
            start_line, start_col = line, col
            advance(2)
            closed = False
            while i < n:
                if src[i] == "*" and i + 1 < n and src[i + 1] == "/":
                    advance(2)
                    closed = True
                    break
                advance()
            if not closed:
                raise LexError("unterminated block comment", start_line, start_col)
            continue

        start_line, start_col = line, col

        if c.isdigit():
            j = i
            while j < n and src[j].isdigit():
                j += 1
            if j < n and src[j] == "." :
                raise LexError("floating point numbers are not supported (i32 only)", start_line, start_col)
            text = src[i:j]
            advance(j - i)
            tokens.append(Token("INT", int(text), start_line, start_col))
            continue

        if c.isalpha() or c == "_":
            j = i
            while j < n and (src[j].isalnum() or src[j] == "_"):
                j += 1
            text = src[i:j]
            advance(j - i)
            if text in KEYWORDS:
                tokens.append(Token(text, text, start_line, start_col))
            else:
                tokens.append(Token("IDENT", text, start_line, start_col))
            continue

        two = src[i:i + 2]
        if two in SYMBOLS2:
            advance(2)
            tokens.append(Token(two, two, start_line, start_col))
            continue

        if c in SYMBOLS1:
            advance(1)
            tokens.append(Token(c, c, start_line, start_col))
            continue

        raise LexError(f"unexpected character {c!r}", start_line, start_col)

    tokens.append(Token("EOF", None, line, col))
    return tokens
