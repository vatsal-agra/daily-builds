"""Lexer: turns Coil source text into a stream of tokens with line/col info."""

from enum import Enum, auto

from .errors import LexError


class T(Enum):
    # literals
    NUMBER = auto()
    STRING = auto()
    IDENT = auto()
    # single-char
    LPAREN = auto()
    RPAREN = auto()
    LBRACE = auto()
    RBRACE = auto()
    LBRACKET = auto()
    RBRACKET = auto()
    COMMA = auto()
    DOT = auto()
    SEMICOLON = auto()
    COLON = auto()
    PLUS = auto()
    MINUS = auto()
    STAR = auto()
    SLASH = auto()
    PERCENT = auto()
    # one/two char
    BANG = auto()
    BANG_EQ = auto()
    EQ = auto()
    EQ_EQ = auto()
    GT = auto()
    GE = auto()
    LT = auto()
    LE = auto()
    # keywords
    AND = auto()
    OR = auto()
    NOT = auto()
    IF = auto()
    ELSE = auto()
    WHILE = auto()
    FOR = auto()
    FN = auto()
    RETURN = auto()
    LET = auto()
    TRUE = auto()
    FALSE = auto()
    NIL = auto()
    PRINT = auto()
    BREAK = auto()
    CONTINUE = auto()
    EOF = auto()


KEYWORDS = {
    "and": T.AND,
    "or": T.OR,
    "not": T.NOT,
    "if": T.IF,
    "else": T.ELSE,
    "while": T.WHILE,
    "for": T.FOR,
    "fn": T.FN,
    "return": T.RETURN,
    "let": T.LET,
    "true": T.TRUE,
    "false": T.FALSE,
    "nil": T.NIL,
    "print": T.PRINT,
    "break": T.BREAK,
    "continue": T.CONTINUE,
}


class Token:
    __slots__ = ("type", "value", "line", "col")

    def __init__(self, type_, value, line, col):
        self.type = type_
        self.value = value
        self.line = line
        self.col = col

    def __repr__(self):
        return f"Token({self.type.name}, {self.value!r}, {self.line}:{self.col})"


class Lexer:
    def __init__(self, source):
        self.src = source
        self.pos = 0
        self.line = 1
        self.col = 1
        self.tokens = []

    def _peek(self, ahead=0):
        i = self.pos + ahead
        return self.src[i] if i < len(self.src) else "\0"

    def _advance(self):
        ch = self.src[self.pos]
        self.pos += 1
        if ch == "\n":
            self.line += 1
            self.col = 1
        else:
            self.col += 1
        return ch

    def _match(self, expected):
        if self._peek() == expected:
            self._advance()
            return True
        return False

    def _add(self, type_, value, line, col):
        self.tokens.append(Token(type_, value, line, col))

    def tokenize(self):
        while self.pos < len(self.src):
            self._scan_token()
        self.tokens.append(Token(T.EOF, None, self.line, self.col))
        return self.tokens

    def _scan_token(self):
        start_line, start_col = self.line, self.col
        ch = self._advance()
        if ch in " \t\r\n":
            return
        if ch == "/" and self._peek() == "/":
            # line comment
            while self._peek() not in ("\n", "\0"):
                self._advance()
            return
        if ch == "/" and self._peek() == "*":
            # block comment (nesting-aware)
            self._advance()
            depth = 1
            while depth > 0:
                if self._peek() == "\0":
                    raise LexError("unterminated block comment", start_line, start_col)
                if self._peek() == "/" and self._peek(1) == "*":
                    self._advance(); self._advance(); depth += 1
                elif self._peek() == "*" and self._peek(1) == "/":
                    self._advance(); self._advance(); depth -= 1
                else:
                    self._advance()
            return

        simple = {
            "(": T.LPAREN, ")": T.RPAREN, "{": T.LBRACE, "}": T.RBRACE,
            "[": T.LBRACKET, "]": T.RBRACKET, ",": T.COMMA, ".": T.DOT,
            ";": T.SEMICOLON, ":": T.COLON, "+": T.PLUS, "-": T.MINUS,
            "*": T.STAR, "%": T.PERCENT,
        }
        if ch in simple:
            self._add(simple[ch], ch, start_line, start_col)
            return
        if ch == "/":
            self._add(T.SLASH, ch, start_line, start_col)
            return
        if ch == "!":
            if self._match("="):
                self._add(T.BANG_EQ, "!=", start_line, start_col)
            else:
                self._add(T.BANG, "!", start_line, start_col)
            return
        if ch == "=":
            if self._match("="):
                self._add(T.EQ_EQ, "==", start_line, start_col)
            else:
                self._add(T.EQ, "=", start_line, start_col)
            return
        if ch == ">":
            if self._match("="):
                self._add(T.GE, ">=", start_line, start_col)
            else:
                self._add(T.GT, ">", start_line, start_col)
            return
        if ch == "<":
            if self._match("="):
                self._add(T.LE, "<=", start_line, start_col)
            else:
                self._add(T.LT, "<", start_line, start_col)
            return
        if ch == '"':
            self._string(start_line, start_col)
            return
        if ch.isdigit():
            self._number(ch, start_line, start_col)
            return
        if ch.isalpha() or ch == "_":
            self._ident(ch, start_line, start_col)
            return
        raise LexError(f"unexpected character {ch!r}", start_line, start_col)

    def _string(self, line, col):
        chars = []
        while True:
            c = self._peek()
            if c == "\0":
                raise LexError("unterminated string", line, col)
            if c == '"':
                self._advance()
                break
            if c == "\\":
                self._advance()
                esc = self._advance()
                mapping = {"n": "\n", "t": "\t", "r": "\r", '"': '"',
                           "\\": "\\", "0": "\0"}
                if esc in mapping:
                    chars.append(mapping[esc])
                else:
                    raise LexError(f"invalid escape \\{esc}", self.line, self.col)
            else:
                chars.append(self._advance())
        self._add(T.STRING, "".join(chars), line, col)

    def _number(self, first, line, col):
        chars = [first]
        while self._peek().isdigit():
            chars.append(self._advance())
        if self._peek() == "." and self._peek(1).isdigit():
            chars.append(self._advance())
            while self._peek().isdigit():
                chars.append(self._advance())
        text = "".join(chars)
        value = float(text)
        # store ints as ints for nicer printing when whole
        self._add(T.NUMBER, value, line, col)

    def _ident(self, first, line, col):
        chars = [first]
        while self._peek().isalnum() or self._peek() == "_":
            chars.append(self._advance())
        text = "".join(chars)
        type_ = KEYWORDS.get(text, T.IDENT)
        self._add(type_, text, line, col)


def tokenize(source):
    return Lexer(source).tokenize()
