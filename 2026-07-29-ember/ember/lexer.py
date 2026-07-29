"""Hand-written scanner for the Ember language.

Produces a flat list of Token objects with 1-based line/column info so
the parser (and users) get real positioned error messages, not just
"syntax error somewhere".
"""

from dataclasses import dataclass

KEYWORDS = {"fn", "let", "if", "else", "while", "return", "true", "false"}

# Longest-match-first ordering matters for the two-character operators.
SYMBOLS = [
    "==", "!=", "<=", ">=", "&&", "||",
    "(", ")", "{", "}", ",", ";", "=", "+", "-", "*", "/", "%",
    "<", ">", "!",
]


@dataclass(frozen=True)
class Token:
    kind: str      # 'INT' | 'IDENT' | 'KW' | 'SYM' | 'EOF'
    text: str
    value: object  # int for INT tokens, else None
    line: int
    col: int

    def __repr__(self):
        return f"Token({self.kind!r}, {self.text!r} @ {self.line}:{self.col})"


class LexError(Exception):
    def __init__(self, message, line, col):
        super().__init__(f"line {line}, col {col}: {message}")
        self.message = message
        self.line = line
        self.col = col


class Lexer:
    def __init__(self, source: str):
        self.src = source
        self.pos = 0
        self.line = 1
        self.col = 1
        self.n = len(source)

    def _peek(self, offset=0):
        i = self.pos + offset
        return self.src[i] if i < self.n else ""

    def _advance(self):
        ch = self.src[self.pos]
        self.pos += 1
        if ch == "\n":
            self.line += 1
            self.col = 1
        else:
            self.col += 1
        return ch

    def tokenize(self):
        tokens = []
        while True:
            self._skip_ws_and_comments()
            if self.pos >= self.n:
                tokens.append(Token("EOF", "", None, self.line, self.col))
                break
            line, col = self.line, self.col
            ch = self._peek()
            if ch.isdigit():
                tokens.append(self._lex_int(line, col))
            elif ch.isalpha() or ch == "_":
                tokens.append(self._lex_ident(line, col))
            else:
                tokens.append(self._lex_symbol(line, col))
        return tokens

    def _skip_ws_and_comments(self):
        while self.pos < self.n:
            ch = self._peek()
            if ch in " \t\r\n":
                self._advance()
            elif ch == "/" and self._peek(1) == "/":
                while self.pos < self.n and self._peek() != "\n":
                    self._advance()
            else:
                break

    def _lex_int(self, line, col):
        start = self.pos
        while self.pos < self.n and self._peek().isdigit():
            self._advance()
        # A digit run immediately followed by a letter/underscore is a
        # malformed literal like "123abc" -- reject it instead of silently
        # truncating to "123" and then choking on a stray "abc" identifier.
        if self.pos < self.n and (self._peek().isalpha() or self._peek() == "_"):
            while self.pos < self.n and (self._peek().isalnum() or self._peek() == "_"):
                self._advance()
            text = self.src[start:self.pos]
            raise LexError(f"malformed number literal {text!r}", line, col)
        text = self.src[start:self.pos]
        return Token("INT", text, int(text), line, col)

    def _lex_ident(self, line, col):
        start = self.pos
        while self.pos < self.n and (self._peek().isalnum() or self._peek() == "_"):
            self._advance()
        text = self.src[start:self.pos]
        kind = "KW" if text in KEYWORDS else "IDENT"
        return Token(kind, text, None, line, col)

    def _lex_symbol(self, line, col):
        for sym in SYMBOLS:
            if self.src.startswith(sym, self.pos):
                for _ in sym:
                    self._advance()
                return Token("SYM", sym, None, line, col)
        raise LexError(f"unexpected character {self._peek()!r}", line, col)


def tokenize(source: str):
    return Lexer(source).tokenize()
