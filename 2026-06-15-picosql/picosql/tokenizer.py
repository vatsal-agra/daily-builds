"""Hand-written SQL lexer.

Turns SQL text into a flat list of `Token`s, each carrying its source position
so the parser can point a caret at the offending token in error messages.
"""

from __future__ import annotations

from typing import List

KEYWORDS = {
    "SELECT", "FROM", "WHERE", "INSERT", "INTO", "VALUES", "CREATE", "TABLE",
    "DROP", "UPDATE", "SET", "DELETE", "ORDER", "BY", "GROUP", "HAVING",
    "LIMIT", "OFFSET", "JOIN", "INNER", "LEFT", "ON", "AS", "AND", "OR", "NOT",
    "NULL", "IS", "ASC", "DESC", "INTEGER", "REAL", "TEXT", "PRIMARY", "KEY",
    "EXPLAIN", "BEGIN", "COMMIT", "ROLLBACK", "TRANSACTION", "DISTINCT",
    "LIKE", "IN", "IF", "EXISTS", "COUNT", "SUM", "AVG", "MIN", "MAX",
}

# Multi-char operators must be tried before single-char ones.
_OPS2 = ("<=", ">=", "<>", "!=")
_OPS1 = set("=<>+-*/%(),.;")


class Token:
    __slots__ = ("type", "value", "pos", "end")

    def __init__(self, type: str, value, pos: int, end: int):
        self.type = type  # 'kw' | 'ident' | 'num' | 'str' | 'op' | 'eof'
        self.value = value
        self.pos = pos
        self.end = end

    def __repr__(self):
        return f"Token({self.type}, {self.value!r}, {self.pos})"


class TokenizeError(Exception):
    def __init__(self, message: str, pos: int):
        super().__init__(message)
        self.message = message
        self.pos = pos


def tokenize(sql: str) -> List[Token]:
    toks: List[Token] = []
    i = 0
    n = len(sql)
    while i < n:
        c = sql[i]
        if c in " \t\r\n":
            i += 1
            continue
        # line comment
        if c == "-" and i + 1 < n and sql[i + 1] == "-":
            while i < n and sql[i] != "\n":
                i += 1
            continue
        # block comment
        if c == "/" and i + 1 < n and sql[i + 1] == "*":
            j = sql.find("*/", i + 2)
            i = (j + 2) if j != -1 else n
            continue
        # string literal
        if c == "'":
            start = i
            i += 1
            buf = []
            while i < n:
                if sql[i] == "'":
                    if i + 1 < n and sql[i + 1] == "'":  # '' -> '
                        buf.append("'")
                        i += 2
                        continue
                    i += 1
                    break
                buf.append(sql[i])
                i += 1
            else:
                raise TokenizeError("unterminated string literal", start)
            toks.append(Token("str", "".join(buf), start, i))
            continue
        # double-quoted identifier
        if c == '"':
            start = i
            i += 1
            buf = []
            while i < n and sql[i] != '"':
                buf.append(sql[i])
                i += 1
            if i >= n:
                raise TokenizeError("unterminated quoted identifier", start)
            i += 1
            toks.append(Token("ident", "".join(buf), start, i))
            continue
        # number
        if c.isdigit() or (c == "." and i + 1 < n and sql[i + 1].isdigit()):
            start = i
            is_float = False
            while i < n and sql[i].isdigit():
                i += 1
            if i < n and sql[i] == ".":
                is_float = True
                i += 1
                while i < n and sql[i].isdigit():
                    i += 1
            if i < n and sql[i] in "eE":
                is_float = True
                i += 1
                if i < n and sql[i] in "+-":
                    i += 1
                while i < n and sql[i].isdigit():
                    i += 1
            text = sql[start:i]
            value = float(text) if is_float else int(text)
            toks.append(Token("num", value, start, i))
            continue
        # identifier / keyword
        if c.isalpha() or c == "_":
            start = i
            while i < n and (sql[i].isalnum() or sql[i] == "_"):
                i += 1
            word = sql[start:i]
            up = word.upper()
            if up in KEYWORDS:
                toks.append(Token("kw", up, start, i))
            else:
                toks.append(Token("ident", word, start, i))
            continue
        # operators
        two = sql[i : i + 2]
        if two in _OPS2:
            toks.append(Token("op", two, i, i + 2))
            i += 2
            continue
        if c in _OPS1:
            toks.append(Token("op", c, i, i + 1))
            i += 1
            continue
        raise TokenizeError(f"unexpected character {c!r}", i)
    toks.append(Token("eof", None, n, n))
    return toks
